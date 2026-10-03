# Protected Cloudflare Access deployment

The application listens on 127.0.0.1. Public access is optional and fail-closed; a configured public Host alone never authorizes workspace access.

## Required local settings
- `WORKOS_PUBLIC_ORIGIN`: exact HTTPS origin (for example, `https://workos.example.com`).
- `WORKOS_ACCESS_TEAM`: your existing Cloudflare Zero Trust team subdomain, not an arbitrary URL.
- `WORKOS_ACCESS_AUD`: audience (AUD) of the specific Access application.
- Existing Python must provide `PyJWT` and `cryptography` for public authentication. Missing optional dependencies deny public requests; local use still works.

## Account prerequisites
1. Create a Self-hosted Access application covering the entire hostname, including `/api/*` and downloads.
2. Apply an Allow policy limited to approved users via an appropriate identity provider. Do not create public bypass policies.
3. DNS must point at a dedicated WorkOS tunnel, whose connector remains off until the Access policy is verified. Do not add a second conflicting connector to a shared tunnel.

Browser login alone does not give this agent an API token or browser automation session. The tunnel origin certificate is not proof of Access policy administration rights. Do not extract browser cookies or place API tokens/passwords in source code, commands, repository remotes or documentation.

## Origin enforcement
Cloudflare forwards the `Cf-Access-Jwt-Assertion` header after authenticating the user. The application checks RS256 signature against the specific team certs, issuer, application audience, expiry, issued-at and subject. It does not trust the email header alone. Public origins must be HTTPS and must pass existing CSRF checks for writes. Public signing keys are cached for at most five minutes. Tokens, email claims and raw key errors are never logged or returned.

## Verify before enabling external use
- Request `/api/bootstrap` and `/api/state` from outside without login: no workspace data may be returned.
- A forged assertion or email header must not grant access.
- Approved login must permit the intended UI/API/download routes; wrong-app and expired tokens must fail.
- Local application and OneDrive mirroring must remain healthy.
- A 404, a 401 or a login page alone is not proof of correctly configured Cloudflare Access; verify the actual policy and authenticated/anonymous behavior.

Cloudflare Access does not directly provide a custom local username/password database. A `workos-user` application account is a separate authentication design and must not be confused with an Access policy. Never reuse a password disclosed in chat for production access.
