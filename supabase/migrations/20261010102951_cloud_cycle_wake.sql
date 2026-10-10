-- Managed Supabase deployment only. Portable CI tests the coordinator migration.
create extension if not exists pg_cron;
create extension if not exists pg_net with schema extensions;
create table company_x2.autonomy_wakes(request_id bigint primary key,created_at timestamptz not null default now());
alter table company_x2.autonomy_wakes enable row level security;
revoke all on company_x2.autonomy_wakes from public,anon,authenticated,service_role;
create function company_x2.wake_cycle() returns bigint language plpgsql security definer set search_path='' as $$
declare credential text; request_id bigint;
begin
 select decrypted_secret into credential from vault.decrypted_secrets where name='company_x2_cycle_agent_token';
 if credential is null or length(credential)<32 then raise exception 'Cycle credential missing';end if;
 select net.http_post(url:='https://company-x2.onrender.com/api/company/agent-scout',headers:=jsonb_build_object('Content-Type','application/json','Authorization','Bearer '||credential),body:='{"action":"cycle"}'::jsonb,timeout_milliseconds:=180000) into request_id;
 insert into company_x2.autonomy_wakes(request_id) values(request_id);
 return request_id;
end;$$;
revoke all on function company_x2.wake_cycle() from public,anon,authenticated,service_role;
-- Credential installation and cron.schedule are operator deployment steps.
