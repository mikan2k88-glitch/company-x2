create table company_x2.outreach_contacts(
 id text primary key check(id ~ '^ot_[a-f0-9]{32}$'),
 url text unique not null check(url ~ '^https://github.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/issues/[1-9][0-9]*$'),
 issue_id text not null,author text not null,message text not null check(length(message) between 1 and 4000),
 status text not null default 'draft' check(status in ('draft','sending','sent','uncertain')),
 comment_url text,attempted_at timestamptz,reply_id bigint,reply_text text check(length(reply_text)<=2000),next_message text check(length(next_message)<=2000),created_at timestamptz not null default now());
alter table company_x2.outreach_contacts enable row level security;
revoke all on company_x2.outreach_contacts from public,anon,authenticated,service_role;
create function public.cx2_outreach(p_action text,p_payload jsonb default '{}'::jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare r company_x2.outreach_contacts; result jsonb;
begin
 if p_action='ping' then return '{"outreach_schema_version":25}'::jsonb;
 elsif p_action='prepare' then
  insert into company_x2.outreach_contacts(id,url,issue_id,author,message) values(p_payload->>'id',p_payload->>'url',p_payload->>'issue_id',p_payload->>'author',p_payload->>'message') on conflict do nothing;return 'true'::jsonb;
 elsif p_action='list' then
  select coalesce(jsonb_agg(to_jsonb(x)),'[]'::jsonb) into result from (select * from company_x2.outreach_contacts order by created_at desc,id limit 50) x;return result;
 elsif p_action='claim' then
  perform pg_catalog.pg_advisory_xact_lock(250025);
  if exists(select 1 from company_x2.outreach_contacts where attempted_at>=date_trunc('day',now() at time zone 'UTC') at time zone 'UTC') then return null;end if;
  select * into r from company_x2.outreach_contacts where status='draft' order by created_at,id limit 1 for update;
  if not found then return null;end if;
  update company_x2.outreach_contacts set status='sending',attempted_at=now() where id=r.id;return to_jsonb(r);
 elsif p_action in ('finish','uncertain') then
  update company_x2.outreach_contacts set status=case when p_action='finish' then 'sent' else 'uncertain' end,comment_url=p_payload->>'comment_url' where id=p_payload->>'id' and status='sending';return to_jsonb(found);
 elsif p_action='observe' then
  update company_x2.outreach_contacts set reply_id=(p_payload->>'reply_id')::bigint,reply_text=left(p_payload->>'reply_text',2000),next_message=left(p_payload->>'next_message',2000)
    where id=p_payload->>'id' and status='sent' and coalesce(reply_id,0)<(p_payload->>'reply_id')::bigint;return to_jsonb(found);
 end if;
 raise exception 'Unknown outreach action' using errcode='22023';
end;
$$;
revoke execute on function public.cx2_outreach(text,jsonb) from public,anon,authenticated;
grant execute on function public.cx2_outreach(text,jsonb) to service_role;
notify pgrst,'reload schema';
