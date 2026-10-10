-- Content-free order metadata. Only the server may select its public cohort.
create or replace function public.cx2_trial(p_action text,p_payload jsonb default '{}'::jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare result jsonb;
begin
 if p_action='ping' then return jsonb_build_object('trial_schema_version',37);end if;
 if p_action<>'report' or jsonb_typeof(p_payload->'ids') is distinct from 'array' then
  raise exception 'Invalid trial report' using errcode='22023';end if;
 if jsonb_array_length(p_payload->'ids')>300 then raise exception 'Trial report limit' using errcode='22023';end if;
 select coalesce(jsonb_agg(to_jsonb(x)),'[]'::jsonb) into result from (
  select o.plan->>'service_key' as service_key,o.status,
   case when e.started is not null and e.finished is not null then greatest(0,extract(epoch from e.finished-e.started)) else null end as processing_seconds
  from company_x2.company_orders o
  left join lateral (select min(created_at) filter(where kind='processing_started') as started,
    min(created_at) filter(where kind='ready') as finished from company_x2.company_events where order_id=o.id) e on true
  where o.id in(select jsonb_array_elements_text(p_payload->'ids')) and o.source_url=''
   and o.plan->>'payment_mode'='sandbox' and o.created_at>=(p_payload->>'since')::timestamptz
 ) x;
 return result;
end;$$;
revoke all on function public.cx2_trial(text,jsonb) from public,anon,authenticated;
grant execute on function public.cx2_trial(text,jsonb) to service_role;
notify pgrst,'reload schema';
