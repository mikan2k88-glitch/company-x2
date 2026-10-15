"""Read-only handoff gate; never treats a web reply as an execution command."""
import hashlib
import re

from .autonomy import consent


def verified_contact(store, contact_id, reply_id):
    if not isinstance(contact_id, str) or not re.fullmatch('ot_[a-f0-9]{32}', contact_id):
        raise ValueError('Invalid contact identity')
    if not isinstance(reply_id, str) or not reply_id.isascii() or not reply_id.isdecimal():
        raise ValueError('Exact observed reply required')
    contact = next((item for item in store.outreach_rpc('list') if item['id'] == contact_id), None)
    if not contact or contact.get('status') != 'sent':
        raise ValueError('Verified sent contact required')
    if str(contact.get('reply_id')) != reply_id or not consent(contact.get('reply_text'))['accepted']:
        raise ValueError('Reply changed or consent unavailable')
    # No customer text, credentials or artifact bytes enter this manifest.
    evidence = contact_id + ':' + reply_id
    return {'contact_id': contact_id, 'reply_id': reply_id,
            'consent_sha256': hashlib.sha256(evidence.encode()).hexdigest(),
            'status': 'awaiting_work_plan', 'external_delivery_allowed': False,
            'notice': 'Consent to free verification does not approve a work plan or external delivery.'}


def recheck_contact(store, contact_id, reply_id, client):
    """Refresh through the source adapter; an unavailable source blocks work."""
    manifest = verified_contact(store, contact_id, reply_id)
    contact = next(item for item in store.outreach_rpc('list') if item['id'] == contact_id)
    observed = client.observe(contact)
    if (not isinstance(observed, dict) or observed.get('id') != contact_id
            or str(observed.get('reply_id')) != reply_id):
        raise ValueError('Current source reply unavailable or changed')
    if not consent(observed.get('reply_text'))['accepted']:
        raise ValueError('Current source consent withdrawn or changed')
    return {**manifest, 'source_rechecked': True}
