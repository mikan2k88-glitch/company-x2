"""Shared server-only metadata lookup validation. Never accepts a namespace."""
import hashlib
import re

SOURCE='customer_template_work'


def scope(owner_hash,client_key=None):
    if not isinstance(owner_hash,str) or not re.fullmatch('[a-f0-9]{64}',owner_hash):
        raise ValueError('Valid owner scope required')
    if client_key is not None and (not isinstance(client_key,str) or not re.fullmatch('[A-Za-z0-9_-]{16,64}',client_key)):
        raise ValueError('Valid customer request key required')
    return hashlib.sha256((owner_hash+':'+client_key).encode()).hexdigest() if client_key is not None else None


def checked_rows(rows,owner_hash,client_key=None):
    identifier=scope(owner_hash,client_key)
    if not isinstance(rows,list) or len(rows)>(1 if identifier else 100):
        raise ValueError('Invalid owned metadata response')
    for row in rows:
        if (not isinstance(row,dict) or row.get('source')!=SOURCE or row.get('owner_hash')!=owner_hash
                or (client_key is not None and row.get('client_key')!=client_key)
                or row.get('external_id')!=scope(owner_hash,row.get('client_key'))):
            raise ValueError('Owned metadata scope mismatch')
    return rows
