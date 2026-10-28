#!/usr/bin/env python3
"""Persist case data and retain the evidence behind reported accounts."""
import json
import os
import re
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ANSI = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')
FOUND = re.compile(r'^\s*\[\+\]\s*([^:]+):\s*(https?://\S+)', re.I)
EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
USERNAME = re.compile(r'\busername["\s]*[:=]\s*["\']?([A-Za-z0-9_.-]+)', re.I)
MENTION = re.compile(r'(?<![A-Za-z0-9._%+-])@([A-Za-z0-9_.-]+)')
SEARCH = re.compile(r'^\s*\[\*\]\s*Checking\s+(username|[A-Za-z0-9_]+_id)\s+(.+?)\s+on:\s*$', re.I)
FIELD = re.compile(r'^\s*[├└]─([A-Za-z0-9_]+):\s*(.*)$')
HOLEHE = re.compile(r'^\s*\[([+x!\-])\]\s+([A-Za-z0-9.-]+\.[A-Za-z]{2,})\s*$', re.I)


def load(case):
    path = case / 'case.json'
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    return {'id': case.name, 'created_at': datetime.now(timezone.utc).isoformat(),
            'identifiers': [], 'accounts': [], 'scans': [], 'relationships': []}


def save(case, data):
    case.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.case-', suffix='.tmp', dir=case)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
        os.replace(tmp, case / 'case.json')
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def ensure_identifier(data, kind, value):
    for item in data['identifiers']:
        if item['type'] == kind and item['value'] == value:
            return item['id']
    identifier = {'id': uuid.uuid4().hex, 'type': kind, 'value': value}
    data['identifiers'].append(identifier)
    return identifier['id']


def add_identifier(case, kind, value):
    if not value:
        return
    data = load(case)
    ensure_identifier(data, kind, value)
    save(case, data)


def add_scan(case, kind, value, tool, filename, status):
    if Path(filename).name != filename or not (case / filename).is_file():
        raise ValueError('Scan output must be a file in the case directory')
    data = load(case)
    target = ensure_identifier(data, kind, value)
    scan = {'id': uuid.uuid4().hex, 'target': target, 'tool': tool,
            'output': filename, 'status': 'completed' if status == 0 else 'failed',
            'created_at': datetime.now(timezone.utc).isoformat()}
    data['scans'].append(scan)
    if status == 0:
        content = ANSI.sub('', (case / filename).read_text(encoding='utf-8', errors='replace'))
        if tool in ('sherlock', 'maigret'):
            parse_accounts(data, scan, kind, value, content)
        else:
            add_mentions(data, scan, content, handles=False)
            if tool == 'holehe':
                statuses = {'+': 'reported', '-': 'not reported', 'x': 'rate limited', '!': 'error'}
                scan['checks'] = [{'site': match.group(2), 'status': statuses[match.group(1).lower()]}
                                  for line in content.splitlines() if (match := HOLEHE.match(line))]
    save(case, data)


def add_mentions(data, scan, content, handles=True):
    for kind, values in (('email', EMAIL.findall(content)),
                         ('username', USERNAME.findall(content) + (MENTION.findall(content) if handles else []))):
        for value in sorted(set(values)):
            identifier = ensure_identifier(data, kind, value)
            if identifier != scan['target'] and not any(
                    r['source'] == scan['id'] and r['target'] == identifier for r in data['relationships']):
                data['relationships'].append({'source': scan['id'], 'target': identifier,
                                              'label': 'mentioned in output', 'certainty': 'lead'})


def parse_accounts(data, scan, original_kind, original_value, content):
    contexts = {(original_kind, original_value): scan}
    current_scan = scan
    observation = None
    block = []

    def finish_block():
        if block:
            add_mentions(data, current_scan, '\n'.join(block))

    for line in content.splitlines():
        search = SEARCH.match(line)
        if search:
            finish_block()
            block = []
            observation = None
            search_kind, search_value = search.groups()
            search_kind = search_kind.lower()
            key = (search_kind, search_value)
            if key not in contexts:
                contexts[key] = {'id': uuid.uuid4().hex,
                                 'target': ensure_identifier(data, search_kind, search_value),
                                 'tool': scan['tool'], 'output': scan['output'],
                                 'status': scan['status'], 'created_at': scan['created_at'],
                                 'scope': 'recursive', 'parent_scan': scan['id']}
                data['scans'].append(contexts[key])
            current_scan = contexts[key]
            continue
        match = FOUND.match(line)
        if match:
            finish_block()
            block = []
            observation = None
            site, url = match.groups()
            url = url.rstrip('.,;')
            try:
                parsed = urlsplit(url)
                hostname = parsed.hostname or ''
            except ValueError:
                continue
            search_value = next(i['value'] for i in data['identifiers'] if i['id'] == current_scan['target'])
            is_profile_host = len(search_value) > 1 and search_value.lower() in hostname.lower().split('.')[:-2]
            if (parsed.scheme not in ('http', 'https') or not parsed.netloc
                    or (parsed.path in ('', '/') and not parsed.query and not parsed.fragment and not is_profile_host)):
                continue
            account = next((item for item in data['accounts'] if item['url'] == url), None)
            if account is None:
                account = {'id': uuid.uuid4().hex, 'site': site.strip(), 'url': url}
                data['accounts'].append(account)
            observations = account.setdefault('observations', [])
            observation = next((item for item in observations if item['scan_id'] == current_scan['id']), None)
            if observation is None:
                observation = {'scan_id': current_scan['id'], 'fields': {}}
                observations.append(observation)
                data['relationships'].append({'source': current_scan['id'], 'target': account['id'],
                                              'label': 'reported account', 'certainty': 'lead'})
            continue
        if re.match(r'^\s*\[(?:-|!|\*)\]', line):
            finish_block()
            block = []
            observation = None
            continue
        if observation is not None:
            field = FIELD.match(line)
            if field:
                observation['fields'][field.group(1)] = field.group(2).strip()
            # Do not treat profile URLs or image URLs as username mentions.
            block.append(re.sub(r'https?://\S+', '', line))
    finish_block()


if __name__ == '__main__':
    action, directory, *args = sys.argv[1:]
    case = Path(directory)
    if action == 'identifier':
        add_identifier(case, *args)
    elif action == 'scan':
        add_scan(case, *args[:-1], int(args[-1]))
    else:
        raise SystemExit('Unknown case action')
