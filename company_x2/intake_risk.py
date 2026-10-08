"""Conservative declarations; never a legal determination or proof of safety."""
VERSION = 'risk-v1'
NOTICE = '自己申告による受付判定です。責任が返金だけに限定される保証ではありません。'
FIELDS = {
    'sensitive_data': '個人情報・機密情報を含む案件は受付対象外です',
    'critical_use': '医療・法律・金融判断、安全や本番システムに直接影響する用途は受付対象外です',
    'extra_liability': '返金を超える補償・保証・独自の責任条件を求める案件は受付対象外です',
}


def assess(context=None):
    if context is None:
        return {'version': VERSION, 'decision': 'needs_information',
                'reasons': ['用途・データ・責任条件の申告がありません'], 'notice': NOTICE}
    if not isinstance(context, dict) or set(context) != set(FIELDS):
        raise ValueError('受付判定の3項目を指定してください')
    if any(value not in ('yes', 'no', 'unknown') for value in context.values()):
        raise ValueError('受付判定は yes / no / unknown を指定してください')
    reasons = [reason for key, reason in FIELDS.items() if context[key] == 'yes']
    unknown = [key for key in FIELDS if context[key] == 'unknown']
    return {'version': VERSION, 'declarations': dict(context),
            'decision': 'reject' if reasons else 'needs_information' if unknown else 'limited_scope',
            'reasons': reasons or (['未確認の項目があるため受付できません'] if unknown else []),
            'notice': NOTICE}


def require_declared_scope(context):
    result = assess(context)
    if result['decision'] != 'limited_scope':
        raise ValueError('受付安全判定: ' + ' / '.join(result['reasons']))
    return result
