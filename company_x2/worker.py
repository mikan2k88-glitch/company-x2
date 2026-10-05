import csv
import logging
from .csv_service import deduplicate_csv
from .supabase_store import StorageUnavailable

logger = logging.getLogger(__name__)


def process_one(store):
    order = store.claim()
    if order is None:
        return False
    try:
        result = deduplicate_csv(order['input'])
        # Independent invariant: output must preserve the first occurrence of each input row.
        import io
        original = list(csv.reader(io.StringIO(order['input'], newline=''), strict=True))
        output = list(csv.reader(io.StringIO(result['csv'], newline=''), strict=True))
        expected = list(dict.fromkeys(tuple(row) for row in original[1:]))
        if output[0] != original[0] or [tuple(row) for row in output[1:]] != expected:
            raise ValueError('Output verification failed')
        result['sha256'] = store.digest(result['csv'])
        store.finish(order['id'], result=result, lease=order.get('lease'))
    except StorageUnavailable:
        raise
    except (ValueError, csv.Error):
        store.finish(order['id'], error='CSVの形式または上限を確認してください。列名は重複不可、各行の列数は統一してください。', lease=order.get('lease'))
    except Exception:
        logger.exception('Order processing failed: %s', order['id'])
        store.finish(order['id'], error='処理に失敗しました。', lease=order.get('lease'))
    return True
