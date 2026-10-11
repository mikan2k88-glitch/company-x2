"""Experimental file-only template work; not yet enabled in public intake."""
import csv
import hashlib
import io
import json

from .data_services import read_csv


def safe_request(data, execute_now=False):
    """Use existing screening; declaration is not proof of legal clearance."""
    from .delivery_safety import inspect_input, check_string
    from .intake_risk import require_declared_scope
    if not isinstance(data, dict):
        raise ValueError('Object required')
    purpose = data.get('purpose')
    if not isinstance(purpose, str) or not 1 <= len(purpose.strip()) <= 1000:
        raise ValueError('Describe the intended result / 完成させたい内容を入力してください')
    check_string(purpose)
    risk = require_declared_scope(data.get('risk_context'))
    text = data.get('csv')
    if not isinstance(text, str) or len(text.encode('utf-8')) > 50000:
        raise ValueError('CSV limit: 50KB')
    safety = inspect_input(text)
    if len(read_csv(text)[1]) > 1000:
        raise ValueError('CSV limit: 1000 rows')
    columns = data.get('columns')
    mapping = data.get('mapping')
    required = data.get('required', [])
    proposal = plan(text, columns, mapping, required)
    for column in columns:
        check_string(column, header=True)
    # Bind declarations and purpose as well as data and transformation.
    approval = hashlib.sha256(json.dumps({'plan': proposal, 'purpose': purpose,
        'risk': risk, 'safety': safety}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if not execute_now:
        return {'plan': proposal, 'approval_sha256': approval,
                'notice': 'Experimental file-only workflow; no external AI or account updates.'}
    if data.get('accepted') is not True or data.get('approval_sha256') != approval:
        raise ValueError('The purpose, conditions or input changed; approve a new plan')
    result = execute(text, columns, mapping, required, proposal['plan_sha256'], True)
    inspect_input(result['csv'])
    return result


def plan(text, columns, mapping, required=()):
    """Unmapped fields become questions, never guessed values."""
    header, rows = read_csv(text)
    if not isinstance(columns, list) or not 1 <= len(columns) <= 200:
        raise ValueError('Invalid template')
    if any(not isinstance(c, str) or not c.strip() for c in columns) or len(set(columns)) != len(columns):
        raise ValueError('Invalid template columns')
    if not isinstance(mapping, dict) or set(mapping) - set(columns):
        raise ValueError('Invalid mapping')
    if any(not isinstance(v, str) or v not in header for v in mapping.values()):
        raise ValueError('Unknown source column')
    if not isinstance(required, (list, tuple)) or any(c not in columns for c in required):
        raise ValueError('Invalid required columns')
    questions = [{'column': c, 'reason': 'source_column_required'} for c in columns if c not in mapping]
    result = {'version': 1, 'columns': columns, 'mapping': mapping,
              'required': list(required), 'input_rows': len(rows), 'questions': questions,
              'input_sha256': hashlib.sha256(text.encode()).hexdigest(),
              'operations': ['copy_exact_values', 'preserve_row_order', 'flag_missing_required'],
              'external_writes': False, 'inference': False}
    result['plan_sha256'] = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return result


def execute(text, columns, mapping, required, approved_hash, accepted=False):
    agreed = plan(text, columns, mapping, required)
    if accepted is not True or approved_hash != agreed['plan_sha256']:
        raise ValueError('Approve the current input and plan before execution')
    if agreed['questions']:
        raise ValueError('Resolve missing column mappings first')
    header, rows = read_csv(text)
    indexes = [header.index(mapping[c]) for c in columns]
    output_rows = [[row[i] for i in indexes] for row in rows]
    issues = [{'record': n, 'column': c, 'reason': 'missing_required'}
              for n, row in enumerate(output_rows, 2)
              for c, value in zip(columns, row) if c in required and not value.strip()]
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(columns)
    writer.writerows(output_rows)
    content = output.getvalue()
    checked_header, checked_rows = read_csv(content)
    if checked_header != columns or len(checked_rows) != len(rows):
        raise ValueError('Output structure verification failed')
    # Verify against source again, independently of output_rows.
    for source, delivered in zip(rows, checked_rows):
        for column, value in zip(columns, delivered):
            if value != source[header.index(mapping[column])]:
                raise ValueError('Source preservation verification failed')
    return {'csv': content, 'report': {'input_rows': len(rows), 'output_rows': len(checked_rows),
            'issues': issues, 'verified': True, 'ready_for_import': not issues,
            'notice': 'File checks only; destination-system import is not verified.'}}
