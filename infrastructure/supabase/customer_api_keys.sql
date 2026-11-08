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

-- WorldFoundry browser sessions are opaque tokens. Supabase Auth is used only
-- server-side to verify login; its JWT is never sent to the browser.
create table if not exists public.wf_sessions (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  token_hash text not null unique,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null,
  revoked_at timestamptz
);
create index if not exists wf_sessions_owner on public.wf_sessions(owner_id, created_at desc);
alter table public.wf_sessions enable row level security;
revoke all on public.wf_sessions from anon, authenticated;

-- Each WorldFoundry key can be managed and tracked separately. This is an
-- operational activity log, not a billing ledger.
alter table public.wf_api_keys
  add column if not exists request_count bigint not null default 0;

create table if not exists public.wf_api_key_activity (
  id bigint generated always as identity primary key,
  key_id uuid not null references public.wf_api_keys(id) on delete cascade,
  owner_id uuid not null references auth.users(id) on delete cascade,
  method text not null check (method in ('GET','POST','PATCH','DELETE')),
  route text not null check (char_length(route) between 1 and 200),
  created_at timestamptz not null default now()
);
create index if not exists wf_api_key_activity_key_created
  on public.wf_api_key_activity(key_id, created_at desc);
alter table public.wf_api_key_activity enable row level security;
revoke all on public.wf_api_key_activity from anon, authenticated;

-- Atomic counter + activity insert. Only the company's service role can call
-- this invoker-rights function. If a key was revoked during lookup, return
-- false and let the API reject the request.
create or replace function public.wf_record_api_key_use(
  p_key_id uuid, p_owner_id uuid, p_method text, p_route text
) returns boolean language plpgsql security invoker set search_path = public as $$
declare v_id uuid;
begin
  update public.wf_api_keys
     set last_used_at = now(), request_count = request_count + 1
   where id = p_key_id and owner_id = p_owner_id and revoked_at is null
     and (expires_at is null or expires_at > now())
   returning id into v_id;
  if v_id is null then return false; end if;
  insert into public.wf_api_key_activity(key_id, owner_id, method, route)
    values (p_key_id, p_owner_id, p_method, left(p_route, 200));
  return true;
end;
$$;
revoke all on function public.wf_record_api_key_use(uuid,uuid,text,text)
  from public, anon, authenticated;
grant execute on function public.wf_record_api_key_use(uuid,uuid,text,text)
  to service_role;
