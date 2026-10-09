-- Only verified order owners can report. No provider refund is sent here.
create table company_x2.support_cases (
 ticket_id text primary key references company_x2.support_tickets(id),
 order_id text not null references company_x2.company_orders(id),
 state text not null default 'pending' check(state in ('pending','confirmed_defect','not_confirmed')),
 reason text not null default '' check(length(reason)<=4000),
 created_at timestamptz not null default now(), resolved_at timestamptz
);
create unique index support_case_pending on company_x2.support_cases(order_id) where state='pending';
create table company_x2.support_case_events (
 id bigint generated always as identity primary key,
 ticket_id text not null references company_x2.support_cases(ticket_id),
 kind text not null check(kind in ('reported','confirmed_defect','not_confirmed')),
 reason text not null default '' check(length(reason)<=4000),created_at timestamptz not null default now()
);
alter table company_x2.support_cases enable row level security;
alter table company_x2.support_case_events enable row level security;
revoke all on company_x2.support_cases,company_x2.support_case_events from public,anon,authenticated,service_role;
create function public.cx2_case(p_action text,p_payload jsonb default '{}'::jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare o company_x2.company_orders; c company_x2.support_cases; t company_x2.support_tickets; result jsonb; created jsonb;
begin
 if p_action='ping' then return '{"case_schema_version":23}'::jsonb;
 elsif p_action='state' then
  return jsonb_build_object('hold',exists(select 1 from company_x2.support_cases where order_id=p_payload->>'order_id' and state in ('pending','confirmed_defect')));
 elsif p_action='report' then
  select * into o from company_x2.company_orders where id=p_payload->>'order_id' and token_hash=p_payload->>'order_token_hash' for update;
  if not found or o.status not in ('ready','delivered','failed') then raise exception 'Case order unavailable' using errcode='22023';end if;
  select * into t from company_x2.support_tickets where token_hash=p_payload->>'token_hash' and request_key=p_payload->>'request_key';
  if found then
   if t.fingerprint<>p_payload->>'fingerprint' or not exists(select 1 from company_x2.support_cases where ticket_id=t.id and order_id=o.id) then raise exception 'Case replay mismatch' using errcode='22023';end if;
   return jsonb_build_object('id',t.id);
  end if;
  if exists(select 1 from company_x2.support_cases where order_id=o.id and state='pending') then raise exception 'Case already pending' using errcode='22023';end if;
  created:=public.cx2_support('create',p_payload);
  insert into company_x2.support_cases(ticket_id,order_id) values(created->>'id',o.id);
  insert into company_x2.support_case_events(ticket_id,kind) values(created->>'id','reported');
  insert into company_x2.company_events(order_id,kind) values(o.id,'support_hold');
  return created;
 elsif p_action='get' then
  select x.* into c from company_x2.support_cases x join company_x2.support_tickets s on s.id=x.ticket_id where s.id=p_payload->>'id' and s.token_hash=p_payload->>'token_hash';
  if not found then return null;end if;
  select coalesce(jsonb_agg(jsonb_build_object('kind',kind,'reason',reason,'created_at',created_at) order by id),'[]'::jsonb) into result from company_x2.support_case_events where ticket_id=c.ticket_id;
  return to_jsonb(c)||jsonb_build_object('history',result);
 elsif p_action='list' then
  select coalesce(jsonb_agg(to_jsonb(x)||jsonb_build_object('ticket',to_jsonb(s)-'token_hash'-'request_key'-'fingerprint') order by (x.state='pending') desc,x.created_at,x.ticket_id),'[]'::jsonb) into result
   from (select * from company_x2.support_cases order by (state='pending') desc,created_at,ticket_id limit 50) x join company_x2.support_tickets s on s.id=x.ticket_id;
  return result;
 elsif p_action='resolve' then
  if coalesce(p_payload->>'decision','') not in ('confirmed_defect','not_confirmed') or length(coalesce(p_payload->>'reason','')) not between 1 and 4000 then raise exception 'Case decision rejected' using errcode='22023';end if;
  -- Lock order first, matching report and the production/refund worker.
  select z.* into o from company_x2.company_orders z join company_x2.support_cases x on x.order_id=z.id where x.ticket_id=p_payload->>'id' for update of z;
  if not found then raise exception 'Case unavailable' using errcode='22023';end if;
  select * into c from company_x2.support_cases where ticket_id=p_payload->>'id' for update;
  if c.state<>'pending' then
   if c.state=p_payload->>'decision' and c.reason=p_payload->>'reason' then return jsonb_build_object('resolved',true,'decision',c.state);end if;
   raise exception 'Case decision already final' using errcode='22023';
  end if;
  if p_payload->>'decision'='confirmed_defect' then
   if o.status not in ('ready','delivered','failed') then raise exception 'Case order busy' using errcode='22023';end if;
   update company_x2.company_orders set status='failed',attempts=3,lease=null,lease_until=null,error='Confirmed defect; delivery held',updated_at=now() where id=o.id;
  end if;
  update company_x2.support_cases set state=p_payload->>'decision',reason=p_payload->>'reason',resolved_at=now() where ticket_id=c.ticket_id;
  insert into company_x2.support_case_events(ticket_id,kind,reason) values(c.ticket_id,p_payload->>'decision',p_payload->>'reason');
  insert into company_x2.company_events(order_id,kind) values(o.id,'support_'||(p_payload->>'decision'));
  update company_x2.support_tickets set reply=p_payload->>'reason',status='answered',updated_at=now() where id=c.ticket_id;
  return jsonb_build_object('resolved',true,'decision',p_payload->>'decision','refund_requested',p_payload->>'decision'='confirmed_defect' and o.payment_status='paid');
 end if;
 raise exception 'Unknown case action' using errcode='22023';
end;
$$;
revoke execute on function public.cx2_case(text,jsonb) from public,anon,authenticated;
grant execute on function public.cx2_case(text,jsonb) to service_role;
notify pgrst,'reload schema';
