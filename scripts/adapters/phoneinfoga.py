from evidence import add_mentions

NAME, KIND = 'phoneinfoga', 'phone'


def arguments(item):
    return ['scan', '-n', item['value']]


def parse(data, scan, content):
    add_mentions(data, scan, content, handles=False)
