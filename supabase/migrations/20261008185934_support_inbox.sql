-- Additive support storage only: existing order/payment RPCs are unchanged.
create table company_x2.support_tickets (
 id text primary key check(id ~ '^sp_[a-f0-9]{32}$'),
 token_hash text not null check(token_hash ~ '^[a-f0-9]{64}$'),
 request_key text not null, fingerprint text not null,
 kind text not null check(kind in ('question','refund','disclosure','receipt')),
 message text not null check(length(message) between 1 and 2000),
 guidance text not null, reply text not null default '' check(length(reply)<=4000),
 status text not null default 'open' check(status in ('open','answered')),
 created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
 unique(token_hash,request_key)
);
create index support_tickets_created on company_x2.support_tickets(created_at);
alter table company_x2.support_tickets enable row level security;
revoke all on company_x2.support_tickets from public,anon,authenticated,service_role;
create function public.cx2_support(p_action text,p_payload jsonb default '{}'::jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare r company_x2.support_tickets; result jsonb;
begin
 if p_action='ping' then return '{"support_schema_version":21}'::jsonb;
 elsif p_action='create' then
  if coalesce(p_payload->>'token_hash','') !~ '^[a-f0-9]{64}$'
   or coalesce(p_payload->>'request_key','') !~ '^[a-zA-Z0-9_-]{16,80}$'
   or coalesce(p_payload->>'fingerprint','') !~ '^[a-f0-9]{64}$'
   or coalesce(p_payload->>'kind','') not in ('question','refund','disclosure','receipt')
   or length(coalesce(p_payload->>'message','')) not between 1 and 2000
   or length(coalesce(p_payload->>'guidance','')) not between 1 and 2000 then
   raise exception 'Support input rejected' using errcode='22023'; end if;
  perform pg_catalog.pg_advisory_xact_lock(210021);
  select * into r from company_x2.support_tickets where token_hash=p_payload->>'token_hash' and request_key=p_payload->>'request_key';
  if found then
   if r.fingerprint<>p_payload->>'fingerprint' then raise exception 'Support replay mismatch' using errcode='22023'; end if;
   return jsonb_build_object('id',r.id);
  end if;
  if (select count(*) from company_x2.support_tickets where created_at>=date_trunc('day',now() at time zone 'UTC') at time zone 'UTC')>=100
   or (select count(*) from company_x2.support_tickets where token_hash=p_payload->>'token_hash' and created_at>=date_trunc('day',now() at time zone 'UTC') at time zone 'UTC')>=3 then
   raise exception 'Daily support limit' using errcode='22023'; end if;
  insert into company_x2.support_tickets(id,token_hash,request_key,fingerprint,kind,message,guidance)
   values(p_payload->>'id',p_payload->>'token_hash',p_payload->>'request_key',p_payload->>'fingerprint',p_payload->>'kind',p_payload->>'message',p_payload->>'guidance') returning * into r;
  return jsonb_build_object('id',r.id);
 elsif p_action='get' then
  select * into r from company_x2.support_tickets where id=p_payload->>'id' and token_hash=p_payload->>'token_hash';
  if not found then return null;end if;
  return to_jsonb(r)-'token_hash'-'request_key'-'fingerprint';
 elsif p_action='list' then
  select coalesce(jsonb_agg(to_jsonb(t)-'token_hash'-'request_key'-'fingerprint'),'[]'::jsonb) into result
   from (select * from company_x2.support_tickets order by (status='open') desc,created_at desc,id desc limit 50) t;
  return result;
 elsif p_action='reply' then
  if length(coalesce(p_payload->>'reply','')) not between 1 and 4000 then raise exception 'Support reply rejected' using errcode='22023';end if;
  update company_x2.support_tickets set reply=p_payload->>'reply',status='answered',updated_at=now() where id=p_payload->>'id';
  if not found then raise exception 'Support ticket unavailable' using errcode='22023';end if;
  return '{"answered":true}'::jsonb;
 end if;
 raise exception 'Unknown support action' using errcode='22023';
end;
$$;
revoke execute on function public.cx2_support(text,jsonb) from public,anon,authenticated;
grant execute on function public.cx2_support(text,jsonb) to service_role;
notify pgrst,'reload schema';
