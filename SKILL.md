---
name: skill-microapp-creator
description: Create, retrofit, update, validate, and package internal Web apps for the controlled App Deployer contract (`deploy.xzd5/v1`) while protecting user-generated data. Use when a user asks to create a micro app for app-deployer, make an existing Web app compatible with the publisher, classify `/app/data`, isolate operator-managed resources from user data, author `app.yaml`, prepare a higher-SemVer code/config release, create a persistent-data-only DataPatch ZIP, or guide the upload and manual publish workflow.
---

# App Deployer Micro App Creator

Create or modify application repositories; do not modify App Deployer itself unless the user explicitly asks. Preserve existing business behavior and data while bringing the application to the platform contract.

## Establish the source of truth

1. Read the target project's `AGENTS.md` files and inspect its worktree before editing.
2. Resolve the live App Deployer root in this order:
   - a path supplied by the user;
   - `APP_DEPLOYER_DIR`;
   - a sibling `app-deployer` directory near the target project;
   - `C:\Users\qizha\Documents\codex_project\app-deployer` when present.
3. When the live root exists, completely read `docs/DEVELOPMENT_STANDARD.md`, `docs/APP_MANIFEST.md`, and the target app's current `app.yaml`. For a DataPatch, also completely read `docs/DATA_UPDATE.md`. Treat live code and schemas as newer than this skill.
4. If upload/update behavior is ambiguous, inspect `internal/manifest`, `internal/archive`, `internal/datapatch`, and `internal/control/server.go`; do not infer platform behavior from generic Docker conventions.
5. Always read [references/DATA_SAFETY.md](references/DATA_SAFETY.md) for a new app, retrofit, stateful update, or DataPatch. This skill's fail-closed user-data policy remains mandatory even when live platform documentation is less strict.
6. Always read [references/release-hardening.md](references/release-hardening.md) before implementing or packaging a code release. It contains failure modes that static validation alone does not catch.
7. If the live root is unavailable, read [references/platform-contract.md](references/platform-contract.md), [references/APP_MANIFEST.md](references/APP_MANIFEST.md), and [references/app.schema.json](references/app.schema.json). For a DataPatch, also read [references/DATA_UPDATE.md](references/DATA_UPDATE.md) and [references/data-update.schema.json](references/data-update.schema.json). Explicitly report that current platform drift was not checked.
8. When the user asks how to install or invoke this skill, read [references/USAGE_GUIDE.md](references/USAGE_GUIDE.md).

## Classify the request

Use one primary path:

| Request | Required path |
|---|---|
| Build a new app | Create a compliant repository and first SemVer code release |
| Make an old app compatible | Audit first, preserve behavior/data, then retrofit |
| Change code, HTML, CSS, JS, templates, image assets tied to code, `app.yaml`, or production env values | Create a higher SemVer code release |
| Change only files under an active manifest's `persistence.mutablePaths` | Create an independent DataPatch revision; do not change app SemVer |
| Upload or publish an artifact | Require explicit authorization; keep upload/validation separate from manual publish/cutover |

If a request mixes code and mutable data, make a code release. Include seed data only for first initialization; never use it to overwrite live data.

## Run the audit before changing code

Execute the bundled read-only scanner:

```text
python <skill-dir>/scripts/audit_microapp.py <project-dir> --format markdown
```

An initial audit of a file-persistent app may intentionally fail with an inventory-required error. Do not suppress it; complete the classification and rerun with the safety flags below. Then trace actual runtime entrypoints, lockfiles, listen host/port, routes, root-relative URLs, API clients, redirects, downloads, Cookie paths, secrets, persistent writes, startup initialization, health behavior, framework route canonicalization, runtime UID/GID, Dockerfile `COPY --chown`, and all user-facing entrypoints. Treat scanner warnings as leads, not proof.

For a retrofit, record an evidence-based ledger with: current behavior, contract gap, planned change, data migration impact, rollback, and verification. Stop for user confirmation only when a choice changes the data model, permissions, user flow, identity, route identity, persistence boundary, or external backup strategy.

## Pass the user-data safety gate

Before writing `app.yaml`, migrating data, or building a DataPatch, produce the data inventory from [references/DATA_SAFETY.md](references/DATA_SAFETY.md). For every persistent path record its producer, readers/writers, source of truth, retention requirement, update mechanism, deletion authority, and backup/restore evidence.

Classify unknown or mixed data as protected user data. Apply these rules without exception:

