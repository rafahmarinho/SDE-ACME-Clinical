-- ACME Clinical - database schema
-- Target: Supabase PostgreSQL 15+ (tested locally against PostgreSQL 17).
--
-- Security model
--   * Every table has Row Level Security enabled.
--   * The browser (role "authenticated") only gets SELECT on the clinical tables it needs
--     for Realtime, filtered by the caller's role in public.profiles. It never writes directly.
--   * All writes go through the FastAPI service, which connects as the dedicated
--     least-privilege login role "acme_api" (no superuser, no BYPASSRLS; explicit policies).
--   * The "anon" role has no access to anything in the public schema.

-- ---------------------------------------------------------------------------
-- Roles
-- ---------------------------------------------------------------------------
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'acme_api') then
    -- Password is set out-of-band:  alter role acme_api with password '<strong secret>';
    create role acme_api login noinherit nocreatedb nocreaterole;
  end if;
end $$;

grant usage on schema public to acme_api;

-- ---------------------------------------------------------------------------
-- Tables
-- ---------------------------------------------------------------------------
create table if not exists public.profiles (
  id uuid primary key,
  email text not null unique check (email = lower(email)),
  full_name text not null check (char_length(full_name) between 1 and 120),
  role text not null check (role in ('nurse', 'physician', 'biomed', 'admin')),
  job_title text check (char_length(job_title) <= 80),
  phone text check (char_length(phone) <= 32),
  unit text not null default 'Ward 4B',
  avatar_path text,
  active boolean not null default true,
  preferences jsonb not null default '{}'::jsonb,
  consent_accepted_at timestamptz,
  consent_version text,
  last_sign_in_at timestamptz,
  last_sign_in_ip text,
  previous_sign_in_at timestamptz,
  previous_sign_in_ip text,
  anonymized_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.beds (
  id text primary key,
  label text not null,
  room text not null,
  ward text not null default 'Ward 4B',
  pos_x numeric not null default 0,
  pos_z numeric not null default 0
);

create table if not exists public.patients (
  id uuid primary key default gen_random_uuid(),
  mrn text not null unique,
  first_name text not null,
  last_name text not null,
  date_of_birth date not null,
  sex text not null check (sex in ('female', 'male', 'other')),
  bed_id text unique references public.beds(id) on delete set null,
  status text not null default 'admitted' check (status in ('admitted', 'discharged')),
  admitted_at timestamptz not null default now(),
  diagnosis text not null default '',
  attending_physician text not null default '',
  acuity text not null default 'medium' check (acuity in ('low', 'medium', 'high')),
  allergies text not null default 'None known',
  code_status text not null default 'Full code',
  restricted boolean not null default false,
  baseline jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.monitors (
  id text primary key,
  serial_number text not null unique,
  model text not null,
  firmware text not null,
  bed_id text unique references public.beds(id) on delete set null,
  status text not null default 'active' check (status in ('active', 'standby', 'maintenance', 'retired')),
  scenario text not null default 'normal'
    check (scenario in ('normal', 'low_spo2', 'weak_battery', 'sensor_issue', 'lost_connection')),
  battery_pct numeric(5, 2) not null default 100 check (battery_pct between 0 and 100),
  connection text not null default 'online' check (connection in ('online', 'offline')),
  sensor_status text not null default 'ok' check (sensor_status in ('ok', 'spo2_probe_off', 'ecg_leads_off')),
  sim_state jsonb not null default '{}'::jsonb,
  last_seen_at timestamptz,
  last_maintenance_at timestamptz,
  next_maintenance_due date,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.monitor_assignments (
  id bigint generated always as identity primary key,
  monitor_id text not null references public.monitors(id) on delete cascade,
  bed_id text not null references public.beds(id) on delete cascade,
  patient_id uuid references public.patients(id) on delete set null,
  assigned_by uuid,
  assigned_at timestamptz not null default now(),
  unassigned_at timestamptz,
  unassigned_by uuid
);

create table if not exists public.vital_readings (
  id bigint generated always as identity primary key,
  monitor_id text not null references public.monitors(id) on delete cascade,
  patient_id uuid references public.patients(id) on delete cascade,
  bed_id text,
  tick integer not null,
  recorded_at timestamptz not null,
  heart_rate integer,
  spo2 integer,
  resp_rate integer,
  systolic integer,
  diastolic integer,
  battery_pct numeric(5, 2),
  quality text not null default 'good' check (quality in ('good', 'artifact', 'no_signal')),
  source text not null default 'simulator' check (source in ('simulator', 'device'))
);
create index if not exists vital_readings_patient_time on public.vital_readings (patient_id, recorded_at desc);
create index if not exists vital_readings_monitor_time on public.vital_readings (monitor_id, recorded_at desc);

create table if not exists public.thresholds (
  id bigint generated always as identity primary key,
  patient_id uuid references public.patients(id) on delete cascade,
  parameter text not null check (parameter in ('heart_rate', 'spo2', 'resp_rate', 'systolic', 'diastolic')),
  low numeric,
  high numeric,
  enabled boolean not null default true,
  updated_by uuid,
  updated_at timestamptz not null default now(),
  check (low is null or high is null or low < high)
);
create unique index if not exists thresholds_scope_param
  on public.thresholds (coalesce(patient_id, '00000000-0000-0000-0000-000000000000'::uuid), parameter);

create table if not exists public.alarms (
  id uuid primary key default gen_random_uuid(),
  monitor_id text not null references public.monitors(id) on delete cascade,
  patient_id uuid references public.patients(id) on delete set null,
  bed_id text,
  type text not null check (type in ('hr_high', 'hr_low', 'spo2_low', 'rr_high', 'rr_low', 'bp_high', 'bp_low',
                                     'battery_low', 'sensor_issue', 'connection_lost')),
  category text not null check (category in ('physiological', 'technical')),
  severity text not null check (severity in ('critical', 'warning', 'advisory')),
  message text not null,
  value numeric,
  threshold numeric,
  state text not null default 'active' check (state in ('active', 'resolved')),
  raised_at timestamptz not null,
  raised_tick integer not null,
  last_seen_at timestamptz not null,
  resolved_at timestamptz,
  acknowledged_at timestamptz,
  acknowledged_by uuid,
  acknowledged_by_name text,
  ack_note text check (char_length(ack_note) <= 500)
);
-- At most one active alarm per monitor and condition type.
create unique index if not exists alarms_one_active on public.alarms (monitor_id, type) where state = 'active';
create index if not exists alarms_state_raised on public.alarms (state, raised_at desc);

create table if not exists public.notes (
  id uuid primary key default gen_random_uuid(),
  patient_id uuid not null references public.patients(id) on delete cascade,
  author_id uuid,
  category text not null check (category in ('nursing', 'physician', 'handover', 'device')),
  body_encrypted text not null,
  created_at timestamptz not null default now()
);
create index if not exists notes_patient_time on public.notes (patient_id, created_at desc);

create table if not exists public.maintenance_records (
  id uuid primary key default gen_random_uuid(),
  monitor_id text not null references public.monitors(id) on delete cascade,
  type text not null check (type in ('inspection', 'battery_replacement', 'sensor_replacement', 'repair', 'calibration', 'issue_report')),
  status text not null default 'open' check (status in ('open', 'in_progress', 'completed')),
  description text not null check (char_length(description) between 1 and 1000),
  resolution text check (char_length(resolution) <= 1000),
  opened_by uuid,
  opened_by_name text,
  completed_by uuid,
  completed_by_name text,
  opened_at timestamptz not null default now(),
  completed_at timestamptz
);

create table if not exists public.sim_state (
  id integer primary key check (id = 1),
  tick integer not null default 0,
  sim_time timestamptz not null default now(),
  seed integer not null default 4242,
  tick_seconds integer not null default 5,
  auto_run boolean not null default false,
  last_advanced_at timestamptz,
  updated_at timestamptz not null default now()
);

create table if not exists public.sim_events (
  id bigint generated always as identity primary key,
  tick integer not null,
  occurred_at timestamptz not null default now(),
  kind text not null,
  monitor_id text,
  patient_id uuid,
  message text not null,
  data jsonb not null default '{}'::jsonb,
  actor_id uuid
);
create index if not exists sim_events_time on public.sim_events (id desc);

create table if not exists public.integration_outbox (
  id bigint generated always as identity primary key,
  channel text not null check (channel in ('pager', 'ehr', 'email', 'privacy_office')),
  recipient text not null,
  subject text not null,
  payload jsonb not null default '{}'::jsonb,
  status text not null default 'delivered' check (status in ('queued', 'delivered', 'failed')),
  created_at timestamptz not null default now()
);

create table if not exists public.reports (
  id uuid primary key default gen_random_uuid(),
  kind text not null check (kind in ('shift_summary', 'alarm_log', 'device_maintenance', 'patient_vitals')),
  title text not null,
  params jsonb not null default '{}'::jsonb,
  summary jsonb not null default '{}'::jsonb,
  deidentified boolean not null default false,
  storage_path text,
  size_bytes integer,
  sha256 text,
  row_count integer,
  created_by uuid,
  created_by_name text,
  created_at timestamptz not null default now()
);

create table if not exists public.audit_log (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  actor_id uuid,
  actor_email text,
  actor_role text,
  action text not null,
  entity_type text,
  entity_id text,
  outcome text not null default 'success' check (outcome in ('success', 'failure', 'denied')),
  details jsonb not null default '{}'::jsonb,
  ip text,
  user_agent text,
  request_id text,
  prev_hash text not null,
  hash text not null
);

create table if not exists public.emergency_access (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  patient_id uuid not null references public.patients(id) on delete cascade,
  reason text not null check (char_length(reason) between 15 and 500),
  granted_at timestamptz not null default now(),
  expires_at timestamptz not null,
  reviewed_by uuid,
  reviewed_at timestamptz
);

create table if not exists public.privacy_requests (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  kind text not null check (kind in ('deletion', 'consent_withdrawal')),
  status text not null default 'pending' check (status in ('pending', 'completed', 'rejected')),
  details text check (char_length(details) <= 500),
  created_at timestamptz not null default now(),
  handled_by uuid,
  handled_at timestamptz
);

create table if not exists public.auth_throttle (
  key text primary key,
  failures integer not null default 0,
  first_failure_at timestamptz,
  locked_until timestamptz
);

create table if not exists public.rate_limits (
  bucket text not null,
  window_start timestamptz not null,
  count integer not null default 0,
  primary key (bucket, window_start)
);

-- Sessions established through the API login endpoint. Any token whose session_id is not here
-- (or is revoked / idle / past its absolute lifetime) is rejected by the API and by RLS.
create table if not exists public.user_sessions (
  session_id uuid primary key,
  user_id uuid not null,
  created_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  expires_at timestamptz not null,
  idle_timeout_seconds integer not null default 900,
  mfa_enrolled boolean not null default false,
  ip text,
  user_agent text,
  revoked_at timestamptz,
  revoked_reason text
);
create index if not exists user_sessions_user on public.user_sessions (user_id, created_at desc);

create table if not exists public.device_nonces (
  nonce text primary key,
  monitor_id text not null,
  seen_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Helper functions used by RLS policies (SECURITY DEFINER, fixed search_path)
-- ---------------------------------------------------------------------------
create or replace function public.app_role() returns text
language sql stable security definer set search_path = ''
as $$
  select p.role
  from public.profiles p
  join public.user_sessions s
    on s.user_id = p.id
   and s.session_id = nullif(auth.jwt() ->> 'session_id', '')::uuid
  where p.id = auth.uid()
    and p.active
    and s.revoked_at is null
    and s.expires_at > now()
    and s.last_seen_at + make_interval(secs => s.idle_timeout_seconds) > now()
$$;

create or replace function public.has_emergency_access(p_patient uuid) returns boolean
language sql stable security definer set search_path = ''
as $$
  select exists (
    select 1 from public.emergency_access e
    where e.user_id = auth.uid() and e.patient_id = p_patient and e.expires_at > now()
  )
$$;

revoke all on function public.app_role() from public;
revoke all on function public.has_emergency_access(uuid) from public;
grant execute on function public.app_role() to authenticated, acme_api;
grant execute on function public.has_emergency_access(uuid) to authenticated, acme_api;

-- Data retention: readings and simulation events older than the retention window are destroyed.
create or replace function public.purge_expired_data(retention interval default interval '7 days') returns integer
language plpgsql security invoker set search_path = ''
as $$
declare
  removed integer := 0;
  n integer;
  cutoff timestamptz;
begin
  select s.sim_time - retention into cutoff from public.sim_state s where s.id = 1;
  if cutoff is null then
    return 0;
  end if;
  delete from public.vital_readings where recorded_at < cutoff;
  get diagnostics n = row_count; removed := removed + n;
  delete from public.rate_limits where window_start < now() - interval '1 day';
  delete from public.device_nonces where seen_at < now() - interval '1 day';
  delete from public.emergency_access where expires_at < now() - interval '90 days';
  delete from public.user_sessions where expires_at < now() - interval '30 days';
  return removed;
end $$;
grant execute on function public.purge_expired_data(interval) to acme_api;

-- ---------------------------------------------------------------------------
-- Privileges
-- ---------------------------------------------------------------------------
-- Supabase grants broad default privileges to anon/authenticated; tighten them.
revoke all on all tables in schema public from anon;
revoke all on all tables in schema public from authenticated;
revoke all on all sequences in schema public from anon, authenticated;

grant select on public.profiles, public.beds, public.patients, public.monitors, public.vital_readings,
  public.thresholds, public.alarms, public.notes, public.maintenance_records, public.sim_state,
  public.sim_events to authenticated;

grant select, insert, update, delete on all tables in schema public to acme_api;
grant usage, select on all sequences in schema public to acme_api;
-- The audit log is append-only for the API.
revoke update, delete on public.audit_log from acme_api;

-- ---------------------------------------------------------------------------
-- Row Level Security
-- ---------------------------------------------------------------------------
do $$
declare
  t text;
begin
  foreach t in array array['profiles', 'beds', 'patients', 'monitors', 'monitor_assignments', 'vital_readings',
    'thresholds', 'alarms', 'notes', 'maintenance_records', 'sim_state', 'sim_events', 'integration_outbox',
    'reports', 'audit_log', 'emergency_access', 'privacy_requests', 'auth_throttle', 'rate_limits',
    'user_sessions', 'device_nonces']
  loop
    execute format('alter table public.%I enable row level security', t);
    execute format('drop policy if exists api_all on public.%I', t);
    execute format('create policy api_all on public.%I for all to acme_api using (true) with check (true)', t);
  end loop;
end $$;

-- The audit log: insert and read only (no update/delete policy for anyone).
drop policy if exists api_all on public.audit_log;
create policy api_insert on public.audit_log for insert to acme_api with check (true);
create policy api_select on public.audit_log for select to acme_api using (true);

-- Browser (Realtime) read access.
drop policy if exists own_profile on public.profiles;
create policy own_profile on public.profiles for select to authenticated using (id = auth.uid());

drop policy if exists staff_read on public.beds;
create policy staff_read on public.beds for select to authenticated using (public.app_role() is not null);

drop policy if exists staff_read on public.monitors;
create policy staff_read on public.monitors for select to authenticated using (public.app_role() is not null);

drop policy if exists staff_read on public.alarms;
create policy staff_read on public.alarms for select to authenticated using (public.app_role() is not null);

drop policy if exists staff_read on public.maintenance_records;
create policy staff_read on public.maintenance_records for select to authenticated using (public.app_role() is not null);

drop policy if exists staff_read on public.sim_state;
create policy staff_read on public.sim_state for select to authenticated using (public.app_role() is not null);

drop policy if exists staff_read on public.sim_events;
create policy staff_read on public.sim_events for select to authenticated using (public.app_role() is not null);

drop policy if exists clinical_read on public.patients;
create policy clinical_read on public.patients for select to authenticated
  using (public.app_role() in ('nurse', 'physician', 'admin') or public.has_emergency_access(id));

drop policy if exists clinical_read on public.vital_readings;
create policy clinical_read on public.vital_readings for select to authenticated
  using (public.app_role() in ('nurse', 'physician', 'admin') or public.has_emergency_access(patient_id));

drop policy if exists clinical_read on public.thresholds;
create policy clinical_read on public.thresholds for select to authenticated
  using (public.app_role() in ('nurse', 'physician', 'admin'));

drop policy if exists clinical_read on public.notes;
create policy clinical_read on public.notes for select to authenticated
  using (public.app_role() in ('nurse', 'physician', 'admin') or public.has_emergency_access(patient_id));

-- ---------------------------------------------------------------------------
-- Database activity auditing (pgaudit is available on Supabase; skipped where absent)
-- ---------------------------------------------------------------------------
do $$
begin
  if exists (select 1 from pg_available_extensions where name = 'pgaudit') then
    create extension if not exists pgaudit;
    execute 'alter role acme_api set pgaudit.log = ''write, ddl, role''';
  end if;
exception when others then
  raise notice 'pgaudit not enabled: %', sqlerrm;
end $$;

-- ---------------------------------------------------------------------------
-- Realtime publication (Supabase). Payloads are filtered by the RLS policies above.
-- ---------------------------------------------------------------------------
do $$
declare
  t text;
begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    foreach t in array array['monitors', 'alarms', 'vital_readings', 'patients', 'notes',
      'maintenance_records', 'sim_state', 'sim_events', 'thresholds']
    loop
      if not exists (select 1 from pg_publication_tables
                     where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = t) then
        execute format('alter publication supabase_realtime add table public.%I', t);
      end if;
    end loop;
  end if;
end $$;

-- ---------------------------------------------------------------------------
-- Private storage buckets (accessed only by the API with short-lived signed URLs)
-- ---------------------------------------------------------------------------
do $$
begin
  if to_regclass('storage.buckets') is not null then
    insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
    values ('avatars', 'avatars', false, 2097152, array['image/png']),
           ('reports', 'reports', false, 10485760, array['text/csv'])
    on conflict (id) do nothing;
  end if;
end $$;
