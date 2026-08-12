# App Deployer platform contract

Use this as a bundled snapshot of `deploy.xzd5/v1`. Prefer the live App Deployer docs, schemas, and validators whenever available.

## Application identity and routing

- Set `apiVersion: deploy.xzd5/v1` and `kind: WebApp`.
- Match `metadata.name` against `^[a-z][a-z0-9-]{2,40}$` and use SemVer for `metadata.version`.
- Use a non-root, no-trailing-slash, URL-safe ASCII `spec.route.path`.
- Use `native` for dynamic services. Preserve the prefix when proxying and make the application consume `APP_BASE_PATH`.
- Use `static-strip` only for fully static content with relative asset/navigation URLs. The proxy strips the prefix.
- For an existing application, keep route path, route mode, and persistence mode unchanged. A new release version must be greater than the latest uploaded version.

## Runtime

The platform injects:

```text
HOST=0.0.0.0
PORT=<manifest container port>
APP_ENV=production
APP_BASE_PATH=<manifest route path>
APP_PUBLIC_URL=<public URL including route path>
APP_RELEASE_ID=<immutable release id>
```

- Listen on `HOST` and `PORT`; never require loopback-only binding.
- Handle SIGTERM and flush state within 30 seconds.
- Write logs to stdout/stderr and redact passwords, tokens, cookies, and environment dumps.
- Provide an unauthenticated, side-effect-free GET health path.
- Restrict smoke tests to GET/HEAD.
- Treat active release environment values as immutable. A wrong environment value requires a new higher-SemVer release and a new environment form; do not edit live release directories or platform records by hand.

## Environment declarations

- Declare business variables in `spec.env` with names matching `^[A-Z][A-Z0-9_]*$`.
- Allow types `string`, `integer`, `boolean`, `url`, and `enum`; require non-empty unique `options` only for `enum`.
- Never declare `HOST`, `PORT`, `APP_ENV`, `APP_BASE_PATH`, `APP_PUBLIC_URL`, or `APP_RELEASE_ID`.
- Never place defaults on secret variables.
- Keep values on the server. `.env.example` is non-production guidance; real `.env` files must not enter ZIPs or images.
- Treat a production environment-value change as a new higher-SemVer release because an active release cannot be modified in place.

## Persistence

- Use `persistence.mode: none` only for stateless apps; omit `containerPath` and `mutablePaths`.
- Use `persistence.mode: files` only with `containerPath: /app/data`.
- Put all file state under `/app/data`; put temporary files under `/tmp`.
- Treat `/app/data` as a platform bind mount. Do not recursively change its descendants at startup, and do not assume UID 0 has normal root capabilities when the platform drops capabilities.
- Put initial data under `seed/data` and copy it only when `/app/data` is empty.
- Use non-absolute, non-traversing, URL-safe relative `mutablePaths`. Do not duplicate, nest, or overlap them.
- Default `mutablePaths` to empty. Keep protected user state outside every mutable path and keep operator-managed resources in exact, disjoint subtrees.
- Never make a database, user upload/submission directory, or an ancestor containing protected data mutable. If user and operator records share one file, use an application-level transactional import instead of DataPatch.
- Keep code-coupled HTML, JS, CSS, templates, and assets in the code release. Put independently updated operator-managed reports, PDFs, CSVs, or business images in reviewed mutable paths.
- Treat external databases/object stores as unprotected until a native platform backup/restore adapter exists.

## Manifest fields

- Require `route`, `container.port`, `health`, `persistence`, and at least one `entrypoint`.
- Permit at most one primary entrypoint. Entrypoint keys use lowercase letters, digits, and hyphens.
- Keep entrypoint and health/smoke paths absolute relative paths such as `/`, `/admin/`, and `/health`.
- Keep resources within CPU `0.1..8`, memory `64m..16g`, and PIDs `32..4096`. Defaults are `1.0`, `512m`, and `256`.
- Treat the live `docs/app.schema.json` and `deployctl validate` as authoritative for all field details.

## Application ZIP

Place these files directly at ZIP root:

```text
app.yaml
Dockerfile
.dockerignore
<source and lock files>
seed/data/  # optional, first initialization only
```

Reject an extra outer directory, real `.env`/`.env.*` other than `.env.example`, root runtime `data`/`.data`, Compose files, root `nginx*.conf`, `.git`, `node_modules`, local build caches, `.next` unless intentionally shipped as a prebuilt artifact, Cloudflare/Wrangler deployment files unless intentionally required and validated, symlinks, special files, and path traversal. Platform limits include archive bytes, expanded bytes, file count, and per-file compression ratio.

The platform generates Compose and Nginx. Do not require host ports, arbitrary host mounts, `privileged`, host networking, or Docker Socket access.
