#!/usr/bin/env python3
"""Interactive UI and batch entry point; execution lives in case_runner."""
import argparse
import json
import os
import signal
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import case_runner as runner
import case_store as store
import llm_review


def create_case():
    workspace = Path(os.environ.get('WORKSPACE', '/workspace'))
    try:
        workspace.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix=datetime.now().strftime('osint-%Y%m%d_%H%M%S-'), dir=workspace)).resolve()
    except OSError as error:
        raise ValueError(f'Cannot create a case in {workspace}. The dashboard container is read-only. '
                         'Run from your host: docker compose run --rm kali osint [username]') from error


def investigate(case, kind, timeout, value=None):
    if value is None:
        value = input(f'Enter {kind}: ')
    item = {'type': kind, 'value': value}
    if kind == 'phone':
        code = input('Country calling code (e.g. +34; blank skips Ignorant): ').strip()
        if code:
            item['country_code'] = code
    item = store.validate_input(item)
    with store.case_lock(case):
        store.add_identifier(case, kind, item['value'])
        (case / f'target_{kind}.txt').write_text(item['value'] + '\n', encoding='utf-8')
    runner.run_targets(case, [item], timeout)


def import_pivots(case, filename):
    inputs = []
    for line in Path(filename).read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        kind = 'email' if '@' in line else 'phone' if line.lstrip('+').isdigit() else 'username'
        if kind == 'phone' and not line.startswith('+'):
            line = '+' + line
        inputs.append(store.validate_input({'type': kind, 'value': line}))
    with store.case_lock(case):
        for item in inputs:
            store.add_identifier(case, item['type'], item['value'])
        store.export_pivots(case)


def select_identifier(case, kind):
    values = sorted({i['value'] for i in store.load(case)['identifiers'] if i['type'] == kind})
    if not values:
        print(f'No {kind} leads available.')
        return None
    for index, value in enumerate(values, 1):
        print(f'{index}) {value}')
    choice = input('Select number (blank cancels): ')
    if choice.isdigit() and 1 <= int(choice) <= len(values):
        return values[int(choice) - 1]
    return None


def pivot_menu(case, timeout):
    while True:
        data = store.load(case)
        print('\nLeads (unverified):')
        for kind in ('username', 'email', 'phone'):
            print(f"{kind}: " + ', '.join(sorted({i['value'] for i in data['identifiers'] if i['type'] == kind})))
        print('1) Investigate a discovered username\n2) Investigate a discovered email\n'
              '3) Investigate a new username\n4) Investigate a new email\n'
              '5) Investigate a phone number\n6) Search all current username/email leads\n'
              '7) View results so far\n8) Back to main menu\n9) Exit\n10) Investigate a discovered phone')
        choice = input('Choice [1-10]: ')
        try:
            if choice in ('1', '2', '10'):
                kind = {'1': 'username', '2': 'email', '10': 'phone'}[choice]
                value = select_identifier(case, kind)
                if value:
                    investigate(case, kind, timeout, value)
            elif choice in ('3', '4', '5'):
                investigate(case, {'3': 'username', '4': 'email', '5': 'phone'}[choice], timeout)
            elif choice == '6':
                # Snapshot only: discoveries from these searches are not automatically queued.
                inputs = []
                for item in data['identifiers']:
                    if item['type'] in ('username', 'email'):
                        try:
                            inputs.append(store.validate_input(item))
                        except ValueError:
                            print(f"Skipping invalid lead: {item['value']}")
                runner.run_targets(case, inputs, timeout)
            elif choice == '7':
                print(f'Results: {case}')
                for scan in data['scans']:
                    print(f"{scan['tool']}: {scan['status']} (parsing: {scan.get('parse_status', 'unknown')})")
                input('Press enter to continue...')
            elif choice == '8':
                return False
            elif choice == '9':
                return True
        except (ValueError, OSError) as error:
            print(f'Cannot run search: {error}', file=sys.stderr)


