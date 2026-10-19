-- Disposable PostgreSQL fixture only. __SCHEMA__ is a generated test identifier.
create schema __SCHEMA__;
create table __SCHEMA__.claims (
 identity text primary key check(identity ~ '^[a-f0-9]{64}$'),
 lease_hash bytea not null,
 state text not null check(state in ('sending','uncertain','confirmed')),
 receipt text check(receipt is null or length(receipt) between 1 and 200),
 check((state='confirmed') = (receipt is not null))
);
alter table __SCHEMA__.claims enable row level security;
revoke all on __SCHEMA__.claims from public;
create function __SCHEMA__.journal(action text,payload jsonb) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare key text := payload->>'identity'; lease text; result jsonb; affected integer;
begin
 if key is null or key !~ '^[a-f0-9]{64}$' then raise exception 'Invalid identity'; end if;
 if action='claim' then
  lease := replace(gen_random_uuid()::text,'-','') || replace(gen_random_uuid()::text,'-','');
  insert into __SCHEMA__.claims values(key,sha256(convert_to(lease,'UTF8')),'sending',null)
   on conflict do nothing;
  get diagnostics affected=row_count;
  if affected=0 then return null; end if;
  return jsonb_build_object('lease',lease);
 elsif action='finish' then
  lease := payload->>'lease';
  if lease is null or lease !~ '^[a-f0-9]{64}$' then raise exception 'Invalid lease'; end if;
  if payload->>'receipt' is not null and length(payload->>'receipt') not between 1 and 200 then
   raise exception 'Invalid receipt';
  end if;
  update __SCHEMA__.claims set state=case when payload->>'receipt' is null then 'uncertain' else 'confirmed' end,
   receipt=payload->>'receipt'
   where identity=key and lease_hash=sha256(convert_to(lease,'UTF8')) and state='sending';
  get diagnostics affected=row_count;
  return to_jsonb(affected=1);
 elsif action='state' then
  select jsonb_build_object('state',state,'has_receipt',receipt is not null) into result
   from __SCHEMA__.claims where identity=key;
  return result;
 end if;
 raise exception 'Unsupported action';
end $$;
revoke all on function __SCHEMA__.journal(text,jsonb) from public;
