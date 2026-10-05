import csv
import logging
import hashlib
from .data_services import produce, verify
from .supabase_store import StorageUnavailable

logger = logging.getLogger(__name__)


def process_one(store):
    order = store.claim()
    if order is None:
        return False
    try:
        service_key = order.get('service_key', 'csv_exact_dedup')
        result = produce(order['input'], service_key)
        verify(order['input'], service_key, result)
        result['sha256'] = store.digest(result['artifact']['content'])
        encoding = 'utf-8-sig' if result['artifact']['content_type'].startswith('text/csv') else 'utf-8'
        result['download_sha256'] = hashlib.sha256(result['artifact']['content'].encode(encoding)).hexdigest()
        store.finish(order['id'], result=result, lease=order.get('lease'))
    except StorageUnavailable:
        raise
    except (ValueError, csv.Error):
        store.finish(order['id'], error='CSVの形式または入出力の上限を確認してください。列名は空欄・重複不可、各行の列数は統一してください。空白整形後に列名が重複する場合も処理できません。', lease=order.get('lease'))
    except Exception:
        logger.exception('Order processing failed: %s', order['id'])
        store.finish(order['id'], error='処理に失敗しました。', lease=order.get('lease'))
    return True
