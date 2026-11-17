-- WorldFoundry managed experiences v0.5: company-controlled data only.
-- Scripts execute deterministically; no customer Python executes on the control plane.
create extension if not exists pgcrypto;

create table if not exists public.wf_billing_customers (
  project_id uuid primary key references public.wf_projects(id) on delete cascade,
  stripe_customer_id text unique,
  stripe_subscription_id text unique,
  subscription_status text not null default 'inactive',
  plan text not null default 'free' check (plan in ('free','pro')),
  monthly_episode_limit integer not null default 20 check (monthly_episode_limit between 0 and 100000),
  updated_at timestamptz not null default now()
);
create table if not exists public.wf_billing_events (
  event_id text primary key,
  event_type text not null,
  processed_at timestamptz not null default now()
);
create table if not exists public.wf_managed_runs (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.wf_projects(id) on delete cascade,
  environment_id uuid not null references public.wf_resources(id),
  scenario_id uuid not null references public.wf_resources(id),
  agent_id uuid not null references public.wf_resources(id),
  requested_episodes integer not null check (requested_episodes between 1 and 100),
  max_steps integer not null check (max_steps between 1 and 100),
  seed bigint not null default 0,
  executor text not null default 'edge_scripted'
    check (executor in ('edge_scripted','cloud_tasks')),
  status text not null default 'queued'
    check (status in ('queued','running','completed','failed','cancelled')),
  idempotency_key text check (idempotency_key is null or char_length(idempotency_key) between 8 and 128),
  completed_episodes integer not null default 0,
  score_mean double precision check (score_mean between 0 and 1),
  error_code text,
  queued_to_cloud_at timestamptz,
  claimed_at timestamptz,
  attempt_count integer not null default 0 check (attempt_count >= 0),
  created_at timestamptz not null default now(),
  finished_at timestamptz,
  updated_at timestamptz not null default now()
);
create unique index if not exists wf_managed_run_idempotency
  on public.wf_managed_runs(project_id,idempotency_key) where idempotency_key is not null;
create index if not exists wf_managed_runs_project_date
  on public.wf_managed_runs(project_id,created_at desc);
create index if not exists wf_managed_runs_dispatch
  on public.wf_managed_runs(created_at) where status = 'queued' and executor = 'cloud_tasks';

create table if not exists public.wf_managed_episodes (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.wf_projects(id) on delete cascade,
  managed_run_id uuid not null references public.wf_managed_runs(id) on delete cascade,
  ordinal integer not null check (ordinal between 0 and 99),
  seed bigint not null,
  status text not null check (status in ('passed','failed','error')),
  score double precision not null check (score between 0 and 1),
  checks jsonb not null default '[]'::jsonb,
  action_count integer not null check (action_count between 0 and 100),
  duration_ms integer not null default 0 check (duration_ms >= 0),
  trace_object_key text,
  created_at timestamptz not null default now(),
  unique(managed_run_id,ordinal)
);
create index if not exists wf_managed_episodes_run
  on public.wf_managed_episodes(managed_run_id,ordinal);

create table if not exists public.wf_artifacts (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.wf_projects(id) on delete cascade,
  managed_run_id uuid references public.wf_managed_runs(id) on delete cascade,
  kind text not null check (kind in ('trace','dataset','report','export')),
  name text not null check (char_length(name) between 1 and 160),
  storage_key text not null unique,
  bytes bigint not null check (bytes between 0 and 52428800),
  content_type text not null default 'application/octet-stream',
  created_at timestamptz not null default now()
);
create index if not exists wf_artifacts_project_date
  on public.wf_artifacts(project_id,created_at desc);

create table if not exists public.wf_managed_usage (
  managed_run_id uuid primary key references public.wf_managed_runs(id) on delete cascade,
  project_id uuid not null references public.wf_projects(id) on delete cascade,
  episodes integer not null check (episodes between 0 and 100),
  actions integer not null check (actions >= 0),
  elapsed_ms bigint not null check (elapsed_ms >= 0),
  source text not null check (source in ('edge_verified','cloud_verified')),
  stripe_reported_at timestamptz,
  created_at timestamptz not null default now()
);