def main_menu(case, timeout):
    while True:
        print(f'\nOSINT investigation\nCase: {case}\n1) Phone number\n2) Username\n3) Email\n4) Load pivots from file\n5) Exit')
        choice = input('Choice [1-5]: ')
        try:
            if choice in ('1', '2', '3'):
                investigate(case, {'1': 'phone', '2': 'username', '3': 'email'}[choice], timeout)
            elif choice == '4':
                import_pivots(case, input('Path to pivots file: '))
            elif choice == '5':
                return
            else:
                continue
            if pivot_menu(case, timeout):
                return
        except (ValueError, OSError) as error:
            print(f'Cannot run search: {error}', file=sys.stderr)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Investigate identifiers and retain evidence in a resumable case.')
    parser.add_argument('username', nargs='?')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--case', type=Path, help='start from a JSON intake file')
    mode.add_argument('--resume', type=Path, help='resume pending/unsuccessful searches in a case directory')
    mode.add_argument('--reparse', type=Path, help='rebuild findings from saved evidence without network searches')
    parser.add_argument('--rerun', action='store_true', help='with --resume, also create new attempts for completed searches')
    parser.add_argument('--batch', action='store_true', help='exit after execution without opening menus')
    parser.add_argument('--timeout', type=float, help=f'whole-process deadline in seconds (new searches: {runner.DEFAULT_TIMEOUT})')
    parser.add_argument('--review', action='store_true', help='require OpenAI review after each tool; saved for this case')
    parser.add_argument('--approve-review', metavar='SCAN_ID', help='with --resume, manually approve a paused review')
    parser.add_argument('--review-note', help='reason for manually approving the paused review')
    args = parser.parse_args(argv)
    if args.username and (args.case or args.resume or args.reparse):
        parser.error('username cannot be combined with --case, --resume or --reparse')
    if args.rerun and not args.resume:
        parser.error('--rerun requires --resume')
    if args.approve_review and (not args.resume or not args.review_note):
        parser.error('--approve-review requires --resume and --review-note')
    if args.review_note and not args.approve_review:
        parser.error('--review-note requires --approve-review')
    if args.review and args.reparse:
        parser.error('--reparse is offline; use --resume --review to review parsed evidence')
    if args.batch and not (args.username or args.case or args.resume or args.reparse):
        parser.error('--batch requires a username, --case, --resume or --reparse')
    case = None
    try:
        policy = llm_review.policy_from_env() if args.review else None
        timeout = runner.validate_timeout(args.timeout if args.timeout is not None else runner.DEFAULT_TIMEOUT)
        if args.username:
            store.validate_input({'type': 'username', 'value': args.username})
        if args.reparse:
            runner.reparse_case(args.reparse)
            print(f'Reparsed saved evidence: {args.reparse}')
            return 0
        if args.resume:
            case = args.resume.resolve()
            if args.approve_review:
                llm_review.approve_review(case, args.approve_review, args.review_note)
            runner.resume_case(case, rerun=args.rerun, timeout=args.timeout, review=policy)
        else:
            intake = json.loads(args.case.read_text(encoding='utf-8-sig')) if args.case else None
            case = create_case()
            print(f'Case: {case}', flush=True)
            if policy:
                with store.case_lock(case):
                    data = store.load(case)
                    llm_review.configure(data, policy)
                    store.save(case, data)
            if intake is not None:
                runner.run_case(case, intake, timeout)
            elif args.username:
                investigate(case, 'username', timeout, args.username)
        if not args.batch:
            if not (args.username or args.case or args.resume) or not pivot_menu(case, timeout):
                main_menu(case, timeout)
        print(f'Results saved to: {case}')
        return 0
    except EOFError:
        print(f'Input closed. Results saved to: {case}')
        return 0
    except KeyboardInterrupt:
        print(f'Interrupted. Resume with: osint --resume {case}', file=sys.stderr)
        return 130
    except llm_review.ReviewBlocked as error:
        print(f'{error}\nResults saved. Resume with: osint --resume {case}', file=sys.stderr)
        return 3
    except (OSError, ValueError) as error:
        print(f'Cannot run case: {error}', file=sys.stderr)
        return 1


def terminate(signum, frame):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    raise KeyboardInterrupt


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    raise SystemExit(main())
