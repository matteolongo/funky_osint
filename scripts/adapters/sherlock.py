from evidence import parse_accounts

NAME, KIND = 'sherlock', 'username'


def arguments(item):
    return [item['value']]


def parse(data, scan, content):
    target = next(i for i in data['identifiers'] if i['id'] == scan['target'])
    parse_accounts(data, scan, target['type'], target['value'], content)
