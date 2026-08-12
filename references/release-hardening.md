# Release hardening and failure modes

Use this file before creating or retrofitting any App Deployer micro app, and again before packaging. It records platform rules that are easy to miss when a local app appears to work.

## Hardening checklist

1. Keep the application model boring unless the business need proves otherwise.
   - Prefer ordinary HTTP servers and framework production output such as Next.js standalone, static files, Go, PHP, or a small Node server.
   - Do not keep Cloudflare Worker, Wrangler, Workerd, Vinext, Vite-plugin-cloudflare, Pages, root Nginx, Compose, host port, or tunnel deployment code in the active runtime for App Deployer packages unless the app truly needs them and the App Deployer contract was verified around it.
   - If such files remain only as historical docs, ensure they are excluded from the ZIP and not imported by runtime/build code.

2. Bound server-side build cost.
   - Assume the publisher can kill long image builds. Avoid dependency downloads or framework builds that can exceed the platform timeout.
   - Use the project-pinned runtime and a lockfile. Keep runtime dependencies minimal.
   - For deployments in China or when the user requests domestic sources, configure Docker base images and package registries explicitly, and verify lockfile resolved URLs do not silently point back to blocked public registries.
   - Exclude generated directories such as `node_modules`, `.next`, `dist`, and local package caches when they are validation output and not intended source.

3. Treat `/app/data` as a platform-owned bind mount.
   - Put persistent file state only under `/app/data`; put scratch files under `/tmp`.
   - Do not recursively `chown`, `chmod`, delete, or rewrite `/app/data` or its descendants at container startup.
   - Do not assume `USER 0` can bypass permissions: the platform can run containers with `cap_drop: ALL` and `no-new-privileges`.
   - Ensure runtime files copied into the image are readable by the configured runtime user/group. Do not copy final runtime files as an unrelated user such as `node:node` while running as a different numeric UID/GID.
   - For file-persistent apps, set a cooperative umask such as `0007` when creating SQLite/WAL/uploads so the platform data group can back up and restore them.
   - If the data root itself is inaccessible, classify it as a platform data-access problem; do not hide it by returning a fake healthy response.

4. Make health and smoke checks honest and side-effect-free.
   - Health must be unauthenticated GET and must not create directories, databases, tables, seed files, sessions, submissions, or cache entries.
   - It may read metadata and attempt read-only access to already initialized protected storage.
   - Smoke tests must be GET or HEAD only and must not submit forms, create users, mutate state, or consume one-time tokens.

5. Verify the full prefixed URL chain.
   - In `native` mode, the browser sees `APP_BASE_PATH`; the upstream app must handle prefixed assets, APIs, redirects, downloads, generated links, cookies, and service-worker scope.
   - Framework routers often expect internal application paths. For example, Next Router navigation should use `"/success"` or `"/?edit=1"`, while `fetch`, `<img>`, `<a href>`, redirects crossing the browser boundary, and download URLs may need base-path-aware helpers.
   - Test both the public route root with and without trailing slash. If the platform Nginx canonicalizes the app root to a trailing slash, align the framework canonical URL, for example with `trailingSlash: true` in Next.js.
   - A request reaching the server is not enough. Verify the final browser-visible DOM/page, network redirects, cookie path, and downloaded URL.

6. Handle secret links and release environment immutability.
   - Declare environment variable names only; never package real values.
   - Prefer query parameters for one-time internal entry links when the client must read them on first load. Hash fragments do not reach the server and can be unavailable to server-side checks. If legacy hash links exist, support both query and hash.
   - A published release's environment values are immutable. If an environment value is wrong, create a strictly higher SemVer release from the same code and fill the environment form again.

7. Preserve application identity for updates.
   - For an existing app, keep `metadata.name`, `route.path`, `route.mode`, and `persistence.mode` unchanged.
   - Every source, Dockerfile, manifest, code-coupled asset, or production environment-value change is a new higher SemVer code release.
   - DataPatch is only for exact operator-managed paths already allowed by the active manifest. It never changes code or SemVer.

## Failure-mode ledger to reproduce before fixing

When a deployed candidate fails, identify which layer failed before changing code:

| Symptom | Likely layer | Evidence to collect | Correct response |
|---|---|---|---|
| `BUILD_FAILED ... signal: killed` | Image build timeout/OOM | build duration, Dockerfile build steps, dependency count, registry hosts | Reduce build cost, fix registry sources, prebuild intentionally, or simplify runtime; do not treat it as a business-code exception. |
| Candidate container disappears from Docker DNS | Process startup crash | `docker inspect`, `docker logs`, entrypoint import errors | Make startup robust enough to expose a clear 503 only when appropriate; fix the crash root cause. |
| `/health` returns 503 with storage error | Persistence access | health logs, `/app/data` ownership/mode, runtime UID/GID, platform data group | Fix app user/file ownership if image-internal; fix App Deployer data-root migration if bind mount root is wrong. |
| `EACCES` reading image files such as start scripts | Image file ownership | final Docker layer `COPY --chown`, runtime `USER`, platform security options | Align final runtime file owner/group with runtime UID/GID; do not rely on root capabilities. |
| Public smoke reports too many redirects | Route canonicalization | response chain for app root with and without slash, framework trailing slash config, generated Nginx | Align framework root slash behavior to platform canonical URL. |
| After form submit URL repeats the base path | Client router misuse | source lines using router plus base-path helper | Use framework-internal paths for router navigation; keep base-path helpers for browser/network URLs. |
| Internal secret link says expired/invalid | Link parsing/session | Network: session endpoint absent/401/200; query vs hash token; cookie path | Prefer `?access=`, keep hash compatibility, verify session cookie path and follow-up API request. |
| Upload succeeds but changes do not appear | Control-plane state | release state `READY` vs `ACTIVE`, publish job status | Explain that upload is not publish; explicit publish/cutover is required. |
| Published environment cannot be edited | Release immutability | active release env form/state | Ship a new higher SemVer package with the same code and refill env values. |

## App Deployer platform repair boundary

Only modify App Deployer itself when the user explicitly asks or evidence proves the platform is the failing layer.

- Platform source directory and runtime data directory can have similar names; verify exact paths before giving commands.
- Platform installers may need a one-shot scoped migration such as `DATA_ACCESS_MIGRATION_APP=<app-name>` to repair exactly one app data root. Keep this as a process environment override, not a persistent global policy.
- A platform data-root repair must change only the mount boundary required for publishing. It must not recursively modify SQLite files, WAL files, uploads, submissions, sessions, or user-generated descendants.
- Runner-side data-root checks should fail closed with a clear code such as `DATA_ACCESS_FAILED` when a root-owned or otherwise noncompliant data root cannot be safely repaired by the runner.
