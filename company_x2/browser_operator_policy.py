"""Operator-only policy boundary. Evidence strings are references, not proof."""
from dataclasses import dataclass
from datetime import datetime,timezone
from urllib.parse import urlsplit
from .delivery_permission import Permit
from .owned_browser_delivery import deliver_owned_browser


@dataclass(frozen=True)
class BrowserPolicy:
    origin: str
    upload_url: str
    expires_at: datetime
    site_policy_evidence: str
    account_permission_evidence: str
    runtime_validation_evidence: str
    enabled: bool = False


def require_policy(policy,permit,*,now=None):
    now=now or datetime.now(timezone.utc)
    if not isinstance(policy,BrowserPolicy) or policy.enabled is not True:
        raise ValueError('Operator browser policy disabled')
    if (not isinstance(permit,Permit) or policy.origin!=permit.origin
            or not isinstance(policy.expires_at,datetime) or policy.expires_at.tzinfo is None
            or now.tzinfo is None or now>=policy.expires_at):
        raise ValueError('Current matching operator policy required')
    for value in (policy.site_policy_evidence,policy.account_permission_evidence,policy.runtime_validation_evidence):
        if not isinstance(value,str) or not value.strip() or len(value)>500:
            raise ValueError('Reviewed policy, account and runtime evidence required')
    origin=urlsplit(policy.origin);upload=urlsplit(policy.upload_url)
    if (origin.scheme!='https' or not origin.hostname or origin.username or origin.password
            or origin.path or origin.query or origin.fragment or origin.port not in (None,443)
            or upload.scheme!='https' or upload.netloc!=origin.netloc or upload.username
            or upload.password or upload.query or upload.fragment):
        raise ValueError('Fixed HTTPS operator routes required')
    return True


def deliver_with_policy(policy,journal,permit,store,grant,signing_key,reply_id,client,owner,data,
                        *,node_executable,is_stopped=lambda:True):
    """No config loader or HTTP route; trusted caller supplies reviewed evidence.

    Recheck policy expiry at every existing stop check, including after stage.
    This does not test the runtime or independently establish site permission.
    """
    def stopped():
        if is_stopped() is not False:return True
        require_policy(policy,permit)
        return False
    if stopped():raise ValueError('External browser delivery stopped')
    return deliver_owned_browser(journal,permit,store,grant,signing_key,reply_id,client,owner,data,
        node_executable=node_executable,upload_url=policy.upload_url,enabled=True,is_stopped=stopped)
