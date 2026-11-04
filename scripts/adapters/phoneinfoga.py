from evidence import parse_output_mentions

NAME, KIND = 'phoneinfoga', 'phone'


def arguments(item):
    return ['scan', '-n', item['value']]


def parse(data, scan, content):
    parse_output_mentions(data, scan, content, handles=False)
