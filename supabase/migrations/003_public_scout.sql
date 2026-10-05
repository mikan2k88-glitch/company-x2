-- E03 public discovery. Apply AFTER 002. Existing orders are preserved.
begin;
create table if not exists company_x2.scout_state (
 id integer primary key check(id=1), status text not null default 'waiting',
 lease text, lease_until timestamptz, next_run_at timestamptz not null default now(),
 last_attempt_at timestamptz, last_success_at timestamptz, error text, report jsonb
);
alter table company_x2.scout_state enable row level security;
insert into company_x2.scout_state(id) values(1) on conflict do nothing;
create or replace function public.cx2_scout(p_action text, p_payload jsonb default '{}'::jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare
 s company_x2.scout_state%rowtype;
 c jsonb;
 items jsonb;
 delay integer;
begin
 if p_action='snapshot' then
  select * into s from company_x2.scout_state where id=1 for share;
  select coalesce(jsonb_agg(data order by external_id),'[]'::jsonb) into items
   from company_x2.sandbox_opportunities where source='github_public_bounty';
  return jsonb_build_object('status',case when s.status='running' and s.lease_until<now() then 'retry_wait' else s.status end,
   'next_run_at',s.next_run_at,'last_attempt_at',s.last_attempt_at,'last_success_at',s.last_success_at,
   'error',s.error,'report',s.report,'items',items);
 elsif p_action='claim' then
  update company_x2.scout_state set status='running',lease=gen_random_uuid()::text,
   lease_until=now()+interval '180 seconds',last_attempt_at=now(),error=null
   where id=1 and next_run_at<=now() and (lease_until is null or lease_until<now()) returning * into s;
  if not found then return null; end if;
  return to_jsonb(s.lease);
 elsif p_action='finish' then
  select * into s from company_x2.scout_state where id=1 for update;
  if s.lease is null or s.lease<>p_payload->>'lease' or s.lease_until<=now() then
   raise exception 'Invalid scout lease' using errcode='22023';
  end if;
  delay=greatest(300,least(86400,coalesce((p_payload->>'delay')::integer,3600)));
  if p_payload->>'error' is null then
   if jsonb_typeof(p_payload->'items') is distinct from 'array' or jsonb_array_length(p_payload->'items')>30 then
    raise exception 'Invalid scout batch' using errcode='22023';
   end if;
   for c in select value from jsonb_array_elements(p_payload->'items') loop
    if c->>'source' is distinct from 'github_public_bounty' or coalesce(c->>'external_id','') !~ '^[0-9]+$'
       or coalesce(c->>'decision','') not in ('needs_review','blocked','rejected') then
     raise exception 'Invalid candidate' using errcode='22023';
    end if;
   end loop;
   -- Replace only this connector's current snapshot, atomically with its completion.
   delete from company_x2.sandbox_opportunities where source='github_public_bounty';
   for c in select value from jsonb_array_elements(p_payload->'items') loop
    insert into company_x2.sandbox_opportunities(source,external_id,data,decision,reason)
     values(c->>'source',c->>'external_id',c,c->>'decision',c->>'reason');
   end loop;
   update company_x2.scout_state set status='completed',last_success_at=now(),report=p_payload->'report',error=null where id=1;
  else
   update company_x2.scout_state set status='retry_wait',error=left(p_payload->>'error',300) where id=1;
  end if;
  update company_x2.scout_state set lease=null,lease_until=null,next_run_at=now()+make_interval(secs=>delay) where id=1;
  return to_jsonb(true);
 end if;
 raise exception 'Unknown scout operation' using errcode='22023';
end;
$$;
revoke all on function public.cx2_scout(text,jsonb) from public,anon,authenticated;
grant execute on function public.cx2_scout(text,jsonb) to service_role;
notify pgrst,'reload schema';
commit;
