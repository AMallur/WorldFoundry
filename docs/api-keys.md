# WorldFoundry API keys

WorldFoundry owns one company backend. Each customer can create multiple
WorldFoundry API keys for different agents or applications. Customers never
create or receive a provider API key.

## What is stored

The company database stores one row per customer key in `wf_api_keys`:

| Field | Purpose |
| --- | --- |
| `owner_id`, optional `project_id` | Customer and optional project boundary |
| `name`, `key_prefix` | Recognize a key without revealing it |
| `key_hash` | Verify the presented key; the full key is not stored |
| `scopes` | `read`, `write`, or both |
| `created_at`, `expires_at`, `revoked_at` | Lifecycle and access control |
| `last_used_at`, `request_count` | Usage summary per key |

`wf_api_key_activity` stores the method, route, and time for each authenticated
key request. It does not store the complete key, request body, agent prompt,
customer content, or query string. The counter, last-used time, and activity
entry are written together. A failure to record activity blocks the request
instead of letting untracked requests proceed. These records are operational
tracking, **not** verified billable usage.

The key and activity tables have row-level security enabled and no direct
`anon` or `authenticated` read grants. Only the company backend uses its
privileged server credential to access them. The browser gets an opaque
WorldFoundry session cookie; it never receives a provider JWT.

## Management API

The following routes are on the WorldFoundry gateway. Key management requires
a signed-in WorldFoundry browser session, not an API key. Mutating session
requests require the matching `X-WF-CSRF` header.

| Operation | Route | Result |
| --- | --- | --- |
| Create | `POST /v1/keys` | Returns the full `wf_live_...` key once |
| List | `GET /v1/keys` | Metadata, status, last use, and request count |
| Inspect | `GET /v1/keys/{id}` | One key's metadata; never the full key |
| Activity | `GET /v1/keys/{id}/activity` | Most recent 100 method, route, time entries |
| Revoke | `DELETE /v1/keys/{id}` | Records revocation; later requests fail |

`POST /v1/keys` accepts `name`, optional `project_id`, optional `scopes`, and
optional ISO 8601 `expires_at`. A project-scoped key can access only that
project. Key strings are generated using 32 random bytes. Customers should
copy the value at creation, store it in their own secret manager, and rotate
by creating a replacement before revoking the old key.

## Current verification

The gateway is deployed at `https://worldfoundry-api.vercel.app`. Its health
route returned 200, and unauthenticated resource calls returned 401. Local
tests cover issuance, one-time display, hash-only storage, scopes, tenant
isolation, activity recording, and revocation. A live account and full
authenticated request sequence are still required before customer onboarding.
The published `worldfoundry==0.2.0` package does not use this gateway by
default. The next SDK source is `0.3.0.dev0` and has not been published.
