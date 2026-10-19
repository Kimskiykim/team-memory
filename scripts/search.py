"""Search all validated records with content-checked disposable indexing."""
import argparse
import datetime
import json
import os
from pathlib import Path
import sys
import tempfile
from records import ROOT, load_records

VERSION = 1


def json_default(value):
    if isinstance(value, datetime.date):
        return value.isoformat()
    raise TypeError(f'unsupported value: {type(value).__name__}')


def catalog(records):
    return {'version': VERSION, 'hashes': {r['path']: r['sha256'] for r in records},
            'records': [dict(r['metadata'], path=r['path'], text=r['text']) for r in records]}


def update_cache(root, fresh, force=False):
    directory = root / '.team-memory'
    cache = directory / 'search.json'
    if directory.is_symlink() or cache.is_symlink():
        raise ValueError(f'{cache}: symlink cache forbidden')
    try:
        existing = json.loads(cache.read_text(encoding='utf-8'))
        if not force and existing == fresh:
            return
    except (OSError, ValueError, UnicodeError):
        pass
    directory.mkdir(exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=directory, prefix='.search-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(fresh, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, cache)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('text', nargs='*')
    parser.add_argument('--root', type=Path, default=ROOT)
    for flag in ('id', 'kind', 'project', 'system', 'assignee', 'status', 'knowledge-type', 'source-type'):
        parser.add_argument('--' + flag, action='append', default=[])
    for flag in ('json', 'all', 'open', 'rebuild', 'no-cache'):
        parser.add_argument('--' + flag, action='store_true')
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('--limit', type=int, default=10)
    args = parser.parse_args()
    if args.offset < 0 or args.limit <= 0:
        parser.error('offset must be nonnegative and limit must be positive')
    root = args.root.resolve()
    if not root.is_dir():
        parser.error(f'{root}: root directory does not exist')
    try:
        records, errors = load_records(root)
        if errors:
            print('\n'.join(errors), file=sys.stderr)
            return 1
        # Always validate current bytes, even when a cache exists. Cached data is
        # disposable; comparing its full shape also detects syntactically valid corruption.
        fresh = json.loads(json.dumps(catalog(records), default=json_default))
        aliases = {}
        for field, kind in (('project', 'project'), ('system', 'system'), ('assignee', 'person')):
            aliases[field] = set()
            candidates = [r['metadata'] for r in records if r['metadata']['kind'] == kind]
            for value in getattr(args, field):
                # Exact spelling disambiguates case-distinct IDs. Otherwise IDs
                # still take precedence over aliases when ignoring case.
                matches = {r['id'] for r in candidates if value == r['id']}
                if not matches:
                    matches = {r['id'] for r in candidates if value.casefold() == r['id'].casefold()}
                if not matches:
                    matches = {r['id'] for r in candidates if value.casefold() in [a.casefold() for a in r['aliases']]}
                if len(matches) != 1:
                    reason = 'ambiguous: ' + ', '.join(sorted(matches)) if matches else 'unknown value'
                    raise ValueError(f'--{field} {value}: {reason}')
                aliases[field].update(matches)
        words = ' '.join(args.text).casefold().split()
        found = []
        for rec in fresh['records']:
            if any(word not in json.dumps(rec, ensure_ascii=False).casefold() for word in words):
                continue
            if any(getattr(args, key) and rec.get(key) not in getattr(args, key) for key in ('id', 'kind', 'status', 'knowledge_type', 'source_type')):
                continue
            if args.open and rec.get('status') not in ('todo', 'in_progress', 'blocked'):
                continue
            if any(aliases[field] and not aliases[field].intersection(rec.get(target, [])) for field, target in (('project', 'projects'), ('system', 'systems'))):
                continue
            if aliases['assignee'] and rec.get('assignee') not in aliases['assignee']:
                continue
            found.append({k: v for k, v in rec.items() if k != 'text'})
        if not args.no_cache:
            update_cache(root, fresh, args.rebuild)
        offset, limit = (0, len(found)) if args.all else (args.offset, args.limit)
        results = found[offset:offset + limit]
        output = dict(total=len(found), offset=offset, limit=limit, next_offset=offset + limit if offset + limit < len(found) else None, results=results)
        if args.json:
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            print(f'{len(found)} matches; showing {len(results)} from {offset}')
            for rec in results:
                print(f'{rec["path"]} [{rec["id"]}] {rec["title"]}\n  {rec["summary"]}')
            if output['next_offset'] is not None:
                print(f'Next: --offset {output["next_offset"]}')
        return 0
    except (OSError, ValueError, RecursionError) as exc:
        print(f'{root}: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
