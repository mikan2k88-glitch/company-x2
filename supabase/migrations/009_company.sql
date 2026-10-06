-- E06-E09 isolated intake, production, test-payment evidence and AI budget ledger.
-- Apply after 002. Does not change earlier queues or another app's schema.
begin;
create table if not exists company_x2.company_orders (
 id text primary key default 'cx_'||gen_random_uuid()::text,
 request_key text unique not null, request_hash text not null, token_hash text not null,
 plan jsonb not null, source_url text not null default '', input text not null,
 status text not null check(status in ('awaiting_payment','queued','processing','ready','delivered','failed')),
 payment_status text not null check(payment_status in ('unpaid','paid','not_required')),
 session_id text unique, session_url text, result jsonb, error text,
 lease text, lease_until timestamptz, attempts integer not null default 0,
 created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table if not exists company_x2.company_events (
 id bigint generated always as identity primary key, order_id text not null references company_x2.company_orders(id),
 kind text not null, created_at timestamptz not null default now()
);
create table if not exists company_x2.company_payment_events (
 event_id text primary key, order_id text not null references company_x2.company_orders(id),
 fingerprint text not null, created_at timestamptz not null default now()
);
create table if not exists company_x2.company_ai_calls (
 request_hash text primary key, month text not null, day text not null,
 reserve bigint not null check(reserve>0), result jsonb, created_at timestamptz not null default now()
);
alter table company_x2.company_orders enable row level security;
alter table company_x2.company_events enable row level security;
alter table company_x2.company_payment_events enable row level security;
alter table company_x2.company_ai_calls enable row level security;
create or replace function public.cx2_company(p_action text,p_payload jsonb default '{}'::jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare
 r company_x2.company_orders%rowtype;
 a company_x2.company_ai_calls%rowtype;
 e company_x2.company_payment_events%rowtype;
 v jsonb; n bigint; d bigint;
begin
 if p_action='ping' then return jsonb_build_object('schema_version',9);
 elsif p_action='create' then
  if jsonb_typeof(p_payload->'input') is distinct from 'string' or octet_length(p_payload->>'input')>1000000
   or length(coalesce(p_payload->>'request_key','')) not between 16 and 128
   or coalesce(p_payload->>'request_hash','') !~ '^[a-f0-9]{64}$'
   or coalesce(p_payload->>'token_hash','') !~ '^[a-f0-9]{64}$'
   or coalesce(p_payload->'plan'->>'payment_mode','') not in ('sandbox','stripe_test')
   or coalesce(p_payload->'plan'->>'service_key','') not in ('csv_exact_dedup','csv_trim','csv_to_json','csv_audit')
   or coalesce(p_payload->'plan'->>'currency','')<>'jpy'
   or coalesce(p_payload->'plan'->>'terms_version','')<>'e09-v1'
   or coalesce(p_payload->'plan'->>'price_jpy','') <> (case when p_payload->'plan'->>'payment_mode'='stripe_test' then '100' else '0' end)
   then raise exception 'Invalid company order' using errcode='22023'; end if;
  perform pg_advisory_xact_lock(20261006,9);
  select * into r from company_x2.company_orders where request_key=p_payload->>'request_key';
  if found then
   if r.request_hash<>p_payload->>'request_hash' or r.token_hash<>p_payload->>'token_hash' then
    raise exception 'Request key conflict' using errcode='22023'; end if;
   return to_jsonb(r.id);
  end if;
  if (select count(*) from company_x2.company_orders where status in ('awaiting_payment','queued','processing'))>=100 then
   raise exception 'Queue full' using errcode='22023'; end if;
  insert into company_x2.company_orders(request_key,request_hash,token_hash,plan,source_url,input,status,payment_status)
   values(p_payload->>'request_key',p_payload->>'request_hash',p_payload->>'token_hash',p_payload->'plan',
    coalesce(p_payload->>'source_url',''),p_payload->>'input',
    case when p_payload->'plan'->>'payment_mode'='stripe_test' then 'awaiting_payment' else 'queued' end,
    case when p_payload->'plan'->>'payment_mode'='stripe_test' then 'unpaid' else 'not_required' end) returning * into r;
  insert into company_x2.company_events(order_id,kind) values(r.id,'agreement_saved');
  return to_jsonb(r.id);
 elsif p_action='get' then
  select * into r from company_x2.company_orders where id=p_payload->>'id' and token_hash=p_payload->>'token_hash';
  if not found then return null; end if;
  select coalesce(jsonb_agg(jsonb_build_object('kind',kind,'created_at',created_at) order by id),'[]'::jsonb)
   into v from company_x2.company_events where order_id=r.id;
  return jsonb_build_object('id',r.id,'status',r.status,'payment_status',r.payment_status,'plan',r.plan,
   'source_url',r.source_url,'session_id',r.session_id,'session_url',r.session_url,'error',r.error,'result',r.result,
   'events',v,'revenue_jpy',0);
 elsif p_action='session' then
  select * into r from company_x2.company_orders where id=p_payload->>'id' and token_hash=p_payload->>'token_hash' for update;
  if not found then raise exception 'Transaction not found' using errcode='22023'; end if;
  if r.session_id is not null then
   if r.session_id<>p_payload->>'session_id' then raise exception 'Session conflict' using errcode='22023'; end if;
   return to_jsonb(true);
  end if;
  if r.status<>'awaiting_payment' or r.plan->>'payment_mode'<>'stripe_test'
    or coalesce(p_payload->>'session_id','') !~ '^cs_test_[A-Za-z0-9]+$'
    or coalesce(p_payload->>'session_url','') !~ '^https://checkout\.stripe\.com/' then
   raise exception 'Checkout not allowed' using errcode='22023'; end if;
  update company_x2.company_orders set session_id=p_payload->>'session_id',session_url=p_payload->>'session_url',updated_at=now() where id=r.id;
  insert into company_x2.company_events(order_id,kind) values(r.id,'checkout_created');
  return to_jsonb(true);
 elsif p_action='payment' then
  perform pg_advisory_xact_lock(20261006,10);
  select * into e from company_x2.company_payment_events where event_id=p_payload->>'event_id';
  if found then
   if e.fingerprint<>p_payload->>'fingerprint' or e.order_id<>p_payload->>'id' then
    raise exception 'Payment event conflict' using errcode='22023'; end if;
   return to_jsonb(true);
  end if;
  select * into r from company_x2.company_orders where id=p_payload->>'id' for update;
  if not found then raise exception 'Transaction not found' using errcode='22023'; end if;
  if r.plan->>'payment_mode'<>'stripe_test' or p_payload->'livemode' is distinct from 'false'::jsonb
    or coalesce(p_payload->>'amount','')<>r.plan->>'price_jpy' or coalesce(p_payload->>'currency','')<>'jpy'
    or r.session_id is null or p_payload->>'session_id' is distinct from r.session_id
    or coalesce(p_payload->>'payment_status','')<>'paid'
    or coalesce(p_payload->>'fingerprint','') !~ '^[a-f0-9]{64}$'
    or length(coalesce(p_payload->>'event_id','')) not between 5 and 200 then
   raise exception 'Payment evidence mismatch' using errcode='22023'; end if;
  insert into company_x2.company_payment_events(event_id,order_id,fingerprint)
   values(p_payload->>'event_id',r.id,p_payload->>'fingerprint');
  if r.payment_status='unpaid' then
   update company_x2.company_orders set payment_status='paid',status='queued',updated_at=now() where id=r.id and status='awaiting_payment';
   insert into company_x2.company_events(order_id,kind) values(r.id,'test_payment_verified');
  end if;
  return to_jsonb(true);
 elsif p_action='claim' then
  with expired as (
   update company_x2.company_orders set status='failed',input='',error='Retry limit exceeded',updated_at=now()
   where status='processing' and lease_until<now() and attempts>=3 returning id
  ) insert into company_x2.company_events(order_id,kind) select id,'failed' from expired;
  select * into r from company_x2.company_orders
   where status='queued' or (status='processing' and lease_until<now() and attempts<3)
   order by created_at,id limit 1 for update skip locked;
  if not found then return null; end if;
  update company_x2.company_orders set status='processing',lease=gen_random_uuid()::text,
   lease_until=now()+interval '120 seconds',attempts=attempts+1,updated_at=now() where id=r.id returning * into r;
  insert into company_x2.company_events(order_id,kind) values(r.id,'processing_started');
  return jsonb_build_object('id',r.id,'input',r.input,'plan',r.plan,'lease',r.lease);
 elsif p_action='finish' then
  if p_payload->>'error' is null and (jsonb_typeof(p_payload->'result'->'artifact'->'content') is distinct from 'string'
   or octet_length(p_payload->'result'->'artifact'->>'content')>8000000
   or coalesce(p_payload->'result'->>'download_sha256','') !~ '^[a-f0-9]{64}$') then
   raise exception 'Invalid artifact' using errcode='22023'; end if;
  update company_x2.company_orders set status=case when p_payload->>'error' is null then 'ready' else 'failed' end,
   result=p_payload->'result',error=p_payload->>'error',input='',lease=null,lease_until=null,updated_at=now()
   where id=p_payload->>'id' and status='processing' and lease=p_payload->>'lease' and lease_until>now()
   and (p_payload->>'error' is not null or plan->>'service_key'=p_payload->'result'->>'service_key') returning * into r;
  if not found then raise exception 'Invalid or expired claim' using errcode='22023'; end if;
  insert into company_x2.company_events(order_id,kind) values(r.id,r.status);
  return to_jsonb(true);
 elsif p_action='receipt' then
  select * into r from company_x2.company_orders where id=p_payload->>'id' and token_hash=p_payload->>'token_hash' for update;
  if not found or r.status not in ('ready','delivered') or p_payload->>'download_sha256' is distinct from r.result->>'download_sha256' then
   raise exception 'Delivery evidence mismatch' using errcode='22023'; end if;
  if r.status='ready' then
   update company_x2.company_orders set status='delivered',updated_at=now() where id=r.id;
   insert into company_x2.company_events(order_id,kind) values(r.id,'client_receipt_confirmed');
  end if;
  return to_jsonb(true);
 elsif p_action='ai_reserve' then
  perform pg_advisory_xact_lock(20261006,11);
  select * into a from company_x2.company_ai_calls where request_hash=p_payload->>'request_hash';
  if found then return jsonb_build_object('reserved',false,'result',a.result); end if;
  if coalesce(p_payload->>'request_hash','') !~ '^[a-f0-9]{64}$'
   or coalesce(p_payload->>'month','') !~ '^[0-9]{4}-[0-9]{2}$'
   or coalesce(p_payload->>'day','') !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
   or (p_payload->>'reserve')::bigint<=0 then raise exception 'Invalid budget reservation' using errcode='22023'; end if;
  select coalesce(sum(reserve),0) into n from company_x2.company_ai_calls where month=p_payload->>'month';
  select coalesce(sum(reserve),0) into d from company_x2.company_ai_calls where day=p_payload->>'day';
  if n+(p_payload->>'reserve')::bigint>(p_payload->>'month_limit')::bigint
   or d+(p_payload->>'reserve')::bigint>(p_payload->>'day_limit')::bigint then
   raise exception 'AI budget exhausted' using errcode='22023'; end if;
  insert into company_x2.company_ai_calls(request_hash,month,day,reserve)
   values(p_payload->>'request_hash',p_payload->>'month',p_payload->>'day',(p_payload->>'reserve')::bigint);
  return jsonb_build_object('reserved',true);
 elsif p_action='ai_finish' then
  update company_x2.company_ai_calls set result=p_payload->'result' where request_hash=p_payload->>'request_hash' and result is null;
  if not found then raise exception 'Reservation unavailable' using errcode='22023'; end if;
  return to_jsonb(true);
 elsif p_action='pending_payments' then
  with pending as (
   select id from company_x2.company_orders where status='awaiting_payment' and session_id is not null
   and updated_at<now()-interval '60 seconds' order by updated_at,id limit 3 for update skip locked
  ), claimed as (
   update company_x2.company_orders set updated_at=now() where id in (select id from pending) returning id,session_id
  ) select coalesce(jsonb_agg(to_jsonb(claimed)),'[]'::jsonb) into v from claimed;
  return v;
 elsif p_action='overview' then
  select coalesce(jsonb_object_agg(s.status,s.n),'{}'::jsonb) into v from (select status,count(*) as n from company_x2.company_orders group by status) s;
  return jsonb_build_object('counts',v,'real_revenue_jpy',0,
   'test_payments_jpy',(select coalesce(sum((plan->>'price_jpy')::integer),0) from company_x2.company_orders where payment_status='paid'),
   'ai_reserved_micro_usd',(select coalesce(sum(reserve),0) from company_x2.company_ai_calls),
   'recent',(select coalesce(jsonb_agg(to_jsonb(s)),'[]'::jsonb) from
    (select id,status,payment_status,error,created_at from company_x2.company_orders order by created_at desc,id desc limit 20) s));
 end if;
 raise exception 'Unknown company operation' using errcode='22023';
end;
$$;
revoke all on function public.cx2_company(text,jsonb) from public,anon,authenticated;
grant execute on function public.cx2_company(text,jsonb) to service_role;
notify pgrst,'reload schema';
commit;
