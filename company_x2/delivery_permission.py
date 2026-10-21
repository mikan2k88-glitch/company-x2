"""Server-owned delivery scope; page content must never construct a permit."""
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit
import re


@dataclass(frozen=True)
class Permit:
    origin: str
    destination: str
    contact_id: str
    reply_id: str
    plan_sha256: str
    artifact_sha256: str
    expires_at: datetime
    policy_evidence: str


def require_delivery_permission(permit, current, *, stopped=True, now=None):
    """Match trusted current verification evidence; default denies all sends."""
    if stopped is not False:raise ValueError('External delivery stopped')
    now=now or datetime.now(timezone.utc)
    if (not isinstance(permit,Permit) or permit.expires_at.tzinfo is None
            or now.tzinfo is None or now>=permit.expires_at or not permit.policy_evidence):
        raise ValueError('Current operator permission required')
    origin=urlsplit(permit.origin);destination=urlsplit(permit.destination)
    if (origin.scheme!='https' or not origin.hostname or origin.username or origin.password
            or origin.path or origin.query or origin.fragment
            or destination.scheme!='https' or destination.netloc!=origin.netloc
            or destination.username or destination.password or destination.fragment or destination.query):
        raise ValueError('Fixed HTTPS delivery destination required')
    for name in ('plan_sha256','artifact_sha256'):
        if not re.fullmatch('[a-f0-9]{64}',getattr(permit,name)):raise ValueError('Verified digest required')
    for name in ('contact_id','reply_id','plan_sha256','artifact_sha256','destination'):
        if current.get(name)!=getattr(permit,name):raise ValueError('Delivery scope changed')
    if (current.get('source_rechecked') is not True or current.get('inspection_passed') is not True
            or current.get('plan_accepted') is not True):
        raise ValueError('Current consent and artifact inspection required')
    return True


def deliver_permitted(journal,permit,artifact,adapter,verify_current,*,is_stopped=lambda:True):
    """Internal coordinator; all targets derive from operator-owned scope."""
    from .delivery_experiment import deliver_once
    def authorize():
        return require_delivery_permission(permit,verify_current(),stopped=is_stopped())
    # Validate before reading fields; a malformed permit cannot fall back.
    authorize()
    return deliver_once(journal,contact=permit.contact_id,reply=permit.reply_id,
        plan=permit.plan_sha256,destination=permit.destination,artifact=artifact,
        approved_sha256=permit.artifact_sha256,adapter=adapter,authorize=authorize)
