#!/usr/bin/env python3
"""Build pinned tools and keep each Python tool's dependencies isolated."""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml


def install(config):
    tools = config.get('tools', [])
    manifest = {}
    for tool in tools:
        if not tool.get('enabled', True):
            continue
        name, ref = tool['name'], tool['ref']
        if not re.fullmatch(r'[a-z][a-z0-9-]*', name) or not re.fullmatch(r'[0-9a-f]{40}', ref):
            raise ValueError(f'{name}: a full pinned commit SHA is required')
        dest = Path(tool['dest'])
        build = tool.get('build') or {}
        dependencies = build.get('apt_deps', [])
        if os.environ.get('INSTALL_SKIP_APT') != '1' and dependencies:
            subprocess.run(['apt-get', 'update'], check=True)
            subprocess.run(['apt-get', 'install', '-y', '--no-install-recommends', *dependencies], check=True)
        print(f'[install-tools] Installing {name} at {ref}', flush=True)
        dest.mkdir(parents=True, exist_ok=True)
        if not (dest / '.git').exists():
            subprocess.run(['git', 'init', str(dest)], check=True)
            subprocess.run(['git', '-C', str(dest), 'remote', 'add', 'origin', tool['repo']], check=True)
        subprocess.run(['git', '-C', str(dest), 'fetch', '--depth', '1', 'origin', ref], check=True)
        subprocess.run(['git', '-C', str(dest), 'checkout', '--detach', ref], check=True)
        actual = subprocess.check_output(['git', '-C', str(dest), 'rev-parse', 'HEAD'], text=True).strip()
        if actual != ref:
            raise ValueError(f'{name}: checkout does not match the pinned revision')
        env = dict(os.environ)
        env.pop('PIP_BREAK_SYSTEM_PACKAGES', None)
        venv = Path('/opt/tools') / name if tool.get('python_env') else None
        if venv:
            subprocess.run([sys.executable, '-m', 'venv', str(venv)], check=True)
            env['PATH'] = str(venv / 'bin') + os.pathsep + env['PATH']
            env['VIRTUAL_ENV'] = str(venv)
        for command in [*build.get('pre_cmds', []), *build.get('cmds', [])]:
            subprocess.run(['bash', '-eo', 'pipefail', '-c', command], cwd=dest, env=env, check=True)
        binary = tool['check_bin']
        if venv:
            executable = venv / 'bin' / binary
            if not executable.is_file():
                raise ValueError(f'{name}: installation did not produce {binary}')
            link = Path('/usr/local/bin') / binary
            if link.is_symlink():
                link.unlink()
            link.symlink_to(executable)
            subprocess.run([str(venv / 'bin/python'), '-m', 'pip', 'check'], check=True)
        elif not shutil.which(binary):
            raise ValueError(f'{name}: installation did not produce {binary}')
        manifest[name] = {'revision': actual, 'python_environment': str(venv) if venv else None}
        if venv:
            manifest[name]['packages'] = subprocess.check_output(
                [str(venv / 'bin/python'), '-m', 'pip', 'freeze', '--all'], text=True).splitlines()
    Path('/tools').mkdir(exist_ok=True)
    Path('/tools/versions.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    with open('/repos.yml', encoding='utf-8') as file:
        install(yaml.safe_load(file))
