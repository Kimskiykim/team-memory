"""Shared, read-only Markdown record reader and structural checks."""
from __future__ import annotations

import datetime as dt
import hashlib
import os
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = ('projects', 'people', 'tasks', 'wiki', 'sources')
SECTIONS = {
    'project': ('Description',), 'person': ('Description',),
    'system': ('Description', 'Sources'), 'task': ('Outcome', 'State', 'Sources'),
    'knowledge': ('Scope', 'Content', 'Sources'),
    'source': ('Original', 'Results', 'Questions'), 'redirect': ('Redirect',),
}


class UniqueSafeLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise ValueError('YAML keys must be strings')
        if key in result:
            raise ValueError(f'duplicate YAML key: {key}')
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueSafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def plain_text(value):
    return isinstance(value, str) and bool(value.strip())


def string_list(value):
    return isinstance(value, list) and all(plain_text(v) for v in value)


def valid_date(value):
    if isinstance(value, dt.datetime):
        return False
    if isinstance(value, dt.date):
        return True
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return False
    try:
        dt.date.fromisoformat(value)
        return True
    except ValueError:
        return False


def strip_code(text, inline=True):
    """Keep line positions, dropping fenced and indented code from link parsing."""
    lines, fence, fence_indent = [], None, 0
    list_indents = []
    for line in text.splitlines():
        expanded = line.expandtabs(4)
        if fence:
            relative = expanded[fence_indent:] if expanded[:fence_indent].isspace() else expanded
            if re.match(r'^ {0,3}' + re.escape(fence[0]) + '{' + str(len(fence)) + r',}\s*$', relative):
                fence = None
            lines.append('')
            continue
        if not line.strip():
            lines.append('')
            continue
        indent = len(expanded) - len(expanded.lstrip(' '))
        while list_indents and indent < list_indents[-1]:
            list_indents.pop()
        base_indent = list_indents[-1] if list_indents else 0
        # Four spaces are code relative to the containing list item, not
        # relative to the document. Nested list markers remain ordinary text.
        if indent >= base_indent + 4:
            lines.append('')
            continue
        relative = expanded[base_indent:]
        marker = re.match(r'^ {0,3}(?:[-+*]|[0-9]{1,9}[.)]) +', relative)
        if marker:
            base_indent += marker.end()
            list_indents.append(base_indent)
            relative = expanded[base_indent:]
        opening = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', relative)
        if opening:
            fence, fence_indent = opening.group(1), base_indent
            lines.append('')
        else:
            lines.append(line)
    text = '\n'.join(lines)
    if inline:
        text = re.sub(r'(`+)(?!`)([\s\S]*?)(?<!`)\1(?!`)', '', text)
    return text


def sections(body):
    # Raw contents retain fenced source material; code headings cannot create sections.
    headings = list(re.finditer(r'^##[ \t]+(.+?)[ \t]*#*[ \t]*$', strip_code(body, inline=False), re.M))
    raw = body.splitlines()
    result = {}
    clean = strip_code(body, inline=False)
    for i, heading in enumerate(headings):
        start = clean[:heading.end()].count('\n') + 1
        end = clean[:headings[i + 1].start()].count('\n') if i + 1 < len(headings) else len(raw)
        result[heading.group(1).strip()] = '\n'.join(raw[start:end]).strip('\n')
    return result


def links(body, context=None):
    text = strip_code(body)
    destination = r'(?:<([^>]+)>|([^\s)]+))(?:\s+[\'\"][^\n]*?[\'\"])?'
    definitions = {}
    for m in re.finditer(r'^ {0,3}\[([^\]]+)\]:\s*' + destination + r'\s*$', strip_code(context) if context is not None else text, re.M):
        definitions[' '.join(m.group(1).lower().split())] = m.group(2) or m.group(3)
    text = re.sub(r'^ {0,3}\[[^\]]+\]:[^\n]*$', '', text, flags=re.M)
    found = [m.group(1) or m.group(2) for m in re.finditer(r'(?<!!)\[[^\]\n]*\]\(\s*' + destination + r'\s*\)', text)]
    for m in re.finditer(r'(?<!!)\[([^\]\n]+)\](?:\[([^\]\n]*)\])?(?!\()', text):
        key = ' '.join((m.group(2) or m.group(1)).lower().split())
        if key in definitions:
            found.append(definitions[key])
    return found


def anchors(body):
    result, counts = set(), {}
    for title in re.findall(r'^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$', strip_code(body, inline=False), re.M):
        title = re.sub(r'\[([^]]+)\]\([^)]*\)', r'\1', title)
        slug = re.sub(r'[^\w\- ]', '', title.lower()).replace(' ', '-')
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        result.add(slug + (f'-{count}' if count else ''))
    return result


