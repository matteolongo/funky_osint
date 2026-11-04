#!/usr/bin/env python3
"""Sequential, recoverable execution shared by interactive and batch searches."""
import json
import math
import os
import re
import shutil
import signal
import subprocess
import tempfile
import uuid
from pathlib import Path

import case_store as store
from adapters import TOOLS

DEFAULT_TIMEOUT = 300
MANIFEST = Path('/tools/versions.json')


def tool_version(name):
    try:
        return json.loads(MANIFEST.read_text(encoding='utf-8')).get(name, {}).get('revision', 'unknown')
    except (OSError, ValueError):
        return 'unknown'


def validate_timeout(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError('timeout must be a positive finite number of seconds')
    return value


def new_scan(data, item, tool, arguments, timeout, previous=None):
    scan_id = uuid.uuid4().hex
    scan = {'id': scan_id, 'target': store.ensure_identifier(data, item['type'], item['value']),
            'input': item, 'tool': tool.name, 'arguments': arguments, 'timeout': timeout,
            'output': f'{tool.name}_{scan_id}.txt', 'status': 'pending', 'parse_status': 'pending',
            'created_at': store.now(), 'tool_version': tool_version(tool.name)}
    if previous:
        scan['previous_attempt'] = previous['id']
    data['scans'].append(scan)
    return scan


def recover(data):
    for scan in data['scans']:
        if scan['status'] == 'running':
            identity = scan.get('process_identity')
            if identity and process_identity(identity['pid']) == identity:
                # Match boot, PID namespace and start time before killing a leftover group.
                try:
                    if os.getpgid(identity['pid']) == identity['pid']:
                        os.killpg(identity['pid'], signal.SIGKILL)
                except ProcessLookupError:
                    pass
            scan.update(status='interrupted', finished_at=store.now(),
                        error='Runner stopped before recording completion')


def process_identity(pid):
    try:
        return {'pid': pid, 'started': Path(f'/proc/{pid}/stat').read_text().rsplit(') ', 1)[1].split()[19],
                'namespace': os.readlink(f'/proc/{pid}/ns/pid'),
                'boot': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
    except (OSError, IndexError):
        return None


def finish_parsing(case, scan_id):
    data = store.load(case)
    scan = next(s for s in data['scans'] if s['id'] == scan_id)
    tool = TOOLS.get(scan['tool'])
    if tool is None:
        return
    try:
        if tool.report_name and scan.get('artifact_dir'):
            artifact_dir = case / scan['artifact_dir']
            if artifact_dir != case / 'artifacts' / scan_id or artifact_dir.resolve() != artifact_dir:
                raise ValueError('Invalid artifact directory')
            report = artifact_dir / tool.report_name(store.validate_input(scan['input']))
            if report.is_file() and report.resolve().parent == artifact_dir:
                filename = f"{tool.name}_{scan_id}.json"
                destination = case / filename
                if destination.resolve().parent != case or destination.is_symlink():
                    raise ValueError('Invalid report destination')
                if not scan.get('structured_output') or not destination.exists():
                    # Publish atomically: a crash must not expose a truncated report.
                    fd, temporary = tempfile.mkstemp(prefix='.report-', dir=case)
                    try:
                        with os.fdopen(fd, 'wb') as file:
                            file.write(report.read_bytes())
                        os.replace(temporary, destination)
                    finally:
                        if os.path.exists(temporary):
                            os.unlink(temporary)
                scan['structured_output'] = filename
                store.save(case, data)
    except (OSError, ValueError) as error:
        scan.update(parse_status='failed', parse_error=f'Cannot collect report: {error}')
        store.save(case, data)
        return
    store.parse_scan(case, scan_id, tool)


def finish_pending_parsing(case):
    for scan in store.load(case)['scans']:
        if scan['status'] not in ('pending', 'running') and scan.get('parse_status') == 'pending' and not scan.get('parent_scan'):
            finish_parsing(case, scan['id'])


def plan(data, inputs, timeout, rerun=False):
    recover(data)
    scheduled = set()
    for item in inputs:
        target = store.ensure_identifier(data, item['type'], item['value'])
        for tool in TOOLS.values():
            if tool.kind != item['type']:
                continue
            arguments = tool.arguments(item)
            if arguments is None:
                continue
            key = (target, tool.name, tuple(arguments))
            if key in scheduled:
                continue
            scheduled.add(key)
            attempts = [s for s in data['scans'] if s['target'] == target and s['tool'] == tool.name
                        and s.get('arguments') == arguments and not s.get('parent_scan')]
            previous = attempts[-1] if attempts else None
            if previous and (previous['status'] == 'pending' or
                             (previous['status'] == 'completed' and not rerun)):
                continue
            new_scan(data, item, tool, arguments, timeout, previous)


def stop_process(process):
    if os.name == 'posix':
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        # The parent may have exited while descendants ignored SIGTERM.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif process.poll() is None:
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    process.wait()


def execute_pending(case):
    data = store.load(case)
    pending = []
    for scan in data['scans']:
        if scan['status'] != 'pending':
            continue
        if not re.fullmatch(r'[0-9a-f]{32}', scan['id']):
            raise ValueError('Invalid scan id')
        if not re.fullmatch(r'[a-z][a-z0-9-]*', scan['tool']):
            raise ValueError('Invalid tool name')
        if scan['output'] != f"{scan['tool']}_{scan['id']}.txt":
            raise ValueError('Invalid pending scan output')
        artifact_dir = case / 'artifacts' / scan['id']
        if artifact_dir.resolve() != artifact_dir:
            raise ValueError('Invalid artifact directory')
        tool = TOOLS.get(scan['tool'])
        if tool:
            item = store.validate_input(scan['input'])
            target = next(i for i in data['identifiers'] if i['id'] == scan['target'])
            if item['type'] != tool.kind or (target['type'], target['value']) != (item['type'], item['value']):
                raise ValueError('Pending scan does not match its input')
            scan['arguments'] = tool.arguments(item)
            if scan['arguments'] is None:
                raise ValueError('Pending scan is missing required input')
        validate_timeout(scan['timeout'])
        pending.append(scan['id'])
    store.save(case, data)
    for scan_id in pending:
        data = store.load(case)
        scan = next(s for s in data['scans'] if s['id'] == scan_id)
        tool = TOOLS.get(scan['tool'])
        executable = shutil.which(scan['tool']) if tool else None
        scan['artifact_dir'] = f"artifacts/{scan_id}"
        artifact_dir = case / scan['artifact_dir']
        artifact_dir.mkdir(parents=True, exist_ok=True)
        scan.update(status='running', started_at=store.now(), command=[executable or scan['tool'], *scan['arguments']])
        store.save(case, data)
        print(f"{scan['tool']} running (deadline {scan['timeout']:g}s)", flush=True)
        process = None
        interrupted = None
        with open(case / scan['output'], 'xb') as output:
            try:
                if not executable:
                    scan.update(status='unavailable', exit_code=None, error='Tool is not installed or has no adapter')
                    output.write((scan['error'] + '\n').encode())
                else:
                    process = subprocess.Popen(scan['command'], cwd=artifact_dir, stdin=subprocess.DEVNULL,
                                               stdout=output, stderr=subprocess.STDOUT,
                                               env={**os.environ, 'OSINT_CASE_DIR': str(case)},
                                               start_new_session=os.name == 'posix')
                    scan['process_identity'] = process_identity(process.pid)
                    store.save(case, data)
                    code = process.wait(timeout=scan['timeout'])
                    scan.update(status='completed' if code == 0 else 'failed', exit_code=code)
                    if code:
                        scan['error'] = f'Tool exited with code {code}'
            except subprocess.TimeoutExpired:
                scan.update(status='timed_out', error='Whole-process deadline exceeded')
            except OSError as error:
                scan.update(status='failed', exit_code=None, error=str(error))
                output.write((str(error) + '\n').encode())
            except KeyboardInterrupt as error:
                scan.update(status='interrupted',
                            error='Cancelled by user or termination signal')
                interrupted = error
            finally:
                if process is not None:
                    stop_process(process)
                    scan['exit_code'] = process.returncode
                scan['finished_at'] = store.now()
                store.save(case, data)
        finish_parsing(case, scan_id)
        store.export_pivots(case)
        print(f"{scan['tool']} {scan['status']}: {scan['output']}", flush=True)
        if interrupted is not None:
            raise interrupted


def run_targets(case, inputs, timeout=DEFAULT_TIMEOUT, rerun=False):
    inputs = [store.validate_input(item) for item in inputs]
    timeout = validate_timeout(timeout)
    case = Path(case).resolve()
    with store.case_lock(case):
        data = store.load(case)
        plan(data, inputs, timeout, rerun)
        store.save(case, data)
        finish_pending_parsing(case)
        execute_pending(case)
        store.export_pivots(case)


def run_case(case, intake, timeout=DEFAULT_TIMEOUT):
    timeout = validate_timeout(timeout)
    case = Path(case).resolve()
    with store.case_lock(case):
        store.add_intake(case, intake)
        data = store.load(case)
        plan(data, [item for person in data['people'] for item in person['inputs']], timeout)
        store.save(case, data)
        finish_pending_parsing(case)
        execute_pending(case)
        store.export_pivots(case)


def resume_case(case, rerun=False, timeout=None):
    case = Path(case).resolve()
    if not (case / 'case.json').is_file():
        raise ValueError('No case.json in the requested case directory')
    if timeout is not None:
        validate_timeout(timeout)
    with store.case_lock(case):
        data = store.load(case)
        recover(data)
        latest = {}
        for scan in data['scans']:
            if 'input' in scan and not scan.get('parent_scan'):
                latest[(scan['target'], scan['tool'], tuple(scan['arguments']))] = scan
        for scan in latest.values():
            if scan['status'] == 'pending':
                if timeout is not None:
                    scan['timeout'] = timeout
                continue
            if scan['status'] == 'completed' and not rerun:
                continue
            tool = TOOLS.get(scan['tool'])
            if tool is None:
                continue
            item = store.validate_input(scan['input'])
            arguments = tool.arguments(item)
            if arguments is not None:
                new_scan(data, item, tool, arguments, timeout if timeout is not None else scan['timeout'], scan)
        store.save(case, data)
        finish_pending_parsing(case)
        execute_pending(case)
        store.export_pivots(case)


def reparse_case(case):
    case = Path(case).resolve()
    if not (case / 'case.json').is_file():
        raise ValueError('No case.json in the requested case directory')
    with store.case_lock(case):
        for scan in store.load(case)['scans']:
            if scan['status'] not in ('pending', 'running') and not scan.get('parent_scan') and scan['tool'] in TOOLS:
                finish_parsing(case, scan['id'])
        store.export_pivots(case)
