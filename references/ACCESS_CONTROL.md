# Access control contract

Use this reference whenever `spec.accessControl.enabled` is true, when creating the matching learning-platform authorization record, or when diagnosing an app that appears publicly reachable.

## Keep four identities separate

| Identity | Source | Purpose |
|---|---|---|
| App Deployer application ID | Control-plane application record and `/deployer/apps/<id>` URL | Stable internal application identity; currently a 32-character hexadecimal value |
| `metadata.name` | `app.yaml` | Package/release identity and gateway application lookup |
| `spec.route.path` | `app.yaml` | Public URL prefix only |
| `spec.accessControl.appId` | `app.yaml` and learning-platform policy record | Exact provider policy key sent as both `appId` and `app_id` |

The provider lookup is exact. A schema-valid route slug or `metadata.name` is not interchangeable with the provider AppID. In the current deployment convention, use the 32-character App Deployer application ID for the learning-platform policy and `spec.accessControl.appId` unless live provider documentation or an existing verified policy explicitly establishes another identifier convention.

Before packaging, record all four values from evidence and run:

```text
python <skill-dir>/scripts/audit_microapp.py <project-dir> \
  --require-access-control \
  --expected-access-app-id <exact-policy-id> \
  --format markdown
```

Do not infer `<exact-policy-id>` from the route or package name.

## Manifest

```yaml
spec:
  accessControl:
    enabled: true
    provider: learning-platform
    appId: <exact-policy-id>
```

When enabled, `provider` must be `learning-platform` and `appId` must match `^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$`. Those syntax checks do not prove that the policy record exists or that the identifier is correct.

Omitting `accessControl` or setting `enabled: false` preserves public access behavior. Creating only a policy record does not protect an app whose active manifest has access control disabled.

Any access-control change is a code/config release and requires a SemVer strictly greater than the latest uploaded release. A historical version cannot be overwritten.

## Existing application workflow

1. Read the control-plane application record and copy its application ID.
2. Read the active/latest manifest and record `metadata.name`, `spec.route.path`, and current access-control values.
3. Create or update the learning-platform policy with the exact chosen AppID, active status, and at least one active tag.
4. Put the same exact AppID in `spec.accessControl.appId`; do not use the route slug as a shortcut.
5. Set the callback to `<scheme>://<host><route.path>/__app-deployer-access/callback`, with no trailing slash or query string.
6. Raise SemVer, audit with `--expected-access-app-id`, validate, package, upload, and explicitly publish.
7. Treat publish preflight and private-browser acceptance as separate required checks.

## New application bootstrap

When the provider convention requires the generated App Deployer application ID, that ID does not exist until the first upload. Use two immutable release versions:

1. Build and validate a bootstrap package that establishes the final `metadata.name`, route, mode, and persistence identity.
2. Upload it only far enough to create the application and a `READY` release. Do not publish a public placeholder release.
3. Copy the new application ID from the control plane.
4. Create the learning-platform policy using that exact ID and the exact generated callback URL.
5. Create a strictly higher-SemVer package with `accessControl.enabled: true` and the exact ID.
6. Audit, upload, publish, and test the final package.

If the provider explicitly supports a preselected logical ID, it may be used only after recording that decision and proving the backend policy uses the same value. Never silently switch identifier conventions.

## Control-plane prerequisites

The App Deployer service, not the microapp container, calls the learning platform. The selected App Deployer environment profile must provide:

```text
LEARNING_PLATFORM_AUTHORIZE_URL
LEARNING_PLATFORM_TOKEN_URL
LEARNING_PLATFORM_POLICY_URL
LEARNING_PLATFORM_CLIENT_ID
LEARNING_PLATFORM_CLIENT_SECRET
LEARNING_PLATFORM_GATEWAY_UPSTREAM
LEARNING_PLATFORM_SESSION_TTL
LEARNING_PLATFORM_REQUEST_TIMEOUT
```

Keep values and secrets in the environment/profile store, not the app package or handoff. Derive `LEARNING_PLATFORM_GATEWAY_UPSTREAM` from the actual API service name and network for that profile; do not copy a development container name into production.

A server may start while these values are absent because public apps do not use the provider. An enabled release calls provider validation during publish and fails closed when the configuration is incomplete.

## Generated gateway behavior

For route `<route>`, the platform generates:

```text
<route>/__app-deployer-access/check      # internal Nginx auth subrequest
<route>/__app-deployer-access/login
<route>/__app-deployer-access/callback
```

The app route uses `auth_request` before proxying to the microapp. The public callback field is exactly:

```text
<scheme>://<host><route>/__app-deployer-access/callback
```

The internal check endpoint is not a public business endpoint. Do not diagnose it by expecting a normal browser page.

## Fail-closed boundaries

- `deployctl validate` and ZIP validation check manifest shape only; they do not call the policy service.
- Publish preflight blocks when the provider configuration is missing, the policy request fails, the policy is missing or disabled, or no active tags exist.
- TLS certificate expiry or hostname/trust failures are provider/platform blockers. Never disable certificate verification or change to insecure HTTP as a workaround.
- Existing valid access-session cookies may remain valid until `LEARNING_PLATFORM_SESSION_TTL` expires. Use a private window or clear only the app authorization cookie when testing first access.
- Policy changes after publish affect new authorization checks, but the generated Nginx gateway exists only when the active manifest enabled access control.

## Diagnostic matrix

| Symptom | Most likely boundary | Check |
|---|---|---|
| Policy request contains a route-like AppID | Manifest/provider identity mismatch | Compare policy record, application ID, and `spec.accessControl.appId` exactly |
| App opens directly and reserved login/check paths return app JSON/404 | Active Nginx config has no generated access gateway | Confirm active manifest enabled access control, release was republished, and renderer/config were current |
| Upload validates but publish fails | Provider preflight | Inspect environment completeness, policy state/tags, AppID, TLS, and provider response |
| App still opens after policy removal | Existing session | Retest in a private browser and account for session TTL |
| `x509` expired/not-yet-valid | Provider certificate or clock | Repair certificate/time; do not bypass TLS |
| Redirect reaches the wrong host/path | Callback/profile mismatch | Compare forwarded scheme/host, route, and exact callback field |

## Acceptance evidence

Retain and report:

- the four identity values and their sources;
- manifest/policy AppID equality;
- callback URL equality;
- enabled policy status and active-tag evidence, without user-sensitive policy data;
- names of all required control-plane environment variables, never secret values;
- static audit and `deployctl validate` results;
- publish-preflight result;
- generated Nginx/gateway behavior or deployed redirect result;
- private-browser unauthorized and authorized outcomes;
- any unperformed environment, publish, or browser checks.
