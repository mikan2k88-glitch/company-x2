"""Bounded deterministic data services and artifact verification."""
import csv
import io
import json
from collections import Counter

from .csv_service import MAX_BYTES, MAX_ROWS, deduplicate_csv

MAX_ARTIFACT_BYTES = 8_000_000
SERVICES = {
    'csv_exact_dedup': {'name': 'CSV重複除去', 'description': '完全一致する重複行を除去。列名・値・先頭の行順を保持します。', 'format': 'csv'},
    'csv_trim': {'name': 'CSV空白整形', 'description': '列名と各値の前後の空白を除去します。内部の空白・行順・重複は保持します。', 'format': 'csv'},
    'csv_to_json': {'name': 'CSV → JSON', 'description': '列名をキーにしたオブジェクト配列へ変換。数値・空欄も文字列として保持します。', 'format': 'json'},
    'csv_audit': {'name': 'CSVデータ検査', 'description': '空欄・完全一致の重複・数式のような値を検査し、JSONレポートを納品します。入力は変更しません。', 'format': 'json'},
}


def require_service(key):
    if not isinstance(key, str) or key not in SERVICES:
        raise ValueError('対応していないサービスです')
    return key


def read_csv(text):
    if not isinstance(text, str) or len(text.encode('utf-8')) > MAX_BYTES:
        raise ValueError('CSV input limit exceeded')
    reader = csv.reader(io.StringIO(text.removeprefix('\ufeff'), newline=''), strict=True)
    header = next(reader, None)
    if not header or len(header) > 200 or any(not h.strip() for h in header) or len(set(header)) != len(header):
        raise ValueError('Invalid headers')
    rows = []
    for row in reader:
        if len(rows) >= MAX_ROWS or len(row) != len(header):
            raise ValueError('Invalid record or row limit')
        rows.append(row)
    return header, rows


def formula_like(value):
    return value.lstrip().startswith(('=', '+', '-', '@'))


def audit(header, rows):
    empty = [0] * len(header)
    formula = [0] * len(header)
    sample = []
    seen = set()
    duplicates = []
    for number, row in enumerate(rows, 2):
        key = tuple(row)
        if key in seen:
            duplicates.append(number)
        seen.add(key)
        for column, value in enumerate(row):
            blank, suspicious = not value.strip(), formula_like(value)
            empty[column] += blank
            formula[column] += suspicious
            if (blank or suspicious) and len(sample) < 50:
                sample.append({'record': number, 'column': header[column],
                               'kind': 'empty' if blank else 'formula_like'})
    return {'schema_version': 1, 'row_count': len(rows), 'column_count': len(header),
            'duplicate_rows': len(duplicates), 'duplicate_record_sample': duplicates[:50],
            'empty_cells': sum(empty), 'formula_like_cells': sum(formula),
            'columns': [{'name': name, 'empty_cells': e, 'formula_like_cells': f}
                        for name, e, f in zip(header, empty, formula)],
            'issue_sample': sample, 'sample_limit': 50,
            'record_numbering': 'ヘッダーを1とするCSVレコード番号。改行を含む値では物理的な行番号と異なります。',
            'notice': '数式のような値は推測です。数値のマイナスなども含みます。実行や修正はしていません。'}


def make_artifact(content, service_key):
    if len(content.encode('utf-8')) > MAX_ARTIFACT_BYTES:
        raise ValueError('Artifact limit exceeded')
    extension = SERVICES[service_key]['format']
    return {'content': content, 'content_type': ('text/csv' if extension == 'csv' else 'application/json') + '; charset=utf-8',
            'filename': 'company-x2-' + service_key.replace('_', '-') + '.' + extension}


def produce(text, service_key):
    require_service(service_key)
    if service_key == 'csv_exact_dedup':
        # Preserve the E02 contract and already submitted orders.
        result = deduplicate_csv(text)
        result['service_key'] = service_key
        result['artifact'] = make_artifact(result['csv'], service_key)
        return result
    header, rows = read_csv(text)
    result = {'service_key': service_key, 'input_rows': len(rows), 'output_rows': len(rows), 'removed_rows': 0}
    if service_key == 'csv_trim':
        cleaned_header = [h.strip() for h in header]
        if len(set(cleaned_header)) != len(cleaned_header):
            raise ValueError('Trimming creates duplicate headers')
        cleaned = [[v.strip() for v in row] for row in rows]
        output = io.StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow(cleaned_header)
        writer.writerows(cleaned)
        content = output.getvalue()
        result['changed_cells'] = sum(a != b for a, b in zip(header, cleaned_header)) + sum(
            a != b for old, new in zip(rows, cleaned) for a, b in zip(old, new))
    elif service_key == 'csv_to_json':
        # Check incremental output size before joining. Long header names repeat per row.
        chunks, size = [], 4
        for row in rows:
            chunk = json.dumps(dict(zip(header, row)), ensure_ascii=False)
            size += len(chunk.encode('utf-8')) + 2
            if size > MAX_ARTIFACT_BYTES:
                raise ValueError('JSON amplification exceeds artifact limit')
            chunks.append(chunk)
        content = '[\n' + ',\n'.join(chunks) + '\n]\n' if chunks else '[]\n'
    else:
        report = audit(header, rows)
        result['summary'] = {k: report[k] for k in ('empty_cells', 'duplicate_rows', 'formula_like_cells')}
        content = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    result['artifact'] = make_artifact(content, service_key)
    return result


def verify(text, service_key, result):
    """Verify the actual serialized artifact against the input contract."""
    artifact = result['artifact']
    content = artifact['content']
    if artifact != make_artifact(content, service_key) or result['service_key'] != service_key:
        raise ValueError('Artifact metadata mismatch')
    # The legacy service accepts >200 columns, so preserve its previous parser contract.
    original = list(csv.reader(io.StringIO(text.removeprefix('\ufeff') if service_key != 'csv_exact_dedup' else text,
                                             newline=''), strict=True))
    header, rows = original[0], original[1:]
    if result['input_rows'] != len(rows):
        raise ValueError('Input count mismatch')
    if service_key in ('csv_exact_dedup', 'csv_trim'):
        output = list(csv.reader(io.StringIO(content, newline=''), strict=True))
        if service_key == 'csv_exact_dedup':
            expected = [list(row) for row in dict.fromkeys(tuple(row) for row in rows)]
            valid = output == [header, *expected] and result['removed_rows'] == len(rows) - len(expected)
        else:
            valid = len(output) == len(original) and all(
                len(old) == len(new) and all(b == a.strip() for a, b in zip(old, new))
                for old, new in zip(original, output))
        valid = valid and result['output_rows'] == len(output) - 1
    elif service_key == 'csv_to_json':
        output = json.loads(content)
        valid = isinstance(output, list) and len(output) == len(rows) and all(
            isinstance(obj, dict) and list(obj) == header and [obj[h] for h in header] == row
            for obj, row in zip(output, rows)) and result['output_rows'] == len(rows)
    else:
        report = json.loads(content)
        counts = Counter(tuple(row) for row in rows)
        valid = (report['row_count'] == len(rows) and report['column_count'] == len(header)
                 and report['duplicate_rows'] == sum(count - 1 for count in counts.values())
                 and report['empty_cells'] == sum(not value.strip() for row in rows for value in row)
                 and report['formula_like_cells'] == sum(formula_like(value) for row in rows for value in row)
                 and [c['name'] for c in report['columns']] == header)
    if not valid:
        raise ValueError('Output verification failed')
