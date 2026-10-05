"""Import an operator-provided listing feed and persist deterministic qualification."""
import argparse
import json
from pathlib import Path
from .discovery import qualify
from .settings import build_store


def import_feed(store, items):
    if not isinstance(items, list) or len(items) > 100:
        raise ValueError('Feed must contain at most 100 listings')
    # Validate whole batch before any writes.
    evaluated = [(candidate, *qualify(candidate)) for candidate in items]
    for candidate, decision, reason in evaluated:
        store.save_opportunity(candidate, decision, reason)
    return [{'external_id': c['external_id'], 'decision': d, 'reason': r,
             'proposal_sent': False} for c, d, r in evaluated]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('feed', help='JSON file from an approved source adapter')
    parser.add_argument('--db', default='work/company-x2.db')
    args = parser.parse_args()
    path = Path(args.feed)
    if path.stat().st_size > 1_000_000:
        raise ValueError('Feed too large')
    print(json.dumps(import_feed(build_store(local_path=args.db), json.loads(path.read_text(encoding='utf-8-sig'))),
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
