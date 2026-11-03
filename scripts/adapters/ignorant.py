from evidence import parse_output_mentions

NAME, KIND = 'ignorant', 'phone'


def arguments(item):
    code = item.get('country_code')
    return [code, item['value'][len(code):]] if code else None


def parse(data, scan, content):
    parse_output_mentions(data, scan, content, handles=False)
