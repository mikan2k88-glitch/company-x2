"""Full automatic refunds, with persistent reservations and provider reconciliation."""
import re


def ready(store):
    try:
        return store.company_rpc('refund_ping') == {'refund_schema_version': 20}
    except Exception:
        return False


def apply_refund(payments, store, refund, mode):
    if (refund.get('object') != 'refund' or ('livemode' in refund and refund['livemode'] is not (mode == 'stripe_live'))
            or not re.fullmatch(r're_[A-Za-z0-9]+', refund.get('id', ''))
            or not re.fullmatch(r'pi_[A-Za-z0-9]+', refund.get('payment_intent', ''))
            or type(refund.get('amount')) is not int or refund['amount'] <= 0
            or refund.get('currency') != 'jpy'
            or refund.get('status') not in ('pending', 'requires_action', 'succeeded', 'failed', 'canceled')):
        raise ValueError('Refund evidence rejected')
    return store.company_rpc('refund_update', {'refund_id': refund['id'],
        'payment_intent': refund['payment_intent'], 'amount': refund['amount'],
        'currency': 'jpy', 'livemode': mode == 'stripe_live', 'status': refund['status']})


def webhook(payments, store, event):
    obj = event.get('data', {}).get('object', {})
    if not isinstance(obj, dict) or not re.fullmatch(r're_[A-Za-z0-9]+', obj.get('id', '')):
        raise ValueError('Refund event rejected')
    mode = 'stripe_live' if event['livemode'] else 'stripe_test'
    # Fetch current state: webhook arrival order is not a state transition order.
    refund = payments.api('refunds/' + obj['id'], payment_mode=mode)
    if refund.get('id') != obj['id']:
        raise ValueError('Refund identity mismatch')
    if not re.fullmatch(r'pi_[A-Za-z0-9]+',refund.get('payment_intent','')):
        raise ValueError('Refund payment identity rejected')
    pi=payments.api('payment_intents/'+refund['payment_intent'],payment_mode=mode)
    if pi.get('id') != refund['payment_intent']:
        raise ValueError('Refund payment identity mismatch')
    return {'received': True, 'refund_verified': apply_refund(payments, store, refund, mode)}


def process_one(payments, store):
    if not ready(store):
        return False
    job = store.company_rpc('refund_claim')
    binding_only=False
    if not job:
        candidates=store.company_rpc('refund_bindings')
        if not candidates:return False
        job=candidates[0];binding_only=True
    mode = job['plan']['payment_mode']
    session = payments.api('checkout/sessions/' + job['session_id'], payment_mode=mode)
    if (session.get('id') != job['session_id'] or session.get('client_reference_id') != job['id']
            or session.get('metadata', {}).get('cx2_order_id') != job['id']
            or session.get('amount_total') != job['plan']['price_jpy'] or session.get('currency') != 'jpy'
            or session.get('payment_status') != 'paid' or session.get('status') != 'complete'
            or session.get('mode') != 'payment'
            or not re.fullmatch(r'pi_[A-Za-z0-9]+', session.get('payment_intent', ''))):
        raise ValueError('Refund payment evidence mismatch')
    pi_id = session['payment_intent']
    store.company_rpc('refund_bind', {'id': job['id'], 'payment_intent': pi_id,
        'session_id': job['session_id'], 'livemode': mode == 'stripe_live'})
    pi = payments.api('payment_intents/' + pi_id + '?expand[]=latest_charge', payment_mode=mode)
    charge = pi.get('latest_charge')
    if (pi.get('id') != pi_id or pi.get('currency') != 'jpy' or pi.get('amount_received') != job['plan']['price_jpy']
            or pi.get('status') != 'succeeded' or not isinstance(charge, dict)
            or charge.get('payment_intent') != pi_id or charge.get('livemode') is not (mode == 'stripe_live')
            or charge.get('disputed') is not False):
        store.company_rpc('refund_review', {'id': job['id']})
        return True
    history = payments.api('refunds?payment_intent=' + pi_id + '&limit=100', payment_mode=mode)
    if not isinstance(history, dict) or history.get('has_more') is not False or not isinstance(history.get('data'), list):
        store.company_rpc('refund_review', {'id': job['id']})
        return True
    # Inspect existing provider refunds even after the 24-hour idempotency retention.
    # A manual/partial/failed refund needs operator review; never create a second refund.
    if history['data']:
        for refund in history['data']:
            if refund.get('payment_intent') != pi_id:
                raise ValueError('Refund history identity mismatch')
            apply_refund(payments, store, refund, mode)
        if not any(x.get('amount') == job['plan']['price_jpy'] and x.get('status') in ('pending', 'succeeded') for x in history['data']):
            store.company_rpc('refund_review', {'id': job['id']})
        return True
    if binding_only:
        return True
    if charge.get('amount_refunded') != 0:
        store.company_rpc('refund_review', {'id': job['id']})
        return True
    refund = payments.api('refunds', {'payment_intent': pi_id, 'amount': job['plan']['price_jpy'],
        'metadata[cx2_order_id]': job['id'], 'metadata[cx2_reason]': 'production_failed_or_overdue'},
        idempotency_key='cx2-refund-' + job['id'], payment_mode=mode)
    if refund.get('payment_intent') != pi_id or refund.get('amount') != job['plan']['price_jpy']:
        raise ValueError('Refund response mismatch')
    apply_refund(payments, store, refund, mode)
    return True
