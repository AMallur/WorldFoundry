-- Hosted declarative simulation sessions. Additive; no existing customer records altered.
-- Every customer request goes through the WorldFoundry API and its ownership checks.
-- Only trusted server credentials may read/write session state and invoke the RPC.
create table if not exists public.wf_sim_sessions (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.wf_projects(id) on delete cascade,
  environment_id uuid not null references public.wf_resources(id),
  scenario_id uuid not null references public.wf_resources(id),
  state jsonb not null,
  initial_state jsonb not null,
  status text not null default 'running'
    check (status in ('running','passed','failed','cancelled')),
  version integer not null default 0 check (version >= 0),
  step integer not null default 0 check (step >= 0),
  max_steps integer not null default 30 check (max_steps between 1 and 1000),
  seed bigint not null default 0,
  score double precision check (score between 0 and 1),
  checks jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint wf_sim_state_size check (octet_length(state::text) <= 65536)
);
create index if not exists wf_sim_sessions_project_created
  on public.wf_sim_sessions(project_id, created_at desc);

create table if not exists public.wf_sim_events (
  id bigint generated always as identity primary key,
  session_id uuid not null references public.wf_sim_sessions(id) on delete cascade,
  project_id uuid not null references public.wf_projects(id) on delete cascade,
  version integer not null,
  call_id text not null check (char_length(call_id) between 8 and 128),
  action text not null,
  parameters jsonb not null default '{}'::jsonb,
  observation jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (session_id, call_id),
  unique (session_id, version)
);
create index if not exists wf_sim_events_session_id on public.wf_sim_events(session_id, id);

alter table public.wf_sim_sessions enable row level security;
alter table public.wf_sim_events enable row level security;
revoke all on public.wf_sim_sessions from anon, authenticated;
revoke all on public.wf_sim_events from anon, authenticated;
revoke all on sequence public.wf_sim_events_id_seq from anon, authenticated;
-- Leave these tables without user RLS policies: all access is via authenticated
-- WorldFoundry server endpoints that check ownership before using secret credentials.

create or replace function public.wf_sim_commit(
  p_session_id uuid,
  p_expected_version integer,
  p_call_id text,
  p_action text,
  p_parameters jsonb,
  p_next_state jsonb,
  p_observation jsonb,
  p_status text,
  p_score double precision,
  p_checks jsonb
) returns jsonb
language plpgsql security invoker set search_path = public
as $$
declare
  v_session public.wf_sim_sessions%rowtype;
begin
  select * into v_session from public.wf_sim_sessions
    where id = p_session_id for update;
  if not found then return jsonb_build_object('error', 'not_found'); end if;
  if exists(select 1 from public.wf_sim_events
            where session_id = p_session_id and call_id = p_call_id) then
    return jsonb_build_object('duplicate', true, 'session', to_jsonb(v_session));
  end if;
  if v_session.status <> 'running' then
    return jsonb_build_object('error', 'not_running');
  end if;
  if v_session.version <> p_expected_version then
    return jsonb_build_object('error', 'conflict', 'version', v_session.version);
  end if;
  if p_call_id is null or char_length(p_call_id) not between 8 and 128 or
     p_action is null or length(p_action) > 64 then
    return jsonb_build_object('error', 'invalid_call');
  end if;
  if (p_action <> '__submit__' and v_session.step >= v_session.max_steps)
     or p_status not in ('running','passed','failed') then
    return jsonb_build_object('error', 'invalid_transition');
  end if;
  if octet_length(p_next_state::text) > 65536 then
    return jsonb_build_object('error', 'state_too_large');
  end if;
  if p_action = '__submit__' and p_status = 'running' then
    return jsonb_build_object('error', 'invalid_transition');
  end if;
  update public.wf_sim_sessions
     set state = p_next_state,
         version = version + 1,
         step = step + case when p_action = '__submit__' then 0 else 1 end,
         status = p_status,
         score = case when p_action = '__submit__' then p_score else score end,
         checks = case when p_action = '__submit__' then p_checks else checks end,
         updated_at = now()
   where id = p_session_id returning * into v_session;
  insert into public.wf_sim_events
     (session_id, project_id, version, call_id, action, parameters, observation)
  values
     (p_session_id, v_session.project_id, v_session.version, p_call_id,
      p_action, coalesce(p_parameters, '{}'::jsonb), coalesce(p_observation, '{}'::jsonb));
  return jsonb_build_object('session', to_jsonb(v_session));
end;
$$;
revoke all on function public.wf_sim_commit(
  uuid, integer, text, text, jsonb, jsonb, jsonb, text, double precision, jsonb
) from public, anon, authenticated;
grant execute on function public.wf_sim_commit(
  uuid, integer, text, text, jsonb, jsonb, jsonb, text, double precision, jsonb
) to service_role;

insert into storage.buckets (id, name, public)
values ('wf-artifacts', 'wf-artifacts', false)
on conflict (id) do nothing;
