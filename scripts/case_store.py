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


def add_intake(case, intake):
    if not isinstance(intake, dict) or not isinstance(intake.get('people'), list) or not intake['people']:
        raise ValueError('people must be a non-empty list')
    people = []
    data = load(case)
    for person in intake['people']:
        if not isinstance(person, dict) or not isinstance(person.get('name'), str) or not person['name'].strip():
            raise ValueError('each person needs a name')
        inputs = person.get('inputs', [])
        if not isinstance(inputs, list):
            raise ValueError('inputs must be a list')
        stored = {'id': uuid.uuid4().hex, 'name': person['name'].strip(), 'inputs': []}
        for item in inputs:
            if not isinstance(item, dict) or item.get('type') not in ('username', 'email', 'phone', 'profile'):
                raise ValueError('unsupported input type')
            value = item.get('value')
            if not isinstance(value, str) or not value.strip() or '\n' in value or '\r' in value:
                raise ValueError('input value must be a non-empty single line')
            value = value.strip()
            if item['type'] == 'username' and not re.fullmatch(r'[A-Za-z0-9_.-]+', value):
                raise ValueError('username must not include @ or spaces')
            if item['type'] == 'phone' and not re.fullmatch(r'\+[0-9]{7,15}', value):
                raise ValueError('phone must include country code and digits only')
            if item['type'] == 'email' and not EMAIL.fullmatch(value):
                raise ValueError('invalid email')
            if item['type'] == 'profile':
                parsed = urlsplit(value)
                if parsed.scheme not in ('http', 'https') or not parsed.hostname:
                    raise ValueError('profile must be an HTTP(S) URL')
            entry = {'type': item['type'], 'value': value,
                     'identifier_id': ensure_identifier(data, item['type'], value)}
            for key in ('source', 'notes', 'country_code'):
                if key in item:
                    if not isinstance(item[key], str) or '\n' in item[key] or '\r' in item[key]:
                        raise ValueError(f'{key} must be a single line')
                    entry[key] = item[key]
            if 'country_code' in entry and (item['type'] != 'phone' or not re.fullmatch(r'\+[0-9]{1,3}', entry['country_code']) or not value.startswith(entry['country_code']) or value == entry['country_code']):
                raise ValueError('country_code must be a prefix of the phone number')
            stored['inputs'].append(entry)
        people.append(stored)
    relationships = []
    supplied_relationships = intake.get('relationships', [])
    if not isinstance(supplied_relationships, list):
        raise ValueError('relationships must be a list')
    for rel in supplied_relationships:
        if not isinstance(rel, dict) or type(rel.get('from')) is not int or type(rel.get('to')) is not int or not 0 <= rel['from'] < len(people) or not 0 <= rel['to'] < len(people) or not isinstance(rel.get('label'), str) or not rel['label'].strip():
            raise ValueError('invalid person relationship')
        relationships.append({'from': people[rel['from']]['id'], 'to': people[rel['to']]['id'],
                              'label': rel['label'].strip(), 'source': 'user supplied'})
    data['people'] = people
    data['person_relationships'] = relationships
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
