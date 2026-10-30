from evidence import HOLEHE, add_mentions

NAME, KIND = 'holehe', 'email'


def arguments(item):
    return [item['value']]


def parse(data, scan, content):
    add_mentions(data, scan, content, handles=False)
    statuses = {'+': 'reported', '-': 'not reported', 'x': 'rate limited', '!': 'error'}
    scan['checks'] = [{'site': match.group(2), 'status': statuses[match.group(1).lower()]}
                      for line in content.splitlines() if (match := HOLEHE.match(line))]
