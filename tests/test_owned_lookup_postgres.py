"""Exact candidate migration; disposable loopback PostgreSQL only."""
import json
from pathlib import Path
import shutil
import unittest
import uuid
import test_delivery_postgres as dbtests
from company_x2.owned_work import scope


@unittest.skipUnless(dbtests.LOCAL and shutil.which('psql'),'Disposable loopback PostgreSQL unavailable')
class OwnedLookupPostgresTests(unittest.TestCase):
    sql=dbtests.DeliveryPostgresTests.sql

    def test_owner_filter_before_limit_and_server_only_invoker(self):
        suffix=uuid.uuid4().hex;schema='owned_'+suffix;api='owned_api_'+suffix
        roles={name:name+'_'+suffix for name in ('anon','authenticated','service_role')}
        self.sql(f'CREATE SCHEMA {schema}; CREATE SCHEMA {api}')
        for role in roles.values():self.sql(f'CREATE ROLE {role}')
        self.sql(f"ALTER ROLE {roles['service_role']} BYPASSRLS")
        self.sql(f'''CREATE TABLE {schema}.sandbox_opportunities (
            source text,external_id text,data jsonb,decision text,reason text,
            created_at timestamptz default now(),primary key(source,external_id));
            ALTER TABLE {schema}.sandbox_opportunities ENABLE ROW LEVEL SECURITY''')
        candidate=(Path(__file__).parents[1]/'supabase/migrations/20261028135635_owned_work_lookup.sql').read_text()
        candidate=candidate.replace('company_x2',schema).replace('public.cx2_owned_work',api+'.cx2_owned_work')
        for name,role in roles.items():candidate=candidate.replace(name,role)
        try:
            self.sql(candidate)
            self.sql(f"GRANT USAGE ON SCHEMA {api} TO {','.join(roles.values())}")
            owner='a'*64;key='synthetic-work-001'
            record=dict(source='customer_template_work',owner_hash=owner,client_key=key,external_id=scope(owner,key))
            encoded=json.dumps(record).replace("'","''")
            self.sql(f"INSERT INTO {schema}.sandbox_opportunities VALUES ('customer_template_work','{record['external_id']}','{encoded}','blocked','synthetic','2000-01-01')")
            self.sql(f"INSERT INTO {schema}.sandbox_opportunities SELECT 'other',i::text,'{{}}'::jsonb,'blocked','synthetic',now() FROM generate_series(1,120) i")
            def lookup(owner,key=None):
                payload=json.dumps(dict(owner_hash=owner,client_key=key))
                raw=self.sql(f"SET ROLE {roles['service_role']}; SELECT {api}.cx2_owned_work('lookup','{payload}'::jsonb)")
                return json.loads(raw.splitlines()[-1])
            self.assertEqual(lookup(owner,key)[0]['client_key'],key)
            self.assertEqual(len(lookup(owner)),1)
            self.assertEqual(lookup('b'*64,key),[])
            with self.assertRaises(AssertionError):lookup('invalid')
            for name in ('anon','authenticated'):
                with self.assertRaises(AssertionError):self.sql(f"SET ROLE {roles[name]}; SELECT {api}.cx2_owned_work('ping')")
            self.assertEqual(self.sql(f"SELECT prosecdef FROM pg_proc WHERE oid='{api}.cx2_owned_work(text,jsonb)'::regprocedure"),'f')
        finally:
            self.sql(f'DROP SCHEMA {api} CASCADE; DROP SCHEMA {schema} CASCADE')
            for role in roles.values():self.sql(f'DROP ROLE {role}')
