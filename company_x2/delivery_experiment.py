"""Synthetic-adapter delivery coordinator; no real site or browser adapter."""
import hashlib
from .delivery_journal import identity


def deliver_once(journal, *, contact, reply, plan, destination, artifact, approved_sha256, adapter, authorize):
    if not isinstance(artifact,bytes) or not 0<len(artifact)<=50000:
        raise ValueError('Bounded verified artifact bytes required')
    digest=hashlib.sha256(artifact).hexdigest()
    if approved_sha256!=digest:
        raise ValueError('Artifact differs from approved inspection evidence')
    key=identity(contact,reply,plan,digest,destination)
    if authorize() is not True:raise ValueError('Delivery stopped')
    lease=journal.claim(key,allowed=True)
    if not lease:return {'replayed':True, **journal.state(key)}
    try:
        if authorize() is not True:raise ValueError('Delivery stopped before send')
        receipt=adapter.send(destination,artifact)
        if (not isinstance(receipt,dict) or receipt.get('destination')!=destination
                or receipt.get('artifact_sha256')!=digest):
            raise ValueError('Delivery acknowledgement mismatch')
        journal.finish(key,lease,receipt.get('id'))
        if not receipt.get('id'):raise ValueError('Receipt identity unavailable')
        return {'replayed':False, **journal.state(key)}
    except Exception:
        if journal.state(key)['state']=='sending':journal.finish(key,lease)
        raise
