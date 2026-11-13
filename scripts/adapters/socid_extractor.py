import json
import re
from urllib.parse import urlsplit

from evidence import add_mentions, add_profile_field, ensure_identifier, reported_account

NAME, KIND = 'socid-extractor', 'profile'
PARSER_VERSION = 1
HANDLE = re.compile(r'[A-Za-z0-9_.-]+')
# Path prefixes that precede the handle on common sites (/in/<handle>, /user/<handle>).
PREFIXES = ('in', 'u', 'user', 'users', 'profile', 'people')


def arguments(item):
    return ['--url', item['value'], '--json']


def results(content):
    """Warnings may precede the JSON list because stderr shares the evidence file."""
    decoder = json.JSONDecoder()
    for start in re.finditer(r'^\[', content, re.M):
        try:
            value, _ = decoder.raw_decode(content, start.start())
        except ValueError:
            continue
        if isinstance(value, list):
            return value
    return []


def url_handle(url):
    parts = [part for part in urlsplit(url).path.split('/') if part]
    if len(parts) == 2 and parts[0].lower() in PREFIXES:
        parts = parts[1:]
    handle = parts[0].lstrip('@') if len(parts) == 1 else ''
    return handle if HANDLE.fullmatch(handle) and not handle.startswith('-') else None


def pointer(*parts):
    return ''.join('/' + str(part).replace('~', '~0').replace('/', '~1') for part in parts)


def parse(data, scan, content):
    target = next(i['value'] for i in data['identifiers'] if i['id'] == scan['target'])
    observation = account_id = None
    for index, entry in enumerate(results(content)):
        info = entry.get('info') if isinstance(entry, dict) else None
        if not isinstance(info, dict) or not info:
            continue
        if observation is None:
            observation = reported_account(data, scan, urlsplit(target).hostname or '', target,
                                           field=pointer(index, 'url'))
            if observation is not None:
                account_id = next(a['id'] for a in data['accounts']
                                  if any(o is observation for o in a['observations']))
        location = {'account_id': account_id} if account_id else {}
        for key, value in info.items():
            field = pointer(index, 'info', key)
            if observation is not None:
                add_profile_field(data, scan, observation, key, value, field=field)
            elif isinstance(value, str):
                add_mentions(data, scan, f'{key}: ' + re.sub(r'https?://\S+', '', value), field=field)
            if isinstance(value, list):
                for position, element in enumerate(value):
                    if isinstance(element, str):
                        add_mentions(data, scan, f'{key}: ' + re.sub(r'https?://\S+', '', element),
                                     field=pointer(index, 'info', key, position), **location)
            # "username: x" is already matched; site-specific keys (instagram_username) are not.
            if (isinstance(value, str) and 'username' in key.lower() and key.lower() != 'username'
                    and HANDLE.fullmatch(value)):
                add_mentions(data, scan, 'username: ' + value, handles=False, field=field, **location)
    handle = url_handle(target)
    if handle:
        # Derived from the supplied URL itself, so there is no artifact location to cite.
        identifier = ensure_identifier(data, 'username', handle)
        if not any(r['source'] == scan['id'] and r['target'] == identifier for r in data['relationships']):
            data['relationships'].append({'source': scan['id'], 'target': identifier,
                                          'label': 'handle in supplied profile URL', 'certainty': 'lead'})
