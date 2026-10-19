import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import records


def put(root, path, meta, body):
    import yaml
    dest = root / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text('---\n' + yaml.safe_dump(meta, allow_unicode=True) + '---\n' + body, encoding='utf-8')
    return dest


def base(id='atlas', kind='project', **extra):
    return dict(dict(id=id, kind=kind, title=id, summary='A useful summary', projects=[], systems=[]), **extra)


def seed(root):
    put(root, 'projects/atlas.md', base(aliases=['AT']), '## Description\nAtlas project\n')
    put(root, 'people/alice.md', base('alice', 'person', aliases=['Al']), '## Description\nAlice\n')
    put(root, 'sources/notes/request.md', base('request', 'source', source_type='note', event_date='2026-10-19', origin='User request'), '## Original\n```text\nUser material\n```\n## Results\nNone\n## Questions\nNone\n')


class RecordsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        seed(self.root)

    def errors(self):
        return '\n'.join(records.load_records(self.root)[1])

    def task(self, **extra):
        meta = base('task-1', 'task', status='todo')
        meta.update(extra)
        return put(self.root, 'tasks/one.md', meta, '## Outcome\nShip\n## State\nWaiting\n## Sources\n[request](../sources/notes/request.md)\n')

    def test_valid_and_duplicate_id(self):
        self.task(projects=['atlas'], assignee='alice', due='2026-12-01')
        self.assertEqual('', self.errors())
        put(self.root, 'projects/other.md', base(aliases=[]), '## Description\nOther\n')
        self.assertIn('duplicate id', self.errors())

    def test_invalid_types_dates_and_references(self):
        for patch in ({'status': []}, {'projects': None}, {'due': '2026-02-30'}, {'due': '2026-01-01T00:00:00'}, {'assignee': []}, {'projects': ['missing']}, {'kind': []}, {'id': []}):
            with self.subTest(patch=patch):
                self.task(**patch)
                self.assertTrue(self.errors())

    def test_yaml_safety_duplicate_keys_and_nonmapping(self):
        path = self.task()
        for raw in ('id: x\nid: y', '!!python/object/apply:os.system [echo unsafe]', '[one, two]', 'a: &a [*a]'):
            path.write_text('---\n' + raw + '\n---\nbody')
            self.assertTrue(self.errors())

    def test_sources_sections_and_links(self):
        path = self.task()
        original = path.read_text()
        for old, new in [('Ship', ''), ('../sources/notes/request.md', '../projects/atlas.md'), ('../sources/notes/request.md', '../../escape.md'), ('../sources/notes/request.md', '/etc/passwd'), ('../sources/notes/request.md', '../sources/notes/request.md#missing')]:
            path.write_text(original.replace(old, new))
            self.assertTrue(self.errors())
        path.write_text(original + '\n`[ignore](missing.md)`\n```md\n[ignore](missing.md)\n```\n[ok][ref]\n[ref]: ../projects/atlas.md#description\n')
        self.assertEqual('', self.errors())

    def test_symlink_rejected(self):
        (self.root / 'projects/link.md').symlink_to(self.root / 'projects/atlas.md')
        self.assertIn('symlink', self.errors())

    def test_decision_and_redirect_lifecycle(self):
        def decision(id, **kw):
            return put(self.root, f'wiki/decisions/{id}.md', base(id, 'knowledge', knowledge_type='decision', decision_status='accepted', **kw), '## Scope\nAll\n## Content\nDecision\n## Sources\n[source](../../sources/notes/request.md)\n')
        old, new = decision('old'), decision('new')
        old.write_text(old.read_text().replace('decision_status: accepted', 'decision_status: superseded\nsuperseded_by: new') + '\n[new](new.md)\n')
        self.assertIn('back', self.errors())
        new.write_text(new.read_text() + '\n[old](old.md)\n')
        self.assertEqual('', self.errors())
        put(self.root, 'tasks/redirect.md', base('redirect-1', 'redirect', target='old'), '## Redirect\n[old](../wiki/decisions/old.md)\n')
        self.assertEqual('', self.errors())
        put(self.root, 'tasks/chain.md', base('redirect-2', 'redirect', target='redirect-1'), '## Redirect\n[redirect](redirect.md)\n')
        self.assertIn('redirect', self.errors())

    def test_howto_fields(self):
        path = put(self.root, 'wiki/how-to/use.md', base('use', 'knowledge', knowledge_type='how-to', verified_on=None, system_version=None), '## Scope\nAll\n## Content\nNot verified\n## Environment\nUnknown\n## Sources\n[source](../../sources/notes/request.md)\n')
        self.assertEqual('', self.errors())
        path.write_text(path.read_text().replace('verified_on: null', 'verified_on: 2026-02-30'))
        self.assertTrue(self.errors())

    def test_reference_sources_defined_outside_section(self):
        path = self.task()
        path.write_text(path.read_text().replace('## Outcome', '[src]: ../sources/notes/request.md\n\n## Outcome').replace('[request](../sources/notes/request.md)', '[request][src]'))
        self.assertEqual('', self.errors())

    def test_invalid_decision_identity_has_diagnostics(self):
        old = put(self.root, 'wiki/decisions/old.md', base('old', 'knowledge', knowledge_type='decision', decision_status='superseded', superseded_by='new'), '## Scope\nAll\n## Content\nOld [new](new.md)\n## Sources\n[source](../../sources/notes/request.md)\n')
        put(self.root, 'wiki/decisions/new.md', base('new', 'knowledge', knowledge_type='decision', decision_status='accepted'), '## Scope\nAll\n## Content\nNew [old](old.md)\n## Sources\n[source](../../sources/notes/request.md)\n')
        old.write_text(old.read_text().replace('id: old', 'id: []'))
        self.assertIn('id must', self.errors())

    def test_encoded_paths_and_github_duplicate_anchors(self):
        put(self.root, 'projects/two words.md', base('words', aliases=[]), '## Description\nWords\n## Hello, Мир!\nOne\n## Hello, Мир!\nTwo\n')
        path = self.task()
        path.write_text(path.read_text() + '\n[one](../projects/two%20words.md#hello-мир-1)\n[two](<../projects/two words.md#description>)\n')
        self.assertEqual('', self.errors())

    def test_decision_cycles_and_redirect_section_target(self):
        for ident, target in [('a', 'b'), ('b', 'a')]:
            put(self.root, f'wiki/decisions/{ident}.md', base(ident, 'knowledge', knowledge_type='decision', decision_status='superseded', superseded_by=target), f'## Scope\nAll\n## Content\n[{target}]({target}.md)\n## Sources\n[source](../../sources/notes/request.md)\n')
        self.assertIn('cycle', self.errors())
        put(self.root, 'tasks/redirect.md', base('redirect', 'redirect', target='atlas'), '## Redirect\nSee other section\n## Other\n[atlas](../projects/atlas.md)\n')
        self.assertIn('Redirect must link to target', self.errors())

    def test_yaml_dates_timestamps_and_code_sections(self):
        import datetime
        path = self.task(due=datetime.date(2026, 12, 1))
        self.assertEqual('', self.errors())
        self.task(due=datetime.datetime(2026, 12, 1))
        self.assertIn('due must', self.errors())
        path = self.task()
        path.write_text(path.read_text().replace('## Outcome\nShip', '```md\n## Outcome\nShip\n```'))
        self.assertIn('Outcome', self.errors())

    def test_source_original_and_directory_symlinks(self):
        path = self.root / 'sources/notes/request.md'
        path.write_text(path.read_text().replace('```text\nUser material\n```', 'User material'))
        self.assertIn('fenced block', self.errors())
        (self.root / 'wiki').mkdir()
        (self.root / 'wiki/linked').symlink_to(self.root / 'projects', target_is_directory=True)
        self.assertIn('symlink', self.errors())

    def test_nested_list_links_are_validated_but_code_is_ignored(self):
        path = self.task()
        original = path.read_text()
        path.write_text(original + '\n- Related tasks:\n    - [Missing task](missing.md)\n')
        self.assertIn('missing.md', self.errors())
        path.write_text(original.replace('[request](../sources/notes/request.md)', '- References:\n    - [request](../sources/notes/request.md)'))
        self.assertEqual('', self.errors())
        path.write_text(original + '\n    - [code](missing.md)\n\n- Examples:\n\n      [indented code](missing.md)\n\n  ```md\n  - [fenced code](missing.md)\n  ```\n')
        self.assertEqual('', self.errors())

    def test_record_directory_file_and_walk_io_errors(self):
        from unittest.mock import patch
        import os
        (self.root / 'wiki').write_text('not a directory')
        self.assertIn('wiki', self.errors())
        (self.root / 'wiki').unlink()
        original_scandir = os.scandir
        def fail_project(path):
            if Path(path).resolve() == (self.root / 'projects').resolve():
                raise PermissionError(13, 'Permission denied', str(path))
            return original_scandir(path)
        with patch('records.os.scandir', side_effect=fail_project):
            errors = self.errors()
        self.assertIn('projects', errors)
        self.assertIn('Permission denied', errors)

    def test_indented_code_cannot_supply_required_source(self):
        path = self.task()
        path.write_text(path.read_text().replace('[request](../sources/notes/request.md)', '    [request](../sources/notes/request.md)'))
        self.assertIn('Sources must link', self.errors())
