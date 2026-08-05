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

from audit_microapp import parse_manifest


APP_RE = re.compile(r"^[a-z][a-z0-9-]{2,40}$")
REVISION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SEGMENT_RE = re.compile(r"^[A-Za-z0-9._~-]+$")
FIXED_TIME = (2020, 1, 1, 0, 0, 0)
PROTECTED_NAME_SEGMENTS = {
    "account", "accounts", "db", "database", "databases", "order", "orders",
    "profile", "profiles", "response", "responses", "session", "sessions",
    "submission", "submissions", "upload", "uploads", "user", "users",
}
BROAD_MUTABLE_SEGMENTS = {"data", "files", "runtime", "state", "storage"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an App Deployer DataPatch ZIP")
    parser.add_argument("--app", required=True, help="active app metadata.name")
    parser.add_argument("--revision", required=True, help="data revision; syntax is checked locally, uniqueness must be confirmed in the control plane")
    parser.add_argument("--target", required=True, help="allowed path relative to /app/data")
    parser.add_argument("--active-manifest", type=Path, required=True, help="current control-plane app.yaml exported from the active release")
    parser.add_argument("--data-inventory", type=Path, required=True, help="completed DATA_SAFETY inventory JSON")
    parser.add_argument("--files", type=Path, help="directory whose contents will be placed under spec.target")
    parser.add_argument("--delete", action="append", default=[], help="path relative to spec.target; repeatable")
    parser.add_argument("--confirm-delete", action="store_true", help="confirm that the user explicitly approved the exact --delete list")
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


def paths_overlap(left: str, right: str) -> bool:
    return left == right or left.startswith(right + "/") or right.startswith(left + "/")


def load_inventory(path: Path, app: str, active_version: str) -> tuple[dict[str, object], list[str], list[str]]:
    path = path.expanduser().resolve()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError(f"data inventory is not UTF-8: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid data inventory JSON:{exc.lineno}:{exc.colno}: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ValueError("data inventory root must be an object")
    if value.get("complete") is not True:
        raise ValueError("data inventory must set complete=true after every persistent path is classified")
    if value.get("app") != app:
        raise ValueError("data inventory app does not match --app")
    if value.get("activeVersion") != active_version:
        raise ValueError("data inventory activeVersion does not match the active manifest")
    entries = value.get("paths")
    if not isinstance(entries, list):
        raise ValueError("data inventory paths must be an array")
    required_text = ("producer", "sourceOfTruth", "updateMechanism", "deleteAuthority", "backupRestore")
    seen: set[str] = set()
    mutable: list[str] = []
    protected: list[str] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"data inventory paths[{index}] must be an object")
        item = safe_data_path(str(entry.get("path", "")), f"data inventory paths[{index}].path")
        if item in seen:
            raise ValueError(f"data inventory contains a duplicate path: {item}")
        seen.add(item)
        classification = entry.get("classification")
        if classification not in {"operator-managed", "protected"}:
            raise ValueError(f"data inventory path {item} must be operator-managed or protected")
        for field in required_text:
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                raise ValueError(f"data inventory path {item} requires non-empty {field}")
        readers_writers = entry.get("readersWriters")
        if not isinstance(readers_writers, list) or not readers_writers or not all(isinstance(row, str) and row.strip() for row in readers_writers):
            raise ValueError(f"data inventory path {item} requires non-empty readersWriters")
        if not isinstance(entry.get("mustSurviveRelease"), bool):
            raise ValueError(f"data inventory path {item} requires boolean mustSurviveRelease")
        if not isinstance(entry.get("dataPatchAllowed"), bool):
            raise ValueError(f"data inventory path {item} requires boolean dataPatchAllowed")
        if classification == "protected" and entry["dataPatchAllowed"]:
            raise ValueError(f"protected data inventory path cannot allow DataPatch: {item}")
        if classification == "operator-managed" and entry["dataPatchAllowed"]:
            mutable.append(item)
        if classification == "protected":
            protected.append(item)
    no_protected = value.get("noProtectedData")
    if protected and no_protected is True:
        raise ValueError("data inventory cannot set noProtectedData=true while protected paths exist")
    if not protected and no_protected is not True:
        raise ValueError("data inventory must set noProtectedData=true or list every protected path")
    return value, mutable, protected


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
        active_manifest = args.active_manifest.expanduser().resolve()
        if not active_manifest.is_file():
            raise ValueError(f"--active-manifest file not found: {active_manifest}")
        active = parse_manifest(active_manifest)
        if active.get("name") != args.app:
            raise ValueError("--active-manifest metadata.name does not match --app")
        if active.get("persistenceMode") != "files" or active.get("containerPath") != "/app/data":
            raise ValueError("--active-manifest must use file persistence at /app/data")
        active_version = str(active.get("version", ""))
        manifest_mutable = list(active.get("mutablePaths") or [])
        if not manifest_mutable:
            raise ValueError("--active-manifest has empty mutablePaths; this app does not allow DataPatch")
        inventory, inventory_mutable, protected_paths = load_inventory(args.data_inventory, args.app, active_version)
        if set(manifest_mutable) != set(inventory_mutable):
            raise ValueError("active manifest mutablePaths must exactly match inventory paths with dataPatchAllowed=true")
        target = safe_data_path(args.target, "--target")
        target_segments = {part.lower() for part in PurePosixPath(target).parts}
        risky = sorted(target_segments & PROTECTED_NAME_SEGMENTS)
        if risky:
            raise ValueError(f"--target uses a protected-data name and cannot be patched: {target} ({', '.join(risky)})")
        broad = sorted(target_segments & BROAD_MUTABLE_SEGMENTS)
        if broad:
            raise ValueError(f"--target is too broad for fail-closed data updates: {target} ({', '.join(broad)})")
        if not any(target == allowed or target.startswith(allowed + "/") for allowed in manifest_mutable):
            raise ValueError("--target is not allowed by the active manifest mutablePaths")
        for protected in protected_paths:
            if paths_overlap(target, protected):
                raise ValueError(f"--target overlaps protected data: {target} vs {protected}")
        deleted = [safe_data_path(item, "--delete") for item in args.delete]
        if len(set(deleted)) != len(deleted):
            raise ValueError("--delete contains duplicates")
        if deleted and not args.confirm_delete:
            raise ValueError("--delete requires --confirm-delete after explicit user approval of the exact deletion list")
        if args.confirm_delete and not deleted:
            raise ValueError("--confirm-delete requires at least one --delete path")
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
        safety_sidecar = Path(str(output) + ".safety.json")
        if (output.exists() or sidecar.exists() or safety_sidecar.exists()) and not args.force:
            raise ValueError(f"output or sidecar already exists; pass --force to replace: {output}")
        if args.files is not None:
            files_root = args.files.expanduser().resolve()
            if output == files_root or files_root in output.parents:
                raise ValueError("--output must not be inside --files")
            inventory_path = args.data_inventory.expanduser().resolve()
            if files_root in active_manifest.parents or files_root in inventory_path.parents:
                raise ValueError("--active-manifest and --data-inventory must stay outside --files and the DataPatch ZIP")
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
        safety_record = {
            "app": args.app,
            "activeVersion": active_version,
            "revision": args.revision,
            "target": target,
            "activeManifestSHA256": sha256(active_manifest),
            "dataInventorySHA256": sha256(args.data_inventory.expanduser().resolve()),
            "mutablePaths": manifest_mutable,
            "protectedPaths": protected_paths,
            "payloadPaths": [rel for _, rel in files],
            "approvedDeletions": deleted,
            "dataInventoryComplete": inventory.get("complete") is True,
        }
        safety_sidecar.write_text(json.dumps(safety_record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"PACKED {output}")
        print(f"SHA256 {digest}")
        protected_summary = ",".join(protected_paths) if protected_paths else "none (explicitly inventoried)"
        print(f"SAFETY active-version={active_version} operator-managed-target={target} protected-paths={protected_summary} deletions-confirmed={bool(deleted)}")
        print(f"SAFETY_RECORD {safety_sidecar}")
        print(f"FILES {len(members)} EXPANDED {expanded} ARCHIVE {output.stat().st_size}")
        for member in members:
            print(f"  {member}")
        return 0
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
