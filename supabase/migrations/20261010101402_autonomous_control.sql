create table company_x2.autonomy_runs(id text primary key check(id ~ '^[0-9]{8}_[0-9]{2}$'),lease text not null,status text not null default 'processing' check(status in ('processing','success','failed')),report jsonb,started_at timestamptz not null default now());
create table company_x2.autonomy_messages(id text primary key,contact_id text unique not null references company_x2.outreach_contacts(id),reply_id bigint not null,body text not null check(length(body) between 1 and 4000),status text not null default 'draft' check(status in ('draft','sending','sent','uncertain')),attempted_at timestamptz,comment_url text);
alter table company_x2.autonomy_runs enable row level security;
alter table company_x2.autonomy_messages enable row level security;
revoke all on company_x2.autonomy_runs,company_x2.autonomy_messages from public,anon,authenticated,service_role;
alter function public.cx2_outreach(text,jsonb) set schema company_x2;
alter function company_x2.cx2_outreach(text,jsonb) rename to cx2_outreach_e25;
revoke all on function company_x2.cx2_outreach_e25(text,jsonb) from public,anon,authenticated,service_role;
create function public.cx2_outreach(p_action text,p_payload jsonb default '{}'::jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
begin
 if p_action='claim' then
  perform pg_catalog.pg_advisory_xact_lock(250025);
  if exists(select 1 from company_x2.autonomy_messages where attempted_at>=date_trunc('day',now() at time zone 'UTC') at time zone 'UTC') then return null;end if;
 end if;
 return company_x2.cx2_outreach_e25(p_action,p_payload);
end;$$;
revoke all on function public.cx2_outreach(text,jsonb) from public,anon,authenticated;
grant execute on function public.cx2_outreach(text,jsonb) to service_role;
create function public.cx2_autonomy(p_action text,p_payload jsonb default '{}'::jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
declare r company_x2.autonomy_messages; v jsonb; newlease text; changed boolean;
begin
 if p_action='ping' then return '{"autonomy_schema_version":34}'::jsonb;
 elsif p_action='claim' then
  if p_payload->>'id'<>to_char(now() at time zone 'UTC','YYYYMMDD_HH24') then raise exception 'Current UTC hour required' using errcode='22023';end if;
  newlease:=gen_random_uuid()::text;
  insert into company_x2.autonomy_runs(id,lease) values(p_payload->>'id',newlease) on conflict do nothing;
  return case when found then to_jsonb(newlease) else null end;
 elsif p_action='finish' then
  if p_payload->>'status' not in ('success','failed') or pg_catalog.octet_length((p_payload->'report')::text)>20000 then raise exception 'Invalid run report' using errcode='22023';end if;
  update company_x2.autonomy_runs set status=p_payload->>'status',report=p_payload->'report' where id=p_payload->>'id' and lease=p_payload->>'lease' and status='processing';return to_jsonb(found);
 elsif p_action='status' then
  return jsonb_build_object('runs',(select coalesce(jsonb_agg(to_jsonb(x)),'[]'::jsonb) from (select id,status,report,started_at from company_x2.autonomy_runs order by started_at desc limit 24) x),'messages',(select coalesce(jsonb_agg(to_jsonb(x)),'[]'::jsonb) from (select id,contact_id,reply_id,status,comment_url from company_x2.autonomy_messages limit 50) x));
 elsif p_action='prepare_message' then
  if not exists(select 1 from company_x2.outreach_contacts where id=p_payload->>'contact_id' and status='sent' and reply_id=(p_payload->>'reply_id')::bigint) then raise exception 'Reply evidence required' using errcode='22023';end if;
  insert into company_x2.autonomy_messages(id,contact_id,reply_id,body) values('am_'||(p_payload->>'contact_id'),p_payload->>'contact_id',(p_payload->>'reply_id')::bigint,p_payload->>'body') on conflict do nothing;return to_jsonb(found);
 elsif p_action='claim_message' then
  perform pg_catalog.pg_advisory_xact_lock(250025);
  if exists(select 1 from company_x2.outreach_contacts where attempted_at>=date_trunc('day',now() at time zone 'UTC') at time zone 'UTC') or exists(select 1 from company_x2.autonomy_messages where attempted_at>=date_trunc('day',now() at time zone 'UTC') at time zone 'UTC') then return null;end if;
  select * into r from company_x2.autonomy_messages where status='draft' order by id limit 1 for update;
  if not found then return null;end if;
  update company_x2.autonomy_messages set status='sending',attempted_at=now() where id=r.id;return to_jsonb(r);
 elsif p_action in ('finish_message','uncertain_message') then
  update company_x2.autonomy_messages set status=case when p_action='finish_message' then 'sent' else 'uncertain' end,comment_url=p_payload->>'url' where id=p_payload->>'id' and status='sending';return to_jsonb(found);
 elsif p_action='metrics' then
  with orders as (select * from company_x2.company_orders where created_at>=date_trunc('month',now() at time zone 'UTC') at time zone 'UTC'),live as (select * from orders where plan->>'payment_mode'='stripe_live' and payment_status='paid'),refunds as (select f.* from company_x2.company_refunds f join live on live.id=f.order_id where f.status='succeeded')
  select jsonb_build_object('orders',(select count(*) from orders),'failed',(select count(*) from orders where status='failed'),'live_orders',(select count(*) from live),'live_revenue_jpy',(select coalesce(sum((plan->>'price_jpy')::integer),0) from live),'live_refunds_jpy',(select coalesce(sum(amount),0) from refunds),'refunded_orders',(select count(distinct order_id) from refunds),'ai_reserved_micro_usd',(select coalesce(sum(reserve),0) from company_x2.company_ai_calls where month=to_char(now() at time zone 'UTC','YYYY-MM'))) into v;return v;
 end if;
 raise exception 'Unknown autonomy action' using errcode='22023';
end;$$;
revoke all on function public.cx2_autonomy(text,jsonb) from public,anon,authenticated;
grant execute on function public.cx2_autonomy(text,jsonb) to service_role;
notify pgrst,'reload schema';