alter table public.wf_billing_customers enable row level security;
alter table public.wf_billing_events enable row level security;
alter table public.wf_managed_runs enable row level security;
alter table public.wf_managed_episodes enable row level security;
alter table public.wf_artifacts enable row level security;
alter table public.wf_managed_usage enable row level security;
revoke all on public.wf_billing_customers, public.wf_billing_events,
  public.wf_managed_runs, public.wf_managed_episodes,
  public.wf_artifacts, public.wf_managed_usage from anon,authenticated;
-- Private server-only tables deliberately have no policies for end-user roles.

-- Serialize each project's admission to avoid quota races. Only service_role
-- may call; customers are authenticated in the WorldFoundry API first.
create or replace function public.wf_reserve_managed_run(
  p_project_id uuid, p_environment_id uuid, p_scenario_id uuid, p_agent_id uuid,
  p_episodes integer, p_max_steps integer, p_seed bigint,
  p_executor text, p_idempotency_key text default null
) returns jsonb
language plpgsql security invoker set search_path = public
as $$
declare
  v_existing public.wf_managed_runs%rowtype;
  v_limit integer;
  v_consumed bigint;
begin
  perform 1 from public.wf_projects where id = p_project_id for update;
  if not found then return jsonb_build_object('error','project_not_found'); end if;
  if p_idempotency_key is not null then
    select * into v_existing from public.wf_managed_runs
      where project_id=p_project_id and idempotency_key=p_idempotency_key;
    if found then return jsonb_build_object('run',to_jsonb(v_existing),'duplicate',true); end if;
  end if;
  if p_executor not in ('edge_scripted','cloud_tasks') or
     p_episodes not between 1 and (case when p_executor='edge_scripted' then 5 else 100 end) or
     p_max_steps not between 1 and (case when p_executor='edge_scripted' then 40 else 100 end)
     or p_idempotency_key is not null and char_length(p_idempotency_key) not between 8 and 128
  then return jsonb_build_object('error','invalid_limits'); end if;
  if (select count(*) from public.wf_resources where project_id=p_project_id and
    (id=p_environment_id and kind='environment' or
     id=p_scenario_id and kind='scenario' or
     id=p_agent_id and kind='agent')) <> 3
  then return jsonb_build_object('error','invalid_resources'); end if;
  select monthly_episode_limit into v_limit from public.wf_billing_customers
    where project_id=p_project_id;
  v_limit := coalesce(v_limit,20);
  select coalesce(sum(requested_episodes),0) into v_consumed from public.wf_managed_runs
   where project_id=p_project_id and created_at>=date_trunc('month',now())
     and status <> 'cancelled';
  if v_consumed+p_episodes > v_limit then
    return jsonb_build_object('error','episode_quota_exceeded','remaining',greatest(0,v_limit-v_consumed));
  end if;
  insert into public.wf_managed_runs
    (project_id,environment_id,scenario_id,agent_id,requested_episodes,
     max_steps,seed,executor,idempotency_key)
  values (p_project_id,p_environment_id,p_scenario_id,p_agent_id,
          p_episodes,p_max_steps,p_seed,p_executor,p_idempotency_key)
  returning * into v_existing;
  return jsonb_build_object('run',to_jsonb(v_existing),'duplicate',false);
end; $$;
revoke all on function public.wf_reserve_managed_run(
  uuid,uuid,uuid,uuid,integer,integer,bigint,text,text)
  from public,anon,authenticated;
grant execute on function public.wf_reserve_managed_run(
  uuid,uuid,uuid,uuid,integer,integer,bigint,text,text)
  to service_role;

insert into storage.buckets (id,name,public,file_size_limit)
values ('wf-artifacts','wf-artifacts',false,52428800)
on conflict (id) do nothing;
