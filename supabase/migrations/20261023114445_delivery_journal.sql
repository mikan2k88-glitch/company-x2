-- Server-only delivery journal. Does not enable sending.
begin;
create schema if not exists company_x2;
create table company_x2.delivery_claims (
 identity text primary key check(identity ~ '^[a-f0-9]{64}$'),
 lease_hash bytea not null,
 state text not null check(state in ('sending','uncertain','confirmed')),
 receipt text check(receipt is null or length(receipt) between 1 and 200),
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now(),
 check((state='confirmed') = (receipt is not null))
);
alter table company_x2.delivery_claims enable row level security;
revoke all on company_x2.delivery_claims from public,anon,authenticated,service_role;
grant usage on schema company_x2 to service_role;
grant select,insert,update on company_x2.delivery_claims to service_role;

create function public.cx2_delivery(p_action text,p_payload jsonb default '{}'::jsonb)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare key text := p_payload->>'identity'; lease text; result jsonb; affected integer;
begin
 if p_action='ping' then return jsonb_build_object('delivery_schema_version',1); end if;
 if jsonb_typeof(p_payload) is distinct from 'object' or key is null or key !~ '^[a-f0-9]{64}$' then
  raise exception 'Invalid identity' using errcode='22023';
 end if;
 if p_action='claim' then
  lease := replace(gen_random_uuid()::text,'-','') || replace(gen_random_uuid()::text,'-','');
  insert into company_x2.delivery_claims(identity,lease_hash,state)
   values(key,sha256(convert_to(lease,'UTF8')),'sending') on conflict do nothing;
  get diagnostics affected=row_count;
  if affected=0 then return null; end if;
  return jsonb_build_object('lease',lease);
 elsif p_action='finish' then
  lease := p_payload->>'lease';
  if lease is null or lease !~ '^[a-f0-9]{64}$' then raise exception 'Invalid lease' using errcode='22023'; end if;
  if p_payload->>'receipt' is not null and length(p_payload->>'receipt') not between 1 and 200 then
   raise exception 'Invalid receipt' using errcode='22023';
  end if;
  update company_x2.delivery_claims set state=case when p_payload->>'receipt' is null then 'uncertain' else 'confirmed' end,
   receipt=p_payload->>'receipt',updated_at=now()
   where identity=key and lease_hash=sha256(convert_to(lease,'UTF8')) and state='sending';
  get diagnostics affected=row_count;
  return to_jsonb(affected=1);
 elsif p_action='state' then
  select jsonb_build_object('state',state,'has_receipt',receipt is not null) into result
   from company_x2.delivery_claims where identity=key;
  return result;
 end if;
 raise exception 'Unsupported action' using errcode='22023';
end $$;
revoke all on function public.cx2_delivery(text,jsonb) from public,anon,authenticated;
grant execute on function public.cx2_delivery(text,jsonb) to service_role;
notify pgrst,'reload schema';
commit;
