create table company_x2.support_reviews(
 ticket_id text primary key references company_x2.support_tickets(id),
 outcome text not null check(outcome in ('manual','answered','confirmed_defect')),
 reason text not null check(length(reason) between 1 and 4000),version text not null,
 created_at timestamptz not null default now());
alter table company_x2.support_reviews enable row level security;
revoke all on company_x2.support_reviews from public,anon,authenticated,service_role;
create function public.cx2_support_auto(p_action text,p_payload jsonb default '{}'::jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare t company_x2.support_tickets;c company_x2.support_cases;o company_x2.company_orders;result jsonb; snap jsonb;
begin
 if p_action='ping' then return '{"automation_schema_version":24}'::jsonb;
 elsif p_action='pending' then
  select coalesce(jsonb_agg(jsonb_build_object('ticket',jsonb_build_object('id',x.id,'kind',x.kind,'message',x.message,'reply',x.reply),'order',case when z.id is null then null else jsonb_build_object('status',z.status,'plan',z.plan,'result',z.result) end) order by x.created_at,x.id),'[]'::jsonb) into result
  from (select s.* from company_x2.support_tickets s left join company_x2.support_reviews r on r.ticket_id=s.id left join company_x2.support_cases k on k.ticket_id=s.id
   where r.ticket_id is null and s.reply='' and ((k.ticket_id is null and s.status='open') or k.state='pending') order by s.created_at,s.id limit 10) x
  left join company_x2.support_cases y on y.ticket_id=x.id left join company_x2.company_orders z on z.id=y.order_id;
  return result;
 elsif p_action='get' then
  select to_jsonb(r) into result from company_x2.support_reviews r join company_x2.support_tickets s on s.id=r.ticket_id where s.id=p_payload->>'id' and s.token_hash=p_payload->>'token_hash';return result;
 elsif p_action='list' then
  select coalesce(jsonb_agg(to_jsonb(r)),'[]'::jsonb) into result from (select * from company_x2.support_reviews order by created_at desc,ticket_id limit 100) r;return result;
 elsif p_action='commit' then
  if coalesce(p_payload->>'outcome','') not in ('manual','answered','confirmed_defect') or p_payload->>'version' is distinct from 'support-auto-v1' or length(coalesce(p_payload->>'reason','')) not between 1 and 4000 then raise exception 'Automation input rejected' using errcode='22023';end if;
  -- Order first, then case/ticket, matching manual resolution and workers.
  select z.* into o from company_x2.company_orders z join company_x2.support_cases x on x.order_id=z.id where x.ticket_id=p_payload->>'id' for update of z;
  select * into c from company_x2.support_cases where ticket_id=p_payload->>'id' for update;
  select * into t from company_x2.support_tickets where id=p_payload->>'id' for update;
  if not found or t.reply is distinct from p_payload->>'expected_reply' or exists(select 1 from company_x2.support_reviews where ticket_id=t.id) then return 'false'::jsonb;end if;
  if c.ticket_id is not null then
   snap:=jsonb_build_object('status',o.status,'plan',o.plan,'result',o.result);
   if c.state<>'pending' or snap is distinct from p_payload->'expected' or p_payload->>'outcome'='answered' then return 'false'::jsonb;end if;
   if p_payload->>'outcome'='confirmed_defect' then
    if o.status not in ('ready','delivered') then return 'false'::jsonb;end if;
    perform public.cx2_case('resolve',jsonb_build_object('id',t.id,'decision','confirmed_defect','reason',p_payload->>'reason'));
   end if;
  elsif p_payload->>'outcome'='confirmed_defect' or coalesce(p_payload->'expected','null'::jsonb)<>'null'::jsonb then return 'false'::jsonb;
  elsif p_payload->>'outcome'='answered' then
   if t.kind<>'question' or t.status<>'open' then return 'false'::jsonb;end if;
   perform public.cx2_support('reply',jsonb_build_object('id',t.id,'reply',p_payload->>'reason'));
  end if;
  insert into company_x2.support_reviews(ticket_id,outcome,reason,version) values(t.id,p_payload->>'outcome',p_payload->>'reason',p_payload->>'version');return 'true'::jsonb;
 end if;
 raise exception 'Unknown automation action' using errcode='22023';
end;
$$;
revoke execute on function public.cx2_support_auto(text,jsonb) from public,anon,authenticated;
grant execute on function public.cx2_support_auto(text,jsonb) to service_role;
notify pgrst,'reload schema';