def scan_files(root):
    files, errors = {}, []
    for directory in DIRECTORIES:
        start = root / directory
        if start.is_symlink():
            errors.append(f'{directory}: symlink forbidden')
            continue
        if not start.exists():
            continue
        if not start.is_dir():
            errors.append(f'{directory}: expected a directory')
            continue
        def walk_error(exc):
            errors.append(f'{directory}: cannot read records: {exc}')
        for parent, dirs, names in os.walk(start, followlinks=False, onerror=walk_error):
            for name in list(dirs):
                path = Path(parent) / name
                if path.is_symlink():
                    errors.append(f'{path.relative_to(root)}: symlink forbidden')
                    dirs.remove(name)
            for name in sorted(names):
                path = Path(parent) / name
                if path.suffix.lower() != '.md':
                    continue
                rel = path.relative_to(root).as_posix()
                if path.is_symlink():
                    errors.append(f'{rel}: symlink forbidden')
                    continue
                try:
                    files[rel] = path.read_bytes()
                except OSError as exc:
                    errors.append(f'{rel}: {exc}')
    return dict(sorted(files.items())), errors


def load_records(root=ROOT):
    root = Path(root).resolve()
    files, errors = scan_files(root)
    records, ids = [], {}
    for path, data in files.items():
        def error(reason):
            errors.append(f'{path}: {reason}')
        try:
            text = data.decode('utf-8')
            match = re.match(r'\A---\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)(.*)\Z', text, re.S)
            if not match:
                raise ValueError('missing YAML frontmatter')
            meta = yaml.load(match.group(1), Loader=UniqueSafeLoader)
            if not isinstance(meta, dict):
                raise ValueError('frontmatter must be a mapping')
            # Reject recursive YAML graphs and non-JSON extension values before indexing.
            def portable(value, active=None):
                active = set() if active is None else active
                if isinstance(value, (list, dict)):
                    if id(value) in active:
                        raise ValueError('recursive YAML aliases forbidden')
                    active.add(id(value))
                    values = value.values() if isinstance(value, dict) else value
                    for v in values:
                        portable(v, active)
                    active.remove(id(value))
                elif not isinstance(value, (str, int, float, bool, dt.date, type(None))):
                    raise ValueError('unsupported YAML value')
            portable(meta)
        except (UnicodeError, yaml.YAMLError, ValueError, RecursionError) as exc:
            error(f'invalid record: {exc}')
            continue
        body = match.group(2)
        for field in ('id', 'kind', 'title', 'summary'):
            if not plain_text(meta.get(field)):
                error(f'{field} must be a nonempty string')
        for field in ('projects', 'systems'):
            if not string_list(meta.get(field)):
                error(f'{field} must be an array of nonempty strings')
        identity, kind = meta.get('id'), meta.get('kind')
        if isinstance(identity, str):
            if not re.fullmatch(r'[A-Za-z0-9_-]+', identity):
                error('id must contain only ASCII letters, digits, hyphens and underscores')
            if identity in ids:
                error(f'duplicate id {identity} (also {ids[identity]["path"]})')
        if not isinstance(kind, str) or kind not in SECTIONS:
            error('unknown kind')
            continue
        rec = dict(path=path, metadata=meta, body=body, text=text, sha256=hashlib.sha256(data).hexdigest())
        records.append(rec)
        if isinstance(identity, str):
            ids[identity] = rec
        sec = sections(body)
        required = list(SECTIONS[kind])
        expected = {'project': 'projects/', 'person': 'people/', 'task': 'tasks/', 'system': 'wiki/systems/', 'knowledge': 'wiki/', 'source': 'sources/'}
        if kind in expected and not path.startswith(expected[kind]):
            error(f'{kind} must be in {expected[kind]}')
        for field in ('due', 'event_date', 'verified_on'):
            if field in meta and not (field == 'verified_on' and meta[field] is None) and not valid_date(meta[field]):
                error(f'{field} must be a real YYYY-MM-DD date')
        if 'assignee' in meta and not plain_text(meta['assignee']):
            error('assignee must be a nonempty person ID')
        if kind in ('project', 'person', 'system') and not string_list(meta.get('aliases')):
            error('aliases must be an array of strings')
        if kind == 'task' and meta.get('status') not in ('todo', 'in_progress', 'blocked', 'done', 'cancelled'):
            error('invalid status')
        if kind == 'knowledge':
            subtype = meta.get('knowledge_type')
            if subtype not in ('concept', 'how-to', 'decision'):
                error('invalid knowledge_type')
            if path.startswith('wiki/systems/'):
                error('knowledge cannot be in wiki/systems/')
            if subtype == 'how-to':
                required.append('Environment')
                if not path.startswith('wiki/how-to/'):
                    error('how-to must be in wiki/how-to/')
                if 'verified_on' not in meta:
                    error('verified_on is required (date or null)')
                if 'system_version' not in meta or (meta['system_version'] is not None and not plain_text(meta['system_version'])):
                    error('system_version is required (string or null)')
            if subtype == 'decision':
                if not path.startswith('wiki/decisions/'):
                    error('decision must be in wiki/decisions/')
                if meta.get('decision_status') not in ('accepted', 'superseded'):
                    error('invalid decision_status')
                if meta.get('decision_status') == 'superseded' and not plain_text(meta.get('superseded_by')):
                    error('superseded_by must be a decision ID')
                if meta.get('decision_status') == 'accepted' and 'superseded_by' in meta:
                    error('accepted decision cannot have superseded_by')
        if kind == 'source':
            subtype = meta.get('source_type')
            folder = 'sources/meetings/' if subtype == 'meeting' else 'sources/notes/'
            if subtype not in ('meeting', 'note') or not path.startswith(folder):
                error('source_type must match sources/meetings/ or sources/notes/')
            if not valid_date(meta.get('event_date')):
                error('event_date is required and must be a real date')
            if not plain_text(meta.get('origin')):
                error('origin must be a nonempty string')
            if not re.search(r'^ {0,3}(`{3,}|~{3,})[^\n]*\n[\s\S]+?\n {0,3}\1\s*$', sec.get('Original', ''), re.M):
                error('Original must contain original material in a fenced block')
        if kind == 'redirect':
            if not plain_text(meta.get('target')):
                error('target must be a canonical record ID')
            for field in ('status', 'decision_status', 'superseded_by'):
                if field in meta:
                    error(f'redirect cannot contain {field}')
        for section in required:
            if not sec.get(section, '').strip():
                error(f'missing or empty section: {section}')

    by_path = {r['path']: r for r in records}
    def resolve_link(rec, destination):
        parts = urlsplit(destination)
        if parts.scheme in ('http', 'https', 'mailto'):
            return None
        if parts.scheme or parts.netloc or unquote(parts.path).startswith(('/', '\\')) or '\\' in unquote(parts.path):
            raise ValueError(f'forbidden absolute or unsupported link: {destination}')
        lexical = root / rec['path'] if not parts.path else (root / rec['path']).parent / unquote(parts.path)
        target = lexical.resolve()
        if not target.is_relative_to(root):
            raise ValueError(f'link escapes root: {destination}')
        # Inspect original components before resolve() erases symlinks.
        if any(p.is_symlink() for p in (lexical, *lexical.parents) if p != root and root in p.parents):
            raise ValueError(f'symlink link forbidden: {destination}')
        if not target.is_file():
            raise ValueError(f'broken link: {destination}')
        rel = target.relative_to(root).as_posix()
        if parts.fragment:
            target_body = by_path[rel]['body'] if rel in by_path else target.read_text(encoding='utf-8')
            if unquote(parts.fragment) not in anchors(target_body):
                raise ValueError(f'missing anchor: {destination}')
        return rel

    all_links = {}
    for rec in records:
        path, meta = rec['path'], rec['metadata']
        resolved = set()
        for destination in links(rec['body']):
            try:
                target = resolve_link(rec, destination)
                if target:
                    resolved.add(target)
            except (ValueError, OSError, UnicodeError, RuntimeError) as exc:
                errors.append(f'{path}: {exc}')
        all_links[path] = resolved
        for field, expected in (('projects', 'project'), ('systems', 'system'), ('assignee', 'person')):
            values = meta.get(field, []) if field != 'assignee' else [meta[field]] if field in meta else []
            if not isinstance(values, list):
                continue
            for value in values:
                if not isinstance(value, str) or value not in ids or ids[value]['metadata']['kind'] != expected:
                    errors.append(f'{path}: {field} refers to unknown {expected}: {value!r}')
        if 'Sources' in SECTIONS[meta['kind']]:
            source_paths = set()
            for destination in links(sections(rec['body']).get('Sources', ''), rec['body']):
                try:
                    source_paths.add(resolve_link(rec, destination))
                except (ValueError, OSError, UnicodeError, RuntimeError):
                    pass
            if not any(p in by_path and by_path[p]['metadata']['kind'] == 'source' for p in source_paths):
                errors.append(f'{path}: Sources must link to a source record')

    for rec in records:
        path, meta = rec['path'], rec['metadata']
        field = 'target' if meta['kind'] == 'redirect' else 'superseded_by'
        value = meta.get(field)
        if value is None:
            continue
        target = ids.get(value) if isinstance(value, str) else None
        if not target or target is rec:
            errors.append(f'{path}: invalid {field} reference')
            continue
        if field == 'target':
            if target['metadata']['kind'] == 'redirect':
                errors.append(f'{path}: redirect chains and cycles forbidden')
            section_links = links(sections(rec['body']).get('Redirect', ''), rec['body'])
            linked = []
            for dest in section_links:
                try:
                    linked.append(resolve_link(rec, dest))
                except (ValueError, OSError, UnicodeError, RuntimeError):
                    pass
            if target['path'] not in linked:
                errors.append(f'{path}: Redirect must link to target')
        else:
            if target['metadata'].get('knowledge_type') != 'decision':
                errors.append(f'{path}: superseded_by must refer to a decision')
            if path not in all_links[target['path']]:
                errors.append(f'{path}: replacement decision must link back to old decision')
            seen, cursor = {path}, target
            while cursor:
                ident = cursor['path']
                if ident in seen:
                    errors.append(f'{path}: decision replacement cycle')
                    break
                seen.add(ident)
                next_id = cursor['metadata'].get('superseded_by')
                cursor = ids.get(next_id) if isinstance(next_id, str) else None
        if target['path'] not in all_links[path]:
            errors.append(f'{path}: {field} requires a Markdown link to {value}')
    return records, errors
