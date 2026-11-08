-- WorldFoundry cloud trace storage and non-billable usage ledger.
insert into storage.buckets (id, name, public)
values ('wf-traces', 'wf-traces', false)
on conflict (id) do nothing;

create policy wf_trace_insert on storage.objects for insert to authenticated
  with check (bucket_id = 'wf-traces' and (storage.foldername(name))[1] = (select auth.uid())::text);
create policy wf_trace_read on storage.objects for select to authenticated
  using (bucket_id = 'wf-traces' and (storage.foldername(name))[1] = (select auth.uid())::text);

create policy wf_episodes_update on public.wf_episodes for update to authenticated
  using (exists (select 1 from public.wf_runs r join public.wf_projects p on p.id = r.project_id
                where r.id = run_id and p.owner_id = (select auth.uid())))
  with check (exists (select 1 from public.wf_runs r join public.wf_projects p on p.id = r.project_id
                     where r.id = run_id and p.owner_id = (select auth.uid())));

create table if not exists public.wf_usage (
  id bigint generated always as identity primary key,
  project_id uuid not null references public.wf_projects(id),
  run_id uuid not null references public.wf_runs(id),
  episode_id uuid not null unique references public.wf_episodes(id),
  unit text not null check (unit = 'episode'),
  quantity integer not null check (quantity = 1),
  source text not null check (source in ('client_reported', 'managed_verified')),
  created_at timestamptz not null default now()
);
alter table public.wf_usage enable row level security;
create policy wf_usage_owner on public.wf_usage for select to authenticated
  using (exists (select 1 from public.wf_projects p where p.id = project_id and p.owner_id = (select auth.uid())));
create policy wf_usage_insert on public.wf_usage for insert to authenticated
  with check (source = 'client_reported' and exists (
    select 1 from public.wf_runs r join public.wf_projects p on p.id = r.project_id
    where r.id = run_id and r.project_id = wf_usage.project_id and p.owner_id = (select auth.uid())
  ));