- User-only state uses `persistence.mode: files`, `/app/data`, and an omitted or empty `mutablePaths`.
- Operator-managed resources and user-generated state must use disjoint subtrees. Only the exact operator-managed subtrees may enter `mutablePaths`.
- Never declare a user database, upload, submission, account, session, order, generated-user-output directory, or any ancestor containing protected data as mutable.
- If one file or database mixes operator-managed records with user records, forbid DataPatch for it. Separate the storage or use an application-level transactional import with business validation.
- Treat a broad or uncertain mutable path as a blocker. Do not solve uncertainty by widening the allowlist.

After classification, rerun the scanner with every known boundary:

```text
python <skill-dir>/scripts/audit_microapp.py <project-dir> --data-inventory <completed-inventory.json> --format markdown
```

The manifest's mutable paths must exactly match inventory paths marked `dataPatchAllowed: true`, and no protected path may overlap them. Manual repeated `--operator-managed-path` and `--protected-path` flags remain available only while drafting the inventory; use `--no-protected-data` only when the completed analysis proves none exists.

## Apply the application contract

Always read [references/platform-contract.md](references/platform-contract.md) and [references/APP_MANIFEST.md](references/APP_MANIFEST.md) before implementing. Use [references/app.schema.json](references/app.schema.json) for editor or CI validation when the live schema is unavailable.

1. Make dynamic services listen on platform `HOST` and `PORT`; the container must accept `0.0.0.0` traffic.
2. Prefer `route.mode: native`. Make pages, assets, APIs, redirects, downloads, generated links, service-worker scope, and Cookie Path honor `APP_BASE_PATH`. Use `static-strip` only for a truly static site whose URLs are all relative.
3. Read business configuration only from environment variables. Declare names and types in `spec.env`; never commit real `.env` values or secret defaults. Do not redeclare platform-reserved variables.
4. Add an unauthenticated, side-effect-free GET health endpoint. Keep smoke tests read-only (`GET` or `HEAD`).
5. Declare every user-facing entrypoint. Mark at most one primary entrypoint.
6. Classify persistence honestly:
   - use `none` only when no state must survive a container replacement;
   - use `files` and exactly `/app/data` for platform-protected file state;
   - use `seed/data` only when initializing an empty data directory;
   - default `mutablePaths` to empty and enable only exact, reviewed operator-managed subtrees;
   - keep user-generated and unknown data outside every mutable path.
7. Treat external MySQL/PostgreSQL, object storage, or state outside `/app/data` as a release blocker until the platform has a native backup/restore adapter. Do not describe filesystem copying as protection for external state.
8. Deliver root-level `app.yaml`, `Dockerfile`, `.dockerignore`, source, and lockfiles. Do not add uploader-controlled Compose, Nginx, shell deployment instructions, host ports/mounts, `privileged`, host network, or Docker Socket access.
9. Keep the App Deployer package runtime-specific, not cloud-provider-specific: remove Cloudflare/Wrangler/Workerd/Vinext/Vite Cloudflare plugin runtime dependencies unless intentionally required and proven under App Deployer; avoid slow external registries and unused dependency trees; configure domestic Docker/package sources when the deployment network requires them.
10. For file-persistent apps, design for the platform security model: `/app/data` is a platform bind mount; do not recursively modify protected data at startup; do not rely on root capabilities when the platform uses `cap_drop: ALL`; make final runtime files readable by the configured runtime user/group; use a cooperative umask for newly created data files.

Start manifests from [assets/app-native.yaml](assets/app-native.yaml) or [assets/app-static-strip.yaml](assets/app-static-strip.yaml), and start `.dockerignore` from [assets/dockerignore.template](assets/dockerignore.template). Replace every example value and remove unused declarations.

## Handle each workflow

Read [references/workflows.md](references/workflows.md) for the selected path.

### New application

Implement the smallest suitable stack, its tests, `app.yaml`, Dockerfile, and `.dockerignore`. Keep framework-native lockfiles. Complete the data inventory first, keep `mutablePaths` empty unless independent operator-managed resources are proven, and add base-path and persistence tests before packaging.

### Existing application retrofit

Preserve existing behavior and user data. Inventory the live data before migration, separate operator-managed resources from user state, and never place a shared ancestor in `mutablePaths`. Migrate writes to `/app/data` with an explicit one-time migration and rollback plan. Initialize from `seed/data` only when `/app/data` is empty. Do not replace the application with a rewrite merely to satisfy packaging.

### Code or configuration update

Read the deployed/current manifest before editing. Keep `metadata.name`, `spec.route.path`, `spec.route.mode`, and `spec.persistence.mode` unchanged for an existing application; the platform rejects changes to the last three app invariants. Raise `metadata.version` above the platform's latest release using SemVer. If route identity or persistence mode must change, stop and plan a new application identity or an explicit platform migration. Environment values are release-scoped; if a published release has a wrong secret or business environment value, create a strictly higher SemVer release from the same code and fill the environment form again instead of editing server files or platform records.

