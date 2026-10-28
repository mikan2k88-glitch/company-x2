"""Reviewed engineering ledger; no customer content or automatic release authority."""
import copy
import json
from pathlib import Path

LEDGER = Path(__file__).with_name('quality-ledger.json')
LEVELS = ('code', 'tests', 'production', 'customers')


def report(ledger=None):
    data = json.loads(LEDGER.read_text(encoding='utf-8')) if ledger is None else copy.deepcopy(ledger)
    if data.get('version') != 1 or not isinstance(data.get('projects'), list):
        raise ValueError('Quality ledger unavailable')
    identifiers = set()
    for project in data['projects']:
        if project['id'] in identifiers:raise ValueError('Duplicate project')
        identifiers.add(project['id'])
        for level in LEVELS:
            stage = project['verification'][level]
            if stage['state'] not in ('verified', 'pending'):
                raise ValueError('Invalid verification state')
            if stage['state'] == 'verified' and not stage.get('evidence'):
                raise ValueError('Verification evidence required')
        seen = set()
        for issue in project['issues']:
            if issue['id'] in seen or issue['priority'] not in (0, 1, 2, 3):
                raise ValueError('Invalid improvement issue')
            seen.add(issue['id'])
            if issue['status'] not in ('open', 'in_progress', 'resolved'):
                raise ValueError('Invalid improvement status')
            if issue['status'] == 'resolved' and not issue.get('evidence'):
                raise ValueError('Resolution evidence required')
        project['issues'].sort(key=lambda item:(item['status']=='resolved',item['priority'],item['id']))
        project['open_issues'] = sum(item['status']!='resolved' for item in project['issues'])
        project['validation_complete'] = all(project['verification'][level]['state']=='verified' for level in LEVELS)
    return {**data, 'read_only':True, 'release_authority':False,
        'notice':'レビュー記録です。ライブ監視ではありません。試験成功を実顧客の受領・収益と扱いません。'}
