-- WorldFoundry customer-owned resource library.
-- No per-organization resource count cap: storage and fair-use limits are
-- controlled at the service/account level, not by fixed hard-coded slots.

-- Resource kinds are extensible without provisioning databases per customer.
alter table public.wf_resources drop constraint if exists wf_resources_kind_check;
alter table public.wf_resources add constraint wf_resources_kind_check check (
  kind in ('template','environment','scenario','agent','dataset','policy','validator',
           'tool','workflow','application')
);
alter table public.wf_resources
  add column if not exists updated_at timestamptz not null default now(),
  add column if not exists archived_at timestamptz;
-- The original unique constraint inadvertently prevented separate resources
-- with the same name and version. IDs, rather than names, identify resources.
alter table public.wf_resources
  drop constraint if exists wf_resources_project_id_kind_name_version_key;
alter table public.wf_resources
  add constraint wf_resource_config_size
  check (octet_length(config::text) <= 131072);
create index if not exists wf_resources_tenant_page
  on public.wf_resources(project_id,kind,created_at desc,id desc);
create index if not exists wf_resources_tenant_active
  on public.wf_resources(project_id,kind,created_at desc,id desc)
  where archived_at is null;

create table if not exists public.wf_resource_revisions (
  resource_id uuid not null references public.wf_resources(id) on delete cascade,
  project_id uuid not null references public.wf_projects(id) on delete cascade,
  kind text not null,
  version integer not null check (version > 0),
  name text not null,
  config jsonb not null,
  archived_at timestamptz,
  created_at timestamptz not null default now(),
  primary key (resource_id, version)
);
create index if not exists wf_resource_revisions_project
  on public.wf_resource_revisions(project_id,kind,resource_id,version desc);
alter table public.wf_resource_revisions enable row level security;
revoke all on public.wf_resource_revisions from anon,authenticated;
-- The only public access to version history is via WorldFoundry's authorized API.

create or replace function public.wf_capture_resource_revision()
returns trigger language plpgsql security invoker
set search_path=public as $$
begin
  if tg_op = 'INSERT' or new.version is distinct from old.version then
    insert into public.wf_resource_revisions
      (resource_id,project_id,kind,version,name,config,archived_at)
    values
      (new.id,new.project_id,new.kind,new.version,new.name,new.config,new.archived_at);
  end if;
  return new;
end $$;
drop trigger if exists wf_capture_resource_revision on public.wf_resources;
create trigger wf_capture_resource_revision
  after insert or update on public.wf_resources
  for each row execute function public.wf_capture_resource_revision();
-- Backfill historical resources, which were not revision-tracked.
insert into public.wf_resource_revisions
  (resource_id,project_id,kind,version,name,config,archived_at)
select id,project_id,kind,version,name,config,archived_at
from public.wf_resources
on conflict (resource_id,version) do nothing;

-- Atomically compare-and-swap the version. Concurrent clients cannot silently
-- overwrite one another's changes. API must authenticate project ownership.
create or replace function public.wf_resource_change(
 p_resource_id uuid,
 p_project_id uuid,
 p_kind text,
 p_expected_version integer,
 p_name text default null,
 p_config jsonb default null,
 p_archive boolean default null
) returns jsonb
language plpgsql security invoker set search_path=public
as $$
declare r public.wf_resources%rowtype;
begin
  select * into r from public.wf_resources
    where id=p_resource_id and project_id=p_project_id and kind=p_kind
    for update;
  if not found then return jsonb_build_object('error','not_found'); end if;
  if p_expected_version is null or r.version<>p_expected_version then
    return jsonb_build_object('error','conflict','current_version',r.version);
  end if;
  if p_name is not null and (char_length(trim(p_name))=0 or char_length(p_name)>160) then
    return jsonb_build_object('error','invalid_name');
  end if;
  if p_config is not null and
     (jsonb_typeof(p_config)<>'object' or octet_length(p_config::text)>131072) then
    return jsonb_build_object('error','invalid_config');
  end if;
  if r.version >= 2147483646 then
    return jsonb_build_object('error','version_limit');
  end if;
  update public.wf_resources
     set name=coalesce(trim(p_name),r.name),
         config=coalesce(p_config,r.config),
         archived_at=case when p_archive is true then now()
                          when p_archive is false then null
                          else r.archived_at end,
         version=r.version+1,updated_at=now()
   where id=p_resource_id returning * into r;
  return jsonb_build_object('resource',to_jsonb(r));
end $$;
revoke all on function public.wf_resource_change(
 uuid,uuid,text,integer,text,jsonb,boolean) from public,anon,authenticated;
grant execute on function public.wf_resource_change(
 uuid,uuid,text,integer,text,jsonb,boolean) to service_role;

-- Versions are frozen at session creation, so editing a template or scenario
-- cannot change an active simulation's actions and grading rules.
alter table public.wf_sim_sessions
  add column if not exists environment_snapshot jsonb,
  add column if not exists scenario_snapshot jsonb,
  add column if not exists environment_resource_version integer,
  add column if not exists scenario_resource_version integer;

update public.wf_sim_sessions s
  set environment_snapshot=e.config,
      scenario_snapshot=c.config,
      environment_resource_version=e.version,
      scenario_resource_version=c.version
from public.wf_resources e,public.wf_resources c
where s.environment_id=e.id and s.scenario_id=c.id
  and s.environment_snapshot is null and s.scenario_snapshot is null;
