-- E20: apply after 019. Keep the E19 RPC private and wrap refund operations.
begin;
do $$ begin
 if to_regprocedure('company_x2.cx2_company_e19(text,jsonb)') is null then
  alter function public.cx2_company(text,jsonb) set schema company_x2;
  alter function company_x2.cx2_company(text,jsonb) rename to cx2_company_e19;
 end if;
end $$;
revoke all on function company_x2.cx2_company_e19(text,jsonb) from public,anon,authenticated,service_role;
create table if not exists company_x2.company_payment_bindings (
 order_id text primary key references company_x2.company_orders(id), payment_intent text unique not null
);
create table if not exists company_x2.company_refund_jobs (
 order_id text primary key references company_x2.company_orders(id), state text not null,
 checked_at timestamptz not null default now()
);
create table if not exists company_x2.company_refunds (
 refund_id text primary key, order_id text not null references company_x2.company_orders(id),
 amount integer not null check(amount>0), status text not null
);
alter table company_x2.company_payment_bindings enable row level security;
alter table company_x2.company_refund_jobs enable row level security;
alter table company_x2.company_refunds enable row level security;
revoke all on company_x2.company_payment_bindings,company_x2.company_refund_jobs,company_x2.company_refunds from public,anon,authenticated;
create or replace function public.cx2_company(p_action text,p_payload jsonb default '{}'::jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare
 r company_x2.company_orders%rowtype;
 f company_x2.company_refunds%rowtype;
 v jsonb; items jsonb; job_state text; refunded integer; total integer; changed boolean;
begin
 if p_action='refund_ping' then return jsonb_build_object('refund_schema_version',20); end if;
 if p_action like 'refund_%' then perform pg_advisory_xact_lock(20261009,20); end if;
 if p_action='refund_bindings' then
  with candidates as (
   select o.id from company_x2.company_orders o where payment_status='paid' and session_id is not null
   and updated_at<=now()-interval '60 seconds' and not exists(select 1 from company_x2.company_payment_bindings b where b.order_id=o.id)
   order by updated_at,id limit 1 for update skip locked
  ), claimed as (
   update company_x2.company_orders set updated_at=now() where id in (select id from candidates) returning id,session_id,plan
  ) select coalesce(jsonb_agg(to_jsonb(claimed)),'[]'::jsonb) into v from claimed;
  return v;
 elsif p_action='refund_bind' then
  select * into r from company_x2.company_orders where id=p_payload->>'id' for update;
  if not found or r.payment_status<>'paid' or r.session_id is distinct from p_payload->>'session_id'
   or p_payload->'livemode' is distinct from to_jsonb(r.plan->>'payment_mode'='stripe_live')
   or coalesce(p_payload->>'payment_intent','') !~ '^pi_[A-Za-z0-9]+$' then
   raise exception 'Payment binding rejected' using errcode='22023'; end if;
  if exists(select 1 from company_x2.company_payment_bindings where order_id=r.id and payment_intent<>p_payload->>'payment_intent') then
   raise exception 'Payment binding conflict' using errcode='22023'; end if;
  insert into company_x2.company_payment_bindings values(r.id,p_payload->>'payment_intent') on conflict(order_id) do nothing;
  return to_jsonb(true);
 elsif p_action='refund_claim' then
  for r in select o.* from company_x2.company_orders o where o.payment_status='paid'
   and o.status in ('failed','queued','processing') and o.session_id is not null
   and (o.status='failed' or exists(select 1 from company_x2.company_payment_events e where e.order_id=o.id and e.created_at<=now()-interval '24 hours'))
   and not exists(select 1 from company_x2.company_refund_jobs j where j.order_id=o.id)
   order by o.id limit 3 for update skip locked loop
   insert into company_x2.company_refund_jobs(order_id,state,checked_at) values(r.id,'requesting',now()-interval '61 seconds');
   update company_x2.company_orders set status='failed',input='',lease=null,lease_until=null,error='Refund processing' where id=r.id;
   insert into company_x2.company_events(order_id,kind) values(r.id,'refund_reserved');
  end loop;
  select o.* into r from company_x2.company_orders o join company_x2.company_refund_jobs j on j.order_id=o.id
   where j.state in ('requesting','pending') and j.checked_at<=now()-interval '60 seconds'
   order by j.checked_at,o.id limit 1 for update of o,j skip locked;
  if not found then return null; end if;
  update company_x2.company_refund_jobs set checked_at=now() where order_id=r.id;
  return jsonb_build_object('id',r.id,'session_id',r.session_id,'plan',r.plan);
 elsif p_action='refund_review' then
  update company_x2.company_refund_jobs set state='review' where order_id=p_payload->>'id' and state<>'succeeded';
  return to_jsonb(true);
 elsif p_action='refund_update' then
  select o.* into r from company_x2.company_orders o join company_x2.company_payment_bindings b on b.order_id=o.id
   where b.payment_intent=p_payload->>'payment_intent' for update of o;
  if not found then return to_jsonb(false); end if;
  if coalesce(p_payload->>'refund_id','') !~ '^re_[A-Za-z0-9]+$' or coalesce(p_payload->>'currency','')<>'jpy'
   or p_payload->'livemode' is distinct from to_jsonb(r.plan->>'payment_mode'='stripe_live')
   or jsonb_typeof(p_payload->'amount') is distinct from 'number'
   or coalesce(p_payload->>'amount','') !~ '^[0-9]{1,5}$'
   or (p_payload->>'amount')::integer not between 1 and (r.plan->>'price_jpy')::integer
   or coalesce(p_payload->>'status','') not in ('pending','requires_action','succeeded','failed','canceled') then
   raise exception 'Refund evidence mismatch' using errcode='22023'; end if;
  select * into f from company_x2.company_refunds where refund_id=p_payload->>'refund_id';
  if found and (f.order_id<>r.id or f.amount<>(p_payload->>'amount')::integer) then
   raise exception 'Refund identity conflict' using errcode='22023'; end if;
  if f.status in ('succeeded','failed','canceled') and p_payload->>'status' in ('pending','requires_action') then return to_jsonb(true); end if;
  select coalesce(sum(amount),0) into total from company_x2.company_refunds where order_id=r.id
   and refund_id<>p_payload->>'refund_id' and status in ('succeeded','pending','requires_action');
  if p_payload->>'status' in ('succeeded','pending','requires_action') and total+(p_payload->>'amount')::integer>(r.plan->>'price_jpy')::integer then
   raise exception 'Refund total mismatch' using errcode='22023'; end if;
  changed:=f.refund_id is null or f.status is distinct from p_payload->>'status';
  insert into company_x2.company_refunds values(p_payload->>'refund_id',r.id,(p_payload->>'amount')::integer,p_payload->>'status')
   on conflict(refund_id) do update set status=excluded.status;
  select coalesce(sum(amount),0) into refunded from company_x2.company_refunds where order_id=r.id and status='succeeded';
  job_state:=case when refunded=(r.plan->>'price_jpy')::integer then 'succeeded'
   when exists(select 1 from company_x2.company_refunds where order_id=r.id and status='pending' and amount=(r.plan->>'price_jpy')::integer) then 'pending' else 'review' end;
  insert into company_x2.company_refund_jobs(order_id,state) values(r.id,job_state) on conflict(order_id) do update set state=excluded.state;
  if job_state in ('pending','succeeded') and r.status not in ('ready','delivered') then
   update company_x2.company_orders set status='failed',input='',lease=null,lease_until=null where id=r.id; end if;
  if changed then insert into company_x2.company_events(order_id,kind) values(r.id,'refund_'||(p_payload->>'status')); end if;
  return to_jsonb(true);
 elsif p_action='finish' and p_payload->>'error' is not null then
  select * into r from company_x2.company_orders where id=p_payload->>'id' for update;
  if r.status='processing' and r.lease=p_payload->>'lease' and r.lease_until>now() and r.attempts<3 then
   update company_x2.company_orders set status='queued',error=p_payload->>'error',lease=null,lease_until=null where id=r.id;
   insert into company_x2.company_events(order_id,kind) values(r.id,'queued'); return to_jsonb(true);
  end if;
 end if;
 if p_action='receipt' then
  perform 1 from company_x2.company_orders where id=p_payload->>'id' for update;
  if exists(select 1 from company_x2.company_refund_jobs where order_id=p_payload->>'id') then
   raise exception 'Refunded order cannot be received' using errcode='22023'; end if;
 end if;
 v:=company_x2.cx2_company_e19(p_action,p_payload);
 if p_action='get' and v is not null then
  select coalesce(jsonb_agg(jsonb_build_object('refund_id',refund_id,'amount',amount,'status',status)),'[]'::jsonb),
   coalesce(sum(amount) filter(where status='succeeded'),0) into items,refunded from company_x2.company_refunds where order_id=p_payload->>'id';
  select state into job_state from company_x2.company_refund_jobs where order_id=p_payload->>'id';
  v:=v||jsonb_build_object('refund',jsonb_build_object('state',coalesce(job_state,'none'),'items',items,'refunded_jpy',refunded));
 elsif p_action='overview' then
  select coalesce(sum(f.amount) filter(where o.plan->>'payment_mode'='stripe_live'),0),
   coalesce(sum(f.amount) filter(where o.plan->>'payment_mode'='stripe_test'),0) into refunded,total
   from company_x2.company_refunds f join company_x2.company_orders o on o.id=f.order_id where f.status='succeeded';
  select coalesce(jsonb_object_agg(state,n),'{}'::jsonb) into items from (select state,count(*) n from company_x2.company_refund_jobs group by state) s;
  v:=v||jsonb_build_object('live_refunded_jpy',refunded,'test_refunded_jpy',total,'refund_counts',items);
  select coalesce(jsonb_agg(x.item||jsonb_build_object('refund_state',coalesce(j.state,'none'))),'[]'::jsonb) into items
   from jsonb_array_elements(v->'recent') x(item) left join company_x2.company_refund_jobs j on j.order_id=x.item->>'id';
  v:=v||jsonb_build_object('recent',items);
 end if;
 return v;
end $$;
revoke all on function public.cx2_company(text,jsonb) from public,anon,authenticated;
grant execute on function public.cx2_company(text,jsonb) to service_role;
notify pgrst,'reload schema';
commit;
