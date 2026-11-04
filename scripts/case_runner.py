#!/usr/bin/env python3
"""Run supported searches for a validated, user-supplied case."""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import case_store


def run_case(case, intake):
    case_store.add_intake(case, intake)
    data = case_store.load(case)
    searched = set()
    for person in data['people']:
        for item in person['inputs']:
            kind, value = item['type'], item['value']
            commands = []
            if kind == 'username':
                commands = [('maigret', [value, '--timeout', '10', '--no-recursion']), ('sherlock', [value])]
            elif kind == 'email':
                commands = [('holehe', [value])]
            elif kind == 'phone':
                commands = [('phoneinfoga', ['scan', '-n', value])]
                if item.get('country_code'):
                    code = item['country_code']
                    commands.append(('ignorant', [code, value[len(code):]]))
            for tool, args in commands:
                key = (kind, value, tool)
                if key in searched:
                    continue
                searched.add(key)
                executable = shutil.which(tool)
                with tempfile.NamedTemporaryFile(prefix=tool + '_', suffix='.txt', dir=case, delete=False) as output:
                    path = Path(output.name)
                    if not executable:
                        output.write(f'{tool} is not available\n'.encode())
                        status = 127
                    else:
                        try:
                            status = subprocess.run([executable, *args], stdout=output, stderr=subprocess.STDOUT, check=False).returncode
                        except OSError as error:
                            output.write(f'{tool} could not start: {error}\n'.encode())
                            status = 127
                case_store.add_scan(case, kind, value, tool, path.name, status)
                print(f'{tool}: {value}: {"completed" if status == 0 else "failed"} ({path.name})', flush=True)


if __name__ == '__main__':
    try:
        with open(sys.argv[2], encoding='utf-8-sig') as file:
            intake = json.load(file)
        run_case(Path(sys.argv[1]), intake)
    except (OSError, ValueError, IndexError) as error:
        raise SystemExit(f'Cannot run case: {error}')
