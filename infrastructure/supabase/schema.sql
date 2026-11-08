-- Proposed hosted control-plane schema. Apply only to an owned Supabase project after review.
-- Workers and API authorization are separate services; this schema does not execute episodes.
create extension if not exists pgcrypto;

create table if not exists public.wf_projects (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id),
  name text not null,
  created_at timestamptz not null default now()
);

create table if not exists public.wf_resources (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.wf_projects(id),
  kind text not null check (kind in ('environment','agent','scenario','dataset','policy','validator')),
  name text not null,
  version integer not null default 1,
  config jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique(project_id, kind, name, version)
);

create table if not exists public.wf_runs (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.wf_projects(id),
  agent_id uuid not null references public.wf_resources(id),
  environment_id uuid not null references public.wf_resources(id),
  status text not null check (status in ('queued','running','completed','failed','cancelled')),
  requested_episodes integer not null check (requested_episodes between 1 and 100000),
  config jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  finished_at timestamptz
);

create table if not exists public.wf_episodes (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references public.wf_runs(id),
  ordinal integer not null,
  seed bigint not null,
  status text not null,
  score double precision check (score between 0 and 1),
  trace_object_key text,
  error_code text,
  unique(run_id, ordinal)
);

create table if not exists public.wf_audit (
  id bigint generated always as identity primary key,
  project_id uuid not null references public.wf_projects(id),
  actor_id uuid references auth.users(id),
  action text not null,
  resource_kind text not null,
  resource_id uuid,
  request_id text,
  detail jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists wf_resources_project_kind on public.wf_resources(project_id, kind);
create index if not exists wf_runs_project_created on public.wf_runs(project_id, created_at desc);
create index if not exists wf_episodes_run on public.wf_episodes(run_id);
create index if not exists wf_audit_project_created on public.wf_audit(project_id, created_at desc);

alter table public.wf_projects enable row level security;
alter table public.wf_resources enable row level security;
alter table public.wf_runs enable row level security;
alter table public.wf_episodes enable row level security;
alter table public.wf_audit enable row level security;

create policy wf_projects_owner on public.wf_projects for all to authenticated
  using (owner_id = (select auth.uid())) with check (owner_id = (select auth.uid()));
create policy wf_resources_owner on public.wf_resources for all to authenticated
  using (exists (select 1 from public.wf_projects p where p.id = project_id and p.owner_id = (select auth.uid())))
  with check (exists (select 1 from public.wf_projects p where p.id = project_id and p.owner_id = (select auth.uid())));
create policy wf_runs_owner on public.wf_runs for all to authenticated
  using (exists (select 1 from public.wf_projects p where p.id = project_id and p.owner_id = (select auth.uid())))
  with check (exists (select 1 from public.wf_projects p where p.id = project_id and p.owner_id = (select auth.uid())));
create policy wf_episodes_owner on public.wf_episodes for select to authenticated
  using (exists (select 1 from public.wf_runs r join public.wf_projects p on p.id = r.project_id
                where r.id = run_id and p.owner_id = (select auth.uid())));
create policy wf_episodes_insert on public.wf_episodes for insert to authenticated
  with check (exists (select 1 from public.wf_runs r join public.wf_projects p on p.id = r.project_id
                     where r.id = run_id and p.owner_id = (select auth.uid())));
create policy wf_runs_update on public.wf_runs for update to authenticated
  using (exists (select 1 from public.wf_projects p where p.id = project_id and p.owner_id = (select auth.uid())))
  with check (exists (select 1 from public.wf_projects p where p.id = project_id and p.owner_id = (select auth.uid())));
create policy wf_audit_owner on public.wf_audit for select to authenticated
  using (exists (select 1 from public.wf_projects p where p.id = project_id and p.owner_id = (select auth.uid())));
