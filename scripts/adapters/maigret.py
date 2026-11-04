import json
import re
from evidence import add_mentions, parse_accounts, reported_account

NAME, KIND = 'maigret', 'username'


def arguments(item):
    return [item['value'], '--timeout', '10', '--no-recursion', '--no-color', '--no-progressbar',
            '--json', 'simple', '--folderoutput', '.']


def report_name(item):
    return f"report_{item['value']}_simple.json"


def parse(data, scan, content):
    if scan.get('structured_output'):
        report = json.loads(content)
        if not isinstance(report, dict):
            raise ValueError('Expected a Maigret simple JSON report')
        for site, result in report.items():
            status = result['status']
            if status['status'].lower() != 'claimed':
                continue
            observation = reported_account(data, scan, site, status['url'])
            if observation is None:
                continue
            fields = status.get('ids') or {}
            if not isinstance(fields, dict):
                raise ValueError('Expected a Maigret profile field mapping')
            observation['fields'].update(fields)
            for key, value in fields.items():
                if isinstance(value, str):
                    add_mentions(data, scan, f"{key}: {re.sub(r'https?://\S+', '', value)}")
        return
    target = next(i for i in data['identifiers'] if i['id'] == scan['target'])
    parse_accounts(data, scan, target['type'], target['value'], content)
