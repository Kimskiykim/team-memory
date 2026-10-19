"""Exercise the shipped demo and materialized templates against the real reader."""
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from records import load_records

ROOT = Path(__file__).resolve().parents[1]


class AssetsTest(unittest.TestCase):
    def test_demo_and_all_templates_are_valid_when_filled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'base'
            shutil.copytree(ROOT / 'tests/fixtures/demo', root)
            records, errors = load_records(root)
            self.assertEqual([], errors)
            self.assertEqual(13, len(records))
            folders = {
                'task': 'tasks', 'person': 'people', 'project': 'projects',
                'system': 'wiki/systems', 'knowledge': 'wiki', 'how-to': 'wiki/how-to',
                'decision': 'wiki/decisions', 'meeting': 'sources/meetings',
                'note': 'sources/notes', 'redirect': 'wiki',
            }
            for name, folder in folders.items():
                with self.subTest(template=name):
                    path = root / folder / ('template-' + name + '.md')
                    path.parent.mkdir(parents=True, exist_ok=True)
                    text = (ROOT / 'skills/team-memory/templates' / (name + '.md')).read_text()
                    text = text.replace('replace-id', 'template-' + name)
                    text = text.replace('REPLACE-SOURCE.md', os.path.relpath(root / 'sources/notes/seed.md', path.parent))
                    text = text.replace('replace-target-id', 'relay')
                    text = text.replace('REPLACE-TARGET.md', os.path.relpath(root / 'wiki/systems/relay.md', path.parent))
                    path.write_text(text)
                    self.assertEqual([], load_records(root)[1])

    def test_discovery_link_points_to_canonical_skill(self):
        skill = ROOT / '.agents/skills/team-memory'
        self.assertTrue(skill.is_symlink())
        self.assertEqual(ROOT / 'skills/team-memory', skill.resolve())


if __name__ == '__main__':
    unittest.main()
