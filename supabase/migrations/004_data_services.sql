-- E04 new-service orders. Apply after 002. Does not change legacy order/scout RPCs.
begin;
create table if not exists company_x2.service_orders (
 id text primary key default 'svc_'||gen_random_uuid()::text,
 token_hash text not null, request_key text not null unique, request_hash text not null,
 service_key text not null check(service_key in ('csv_trim','csv_to_json','csv_audit')),
 status text not null check(status in ('queued','processing','ready','failed')),
 input text not null, result jsonb, error text,
 lease text, lease_until timestamptz, attempts integer not null default 0,
 created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table if not exists company_x2.service_events (
 id bigint generated always as identity primary key,
 order_id text not null references company_x2.service_orders(id),
 kind text not null, created_at timestamptz not null default now()
);
alter table company_x2.service_orders enable row level security;
alter table company_x2.service_events enable row level security;
-- A request key cannot change service even across legacy/new queues.
create or replace function company_x2.order_key_guard() returns trigger
language plpgsql security definer set search_path='' as $$
begin
 perform pg_advisory_xact_lock(20261006,2);
 if TG_TABLE_NAME='service_orders' then
  if exists(select 1 from company_x2.sandbox_orders where request_key=NEW.request_key) then
   raise exception 'Request key conflict' using errcode='22023';
  end if;
 else
  if exists(select 1 from company_x2.service_orders where request_key=NEW.request_key) then
   raise exception 'Request key conflict' using errcode='22023';
  end if;
 end if;
 return NEW;
end;
$$;
revoke all on function company_x2.order_key_guard() from public,anon,authenticated;
drop trigger if exists cx2_order_key_guard on company_x2.service_orders;
create trigger cx2_order_key_guard before insert on company_x2.service_orders
 for each row execute function company_x2.order_key_guard();
drop trigger if exists cx2_order_key_guard on company_x2.sandbox_orders;
create trigger cx2_order_key_guard before insert on company_x2.sandbox_orders
 for each row execute function company_x2.order_key_guard();
create or replace function public.cx2_services(p_action text, p_payload jsonb default '{}'::jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare
 r company_x2.service_orders%rowtype;
 v_result jsonb;
begin
 if p_action='ping' then
  return jsonb_build_object('schema_version',4);
 elsif p_action='submit' then
  if length(coalesce(p_payload->>'request_key','')) not between 16 and 128
     or coalesce(p_payload->>'service_key','') not in ('csv_trim','csv_to_json','csv_audit')
     or coalesce(p_payload->>'token_hash','') !~ '^[a-f0-9]{64}$'
     or coalesce(p_payload->>'request_hash','') !~ '^[a-f0-9]{64}$'
     or jsonb_typeof(p_payload->'input') is distinct from 'string'
     or octet_length(p_payload->>'input') > 1000000 then
   raise exception 'Invalid service order' using errcode='22023';
  end if;
  perform pg_advisory_xact_lock(20261006,4);
  select * into r from company_x2.service_orders where request_key=p_payload->>'request_key';
  if found then
   if r.request_hash<>p_payload->>'request_hash' or r.token_hash<>p_payload->>'token_hash'
      or r.service_key<>p_payload->>'service_key' then
    raise exception 'Request key conflict' using errcode='22023';
   end if;
   return to_jsonb(r.id);
  end if;
  if (select count(*) from company_x2.service_orders where status in ('queued','processing'))>=100 then
   raise exception 'Queue capacity exceeded' using errcode='22023';
  end if;
  insert into company_x2.service_orders(token_hash,request_key,request_hash,service_key,status,input)
   values(p_payload->>'token_hash',p_payload->>'request_key',p_payload->>'request_hash',
          p_payload->>'service_key','queued',p_payload->>'input') returning * into r;
  insert into company_x2.service_events(order_id,kind) values(r.id,'sandbox_order_received');
  return to_jsonb(r.id);
 elsif p_action='claim' then
  with expired as (
   update company_x2.service_orders set status='failed',error='Retry limit exceeded',input='',updated_at=now()
   where status='processing' and lease_until<now() and attempts>=3 returning id
  ) insert into company_x2.service_events(order_id,kind) select id,'failed' from expired;
  select * into r from company_x2.service_orders
   where status='queued' or (status='processing' and lease_until<now() and attempts<3)
   order by created_at,id limit 1 for update skip locked;
  if not found then return null; end if;
  if r.status='processing' then
   insert into company_x2.service_events(order_id,kind) values(r.id,'restart_requeued');
  end if;
  update company_x2.service_orders set status='processing',lease=gen_random_uuid()::text,
   lease_until=now()+interval '120 seconds',attempts=attempts+1,updated_at=now()
   where id=r.id returning * into r;
  insert into company_x2.service_events(order_id,kind) values(r.id,'processing_started');
  return jsonb_build_object('id',r.id,'input',r.input,'lease',r.lease,'service_key',r.service_key);
 elsif p_action='finish' then
  if p_payload->>'error' is null and (jsonb_typeof(p_payload->'result') is distinct from 'object'
     or jsonb_typeof(p_payload->'result'->'artifact'->'content') is distinct from 'string'
     or octet_length(coalesce(p_payload->'result'->'artifact'->>'content',''))>8000000) then
   raise exception 'Invalid artifact' using errcode='22023';
  end if;
  update company_x2.service_orders set
   status=case when p_payload->>'error' is null then 'ready' else 'failed' end,
   result=p_payload->'result',error=p_payload->>'error',input='',lease=null,lease_until=null,updated_at=now()
   where id=p_payload->>'id' and status='processing' and lease=p_payload->>'lease' and lease_until>now()
    and (p_payload->>'error' is not null or service_key=p_payload->'result'->>'service_key')
   returning * into r;
  if not found then raise exception 'Invalid or expired claim' using errcode='22023'; end if;
  insert into company_x2.service_events(order_id,kind) values(r.id,r.status);
  return to_jsonb(true);
 elsif p_action='get' then
  select * into r from company_x2.service_orders where id=p_payload->>'id' and token_hash=p_payload->>'token_hash';
  if not found then return null; end if;
  select coalesce(jsonb_agg(jsonb_build_object('kind',kind,'created_at',created_at) order by id),'[]'::jsonb)
   into v_result from company_x2.service_events where order_id=r.id;
  return jsonb_build_object('id',r.id,'status',r.status,'service_key',r.service_key,'error',r.error,'result',r.result,
   'events',v_result,'mode','sandbox','revenue_jpy',0);
 end if;
 raise exception 'Unknown operation' using errcode='22023';
end;
$$;
revoke all on function public.cx2_services(text,jsonb) from public,anon,authenticated;
grant execute on function public.cx2_services(text,jsonb) to service_role;
notify pgrst,'reload schema';
commit;
