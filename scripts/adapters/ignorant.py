from evidence import HOLEHE, parse_output_mentions, record_evidence

NAME, KIND = 'ignorant', 'phone'
PARSER_VERSION = 3


def arguments(item):
    # Ignorant's site modules look the calling code up without its leading plus.
    code = item.get('country_code')
    return [code.lstrip('+'), item['value'][len(code):]] if code else None


def parse(data, scan, content):
    parse_output_mentions(data, scan, content, handles=False)
    statuses = {'+': 'reported', '-': 'not reported', 'x': 'rate limited'}
    scan['checks'] = []
    for line_number, line in enumerate(content.split('\n'), 1):
        match = HOLEHE.match(line)
        if match and match.group(1).lower() in statuses:
            scan['checks'].append({'site': match.group(2), 'status': statuses[match.group(1).lower()]})
            record_evidence(data, scan, 'check', match.group(0), line=line_number)
