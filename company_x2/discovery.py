"""Evaluate real structured listings. Never invent customers or send proposals."""
from urllib.parse import urlparse


def qualify(candidate):
    required = ('source', 'external_id', 'url', 'title', 'service_key')
    if not isinstance(candidate, dict) or any(not isinstance(candidate.get(k), str) or not candidate[k].strip() for k in required):
        raise ValueError('Source, external ID, URL, title and service key are required')
    if any(len(candidate[k]) > 2048 for k in required):
        raise ValueError('Listing field too long')
    parsed = urlparse(candidate['url'])
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Listing URL must be HTTPS without credentials')
    if candidate['service_key'] != 'csv_exact_dedup':
        return 'rejected', 'Unsupported service'
    budget = candidate.get('budget_jpy')
    cost = candidate.get('estimated_cost_jpy')
    if type(budget) is not int or type(cost) is not int or not 0 <= cost < budget:
        return 'rejected', 'Missing or insufficient contribution margin'
    if candidate.get('automated_proposals_allowed') is not True:
        return 'blocked', 'Automation permission has not been established'
    return 'qualified', 'Structured candidate matches service and budget; source authenticity and terms need connector verification'
