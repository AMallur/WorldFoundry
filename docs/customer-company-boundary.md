# WorldFoundry customer and provider boundary

## Product contract

WorldFoundry is the customer-facing product. Customers create a WorldFoundry
account, create a WorldFoundry API key, and send SDK or REST requests to a
WorldFoundry-owned API domain. They use WorldFoundry's web app, future desktop
app, SDK, and API to save and retrieve their work. They never need a Supabase
account, project, URL, API key, or user access token.

Supabase is **one company-owned backend resource**, not a resource each
customer provisions. The company owns and pays for its Supabase project. Its
privileged provider credential stays in the WorldFoundry server's secret store;
the founder is the only human who should see or manage that credential.
Customers and customer-facing code never receive it. The company uses the
project for identity, PostgreSQL, private object storage, and persisted
platform data. A customer's WorldFoundry account, API key, projects, runs,
traces, and files are WorldFoundry concepts even when the records and objects
reside in this company-owned Supabase project.

The old provider-token prototype endpoint has been retired. The new customer
API validates WorldFoundry keys and rejects direct calls that do not come
through the WorldFoundry gateway. Its gateway deployment still lacks its
private production configuration, so the customer API is **not operational
end to end yet**. The published `worldfoundry==0.2.0`
package has not been updated to use it and does not issue WorldFoundry keys.

## Customer flow to implement

1. Customer signs up or signs in through a WorldFoundry app. WorldFoundry's
   server uses the company Supabase project behind the scenes for identity and
   account records. Browser sessions use secure, HTTP-only cookies; the
   browser never receives the company's privileged provider credential.
2. Customer creates a key in the WorldFoundry dashboard. The server creates a
   cryptographically random token and stores only a hash, prefix,
   owner/workspace, scopes, creation time, and optional expiry in Supabase.
   The complete token is displayed once, never returned by list or get.
3. The SDK sends `Authorization: Bearer <WorldFoundry key>` to a branded
   WorldFoundry API endpoint. The API validates the key, expiry, revocation,
   scope, and workspace before touching any resource.
4. WorldFoundry maps the authorized request to its company-owned Supabase data
   services. Every read and write is constrained to the customer's workspace.
   Private traces and artifacts are stored in Supabase Storage and accessed
   through WorldFoundry-authorized endpoints or short-lived signed URLs.
5. A customer can list key metadata, revoke a key, and rotate by issuing a
   replacement. Revocation takes effect before another API request succeeds.
   Never log complete keys or send them to traces, agent tools, or model input.

## Company-owned provider map

| WorldFoundry capability | Internal provider responsibility |
| --- | --- |
| Accounts and sessions | Company Supabase Auth project, mediated by WorldFoundry server |
| Workspaces, members, projects, resources, runs, episodes | Supabase PostgreSQL with tenant isolation |
| API key metadata and revocation | Supabase PostgreSQL; verification on WorldFoundry server |
| Traces, datasets, reports, exports | Private Supabase Storage plus metadata in PostgreSQL |
| Search and recall | PostgreSQL indexes and approved search/vector features, with workspace filters |
| Audit and usage ledgers | Append-only company-controlled records in PostgreSQL |

Supabase provides persistence, identity, and server-side application logic.
It does not safely run arbitrary customer Python agents. Managed agent runs
still require an isolated worker service and a job queue. The worker may read
and write WorldFoundry state through controlled internal APIs, while Supabase
remains the system of record. The local SDK can continue to run episodes on
the customer's computer.

## Release gates

- Branded WorldFoundry domain and a server/gateway that does not expose
  provider credentials or provider-specific URLs in customer examples or apps.
- Company-owned privileged provider credential held in a server-side secret
  store, with only the founder given human access; no customer-owned Supabase
  projects or credentials are required.
- API key issuance, one-time display, hash-only storage, lookup, scopes,
  revocation, expiry, and tenant-isolation tests.
- WorldFoundry account/session flow and private trace access tests.
- SDK `WorldFoundry(api_key=...)` targeting the WorldFoundry API by default.
- Separate metering and billing verification before any customer charges.

Until these gates pass, keep cloud examples out of customer onboarding and do
not publish an SDK release that defaults to the gateway.
