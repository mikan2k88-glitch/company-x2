-- Standalone sandbox persistence. Run in Supabase SQL Editor as project owner.
-- Does not modify existing applications' tables. API access is service-role only.
begin;
create schema if not exists company_x2;
create table if not exists company_x2.sandbox_orders (
 id text primary key default gen_random_uuid()::text,
 token_hash text not null, request_key text not null unique, request_hash text not null,
 status text not null check(status in ('queued','processing','ready','failed')),
 input text not null, result jsonb, error text,
 lease text, lease_until timestamptz, attempts integer not null default 0,
 created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table if not exists company_x2.sandbox_events (
 id bigint generated always as identity primary key,
 order_id text not null references company_x2.sandbox_orders(id),
 kind text not null, created_at timestamptz not null default now()
);
create table if not exists company_x2.sandbox_opportunities (
 source text not null, external_id text not null, data jsonb not null,
 decision text not null, reason text not null, created_at timestamptz not null default now(),
 primary key(source,external_id)
);
alter table company_x2.sandbox_orders enable row level security;
alter table company_x2.sandbox_events enable row level security;
alter table company_x2.sandbox_opportunities enable row level security;
revoke all on schema company_x2 from anon, authenticated;

create or replace function public.cx2_store(p_action text, p_payload jsonb default '{}'::jsonb)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
 r company_x2.sandbox_orders%rowtype;
 v_result jsonb;
 v_candidate jsonb;
begin
 if p_action='ping' then
  return jsonb_build_object('schema_version',2);
 elsif p_action='submit' then
  if length(coalesce(p_payload->>'request_key','')) not between 16 and 128
     or coalesce(p_payload->>'token_hash','') !~ '^[a-f0-9]{64}$'
     or coalesce(p_payload->>'request_hash','') !~ '^[a-f0-9]{64}$'
     or octet_length(coalesce(p_payload->>'input','')) > 1000000 then
   raise exception 'Invalid order' using errcode='22023';
  end if;
  -- Serialize intake to enforce pending-order capacity and idempotency atomically.
  perform pg_advisory_xact_lock(20261006,2);
  select * into r from company_x2.sandbox_orders where request_key=p_payload->>'request_key';
  if found then
   if r.request_hash <> p_payload->>'request_hash' or r.token_hash <> p_payload->>'token_hash' then
    raise exception 'Request key conflict' using errcode='22023';
   end if;
   return to_jsonb(r.id);
  end if;
  if (select count(*) from company_x2.sandbox_orders where status in ('queued','processing')) >= 100 then
   raise exception 'Queue capacity exceeded' using errcode='22023';
  end if;
  insert into company_x2.sandbox_orders(token_hash,request_key,request_hash,status,input)
   values(p_payload->>'token_hash',p_payload->>'request_key',p_payload->>'request_hash','queued',p_payload->>'input')
   returning * into r;
  insert into company_x2.sandbox_events(order_id,kind) values(r.id,'sandbox_order_received');
  return to_jsonb(r.id);
 elsif p_action='claim' then
  with expired as (
   update company_x2.sandbox_orders set status='failed',error='Retry limit exceeded',input='',updated_at=now()
   where status='processing' and lease_until<now() and attempts>=3 returning id
  ) insert into company_x2.sandbox_events(order_id,kind) select id,'failed' from expired;
  select * into r from company_x2.sandbox_orders
   where status='queued' or (status='processing' and lease_until<now() and attempts<3)
   order by created_at,id limit 1 for update skip locked;
  if not found then return null; end if;
  if r.status='processing' then
   insert into company_x2.sandbox_events(order_id,kind) values(r.id,'restart_requeued');
  end if;
  update company_x2.sandbox_orders set status='processing',lease=gen_random_uuid()::text,
   lease_until=now()+interval '120 seconds',attempts=attempts+1,updated_at=now()
   where id=r.id returning * into r;
  insert into company_x2.sandbox_events(order_id,kind) values(r.id,'processing_started');
  return jsonb_build_object('id',r.id,'input',r.input,'lease',r.lease);
 elsif p_action='finish' then
  update company_x2.sandbox_orders set
   status=case when p_payload->>'error' is null then 'ready' else 'failed' end,
   result=p_payload->'result',error=p_payload->>'error',input='',lease=null,lease_until=null,updated_at=now()
   where id=p_payload->>'id' and status='processing' and lease=p_payload->>'lease' and lease_until>now()
   returning * into r;
  if not found then raise exception 'Invalid or expired claim' using errcode='22023'; end if;
  insert into company_x2.sandbox_events(order_id,kind) values(r.id,r.status);
  return to_jsonb(true);
 elsif p_action='get' then
  select * into r from company_x2.sandbox_orders where id=p_payload->>'id' and token_hash=p_payload->>'token_hash';
  if not found then return null; end if;
  select coalesce(jsonb_agg(jsonb_build_object('kind',kind,'created_at',created_at) order by id),'[]'::jsonb)
   into v_result from company_x2.sandbox_events where order_id=r.id;
  return jsonb_build_object('id',r.id,'status',r.status,'error',r.error,'result',r.result,
   'events',v_result,'mode','sandbox','revenue_jpy',0);
 elsif p_action='opportunity' then
  v_candidate=p_payload->'candidate';
  insert into company_x2.sandbox_opportunities(source,external_id,data,decision,reason)
   values(v_candidate->>'source',v_candidate->>'external_id',v_candidate,p_payload->>'decision',p_payload->>'reason')
   on conflict(source,external_id) do update set data=excluded.data,decision=excluded.decision,reason=excluded.reason;
  return to_jsonb(true);
 elsif p_action='opportunities' then
  select coalesce(jsonb_agg(data || jsonb_build_object('decision',decision,'reason',reason)),'[]'::jsonb)
   into v_result from (select * from company_x2.sandbox_opportunities order by created_at desc limit 100) q;
  return v_result;
 end if;
 raise exception 'Unknown operation' using errcode='22023';
end;
$$;
revoke all on function public.cx2_store(text,jsonb) from public,anon,authenticated;
grant execute on function public.cx2_store(text,jsonb) to service_role;
notify pgrst,'reload schema';
commit;
