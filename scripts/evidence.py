import re
import uuid
from urllib.parse import urlsplit

ANSI = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')
FOUND = re.compile(r'^\s*\[\+\]\s*([^:]+):\s*(https?://\S+)', re.I)
EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
USERNAME = re.compile(r'\busername["\s]*[:=]\s*["\']?([A-Za-z0-9_.-]+)', re.I)
MENTION = re.compile(r'(?<![A-Za-z0-9._%+-])@([A-Za-z0-9_.-]+)')
SEARCH = re.compile(r'^\s*\[\*\]\s*Checking\s+(username|[A-Za-z0-9_]+_id)\s+(.+?)\s+on:\s*$', re.I)
FIELD = re.compile(r'^\s*[├└]─([A-Za-z0-9_]+):\s*(.*)$')
HOLEHE = re.compile(r'^\s*\[([+x!\-])\]\s+([A-Za-z0-9.-]+\.[A-Za-z]{2,})\s*$', re.I)


def ensure_identifier(data, kind, value):
    for item in data['identifiers']:
        if item['type'] == kind and item['value'] == value:
            return item['id']
    identifier = {'id': uuid.uuid4().hex, 'type': kind, 'value': value}
    data['identifiers'].append(identifier)
    return identifier['id']


def add_mentions(data, scan, content, handles=True):
    for kind, values in (('email', EMAIL.findall(content)),
                         ('username', USERNAME.findall(content) + (MENTION.findall(content) if handles else []))):
        for value in sorted(set(values)):
            identifier = ensure_identifier(data, kind, value)
            if identifier != scan['target'] and not any(
                    r['source'] == scan['id'] and r['target'] == identifier for r in data['relationships']):
                data['relationships'].append({'source': scan['id'], 'target': identifier,
                                              'label': 'mentioned in output', 'certainty': 'lead'})


def reported_account(data, scan, site, url):
    if not isinstance(url, str) or any(c.isspace() for c in url):
        return None
    url = url.rstrip('.,;')
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
    account = next((a for a in data['accounts'] if a['url'] == url), None)
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
    return observation


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
            observation = reported_account(data, current_scan, site, url)
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
