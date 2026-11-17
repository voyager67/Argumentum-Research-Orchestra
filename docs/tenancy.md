# Workspaces, identities, and role permissions

Argumentum's self-hosted API supports tenant-scoped workspaces and API credentials. It does not implement browser passwords, password reset, OIDC, SAML, SSO, MFA, SCIM, or a public identity provider. Operators provision workspaces and researchers use revocable bearer tokens.

## Credential types

| Environment variable | Purpose | Scope |
|---|---|---|
| `ARGUMENTUM_ADMIN_TOKEN` | Platform administrator bootstrap credential | Create/list/disable workspaces and use platform maintenance endpoints. It is not a workspace identity and cannot submit research runs. |
| `ARGUMENTUM_API_TOKEN` | Default-workspace owner bootstrap credential | Owner access to the pre-created `default` workspace. It is convenient for a single operator and initial setup. |

The initializer writes distinct high-entropy values to `.env`. Keep the file private and do not send either value to researchers. Database records store SHA-256 digests of bearer tokens, not the raw user-issued values. A newly created tenant owner token or user token is shown once in the create response; store it in an approved secret manager. The UI keeps its current bearer token in page memory only and clears it on refresh/disconnect.

To rotate the environment-managed default-workspace token, replace `ARGUMENTUM_API_TOKEN` with a new value and restart the API. When the replacement token is first used, the previous active bootstrap credential is deactivated. User-issued tokens are unaffected. For an immediate, auditable revocation independent of this lazy bootstrap rotation, use a user-issued credential and revoke it through the workspace credential API.

## Create a workspace

Use the platform administrator token only for platform administration:

```bash
export ARGUMENTUM_ADMIN_TOKEN="$(sed -n 's/^ARGUMENTUM_ADMIN_TOKEN=//p' .env)"
curl --fail-with-body http://127.0.0.1:8080/api/v1/admin/tenants \
  -H "Authorization: Bearer ${ARGUMENTUM_ADMIN_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"name":"Neuroscience Lab","slug":"neuroscience-lab"}'
```

The response contains `owner_token`. It is returned only when that owner credential is created. Copy it securely; the database stores its digest and cannot reveal it again. Do not paste tokens into tickets, chat, source control, or research manuscripts.

## Issue individual credentials

Use the tenant owner credential to create named credentials for people or services:

```bash
export WORKSPACE_OWNER_TOKEN="<owner_token_from_workspace_creation>"
curl --fail-with-body http://127.0.0.1:8080/api/v1/tenant/credentials \
  -H "Authorization: Bearer ${WORKSPACE_OWNER_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"name":"Dr. Example — research account","role":"researcher"}'
```

The token in the response is displayed once. The workspace owner can list credentials and revoke them:

```bash
curl --fail http://127.0.0.1:8080/api/v1/tenant/credentials \
  -H "Authorization: Bearer ${WORKSPACE_OWNER_TOKEN}"

curl --fail -X DELETE http://127.0.0.1:8080/api/v1/tenant/credentials/CREDENTIAL_ID \
  -H "Authorization: Bearer ${WORKSPACE_OWNER_TOKEN}"
```

## Roles

| Role | Submit runs | Read own workspace runs/artifacts | Manage credentials | Issue admin credentials | Submit approved experiments |
|---|---:|---:|---:|---:|---:|
| `owner` | Yes | Yes | Yes | Yes | Yes |
| `admin` | Yes | Yes | Yes, except owner/admin revocation | No | Yes |
| `researcher` | Yes | Yes | No | No | No |
| `viewer` | No | Yes | No | No | No |

A platform administrator can create, list, and enable/disable tenants, but is not automatically a member of every workspace. It must use a workspace credential to submit research runs. API job queries and artifact downloads are tenant-filtered; an out-of-tenant run is reported as not found.

## Boundaries and deployment requirements

- These are bearer-token identities, not full user accounts. There is no password login, SSO, OIDC/SAML, MFA, SCIM, session management, or email verification.
- Role checks and tenant scoping are enforced in the API. PostgreSQL row-level security is not enabled; do not expose the database directly to tenant users.
- The platform-admin token is a single shared operator secret. Protect it like a root credential and restrict it to the operator environment.
- Tenant run quotas and billing limits are not implemented. The experimental-code queue has a fixed small per-tenant pending/running cap; this is not a general resource quota system.
- Use TLS, a firewall/VPN, secret management, database backups, encrypted artifact storage, and an identity-aware gateway where institutional policy requires centralized identity or stronger controls.
- The `/ui` page is a small run-submission and artifact-viewing interface. It is not a full project-management or administration console; credential and tenant administration use the API endpoints above.
