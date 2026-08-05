#!/usr/bin/env python3
"""Build a canonical App Deployer DataPatch ZIP and SHA-256 sidecar."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


APP_RE = re.compile(r"^[a-z][a-z0-9-]{2,40}$")
REVISION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SEGMENT_RE = re.compile(r"^[A-Za-z0-9._~-]+$")
FIXED_TIME = (2020, 1, 1, 0, 0, 0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an App Deployer DataPatch ZIP")
    parser.add_argument("--app", required=True, help="active app metadata.name")
    parser.add_argument("--revision", required=True, help="data revision; syntax is checked locally, uniqueness must be confirmed in the control plane")
    parser.add_argument("--target", required=True, help="allowed path relative to /app/data")
    parser.add_argument("--files", type=Path, help="directory whose contents will be placed under spec.target")
    parser.add_argument("--delete", action="append", default=[], help="path relative to spec.target; repeatable")
    parser.add_argument("--description", default="", help="single-line description, at most 200 characters")
    parser.add_argument("--validate-json", action="store_true", help="require every payload file to be valid UTF-8 JSON")
    parser.add_argument("--output", type=Path, required=True, help="output .zip path")
    parser.add_argument("--force", action="store_true", help="replace an existing output and sidecar")
    parser.add_argument("--max-files", type=int, default=10000)
    parser.add_argument("--max-expanded-bytes", type=int, default=2 * 1024 * 1024 * 1024)
    parser.add_argument("--max-archive-bytes", type=int, default=500 * 1024 * 1024)
    parser.add_argument("--max-compression-ratio", type=float, default=100.0)
    return parser.parse_args()


def safe_data_path(value: str, label: str) -> str:
    if not value or value.startswith("/") or "\\" in value or any(ch in value for ch in ":#?%\x00\r\n"):
        raise ValueError(f"{label} must be a safe relative path")
    path = PurePosixPath(value)
    if str(path) != value or value == "." or ".." in path.parts:
        raise ValueError(f"{label} must not contain traversal or redundant segments")
    if not all(SEGMENT_RE.fullmatch(part) for part in path.parts):
        raise ValueError(f"{label} may contain only URL-safe ASCII path segments")
    return value


def safe_payload_rel(path: Path, root: Path) -> str:
    rel = path.relative_to(root).as_posix()
    pure = PurePosixPath(rel)
    lower_parts = [part.lower() for part in pure.parts]
    if (
        not rel
        or rel == "."
        or pure.is_absolute()
        or ".." in pure.parts
        or ":" in rel
        or "\\" in rel
        or any("\x00" in part for part in pure.parts)
    ):
        raise ValueError(f"unsafe payload path: {rel}")
    if any(part in {".git", "node_modules"} or part == ".env" or part.startswith(".env.") for part in lower_parts):
        raise ValueError(f"forbidden payload path: {rel}")
    return rel


def collect_files(root: Path | None) -> list[tuple[Path, str]]:
    if root is None:
        return []
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"--files directory not found: {root}")
    result: list[tuple[Path, str]] = []
    for current, dirs, names in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in list(dirs):
            candidate = current_path / name
            if candidate.is_symlink():
                raise ValueError(f"symbolic link is forbidden: {safe_payload_rel(candidate, root)}")
        for name in names:
            candidate = current_path / name
            rel = safe_payload_rel(candidate, root)
            mode = candidate.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise ValueError(f"symbolic link is forbidden: {rel}")
            if not stat.S_ISREG(mode):
                raise ValueError(f"special file is forbidden: {rel}")
            result.append((candidate, rel))
    result.sort(key=lambda item: item[1])
    return result


def conflicts(uploaded: list[str], deleted: list[str]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for upload in uploaded:
        for delete in deleted:
            if upload == delete or upload.startswith(delete + "/") or delete.startswith(upload + "/"):
                result.append((upload, delete))
    return result


def validate_json_files(files: list[tuple[Path, str]]) -> None:
    for source, rel in files:
        if source.suffix.lower() != ".json":
            raise ValueError(f"--validate-json requires a .json payload: {rel}")
        try:
            with source.open("r", encoding="utf-8") as handle:
                json.load(handle)
        except UnicodeDecodeError as exc:
            raise ValueError(f"JSON payload is not UTF-8: {rel}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON payload: {rel}:{exc.lineno}:{exc.colno}: {exc.msg}") from exc


def yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def make_manifest(app: str, revision: str, target: str, description: str, deleted: list[str]) -> bytes:
    lines = [
        "apiVersion: deploy.xzd5/v1",
        "kind: DataPatch",
        "",
        "metadata:",
        f"  app: {app}",
        f"  revision: {revision}",
    ]
    if description:
        lines.append(f"  description: {yaml_string(description)}")
    lines.extend(["", "spec:", f"  target: {target}", "  mode: merge"])
    if deleted:
        lines.append("  delete:")
        lines.extend(f"    - {yaml_string(item)}" for item in deleted)
    else:
        lines.append("  delete: []")
    return ("\n".join(lines) + "\n").encode("utf-8")


def zip_info(name: str, compression: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_TIME)
    info.compress_type = compression
    info.external_attr = (0o100640 & 0xFFFF) << 16
    info.create_system = 3
    return info


def write_zip(path: Path, manifest: bytes, files: list[tuple[Path, str]], stored: set[str]) -> None:
    with zipfile.ZipFile(path, "w", allowZip64=True) as archive:
        archive.writestr(zip_info("data-update.yaml", zipfile.ZIP_DEFLATED), manifest)
        for source, rel in files:
            arcname = "files/" + rel
            compression = zipfile.ZIP_STORED if arcname in stored else zipfile.ZIP_DEFLATED
            with archive.open(zip_info(arcname, compression), "w") as target, source.open("rb") as origin:
                shutil.copyfileobj(origin, target, length=1024 * 1024)


def high_ratio_members(path: Path, maximum: float) -> set[str]:
    result: set[str] = set()
    with zipfile.ZipFile(path, "r") as archive:
        for info in archive.infolist():
            if info.compress_size > 0 and info.file_size / info.compress_size > maximum:
                result.add(info.filename)
    return result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    args = parse_args()
    try:
        if not APP_RE.fullmatch(args.app):
            raise ValueError("--app must match ^[a-z][a-z0-9-]{2,40}$")
        if not REVISION_RE.fullmatch(args.revision):
            raise ValueError("--revision must match ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
        target = safe_data_path(args.target, "--target")
        deleted = [safe_data_path(item, "--delete") for item in args.delete]
        if len(set(deleted)) != len(deleted):
            raise ValueError("--delete contains duplicates")
        if len(args.description) > 200 or any(ch in args.description for ch in "\x00\r\n"):
            raise ValueError("--description must be one line and at most 200 characters")
        files = collect_files(args.files)
        if args.validate_json:
            validate_json_files(files)
        if not files and not deleted:
            raise ValueError("the patch must upload at least one file or declare at least one deletion")
        collisions = conflicts([rel for _, rel in files], deleted)
        if collisions:
            raise ValueError(f"uploaded and deleted paths conflict: {collisions[0][0]} vs {collisions[0][1]}")
        manifest = make_manifest(args.app, args.revision, target, args.description, deleted)
        expanded = len(manifest) + sum(source.stat().st_size for source, _ in files)
        if len(files) + 1 > args.max_files:
            raise ValueError(f"file count {len(files) + 1} exceeds limit {args.max_files}")
        if expanded > args.max_expanded_bytes:
            raise ValueError(f"expanded bytes {expanded} exceed limit {args.max_expanded_bytes}")

        output = args.output.expanduser().resolve()
        sidecar = Path(str(output) + ".sha256")
        if (output.exists() or sidecar.exists()) and not args.force:
            raise ValueError(f"output or sidecar already exists; pass --force to replace: {output}")
        if args.files is not None:
            files_root = args.files.expanduser().resolve()
            if output == files_root or files_root in output.parents:
                raise ValueError("--output must not be inside --files")
        output.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="datapatch-", dir=output.parent) as temp_dir:
            temporary = Path(temp_dir) / "patch.zip"
            write_zip(temporary, manifest, files, set())
            stored = high_ratio_members(temporary, args.max_compression_ratio)
            if stored:
                temporary.unlink()
                write_zip(temporary, manifest, files, stored)
            if temporary.stat().st_size > args.max_archive_bytes:
                raise ValueError(f"archive bytes {temporary.stat().st_size} exceed limit {args.max_archive_bytes}")
            digest = sha256(temporary)
            if output.exists():
                output.unlink()
            os.replace(temporary, output)
        sidecar.write_text(f"{digest}  {output.name}\n", encoding="utf-8", newline="\n")

        with zipfile.ZipFile(output, "r") as archive:
            members = archive.namelist()
        print(f"PACKED {output}")
        print(f"SHA256 {digest}")
        print(f"FILES {len(members)} EXPANDED {expanded} ARCHIVE {output.stat().st_size}")
        for member in members:
            print(f"  {member}")
        return 0
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
