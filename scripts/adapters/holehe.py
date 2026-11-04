from evidence import HOLEHE, parse_output_mentions, record_evidence

NAME, KIND = 'holehe', 'email'


def arguments(item):
    return [item['value']]


def parse(data, scan, content):
    parse_output_mentions(data, scan, content, handles=False)
    statuses = {'+': 'reported', '-': 'not reported', 'x': 'rate limited', '!': 'error'}
    scan['checks'] = []
    for line_number, line in enumerate(content.split('\n'), 1):
        if match := HOLEHE.match(line):
            scan['checks'].append({'site': match.group(2), 'status': statuses[match.group(1).lower()]})
            record_evidence(data, scan, 'check', match.group(0), line=line_number)
