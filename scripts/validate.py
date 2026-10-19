"""Validate the record tree without modifying files."""
import argparse
from pathlib import Path
import sys
from records import ROOT, load_records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    if not args.root.is_dir():
        parser.error(f'{args.root}: root directory does not exist')
    try:
        records, errors = load_records(args.root)
    except (OSError, ValueError, RecursionError) as exc:
        print(f'{args.root}: {exc}', file=sys.stderr)
        return 1
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1
    print(f'Valid: {len(records)} records')
    return 0


if __name__ == '__main__':
    sys.exit(main())
