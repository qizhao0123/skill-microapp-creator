# Verification and handoff

## Resolve deployctl

Prefer the validator built from the live App Deployer source. From its root, run:

```text
go run ./cmd/deployctl <command> ...
```

If Go is unavailable, use a current `bin/deployctl.exe`, `bin/deployctl`, or server-provided binary and state which build was used. Do not silently validate against a stale binary when live source has changed.

## Verification ladder

Run the applicable levels in order and report them separately:

1. Project checks: pinned runtime, native unit tests, syntax/lint, build, migration/seed tests.
2. Static contract: `audit_microapp.py`, live schemas, `deployctl validate <project>`.
3. Container: check `docker version`, then `deployctl build [--env-file ...] <project>`. This builds an image, injects platform variables, mounts `/app/data` when needed, and checks health from a peer container.
4. Package: `deployctl pack`, `deployctl validate <zip>`, archive listing, SHA-256 comparison, and secret scan.
5. Deployed route: authorized `deployctl smoke --base-url <scheme-and-domain> <project>` after deployment.
6. Browser/business: real prefixed entrypoints, assets, APIs, redirects, downloads, auth cookies, user-visible results, and supported devices.
7. Stateful operations: actual verified backup, failure recovery, and rollback drill on the target server.

If Docker reports `open //./pipe/docker_engine: The system cannot find the file specified`, classify Docker Desktop/daemon as unavailable. Keep static checks, and list container/Nginx/public verification as outstanding.

## Application package commands

From the live App Deployer root, replace placeholders with absolute paths:

```text
go run ./cmd/deployctl validate <project>
go run ./cmd/deployctl env-example -o <project>/.env.example <project>
go run ./cmd/deployctl build --env-file <nonproduction-env> <project>
go run ./cmd/deployctl pack -o <artifact.zip> <project>
go run ./cmd/deployctl validate <artifact.zip>
go run ./cmd/deployctl smoke --base-url https://micro.xfwings.com <project>
```

Omit `--env-file` if the application has no required business environment values. Never use production secrets for local build validation.

## Required evidence

For code releases, retain:

- app name and SemVer;
- route/mode/persistence identity comparison to the latest release;
- project test output;
- `deployctl validate`, build, pack, and final ZIP validation output as actually run;
- artifact absolute path, bytes, SHA-256, and ZIP root listing;
- environment variable names, entrypoints, and data directories without secret values.

For DataPatches, retain:

- active app name and active manifest evidence;
- target-to-`mutablePaths` match;
- revision syntax plus control-plane uniqueness evidence, uploaded files, and explicit deletions;
- artifact absolute path, bytes, SHA-256, and ZIP root listing;
- confirmation that no source/app manifest files are present.

## Honest final status

Separate:

- implemented and statically checked;
- container-validated locally;
- uploaded and `READY`;
- published and terminally successful;
- real Nginx/public-route/browser/device/data-backup/rollback acceptance.

Do not turn an earlier level into evidence for a later level.
