from evidence import add_mentions

NAME, KIND = 'ignorant', 'phone'


def arguments(item):
    code = item.get('country_code')
    return [code, item['value'][len(code):]] if code else None


def parse(data, scan, content):
    add_mentions(data, scan, content, handles=False)
