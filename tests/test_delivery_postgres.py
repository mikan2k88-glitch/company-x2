"""Disposable loopback PostgreSQL only; never a production migration."""
import os
import shutil
import subprocess
import unittest
import uuid
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
