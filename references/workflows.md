# App creation, update, and DataPatch workflows

## Contents

1. New application
2. Existing application retrofit
3. Code or environment update
4. Data-only update
5. Console upload and publish states

## 1. New application

1. Confirm the business users, pages, permissions, fields, imports/exports, entrypoints, state, environment variable names, route path, app identity, and initial version.
2. Choose the smallest stack that satisfies the business need and preserve its lockfile.
3. Implement platform host/port and native base-path behavior. Cover assets, APIs, redirects, download URLs, generated links, Cookie Path, and service workers.
4. Add the no-auth GET health endpoint and read-only smoke routes.
5. Decide `none` versus `files`. Put state under `/app/data`; use `seed/data` only for empty-directory initialization.
6. Add only independently updated data subtrees to `mutablePaths`.
7. Create `app.yaml`, Dockerfile, and `.dockerignore`; generate `.env.example` through `deployctl`.
8. Test, validate, build when Docker is available, package, validate the ZIP, and inspect the archive.

## 2. Existing application retrofit

Audit before editing:

- runtime and pinned version;
- start/build commands and lockfiles;
- hard-coded bind host/port;
- root-relative assets, requests, redirects, downloads, cookies, and service workers;
- all configuration sources and secret defaults;
- every persistent read/write path, SQLite file, upload, generated file, and report directory;
- startup seed/migration behavior;
- current Compose/Nginx assumptions;
- health behavior, entrypoints, and read-only acceptance paths.

Preserve behavior and data. Add a one-time data migration only when necessary, make it idempotent, and document both backup and rollback. Never copy seed data over a non-empty `/app/data`. Do not delete legacy deployment files merely because the platform ZIP rejects them unless the user authorizes repository cleanup; excluding them from the package and removing them from active runtime are separate decisions.

For base-path work, verify the full chain: browser URL -> HTML references -> client route/request -> server routing -> redirect/download response -> final visible behavior. A request reaching the server does not prove the prefixed browser flow works.

## 3. Code or environment update

Use a code release for any source, app manifest, code-coupled asset, schema, Dockerfile, or production environment-value change.

1. Read the current/latest platform release manifest, not just the local copy.
2. Preserve application name, route path, route mode, and persistence mode. The control plane rejects changed route/mode/persistence identity for an existing name.
3. Choose a SemVer greater than the latest uploaded release; do not overwrite or reuse a historical version.
4. Preserve at least one-version data compatibility. Avoid destructive startup migrations.
5. Run tests and package a new immutable ZIP.
6. Upload -> receive `READY` -> save the release-specific environment revision -> explicitly publish.

If a route or persistence-mode change is required, plan a new application identity or a platform-level migration. Do not hide the identity change inside a normal release.

## 4. Data-only update

Use a DataPatch only when all changed files belong under one target allowed by the active manifest. Split changes into multiple patches when targets belong to separate non-overlapping mutable paths.

Preconditions:

- the application has an active release;
- its persistence mode is `files`;
- the target equals or is nested under a declared `mutablePaths` entry;
- no code, `app.yaml`, Dockerfile, runtime config, HTML, JS, CSS, or code-coupled template changes are included.

The ZIP root is exactly:

```text
data-update.yaml
files/  # optional only for deletion-only patch
```

The manifest is `deploy.xzd5/v1`, `kind: DataPatch`, with matching `metadata.app`, a data `revision` whose syntax is locally valid and whose uniqueness is confirmed against the control plane, optional single-line description, safe relative `spec.target`, `mode: merge`, and explicit safe relative deletion paths. Uploaded and deleted paths must not equal, contain, or be contained by one another.

Missing files never imply deletion. A patch must add/replace at least one file or explicitly delete at least one path. A DataPatch does not change code SemVer or the active code release.

For JSON-only requests, pass `--validate-json` to the builder. This checks that every payload file has a `.json` suffix, is UTF-8, and parses as JSON; it does not validate business fields or a domain schema. Run domain-specific checks separately.

## 5. Console upload and publish states

Application package:

1. Upload ZIP through “上传应用 ZIP” or “上传新版本”.
2. Let the platform validate archive limits, file paths, required root files, and `app.yaml`.
3. For a new `metadata.name`, the upload creates the application. For an existing name, it enforces invariant route/mode/persistence and higher SemVer.
4. A successful upload creates `READY`; it does not deploy.
5. Save environment values for that release without exposing them in output.
6. Trigger “发布” only with explicit authorization and monitor the job to `ACTIVE` or `FAILED`.

DataPatch:

1. Open an active file-persistent application and upload the data ZIP.
2. Let the platform validate app identity, active manifest allowlist, package contents, and non-empty change.
3. A successful upload creates data-update `READY`; it does not modify live data.
4. Trigger “发布数据” only with explicit authorization and monitor to `SUCCEEDED` or `FAILED`.

Stateful code releases and DataPatches stop the active container and require a readable, verified full `/app/data` backup before replacement. Do not call upload completion a production release.
