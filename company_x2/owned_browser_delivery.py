"""Internal operator entry; deliberately not registered as an HTTP route."""
from urllib.parse import urlsplit
from .browser_bridge import BrowserBridge
from .delivery_evidence import deliver_owned_work
from .delivery_permission import Permit
from .staged_delivery import StagedAdapter


def deliver_owned_browser(journal,permit,store,grant,signing_key,reply_id,client,owner,data,
                          *,node_executable,upload_url,enabled=False,is_stopped=lambda:True):
    """Only trusted server code supplies runtime, upload route and permit.

    Customer data goes exclusively to the owned-work coordinator. No arbitrary
    backend configuration, fixture override, selectors or executable is accepted
    from that data. Browser launch remains lazy until authorization and claim.
    """
    if enabled is not True or is_stopped() is not False:
        raise ValueError('Browser delivery disabled or stopped')
    if not isinstance(permit,Permit):raise ValueError('Operator permission required')
    target=urlsplit(permit.destination);upload=urlsplit(upload_url)
    if (target.scheme!='https' or not target.netloc or target.username or target.password
            or target.query or target.fragment or upload.scheme!='https'
            or upload.netloc!=target.netloc or upload.username or upload.password
            or upload.query or upload.fragment):
        raise ValueError('Fixed same-origin HTTPS upload route required')
    config=dict(enabled=True,pageUrl=permit.destination,uploadUrl=upload_url,
                destination=permit.destination)
    with BrowserBridge(node_executable,config,enabled=True) as bridge:
        return deliver_owned_work(journal,permit,StagedAdapter(bridge),store,grant,
            signing_key,reply_id,client,owner,data,is_stopped=is_stopped)
