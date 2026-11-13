import re

from evidence import HOLEHE, parse_output_mentions, record_evidence

NAME, KIND = 'holehe', 'email'
PARSER_VERSION = 3
DETAILS = (('FullName ', 'reported_name'), ('Date, time of the creation ', 'account_created'))


def arguments(item):
    return [item['value']]


def parse(data, scan, content):
    parse_output_mentions(data, scan, content, handles=False)
    statuses = {'+': 'reported', '-': 'not reported', 'x': 'rate limited', '!': 'error'}
    scan['checks'] = []
    for line_number, line in enumerate(content.split('\n'), 1):
        if match := HOLEHE.match(line):
            status, site, detail = match.groups()
            check = {'site': site, 'status': statuses[status.lower()]}
            if detail:
                check['detail'] = detail
            scan['checks'].append(check)
            record_evidence(data, scan, 'check', match.group(0), line=line_number)
            if status != '+' or not detail:
                continue
            # Holehe appends recovery hints to a hit: "<email> / <phone> / FullName <name> / Date, ...".
            # Hints are usually masked, so they are evidence only and never searchable identifiers.
            for part in re.split(r'(?:^|\s)/\s', detail):
                part = part.strip()
                if not part:
                    continue
                kind, value = next(((kind, part[len(prefix):]) for prefix, kind in DETAILS
                                    if part.startswith(prefix)),
                                   ('recovery_email' if '@' in part else 'recovery_phone', part))
                record_evidence(data, scan, kind, value, line=line_number, field=site)
