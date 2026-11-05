# Publish a code or configuration release over HTTP

Use this workflow for authorized code/config ZIP uploads and releases on App Deployer. For DataPatch, use the separate data workflow in [workflows.md](workflows.md). Follow the main skill’s access-control, stateful backup, and production verification requirements.

## Before using the console

- Console base (`BASE`) is `https://micro.xfwings.com/deployer`. App URLs use the route from `app.yaml`.
- Read `DEPLOYER_USERNAME` and `DEPLOYER_PASSWORD` from the release environment or use the operator’s existing vault or credential file on the release host. If missing, ask the operator to supply it through that secure channel. Keep passwords and session cookies out of chat, memory, repositories, command output, and task artifacts.
- Confirm whether the user authorized upload, production publish, or both for the specific package or version. Identify the intended application and confirm the package’s `metadata.name`, version, and SHA-256. Keep the ready ZIP on the release host when possible. For an existing app, use the known application ID when verifying the upload response.
- Preserve a user-provided package as delivered. If it fails validation, report the issue. Build or change a package only when requested and obtain authorization for the resulting release.
- For an access-controlled app, confirm the exact application and policy AppIDs, callback, provider environment, and active tags. Preserve the bootstrap upload-only path when a new application ID is needed.

## HTTP procedure

Use Python `urllib` with `http.cookiejar` or `curl` with a protected cookie jar. For browser-style headers, set `Origin: https://micro.xfwings.com` and `Referer: https://micro.xfwings.com/deployer/`. Keep TLS verification enabled.

1. **Login.** Open `GET {BASE}/login`. Submit `POST {BASE}/login` as `application/x-www-form-urlencoded` with `username` and `password`. Store the session cookie and confirm an authenticated console page. Stop on a login redirect or rate limit.
2. **Upload if requested.** Send `POST {BASE}/apps/upload` with a multipart field named `package` and the ZIP filename. Allow a timeout suitable for the ZIP size. Get the application ID from the redirect or final `/apps/<app-id>` URL and verify it against the intended application. After an ambiguous timeout, inspect the app’s releases before considering another upload.
3. **Resolve the release.** Read `GET {BASE}/apps/{app_id}` and find the unique release row matching both the authorized version and the ZIP’s SHA-256 prefix shown in the console. Capture the release ID from the row’s `/releases/<release-id>/publish` form or release link. For a fresh upload, wait briefly for the matching row to become `READY`. Stop if the app, version, checksum, or release ID cannot be confirmed. End here for upload-only requests.
4. **Save release configuration when needed.** Use the console form or submit `POST {BASE}/apps/{app_id}/config` with `releaseId={rid}` and the authorized `env_<NAME>` fields declared in `app.yaml`. Verify the save succeeded. Use the form’s supported handling for existing secrets and obtain any missing required values through the approved secure source. Resolve a failed access-control preflight before continuing.
5. **Publish the verified release.** If it is already `ACTIVE`, verify it and report that state. If it is already deploying, find and monitor the existing job. For a new release in `READY`, submit `POST {BASE}/releases/{rid}/publish` and capture the job ID from the `/jobs/<job-id>` redirect. If the result is unclear or no job ID is returned, read the app and job records before doing anything else. Report failed releases and seek explicit direction for a retry. Rollback requires explicit authorization for the target version.
6. **Monitor the job.** Poll `GET {BASE}/jobs/{jid}` every 5–10 seconds. On `FAILED`, report the failed step and relevant redacted diagnostics. On `SUCCEEDED`, confirm the intended version is `ACTIVE`. If progress stalls for about 10 minutes, notify the user and keep monitoring within the agreed wait window. If the job remains in flight when the window ends, report its ID and last observed status.
7. **Verify production.** Once `SUCCEEDED` and `ACTIVE` are confirmed, notify the user with the version, URL, release ID, job ID, and ZIP SHA-256. Then check the documented health endpoint and key entrypoints using read-only requests. Verify the required backup for stateful apps and the expected private-session redirect for access-controlled apps. Report the exact checks performed.

If the HTTP workflow is blocked and the signed-in console works, use the corresponding console action for the same authorized package or release after checking for an existing upload or job.

## Release tracking when authorized

If the user authorizes issue tracking, use the project and credentials configured for the team. Create a requirement issue for a new app or update the existing issue for a follow-up. After go-live, record the release and update or close the issue within the authorized scope. Report any tracking access blocker separately from the production release result.
