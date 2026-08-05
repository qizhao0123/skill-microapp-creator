# User data safety gate

Use this policy for every new app, retrofit, stateful code update, and DataPatch. It is intentionally stricter than the platform schema. The platform protects paths and backups; it cannot infer business ownership inside a file or database.

## Mandatory inventory

Complete this table from requirements, source code, the active manifest, and live storage evidence before selecting persistence or `mutablePaths`:

| Path or external store | Data examples | Producer | Readers/writers | Source of truth | Must survive release | Update mechanism | Delete authority | Backup/restore evidence | Classification |
|---|---|---|---|---|---|---|---|---|---|
| `/app/data/...` | | user, app, operator, import | | | yes/no | code release, DataPatch, app API, never | | | operator-managed, protected, seed, temporary, external |

Do not guess missing cells. Classify an unknown path as protected until evidence proves otherwise.

## Classifications

- **Stateless/code-coupled**: no state must survive replacement. Use `persistence.mode: none`; update through a higher-SemVer application ZIP.
- **Seed**: initial non-production data copied from `seed/data` only when `/app/data` is empty. Never use seed data to update a live app.
- **Operator-managed mutable resource**: reports, reference JSON, PDFs, CSVs, or business images whose complete lifecycle is controlled by an authorized operator. Store in a dedicated subtree and allow only that exact subtree in `mutablePaths`.
- **Protected state**: user uploads, submissions, profiles, accounts, sessions, orders, user-generated reports, application databases, audit records, or any unknown/mixed state. Persist under `/app/data`, but never declare it or an ancestor as mutable.
- **External state**: a database, object store, or service outside `/app/data`. Block the protected-release claim until native backup and restore exist.

An application that only reads operator uploads is still stateful when those resources must survive code releases. An application that only creates user data uses `files` with an omitted or empty `mutablePaths`.

## Safe layouts

User-data-only application:

```yaml
persistence:
  mode: files
  containerPath: /app/data
  mutablePaths: []
```

Mixed application:

```text
/app/data/resources/   operator-managed; DataPatch allowed
/app/data/uploads/     protected user data
/app/data/db/          protected application database
```

```yaml
persistence:
  mode: files
  containerPath: /app/data
  mutablePaths:
    - resources
```

Never declare `uploads`, `db`, or a shared parent containing `resources` plus protected paths. If operator and user records share one SQLite database, JSON file, or directory, DataPatch is forbidden. Separate them or implement a transactional application import that validates business keys, ownership, referential integrity, and rollback.

## DataPatch safety review

Treat the platform operation as file-level overlay, not a semantic merge:

- uploading an existing relative path replaces its complete contents;
- `spec.delete` recursively removes the declared relative file or directory;
- a missing payload path does not delete the live path;
- JSON validation checks syntax only unless a domain-specific schema/test is also run;
- upload creates `READY`; publish performs the real mutation;
- the platform backs up all of `/app/data` and restores on technical failure, but a logically wrong patch may pass health and smoke checks.

Before building a patch:

1. Read the active manifest and current target inventory.
2. Copy [`assets/data-safety-inventory.json`](../assets/data-safety-inventory.json), replace every sample value, list all operator-managed and protected persistent paths, and set `complete: true` only after review. Keep this evidence file outside the application and DataPatch ZIPs.
3. Prove the target is operator-managed and disjoint from every protected path.
4. List each payload as `new`, `replacement`, or `unknown`; block `unknown` until inspected.
5. Require explicit user approval for every replacement that changes meaning and every deletion.
6. Run domain validation for structured data; JSON parsing alone is insufficient.
7. Retain the generated `.safety.json` sidecar, the pre-publish backup identifier, and a tested restore path for production publication.

## Fail-closed outcomes

- Empty `mutablePaths`: do not create or upload a DataPatch, even if the UI shows an upload entry. Report that the server will reject it.
- Mixed or unknown target ownership: stop and propose separation or an application-level import.
- Protected path overlaps a mutable path in either direction: reject the manifest or patch.
- No active-manifest evidence: do not assume a local `app.yaml` authorizes a live data update.
- Incomplete or version-mismatched inventory: do not build the patch.
- No business validation or deletion approval: artifact creation may proceed only after the missing evidence is supplied; publication remains separately authorized.
