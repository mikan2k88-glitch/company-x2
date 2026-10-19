"""Disposable loopback PostgreSQL only; never a production migration."""
import os
import shutil
import subprocess
import unittest
import uuid
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

DSN=os.environ.get('CX2_TEST_DSN','')
LOCAL=bool(DSN) and urlparse(DSN).hostname in ('localhost','127.0.0.1','::1')


@unittest.skipUnless(LOCAL and shutil.which('psql'),'Disposable loopback PostgreSQL unavailable')
class DeliveryPostgresTests(unittest.TestCase):
    def sql(self,text):
        result=subprocess.run(['psql',DSN,'-X','-A','-t','-v','ON_ERROR_STOP=1','-c',text],
            capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        return result.stdout.strip()

    def test_concurrent_claim_and_conditional_finish(self):
        table='delivery_test_'+uuid.uuid4().hex
        self.sql(f"CREATE TABLE {table} (id text PRIMARY KEY, lease text NOT NULL, state text NOT NULL CHECK(state IN ('sending','uncertain','confirmed')))")
        try:
            def claim(lease):
                return self.sql(f"INSERT INTO {table} VALUES ('fixed-key','{lease}','sending') ON CONFLICT DO NOTHING RETURNING lease")
            with ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(claim,('lease-a','lease-b')))
            winners=[value.splitlines()[0] for value in results if value.startswith('lease-')]
            self.assertEqual(len(winners),1)
            winner=winners[0]
            self.assertNotIn('lease-c',claim('lease-c'))
            self.assertIn('UPDATE 0',self.sql(f"UPDATE {table} SET state='confirmed' WHERE id='fixed-key' AND lease='wrong' AND state='sending'"))
            self.assertIn('UPDATE 1',self.sql(f"UPDATE {table} SET state='uncertain' WHERE id='fixed-key' AND lease='{winner}' AND state='sending'"))
            self.assertNotIn('lease-d',claim('lease-d'))
            self.assertIn('UPDATE 0',self.sql(f"UPDATE {table} SET state='confirmed' WHERE id='fixed-key' AND lease='{winner}' AND state='sending'"))
        finally:
            self.sql(f'DROP TABLE {table}')

    def test_rpc_contract_and_digest_only_lease_storage(self):
        schema='delivery_rpc_'+uuid.uuid4().hex
        fixture=(Path(__file__).parent/'fixtures'/'delivery_rpc.sql').read_text()
        self.sql(fixture.replace('__SCHEMA__',schema))
        def rpc(action,payload):
            raw=self.sql(f"SELECT {schema}.journal('{action}','{json.dumps(payload)}'::jsonb)")
            return json.loads(raw) if raw else None
        try:
            from company_x2.cloud_delivery_journal import CloudJournal
            journal=CloudJournal(rpc);key='a'*64
            with ThreadPoolExecutor(max_workers=2) as pool:
                leases=list(pool.map(lambda _:journal.claim('c'*64,allowed=True),range(2)))
            self.assertEqual(sum(lease is not None for lease in leases),1)
            role='delivery_guest_'+uuid.uuid4().hex
            self.sql(f'CREATE ROLE {role}; GRANT USAGE ON SCHEMA {schema} TO {role}')
            try:
                denied=subprocess.run(['psql',DSN,'-X','-v','ON_ERROR_STOP=1','-c',
                    f"SET ROLE {role}; SELECT {schema}.journal('state','{{\"identity\":\"{'a'*64}\"}}'::jsonb)"],
                    capture_output=True,text=True)
                self.assertNotEqual(denied.returncode,0)
                self.assertIn('permission denied',denied.stderr)
            finally:
                self.sql(f'REVOKE USAGE ON SCHEMA {schema} FROM {role}; DROP ROLE {role}')
            lease=journal.claim(key,allowed=True)
            self.assertIsNone(journal.claim(key,allowed=True))
            with self.assertRaises(ValueError):journal.finish(key,'b'*64,'receipt')
            journal.finish(key,lease,'synthetic-receipt')
            self.assertEqual(journal.state(key),{'state':'confirmed','has_receipt':True})
            self.assertNotIn(lease,self.sql(f'SELECT lease_hash FROM {schema}.claims'))
        finally:self.sql(f'DROP SCHEMA {schema} CASCADE')
