#!/usr/bin/env python3
"""Persist case data and retain the evidence behind reported accounts."""
import json
import os
import re
import sys
import tempfile
import uuid
import copy
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from evidence import ANSI, EMAIL, ensure_identifier, parse_accounts


@contextmanager
def case_lock(case):
    """OS locks release after a crash; never delete the lock file while in use."""
    case.mkdir(parents=True, exist_ok=True)
    with open(case / '.writer.lock', 'a+b') as file:
        if os.fstat(file.fileno()).st_size == 0:
            file.write(b'0')
            file.flush()
        file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ValueError('This case is already being modified by another runner') from error
        try:
            yield
        finally:
            file.seek(0)
            if os.name == 'nt':
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(file.fileno(), fcntl.LOCK_UN)


def now():
    return datetime.now(timezone.utc).isoformat()


def validate_input(item):
    if not isinstance(item, dict) or item.get('type') not in ('username', 'email', 'phone', 'profile'):
        raise ValueError('unsupported input type')
    value = item.get('value')
    if not isinstance(value, str) or not value.strip() or '\n' in value or '\r' in value or '\x00' in value:
        raise ValueError('input value must be a non-empty single line')
    value = value.strip()
    if value.startswith('-'):
        raise ValueError('input must not start with a command option')
    kind = item['type']
    if kind == 'username' and not re.fullmatch(r'[A-Za-z0-9_.-]+', value):
        raise ValueError('username must not include @ or spaces')
    if kind == 'phone' and not re.fullmatch(r'\+[0-9]{7,15}', value):
        raise ValueError('phone must include country code and digits only')
    if kind == 'email' and not EMAIL.fullmatch(value):
        raise ValueError('invalid email')
    if kind == 'profile':
        parsed = urlsplit(value)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            raise ValueError('profile must be an HTTP(S) URL')
    result = {'type': kind, 'value': value}
    for key in ('source', 'notes', 'country_code'):
        if key in item:
            if not isinstance(item[key], str) or any(c in item[key] for c in ('\n', '\r', '\x00')):
                raise ValueError(f'{key} must be a single line')
            result[key] = item[key]
    code = result.get('country_code')
    if code is not None and (kind != 'phone' or not re.fullmatch(r'\+[0-9]{1,3}', code) or not value.startswith(code) or value == code):
        raise ValueError('country_code must be a prefix of the phone number')
    return result


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


def add_identifier(case, kind, value):
    value = validate_input({'type': kind, 'value': value})['value']
    data = load(case)
    identifier = ensure_identifier(data, kind, value)
    next(i for i in data['identifiers'] if i['id'] == identifier)['supplied'] = True
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
            entry = validate_input(item)
            entry['identifier_id'] = ensure_identifier(data, entry['type'], entry['value'])
            next(i for i in data['identifiers'] if i['id'] == entry['identifier_id'])['supplied'] = True
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
    save(case, data)
    if status == 0:
        from adapters import TOOLS
        parse_scan(case, scan['id'], TOOLS[tool])


def parse_scan(case, scan_id, adapter):
    original = load(case)
    data = copy.deepcopy(original)
    scan = next(s for s in data['scans'] if s['id'] == scan_id)
    # Replace only this attempt's derived results; other attempts keep their evidence.
    derived = {scan_id} | {s['id'] for s in data['scans'] if s.get('parent_scan') == scan_id}
    old_identifiers = {r['target'] for r in data['relationships'] if r['source'] in derived}
    old_identifiers.update(s['target'] for s in data['scans'] if s['id'] in derived and s['id'] != scan_id)
    data['scans'] = [s for s in data['scans'] if s['id'] == scan_id or s['id'] not in derived]
    data['relationships'] = [r for r in data['relationships'] if r['source'] not in derived]
    for account in data['accounts']:
        account['observations'] = [o for o in account.get('observations', []) if o['scan_id'] not in derived]
    scan.pop('checks', None)
    try:
        filename = scan.get('structured_output', scan['output'])
        path = (case / filename).resolve()
        if Path(filename).name != filename or path.parent != case.resolve():
            raise ValueError('invalid evidence path')
        content = ANSI.sub('', path.read_text(encoding='utf-8', errors='replace'))
        adapter.parse(data, scan, content)
        data['accounts'] = [a for a in data['accounts'] if a.get('observations')]
        retained = {s['target'] for s in data['scans']} | {r['target'] for r in data['relationships']}
        retained.update(item['identifier_id'] for person in data.get('people', []) for item in person['inputs'])
        data['identifiers'] = [i for i in data['identifiers']
                               if i['id'] not in old_identifiers or i['id'] in retained or i.get('supplied')]
        scan['parse_status'] = 'completed'
        scan.pop('parse_error', None)
    except Exception as error:
        data = original
        scan = next(s for s in data['scans'] if s['id'] == scan_id)
        scan['parse_status'] = 'failed'
        scan['parse_error'] = f'{type(error).__name__}: {error}'
    scan['parser_version'] = adapter.parser_version
    scan['parsed_at'] = now()
    save(case, data)


def export_pivots(case):
    data = load(case)
    for kind in ('username', 'email'):
        values = sorted({i['value'] for i in data['identifiers'] if i['type'] == kind})
        (case / f'pivot_{kind}s.txt').write_text(''.join(v + '\n' for v in values), encoding='utf-8')


if __name__ == '__main__':
    action, directory, *args = sys.argv[1:]
    case = Path(directory)
    with case_lock(case):
        if action == 'identifier':
            add_identifier(case, *args)
        elif action == 'scan':
            add_scan(case, *args[:-1], int(args[-1]))
        else:
            raise SystemExit('Unknown case action')
