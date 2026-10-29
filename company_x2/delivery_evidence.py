"""Internal evidence from owned stored work plus a fresh independent replay."""
import hashlib
from . import template_customer, template_session, public_intake
from .work_handoff import process_request


def prepare_delivery(store,grant,signing_key,reply_id,client,owner,data,*,destination):
    """Destination is supplied by operator configuration, never customer input."""
    with public_intake.LOCK, template_session.LOCK:
        record=template_customer.OwnedStore(store,owner).get_work_record(data.get('request_key'))
        if not record or record['status'] not in ('ready','received') or not record.get('handoff'):
            raise ValueError('Previously verified source-bound artifact required')
        if record.get('issue_count')!=0:raise ValueError('Unresolved artifact inspection issues')
        result=process_request(store,grant,signing_key,reply_id,client,owner,data)
        report=result.get('report',{})
        if report.get('verified') is not True or report.get('ready_for_import') is not True or report.get('issues'):
            raise ValueError('Independent replay inspection failed')
        artifact=result['csv'].encode('utf-8')
        digest=hashlib.sha256(artifact).hexdigest()
        if digest!=record.get('artifact_sha256'):raise ValueError('Stored artifact evidence differs')
        evidence={'contact_id':record['handoff']['contact_id'],'reply_id':record['handoff']['reply_id'],
            'plan_sha256':record['approval_sha256'],'artifact_sha256':digest,'destination':destination,
            'source_rechecked':True,'inspection_passed':True,'plan_accepted':True}
        return {'evidence':evidence,'artifact':artifact}


def deliver_owned_work(journal,permit,adapter,store,grant,signing_key,reply_id,client,owner,data,
                       *,is_stopped=lambda:True):
    """Internal entry point: callers cannot supply inspection or consent evidence.

    Requires an operator-owned permit and adapter. No HTTP route enables this.
    Rebuilds evidence before claiming and immediately before the adapter send.
    Customer input and artifact bytes remain transient, outside the journal.
    """
    from .delivery_permission import Permit,deliver_permitted
    if is_stopped() is not False:raise ValueError('External delivery stopped')
    if not isinstance(permit,Permit):raise ValueError('Operator permission required')
    def prepare():
        return prepare_delivery(store,grant,signing_key,reply_id,client,owner,data,
                                destination=permit.destination)
    prepared=prepare()
    return deliver_permitted(journal,permit,prepared['artifact'],adapter,
                             lambda:prepare()['evidence'],is_stopped=is_stopped)