### Data-only update

Confirm that the application is active, uses `persistence.mode: files`, and that the active manifest allows the exact target. Rebuild the data inventory from the active runtime and prove that the target contains only operator-managed resources. If ownership is mixed or unknown, stop; do not generate a patch. If the target is not allowed, first ship and activate a higher-SemVer code release that declares only the reviewed subtree.

Read [references/DATA_UPDATE.md](references/DATA_UPDATE.md) and [references/data-update.schema.json](references/data-update.schema.json) before creating the patch when the live specification is unavailable.

Build a canonical patch with:

```text
python <skill-dir>/scripts/build_data_patch.py --app <metadata.name> --revision <data-revision> --target <allowed-relative-target> --active-manifest <active-app.yaml> --data-inventory <completed-inventory.json> --files <directory-to-place-under-target> --delete <relative-path-if-needed> --confirm-delete --description <short-description> --output <artifact.zip>
```

Start the inventory from [assets/data-safety-inventory.json](assets/data-safety-inventory.json), replace every sample value, list every protected and operator-managed persistent path, set `complete: true` only after review, and keep it outside the application/DataPatch ZIP as delivery evidence. The builder requires the exported active manifest, verifies app/version/persistence, requires its mutable paths to exactly equal inventory paths with `dataPatchAllowed: true`, rejects protected overlap, and writes an external `.safety.json` evidence sidecar. Omit `--files` for deletion-only patches; repeat `--delete` as needed, and pass `--confirm-delete` only after the user explicitly approves the exact deletion list. Add `--validate-json` when every uploaded payload must be a syntactically valid UTF-8 JSON file. Never infer deletion from a missing file. Treat every uploaded path as a possible overwrite of the same live path; compare against the current target and report additions versus replacements. Never include code, `app.yaml`, or paths outside `data-update.yaml` and `files/`. The builder validates revision syntax, not platform uniqueness; confirm that the revision is unused in the target application's control-plane records before upload.

## Verify and package

Read [references/verification.md](references/verification.md) before reporting completion.

1. Run the project's native tests, syntax checks, and build with its pinned runtime.
2. Re-run `audit_microapp.py` with the classified operator-managed and protected paths. Resolve every hard error and review each heuristic finding against actual code.
3. Use the live `deployctl` contract:

```text
deployctl validate <project-dir>
deployctl env-example -o <project-dir>/.env.example <project-dir>
deployctl build [--env-file <local-nonproduction-env>] <project-dir>
deployctl pack -o <output.zip> <project-dir>
deployctl validate <output.zip>
```

4. Run `deployctl smoke --base-url <public-scheme-and-domain> <project-dir>` only against an explicitly authorized deployed target.
5. Re-run the release-hardening checks from [references/release-hardening.md](references/release-hardening.md): dependency/source drift, Dockerfile runtime ownership, `/app/data` behavior, health side effects, base path, trailing slash behavior, Router versus browser URL usage, secret-link parsing, and release-environment immutability.
6. Inspect the final ZIP listing, SHA-256 sidecar, and Git diff. Ensure no secret, production data, `.git`, `node_modules`, `.next`, local cache, Compose, root Nginx configuration, Cloudflare/Wrangler deployment files, or data-safety evidence sidecars entered the package.
7. Do not claim Docker, Nginx, public-route, browser, data-backup, or rollback validation unless each was actually exercised.

## Upload and publish safely

Treat artifact creation as the default endpoint. Upload or publish only when the user explicitly requests that external mutation.

- Code ZIP upload validates and creates a `READY` release; a new name creates the application, while an existing name requires a strictly higher SemVer and unchanged route/mode/persistence identity.
- Complete the new release's environment form without exposing secrets. An active release cannot be edited or republished in place.
- DataPatch upload validates and creates `READY`; it does not change live data until the separate “发布数据” action.
- Never turn “upload” into “publish.” A publish action performs the real cutover and must remain explicit.
- After an authorized publish, wait for the terminal state and report job steps, backup verification for stateful apps, health, public smoke, and any remaining browser acceptance.

## Handoff

Report: selected workflow, changed files, app SemVer or DataPatch revision, environment variable names only, entrypoints, the completed data inventory, protected paths, exact mutable paths, overwrite/delete review, persistence/migration impact, artifact path and SHA-256, validations actually run, environment blockers, and manual/production checks still outstanding. Never include secret values.
