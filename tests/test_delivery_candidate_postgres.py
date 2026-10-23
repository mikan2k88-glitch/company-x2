"""Role-bound deployment candidate tested only in disposable loopback PostgreSQL."""
import json
import uuid
import unittest
import shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import test_delivery_postgres as dbtests
from company_x2.cloud_delivery_journal import CloudJournal


@unittest.skipUnless(dbtests.LOCAL and shutil.which('psql'),'Disposable loopback PostgreSQL unavailable')
class DeliveryCandidateTests(unittest.TestCase):
    sql=dbtests.DeliveryPostgresTests.sql
    def test_candidate_invoker_server_grants_and_atomic_claim(self):
        suffix=uuid.uuid4().hex
        schema='delivery_candidate_'+suffix
        api='delivery_api_'+suffix
        roles={name:name+'_'+suffix for name in ('anon','authenticated','service_role')}
        self.sql(f'CREATE SCHEMA {api}; CREATE SCHEMA {schema}')
        for role in roles.values():self.sql(f'CREATE ROLE {role}')
        # Supabase service_role bypasses RLS; reproduce that only in this test DB.
        self.sql(f"ALTER ROLE {roles['service_role']} BYPASSRLS")
        candidate=(Path(__file__).parents[1]/'supabase'/'migrations'/'20261023114445_delivery_journal.sql').read_text()
        candidate=candidate.replace('company_x2',schema).replace('public.cx2_delivery',api+'.cx2_delivery')
        # Keep PUBLIC as the built-in role; replace only the named Supabase roles.
        for name,role in roles.items():candidate=candidate.replace(name,role)
        try:
            self.sql(candidate)
            self.sql(f"GRANT USAGE ON SCHEMA {api} TO {','.join(roles.values())}")
            for name in ('anon','authenticated'):
                with self.assertRaises(AssertionError):
                    self.sql(f"SET ROLE {roles[name]}; SELECT {api}.cx2_delivery('ping')")
            def rpc(action,payload):
                encoded=json.dumps(payload).replace("'","''")
                raw=self.sql(f"SET ROLE {roles['service_role']}; SELECT coalesce({api}.cx2_delivery('{action}','{encoded}'::jsonb)::text,'null')")
                return json.loads(raw.splitlines()[-1])
            journal=CloudJournal(rpc)
            with ThreadPoolExecutor(max_workers=2) as pool:
                leases=list(pool.map(lambda _:journal.claim('a'*64,allowed=True),range(2)))
            self.assertEqual(sum(x is not None for x in leases),1)
            lease=next(x for x in leases if x)
            journal.finish('a'*64,lease,'synthetic-receipt')
            self.assertEqual(journal.state('a'*64),dict(state='confirmed',has_receipt=True))
            self.assertIsNone(journal.claim('a'*64,allowed=True))
            self.assertEqual(self.sql(f"SELECT prosecdef FROM pg_proc WHERE oid='{api}.cx2_delivery(text,jsonb)'::regprocedure"),'f')
            self.assertEqual(self.sql(f"SELECT relrowsecurity FROM pg_class WHERE oid='{schema}.delivery_claims'::regclass"),'t')
        finally:
            self.sql(f'DROP SCHEMA {api} CASCADE; DROP SCHEMA {schema} CASCADE')
            for role in roles.values():self.sql(f'DROP ROLE {role}')
