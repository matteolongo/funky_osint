import hashlib
import json
import re
import uuid
from bisect import bisect_left
from urllib.parse import urlsplit

ANSI = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')
# International format only; a number followed by a mask (*) is partial and not a lead.
PHONE = re.compile(r'(?<![\w+*])\+[1-9](?:[ ().-]{0,2}[0-9]){6,14}(?!\s?[0-9*])')
FOUND = re.compile(r'^\s*\[\+\]\s*([^:]+):\s*(https?://\S+)', re.I)
# A preceding * marks a masked address; its visible tail is not an address.
EMAIL = re.compile(r'(?<![A-Za-z0-9._%+*-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
USERNAME = re.compile(r'\busername["\s]*[:=]\s*["\']?([A-Za-z0-9_.-]+)', re.I)
MENTION = re.compile(r'(?<![A-Za-z0-9._%+-])@([A-Za-z0-9_.-]+)')
SEARCH = re.compile(r'^\s*\[\*\]\s*Checking\s+(username|[A-Za-z0-9_]+_id)\s+(.+?)\s+on:\s*$', re.I)
FIELD = re.compile(r'^\s*[├└]─([A-Za-z0-9_]+):\s*(.*)$')
HOLEHE = re.compile(r'^\s*\[([+x!\-])\]\s+([A-Za-z0-9.-]+\.[A-Za-z]{2,})(?:\s+(.*\S))?\s*$', re.I)


def ensure_identifier(data, kind, value):
    for item in data['identifiers']:
        if item['type'] == kind and item['value'] == value:
            return item['id']
    identifier = {'id': uuid.uuid4().hex, 'type': kind, 'value': value}
    data['identifiers'].append(identifier)
    return identifier['id']


def comparison_key(kind, value):
    if kind == 'email':
        local, separator, domain = value.rpartition('@')
        return local + separator + domain.lower() if separator else value
    if kind in ('account', 'profile'):
        authority = re.match(r'https?://(?:[^/?#]*@)?(\[[^\]]+\]|[^:/?#]+)', value, re.I)
        if authority:
            start, end = authority.span(1)
            return value[:start] + value[start:end].lower() + value[end:]
    return value


def record_evidence(data, scan, kind, value, **location):
    artifact = scan.get('artifact')
    if artifact is None:
        return
    attempt_id = scan.get('parent_scan', scan['id'])
    identity = [attempt_id, artifact, kind, value, location.get('line'), location.get('field')]
    if 'end_line' in location:
        identity.append(location['end_line'])
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    item = {'id': digest, 'scan_id': scan['id'], 'attempt_id': attempt_id, **artifact,
            'kind': kind, 'value': value, **location}
    if isinstance(value, str):
        item['comparison_key'] = comparison_key(kind, value)
    data.setdefault('evidence', []).append(item)


def add_mentions(data, scan, content, handles=True, first_line=None, fields=None, **location):
    newlines = [match.start() for match in re.finditer('\n', content)] if first_line is not None else []
    patterns = [('email', EMAIL), ('username', USERNAME), ('phone', PHONE)]
    if handles:
        patterns.append(('username', MENTION))
    seen = set()
    for kind, pattern in patterns:
        for match in pattern.finditer(content):
            value = match.group(match.lastindex or 0)
            if kind == 'phone':
                value = '+' + re.sub(r'\D', '', value)
            source = location.copy()
            if first_line is not None:
                start = bisect_left(newlines, match.start())
                end = bisect_left(newlines, match.end() - 1)
                source['line'] = first_line + start
                if start != end:
                    source['end_line'] = first_line + end
                if fields and fields[start]:
                    source['field'] = fields[start]
            key = (kind, value, source.get('line'), source.get('end_line'), source.get('field'))
            if key in seen:
                continue
            seen.add(key)
            identifier = ensure_identifier(data, kind, value)
            if identifier != scan['target']:
                record_evidence(data, scan, kind, value, identifier_id=identifier, **source)
            if identifier != scan['target'] and not any(
                    r['source'] == scan['id'] and r['target'] == identifier for r in data['relationships']):
                data['relationships'].append({'source': scan['id'], 'target': identifier,
                                              'label': 'mentioned in output', 'certainty': 'lead'})


def reported_account(data, scan, site, url, **location):
    if not isinstance(url, str) or any(c.isspace() for c in url):
        return None
    original = url
    url = url.rstrip('.,;') if 'field' not in location else url
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname or ''
    except ValueError:
        return None
    value = next(i['value'] for i in data['identifiers'] if i['id'] == scan['target'])
    profile_host = len(value) > 1 and value.lower() in hostname.lower().split('.')[:-2]
    if (parsed.scheme not in ('http', 'https') or not parsed.netloc
            or (parsed.path in ('', '/') and not parsed.query and not parsed.fragment and not profile_host)):
        return None
    key = comparison_key('account', url)
    account = next((a for a in data['accounts'] if comparison_key('account', a['url']) == key), None)
    if account is None:
        account = {'id': uuid.uuid4().hex, 'site': site.strip(), 'url': url}
        data['accounts'].append(account)
    observations = account.setdefault('observations', [])
    observation = next((o for o in observations if o['scan_id'] == scan['id']), None)
    if observation is None:
        observation = {'scan_id': scan['id'], 'fields': {}}
        observations.append(observation)
        data['relationships'].append({'source': scan['id'], 'target': account['id'],
                                      'label': 'reported account', 'certainty': 'lead'})
    record_evidence(data, scan, 'account', original, account_id=account['id'], **location)
    return observation


def add_profile_field(data, scan, observation, key, value, **location):
    observation['fields'][key] = value
    account = next(a for a in data['accounts'] if any(o is observation for o in a['observations']))
    location['account_id'] = account['id']
    record_evidence(data, scan, 'profile_field', value, **location)
    if isinstance(value, str) and 'line' not in location:
        add_mentions(data, scan, f"{key}: " + re.sub(r'https?://\S+', '', value), **location)


def parse_output_mentions(data, scan, content, handles=True):
    add_mentions(data, scan, content, handles=handles, first_line=1)


def parse_accounts(data, scan, original_kind, original_value, content):
    contexts = {(original_kind, original_value): scan}
    current_scan = scan
    observation = None
    block = []
    fields = []

    def finish_block(next_line):
        if block:
            account = next(a for a in data['accounts'] if any(o is observation for o in a['observations']))
            add_mentions(data, current_scan, '\n'.join(block), first_line=next_line - len(block),
                         fields=fields, account_id=account['id'])
            block.clear()
            fields.clear()

    lines = content.split('\n')
    for line_number, line in enumerate(lines, 1):
        search = SEARCH.match(line)
        if search:
            finish_block(line_number)
            observation = None
            search_kind, search_value = search.groups()
            search_kind = search_kind.lower()
            key = (search_kind, search_value)
            if key not in contexts:
                contexts[key] = {'id': uuid.uuid5(uuid.NAMESPACE_URL, json.dumps([scan['id'], key])).hex,
                                 'target': ensure_identifier(data, search_kind, search_value),
                                 'tool': scan['tool'], 'output': scan['output'],
                                 'status': scan['status'], 'created_at': scan['created_at'],
                                 'scope': 'recursive', 'parent_scan': scan['id']}
                if 'artifact' in scan:
                    contexts[key]['artifact'] = scan['artifact']
                data['scans'].append(contexts[key])
            current_scan = contexts[key]
            continue
        match = FOUND.match(line)
        if match:
            finish_block(line_number)
            site, url = match.groups()
            observation = reported_account(data, current_scan, site, url, line=line_number)
            continue
        if re.match(r'^\s*\[(?:-|!|\*)\]', line):
            finish_block(line_number)
            observation = None
            continue
        if observation is not None:
            field = FIELD.match(line)
            if field:
                key, value = field.groups()
                add_profile_field(data, current_scan, observation, key, value,
                                  line=line_number, field=key)
            fields.append(field.group(1) if field else None)
            block.append(re.sub(r'https?://\S+', '', line))
    finish_block(len(lines) + 1)
