-- WorldFoundry API key verifiers. Only company backend code may read this table.
-- Never store or return a complete customer API key after issuance.
create table if not exists public.wf_api_keys (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  project_id uuid references public.wf_projects(id) on delete cascade,
  name text not null check (char_length(name) between 1 and 100),
  key_prefix text not null,
  key_hash text not null unique,
  scopes text[] not null default array['read','write']::text[],
  created_at timestamptz not null default now(),
  expires_at timestamptz,
  revoked_at timestamptz,
  last_used_at timestamptz,
  constraint wf_api_keys_scopes check (scopes <@ array['read','write']::text[])
);

create index if not exists wf_api_keys_owner_created
  on public.wf_api_keys(owner_id, created_at desc);

alter table public.wf_api_keys enable row level security;
revoke all on public.wf_api_keys from anon, authenticated;
-- No policies: only the server's service credential can access key hashes.

-- The public WorldFoundry gateway proves that a call came through company
-- infrastructure. The complete gateway token lives only in gateway secrets.
create table if not exists public.wf_gateway_config (
  id boolean primary key default true check (id),
  secret_hash text not null,
  created_at timestamptz not null default now()
);
alter table public.wf_gateway_config enable row level security;
revoke all on public.wf_gateway_config from anon, authenticated;
