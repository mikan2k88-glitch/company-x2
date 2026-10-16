"""SQLite-only delivery claim experiment. Not a production sender or browser."""
import hashlib
import json
import secrets
import sqlite3
from contextlib import closing


def identity(contact, reply, plan, artifact, destination):
    values=(contact, reply, plan, artifact, destination)
    if not all(isinstance(value,str) and value and len(value)<=2048
               and not any(ord(c)<32 for c in value) for value in values):
        raise ValueError('Complete fixed delivery identity required')
    return hashlib.sha256(json.dumps(values,separators=(',',':')).encode()).hexdigest()


class Journal:
    def __init__(self,path):
        self.path=path
        with closing(self.connect()) as db:
            db.execute('CREATE TABLE IF NOT EXISTS delivery_claims (id TEXT PRIMARY KEY, lease TEXT NOT NULL, state TEXT NOT NULL, receipt TEXT)')
            db.commit()

    def connect(self):
        return sqlite3.connect(self.path,timeout=5)

    def claim(self,key,*,allowed=False):
        if allowed is not True:raise ValueError('Delivery is stopped or unauthorized')
        if not isinstance(key,str) or len(key)!=64 or any(c not in '0123456789abcdef' for c in key):raise ValueError('Invalid delivery identity')
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM delivery_claims WHERE id=?',(key,)).fetchone():
                db.rollback();return None  # Includes ambiguous sending after restart.
            lease=secrets.token_hex(32)
            db.execute('INSERT INTO delivery_claims VALUES (?,?,?,NULL)',(key,lease,'sending'))
            db.commit();return lease

    def finish(self,key,lease,receipt=None):
        # The adapter must validate receipt authenticity and destination first.
        if receipt is not None and (not isinstance(receipt,str) or not receipt or len(receipt)>200):
            raise ValueError('Invalid receipt evidence')
        with closing(self.connect()) as db:
            cursor=db.execute('UPDATE delivery_claims SET state=?,receipt=? WHERE id=? AND lease=? AND state=?',
                ('confirmed' if receipt else 'uncertain',receipt,key,lease,'sending'))
            if cursor.rowcount!=1:db.rollback();raise ValueError('Claim mismatch or already completed')
            db.commit()

    def state(self,key):
        with closing(self.connect()) as db:
            row=db.execute('SELECT state,receipt IS NOT NULL FROM delivery_claims WHERE id=?',(key,)).fetchone()
            return {'state':row[0],'has_receipt':bool(row[1])} if row else None
