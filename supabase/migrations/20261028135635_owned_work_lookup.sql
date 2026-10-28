-- Read-only server RPC; existing workflow is not switched until deployment is verified.
begin;
grant usage on schema company_x2 to service_role;
grant select on company_x2.sandbox_opportunities to service_role;
create or replace function public.cx2_owned_work(p_action text,p_payload jsonb default '{}'::jsonb)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare
 v_owner text := p_payload->>'owner_hash';
 v_key text := p_payload->>'client_key';
 v_id text;
 v_result jsonb;
begin
 if p_action='ping' then return jsonb_build_object('owned_work_schema_version',1); end if;
 if p_action is distinct from 'lookup' or v_owner is null or v_owner !~ '^[a-f0-9]{64}$'
    or (v_key is not null and v_key !~ '^[A-Za-z0-9_-]{16,64}$') then
  raise exception 'Invalid owned work lookup' using errcode='22023';
 end if;
 if v_key is not null then v_id := encode(sha256(convert_to(v_owner||':'||v_key,'UTF8')),'hex'); end if;
 select coalesce(jsonb_agg(r.value order by r.created_at desc,r.external_id),'[]'::jsonb) into v_result
 from (
  select data||jsonb_build_object('decision',decision,'reason',reason) as value,created_at,external_id
  from company_x2.sandbox_opportunities
  where source='customer_template_work' and data->>'owner_hash'=v_owner
    and (v_id is null or (external_id=v_id and data->>'client_key'=v_key))
  order by created_at desc,external_id limit 100
 ) r;
 return v_result;
end;
$$;
revoke all on function public.cx2_owned_work(text,jsonb) from public,anon,authenticated;
grant execute on function public.cx2_owned_work(text,jsonb) to service_role;
notify pgrst,'reload schema';
commit;
