#!/usr/bin/env python3
"""Read-only preflight scanner for App Deployer application repositories."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", "dist", "build", "vendor", "__pycache__", ".venv", "venv"}
TEXT_SUFFIXES = {
    ".c", ".conf", ".cpp", ".cs", ".css", ".env", ".go", ".h", ".html",
    ".java", ".js", ".json", ".jsx", ".mjs", ".php", ".properties", ".py",
    ".rb", ".rs", ".sh", ".sql", ".svelte", ".toml", ".ts", ".tsx", ".txt",
    ".vue", ".xml", ".yaml", ".yml",
}
MAX_TEXT_BYTES = 2 * 1024 * 1024
APP_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{2,40}$")
SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
ROUTE_RE = re.compile(r"^/(?:[A-Za-z0-9._~-]+(?:/[A-Za-z0-9._~-]+)*)$")
DATA_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._~-]+$")
PROTECTED_NAME_SEGMENTS = {
    "account", "accounts", "db", "database", "databases", "order", "orders",
    "profile", "profiles", "response", "responses", "session", "sessions",
    "submission", "submissions", "upload", "uploads", "user", "users",
}
BROAD_MUTABLE_SEGMENTS = {"data", "files", "runtime", "state", "storage"}


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    message: str
    path: str = ""
    line: int | None = None
    evidence: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only App Deployer compatibility audit")
    parser.add_argument("project", type=Path, help="application project directory")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--data-inventory", type=Path, help="completed DATA_SAFETY inventory JSON; replaces manual boundary flags")
    parser.add_argument("--operator-managed-path", action="append", default=[], help="exact mutable path owned by operators; repeatable")
    protected = parser.add_mutually_exclusive_group()
    protected.add_argument("--protected-path", action="append", default=[], help="user-generated or otherwise protected path; repeatable")
    protected.add_argument("--no-protected-data", action="store_true", help="assert that the data inventory found no protected state")
    args = parser.parse_args()
    if args.data_inventory and (args.operator_managed_path or args.protected_path or args.no_protected_data):
        parser.error("--data-inventory cannot be combined with manual data boundary flags")
    return args


def relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def iter_project_files(root: Path) -> tuple[list[Path], list[Finding]]:
    files: list[Path] = []
    findings: list[Finding] = []
    for current, dirs, names in os.walk(root, followlinks=False):
        current_path = Path(current)
        kept: list[str] = []
        for name in sorted(dirs):
            candidate = current_path / name
            if candidate.is_symlink():
                findings.append(Finding("error", "SYMLINK", "Symbolic links are forbidden in application packages.", relative(candidate, root)))
            elif name not in SKIP_DIRS:
                kept.append(name)
        dirs[:] = kept
        for name in sorted(names):
            candidate = current_path / name
            rel = relative(candidate, root)
            if candidate.is_symlink():
                findings.append(Finding("error", "SYMLINK", "Symbolic links are forbidden in application packages.", rel))
            elif candidate.is_file():
                files.append(candidate)
            else:
                findings.append(Finding("error", "SPECIAL_FILE", "Special files are forbidden in application packages.", rel))
    return files, findings


def unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def manifest_scalar(lines: list[str], section: str, key: str) -> str:
    section_indent: int | None = None
    for raw in lines:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        stripped = raw.strip()
        if stripped == section + ":":
            section_indent = indent
            continue
        if section_indent is None:
            continue
        if indent <= section_indent:
            section_indent = None
            continue
        match = re.match(rf"{re.escape(key)}\s*:\s*(.*?)\s*(?:#.*)?$", stripped)
        if match:
            return unquote(match.group(1))
    return ""


def manifest_list(lines: list[str], section: str, key: str) -> list[str]:
    section_indent: int | None = None
    for index, raw in enumerate(lines):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        stripped = raw.strip()
        if stripped == section + ":":
            section_indent = indent
            continue
        if section_indent is None:
            continue
        if indent <= section_indent:
            section_indent = None
            continue
        match = re.match(rf"{re.escape(key)}\s*:\s*(.*?)\s*(?:#.*)?$", stripped)
        if not match:
            continue
        value = match.group(1).strip()
        if value == "[]":
            return []
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            return [unquote(item.strip()) for item in inner.split(",") if item.strip()]
        if value:
            return [unquote(value)]
        result: list[str] = []
        key_indent = indent
        for item_raw in lines[index + 1:]:
            if not item_raw.strip() or item_raw.lstrip().startswith("#"):
                continue
            item_indent = len(item_raw) - len(item_raw.lstrip(" "))
            if item_indent <= key_indent:
                break
            item_match = re.match(r"-\s*(.*?)\s*(?:#.*)?$", item_raw.strip())
            if item_match:
                result.append(unquote(item_match.group(1)))
        return result
    return []


def parse_manifest(path: Path) -> dict[str, Any]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return {}
    top: dict[str, str] = {}
    for raw in lines:
        if raw.startswith((" ", "\t")) or raw.lstrip().startswith("#"):
            continue
        match = re.match(r"([A-Za-z][A-Za-z0-9]*)\s*:\s*(.*?)\s*(?:#.*)?$", raw)
        if match and match.group(2):
            top[match.group(1)] = unquote(match.group(2))
    return {
        "apiVersion": top.get("apiVersion", ""),
        "kind": top.get("kind", ""),
        "name": manifest_scalar(lines, "metadata", "name"),
        "version": manifest_scalar(lines, "metadata", "version"),
        "routePath": manifest_scalar(lines, "route", "path"),
        "routeMode": manifest_scalar(lines, "route", "mode"),
        "containerPort": manifest_scalar(lines, "container", "port"),
        "healthPath": manifest_scalar(lines, "health", "path"),
        "persistenceMode": manifest_scalar(lines, "persistence", "mode"),
        "containerPath": manifest_scalar(lines, "persistence", "containerPath"),
        "mutablePaths": manifest_list(lines, "persistence", "mutablePaths"),
    }


def validate_data_path(value: str) -> bool:
    if not value or value.startswith("/") or "\\" in value or any(ch in value for ch in ":#?%\x00\r\n"):
        return False
    parts = value.split("/")
    return value != "." and all(part not in {"", ".", ".."} and DATA_SEGMENT_RE.fullmatch(part) for part in parts)


def data_paths_overlap(left: str, right: str) -> bool:
    return left == right or left.startswith(right + "/") or right.startswith(left + "/")


def load_inventory_boundaries(path: Path) -> tuple[dict[str, Any], list[str], list[str], bool]:
    path = path.expanduser().resolve()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError(f"data inventory is not UTF-8: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid data inventory JSON:{exc.lineno}:{exc.colno}: {exc.msg}") from exc
    if not isinstance(value, dict) or value.get("complete") is not True:
        raise ValueError("data inventory must be an object with complete=true")
    entries = value.get("paths")
    if not isinstance(entries, list):
        raise ValueError("data inventory paths must be an array")
    operator: list[str] = []
    protected: list[str] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise ValueError(f"data inventory paths[{index}] must contain a string path")
        classification = entry.get("classification")
        allowed = entry.get("dataPatchAllowed")
        if classification == "operator-managed" and allowed is True:
            operator.append(entry["path"])
        elif classification == "protected" and allowed is False:
            protected.append(entry["path"])
        elif classification == "protected" and allowed is True:
            raise ValueError(f"protected data inventory path cannot allow DataPatch: {entry['path']}")
    return value, operator, protected, value.get("noProtectedData") is True


def check_required_and_forbidden(root: Path, files: Iterable[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for required in ("app.yaml", "Dockerfile", ".dockerignore"):
        if not (root / required).is_file():
            findings.append(Finding("error", "MISSING_ROOT_FILE", f"Required ZIP-root file is missing: {required}", required))
    for path in files:
        rel = relative(path, root)
        lower = rel.lower()
        parts = lower.split("/")
        if any(part == ".env" or (part.startswith(".env.") and part != ".env.example") for part in parts):
            findings.append(Finding("error", "REAL_ENV", "Real .env files are forbidden; keep values on the server.", rel))
        if lower in {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}:
            findings.append(Finding("error", "ROOT_COMPOSE", "Compose is platform-generated and cannot be packaged.", rel))
        if "/" not in lower and lower.startswith("nginx") and lower.endswith(".conf"):
            findings.append(Finding("error", "ROOT_NGINX", "Root Nginx configuration is platform-generated and cannot be packaged.", rel))
        if parts[0] == "data":
            findings.append(Finding("error", "ROOT_RUNTIME_DATA", "Top-level runtime data cannot enter the code ZIP; use /app/data or seed/data.", rel))
        if parts[-1] == "data-safety-inventory.json" or lower.endswith(".zip.safety.json"):
            findings.append(Finding("error", "SAFETY_EVIDENCE_IN_PACKAGE", "Data-safety inventory and evidence sidecars must remain outside application and DataPatch payloads.", rel))
    return findings


def check_manifest(root: Path) -> tuple[dict[str, Any], list[Finding]]:
    path = root / "app.yaml"
    if not path.is_file():
        return {}, []
    summary = parse_manifest(path)
    findings: list[Finding] = []
    checks = (
        (summary.get("apiVersion") == "deploy.xzd5/v1", "MANIFEST_API", "apiVersion must be deploy.xzd5/v1."),
        (summary.get("kind") == "WebApp", "MANIFEST_KIND", "kind must be WebApp."),
        (bool(APP_NAME_RE.fullmatch(summary.get("name", ""))), "MANIFEST_NAME", "metadata.name does not match the App Deployer slug contract."),
        (bool(SEMVER_RE.fullmatch(summary.get("version", ""))), "MANIFEST_VERSION", "metadata.version is missing or is not SemVer."),
        (bool(ROUTE_RE.fullmatch(summary.get("routePath", ""))), "MANIFEST_ROUTE", "spec.route.path must be a non-root, no-trailing-slash URL-safe path."),
        (summary.get("routeMode") in {"native", "static-strip"}, "MANIFEST_MODE", "spec.route.mode must be native or static-strip."),
        (summary.get("persistenceMode") in {"none", "files"}, "MANIFEST_PERSISTENCE", "spec.persistence.mode must be none or files."),
    )
    for passed, code, message in checks:
        if not passed:
            findings.append(Finding("error", code, message, "app.yaml"))
    if summary.get("persistenceMode") == "files" and summary.get("containerPath") != "/app/data":
        findings.append(Finding("error", "MANIFEST_DATA_PATH", "File persistence must use containerPath: /app/data.", "app.yaml"))
    if summary.get("persistenceMode") == "none" and summary.get("containerPath"):
        findings.append(Finding("error", "MANIFEST_STATELESS_PATH", "Stateless apps must omit persistence.containerPath.", "app.yaml"))
    return summary, findings


def check_data_inventory(manifest: dict[str, Any], operator_paths: list[str], protected_paths: list[str], no_protected_data: bool) -> list[Finding]:
    findings: list[Finding] = []
    mutable_paths = list(manifest.get("mutablePaths") or [])
    for label, values in (("mutablePaths", mutable_paths), ("--operator-managed-path", operator_paths), ("--protected-path", protected_paths)):
        seen: set[str] = set()
        for value in values:
            if not validate_data_path(value):
                findings.append(Finding("error", "UNSAFE_DATA_PATH", f"{label} contains an unsafe data path: {value}", "app.yaml" if label == "mutablePaths" else ""))
            if value in seen:
                findings.append(Finding("error", "DUPLICATE_DATA_PATH", f"{label} contains a duplicate path: {value}", "app.yaml" if label == "mutablePaths" else ""))
            seen.add(value)

    mode = manifest.get("persistenceMode")
    if mode == "none" and (mutable_paths or operator_paths or protected_paths):
        findings.append(Finding("error", "STATELESS_DATA_BOUNDARY", "Stateless apps cannot declare mutable, operator-managed, or protected persistent paths.", "app.yaml"))
        return findings
    if mode != "files":
        return findings

    if not protected_paths and not no_protected_data:
        findings.append(Finding("error", "PROTECTED_INVENTORY_REQUIRED", "File-persistent apps must list every protected path or explicitly pass --no-protected-data after completing the inventory.", "app.yaml"))
    if mutable_paths and not operator_paths:
        findings.append(Finding("error", "OPERATOR_INVENTORY_REQUIRED", "Every mutable path requires a matching --operator-managed-path classification.", "app.yaml"))

    mutable_set = set(mutable_paths)
    operator_set = set(operator_paths)
    for value in sorted(mutable_set - operator_set):
        findings.append(Finding("error", "UNCLASSIFIED_MUTABLE_PATH", f"Manifest mutable path is not proven operator-managed: {value}", "app.yaml"))
    for value in sorted(operator_set - mutable_set):
        findings.append(Finding("error", "UNDECLARED_OPERATOR_PATH", f"Operator-managed path does not exactly match a manifest mutable path: {value}", "app.yaml"))

    for mutable in mutable_paths:
        segments = {part.lower() for part in mutable.split("/")}
        risky = sorted(segments & PROTECTED_NAME_SEGMENTS)
        broad = sorted(segments & BROAD_MUTABLE_SEGMENTS)
        if risky:
            findings.append(Finding("error", "PROTECTED_NAME_MUTABLE", f"Mutable path uses a protected-data name and must be isolated or renamed: {mutable} ({', '.join(risky)})", "app.yaml"))
        if broad:
            findings.append(Finding("error", "BROAD_MUTABLE_PATH", f"Mutable path is too broad for fail-closed data updates: {mutable} ({', '.join(broad)})", "app.yaml"))
        for protected in protected_paths:
            if data_paths_overlap(mutable, protected):
                findings.append(Finding("error", "MUTABLE_PROTECTED_OVERLAP", f"Mutable path {mutable} overlaps protected path {protected}; separate the storage before enabling DataPatch.", "app.yaml"))
    return findings


def read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_TEXT_BYTES:
            return None
        if path.suffix.lower() not in TEXT_SUFFIXES and not path.name.startswith("Dockerfile"):
            return None
        raw = path.read_bytes()
        if b"\x00" in raw:
            return None
        return raw.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def first_match(root: Path, files: Iterable[Path], pattern: re.Pattern[str]) -> Finding | None:
    for path in files:
        text = read_text(path)
        if text is None:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            match = pattern.search(line)
            if match:
                evidence = line.strip()
                if len(evidence) > 180:
                    evidence = evidence[:177] + "..."
                return Finding("warning", "", "", relative(path, root), number, evidence)
    return None


def heuristic_findings(root: Path, files: list[Path], manifest: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    joined_names = "\n".join(
        relative(path, root).lower()
        for path in files
        if not relative(path, root).lower().startswith("seed/data/")
    )
    patterns = [
        ("BASE_PATH_EVIDENCE", re.compile(r"APP_BASE_PATH"), "No APP_BASE_PATH reference was found; verify the full prefixed URL chain."),
        ("HOST_EVIDENCE", re.compile(r"(?:process\.env|os\.(?:getenv|environ)|getenv|Environment\.GetEnvironmentVariable)[^\n]{0,80}\bHOST\b", re.I), "No runtime HOST environment read was found; verify dynamic binding."),
        ("PORT_EVIDENCE", re.compile(r"(?:process\.env|os\.(?:getenv|environ)|getenv|Environment\.GetEnvironmentVariable)[^\n]{0,80}\bPORT\b", re.I), "No runtime PORT environment read was found; verify dynamic binding."),
        ("HEALTH_EVIDENCE", re.compile(r"(?:/health|healthz|healthcheck)", re.I), "No obvious health route was found; verify an unauthenticated side-effect-free GET endpoint."),
    ]
    if manifest.get("routeMode") == "native":
        pattern_rows = patterns
    else:
        pattern_rows = patterns[1:]
    for code, pattern, missing_message in pattern_rows:
        if first_match(root, files, pattern) is None:
            findings.append(Finding("warning", code, missing_message))

    root_url = re.compile(r"(?:\b(?:src|href|action)\s*=\s*['\"]/(?!/)|\b(?:fetch|axios\.(?:get|post|put|delete)|window\.open)\s*\(\s*['\"]/(?!/)|\burl\(\s*['\"]?/(?!/))", re.I)
    match = first_match(root, files, root_url)
    if match:
        findings.append(Finding("warning", "ROOT_RELATIVE_URL", "Root-relative URL candidate may bypass APP_BASE_PATH; inspect in framework context.", match.path, match.line, match.evidence))

    loopback = re.compile(r"(?:listen|host|bind)[^\n]{0,40}(?:127\.0\.0\.1|localhost)", re.I)
    match = first_match(root, files, loopback)
    if match and "HOST" not in match.evidence.upper():
        findings.append(Finding("warning", "LOOPBACK_BIND", "Loopback bind candidate may be unreachable from the proxy network.", match.path, match.line, match.evidence))

    external = re.compile(r"(?:mysql|postgres(?:ql)?|mongodb|redis://|s3[_-]|minio|object.?storage)", re.I)
    match = first_match(root, files, external)
    if match:
        findings.append(Finding("warning", "EXTERNAL_STATE", "External state dependency found; confirm native backup/restore coverage before release.", match.path, match.line, match.evidence))

    state_names = (".sqlite", ".sqlite3", ".db", "/uploads/", "/reports/", "/generated/")
    if any(token in joined_names for token in state_names) or "data/" in joined_names:
        findings.append(Finding("warning", "STATE_PATHS", "State-like files or directories exist; trace every runtime read/write and migrate persistent state to /app/data."))
    return findings


def render_markdown(root: Path, manifest: dict[str, Any], findings: list[Finding], file_count: int) -> str:
    errors = [item for item in findings if item.severity == "error"]
    warnings = [item for item in findings if item.severity == "warning"]
    lines = [f"# Microapp audit: {root}", "", f"- Scanned files: {file_count}", f"- Hard errors: {len(errors)}", f"- Heuristic findings: {len(warnings)}"]
    if manifest:
        lines.extend(["", "## Manifest summary", ""])
        for key in ("name", "version", "routePath", "routeMode", "persistenceMode", "containerPath", "mutablePaths", "healthPath", "containerPort"):
            value = manifest.get(key, "")
            if isinstance(value, list):
                value = ", ".join(value) if value else "[]"
            lines.append(f"- {key}: `{value}`")
    for title, items in (("Hard errors", errors), ("Heuristic findings", warnings)):
        lines.extend(["", f"## {title}", ""])
        if not items:
            lines.append("- None")
            continue
        for item in items:
            location = item.path
            if item.line is not None:
                location += f":{item.line}"
            suffix = f" ({location})" if location else ""
            evidence = f" Evidence: `{item.evidence}`" if item.evidence else ""
            lines.append(f"- [{item.code}] {item.message}{suffix}{evidence}")
    lines.extend(["", "> This scanner is a read-only lead generator. Confirm warnings in actual code and run the live deployctl validator."])
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    root = args.project.expanduser().resolve()
    if not root.is_dir():
        print(f"ERROR: project directory not found: {root}", file=sys.stderr)
        return 2
    files, findings = iter_project_files(root)
    findings.extend(check_required_and_forbidden(root, files))
    manifest, manifest_findings = check_manifest(root)
    findings.extend(manifest_findings)
    operator_paths = args.operator_managed_path
    protected_paths = args.protected_path
    no_protected_data = args.no_protected_data
    if args.data_inventory:
        try:
            inventory, operator_paths, protected_paths, no_protected_data = load_inventory_boundaries(args.data_inventory)
            if inventory.get("app") != manifest.get("name"):
                findings.append(Finding("error", "INVENTORY_APP_MISMATCH", "Data inventory app does not match manifest metadata.name.", "app.yaml"))
            if inventory.get("activeVersion") != manifest.get("version"):
                findings.append(Finding("error", "INVENTORY_VERSION_MISMATCH", "Data inventory activeVersion does not match manifest metadata.version.", "app.yaml"))
        except (OSError, ValueError) as exc:
            findings.append(Finding("error", "INVALID_DATA_INVENTORY", str(exc), str(args.data_inventory)))
    findings.extend(check_data_inventory(manifest, operator_paths, protected_paths, no_protected_data))
    findings.extend(heuristic_findings(root, files, manifest))
    findings.sort(key=lambda item: (0 if item.severity == "error" else 1, item.code, item.path, item.line or 0))
    if args.format == "json":
        print(json.dumps({"project": str(root), "fileCount": len(files), "manifest": manifest, "findings": [asdict(item) for item in findings]}, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(root, manifest, findings, len(files)))
    return 1 if any(item.severity == "error" for item in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
