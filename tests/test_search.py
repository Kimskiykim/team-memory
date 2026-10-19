import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
import test_records
from test_records import base, put

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/search.py'


class SearchTest(unittest.TestCase):
    setUp = test_records.RecordsTest.setUp
    task = test_records.RecordsTest.task
    def run_search(self, *args, ok=True):
        result = subprocess.run([sys.executable, str(SCRIPT), '--root', str(self.root), '--json', *args], text=True, capture_output=True)
        self.assertEqual(result.returncode == 0, ok, result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        return json.loads(result.stdout) if ok else result.stderr

    def test_complete_pagination_filters_and_alias(self):
        for i in range(23):
            put(self.root, f'tasks/{i:02}.md', base(f'task-{i}', 'task', status='todo' if i % 2 else 'done', assignee='alice', projects=['atlas']), '## Outcome\nShip blue rocket\n## State\nWaiting\n## Sources\n[source](../sources/notes/request.md)\n')
        first = self.run_search('--kind', 'task')
        self.assertEqual((23, 10, 10), (first['total'], len(first['results']), first['next_offset']))
        ids = [r['id'] for offset in (0, 10, 20) for r in self.run_search('--kind', 'task', '--offset', str(offset))['results']]
        self.assertEqual(23, len(set(ids)))
        self.assertEqual(11, self.run_search('BLUE rocket', '--open', '--all', '--project', 'at', '--assignee', 'AL')['total'])
        self.assertEqual(23, self.run_search('--status', 'todo', '--status', 'done', '--all', '--offset', '99')['total'])

    def test_cache_hash_corruption_removal_rename_and_readonly(self):
        path = self.task()
        self.run_search('--id', 'task-1')
        cache = self.root / '.team-memory/search.json'
        self.assertTrue(cache.exists())
        stat = path.stat()
        path.write_text(path.read_text().replace('Ship', 'Send'))
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertEqual(1, self.run_search('Send')['total'])
        cache.write_text('{broken')
        self.assertEqual(1, self.run_search('--id', 'task-1')['total'])
        cache.unlink()
        path.rename(path.with_name('renamed.md'))
        self.assertEqual('tasks/renamed.md', self.run_search('--id', 'task-1')['results'][0]['path'])
        path.with_name('renamed.md').unlink()
        self.assertEqual(0, self.run_search('--id', 'task-1')['total'])
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.run_search('--no-cache', '--rebuild')
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_alias_errors_and_invalid_records_no_stale_cache(self):
        self.run_search()
        put(self.root, 'projects/beta.md', base('beta', aliases=['AT']), '## Description\nBeta\n')
        error = self.run_search('--project', 'AT', ok=False)
        self.assertIn('atlas', error)
        self.assertIn('beta', error)
        self.run_search('--project', 'unknown', ok=False)
        path = self.task(status='invalid')
        self.assertIn('tasks/one.md', self.run_search(ok=False))
        path.unlink()
        self.run_search('--limit', '-1', ok=False)

    def test_all_filter_modes_and_redirect_identity(self):
        put(self.root, 'wiki/systems/api.md', base('api', 'system', aliases=['API server']), '## Description\nAPI\n## Sources\n[source](../../sources/notes/request.md)\n')
        self.task(systems=['api'], assignee='alice')
        self.assertEqual(1, self.run_search('--system', 'api SERVER', '--kind', 'task')['total'])
        self.assertEqual(1, self.run_search('--source-type', 'note')['total'])
        put(self.root, 'wiki/concept.md', base('concept', 'knowledge', knowledge_type='concept'), '## Scope\nGlobal\n## Content\nShared knowledge\n## Sources\n[source](../sources/notes/request.md)\n')
        self.assertEqual(1, self.run_search('--knowledge-type', 'concept')['total'])
        put(self.root, 'tasks/old.md', base('old', 'redirect', target='task-1'), '## Redirect\n[new](one.md)\n')
        result = self.run_search('--id', 'old')['results'][0]
        self.assertEqual(('redirect', 'task-1'), (result['kind'], result['target']))
        self.assertEqual(0, self.run_search('--kind', 'task', '--offset', '999')['results'].__len__())

    def test_cache_integrity_rebuild_and_no_cache_creates_nothing(self):
        self.task()
        self.run_search('--no-cache')
        self.assertFalse((self.root / '.team-memory').exists())
        self.run_search()
        path = self.root / '.team-memory/search.json'
        data = json.loads(path.read_text())
        self.assertEqual(64, len(data['hashes']['tasks/one.md']))
        data['records'][0]['title'] = 'INJECTED'
        path.write_text(json.dumps(data))
        self.assertNotIn('INJECTED', json.dumps(self.run_search()))
        self.assertNotIn('INJECTED', path.read_text())
        self.run_search('--rebuild')
        self.assertEqual([], list(path.parent.glob('*.tmp')))

    def test_validator_is_readonly_and_diagnoses_cli_errors(self):
        self.task(due='2026-02-30')
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result = subprocess.run([sys.executable, str(SCRIPT.with_name('validate.py')), '--root', str(self.root)], text=True, capture_output=True)
        self.assertNotEqual(0, result.returncode)
        self.assertIn('tasks/one.md', result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_project_id_takes_precedence_over_conflicting_alias(self):
        self.task(projects=['atlas'])
        put(self.root, 'projects/beta.md', base('beta', aliases=['atlas']), '## Description\nBeta\n')
        for value in ('atlas', 'ATLAS'):
            result = self.run_search('--project', value, '--kind', 'task')
            self.assertEqual(['task-1'], [r['id'] for r in result['results']])

    def test_exact_spelling_disambiguates_case_distinct_ids(self):
        self.task(projects=['atlas'])
        put(self.root, 'projects/upper.md', base('ATLAS', aliases=[]), '## Description\nUppercase project\n')
        self.assertEqual(1, self.run_search('--project', 'atlas', '--kind', 'task')['total'])
        self.assertEqual(0, self.run_search('--project', 'ATLAS', '--kind', 'task')['total'])
        error = self.run_search('--project', 'Atlas', ok=False)
        self.assertIn('ambiguous', error)
        self.assertIn('atlas', error)
        self.assertIn('ATLAS', error)
