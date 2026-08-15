#!/usr/bin/env python3
"""Preserve local Claude Cowork work when switching the signed-in account.

Conversations themselves are never account-scoped and are never lost. What IS
scoped per account+organization, and therefore disappears from the UI after a
switch, is the catalog around them:

  1. chat cards      claude-code-sessions/<account>/<org>/local_*.json
                     plus deleted_* markers and scheduled-tasks.json
  2. agent sessions  local-agent-mode-sessions/<account>/<org>/local_*.json
  3. sidebar groups  claude_desktop_config.json
                     preferences.epitaxyPrefs["dframe-group-scopes"]

Usage:
    migrate.py record            before switching: remember the current account
    migrate.py apply             after switching, app QUIT: migrate everything
    migrate.py apply --dry-run   show what would happen, change nothing
    migrate.py status            show accounts found on this machine

Tested on macOS. See README for details.
"""
import argparse
import fcntl
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time

HOME = os.path.expanduser('~')
APP_SUPPORT = os.path.join(HOME, 'Library/Application Support/Claude')
CONFIG = os.path.join(APP_SUPPORT, 'claude_desktop_config.json')
LEVELDB_LOCK = os.path.join(APP_SUPPORT, 'Local Storage/leveldb/LOCK')
CLAUDE_JSON = os.path.join(HOME, '.claude.json')
STATE_DIR = os.path.join(HOME, '.claude-cowork-multilogin')
STATE_FILE = os.path.join(STATE_DIR, 'previous-account.json')
BACKUP_DIR = os.path.join(STATE_DIR, 'backups')
STORES = ('claude-code-sessions', 'local-agent-mode-sessions')
GROUP_SCOPES_KEY = 'dframe-group-scopes'


class Abort(Exception):
    """Fatal condition with a message meant for the user."""


# --------------------------------------------------------------- environment
def signed_in_account():
    """(account_uuid, org_uuid, email) of the account currently signed in."""
    if not os.path.exists(CLAUDE_JSON):
        raise Abort(f'{CLAUDE_JSON} not found. Is Claude installed and signed in?')
    try:
        with open(CLAUDE_JSON) as fh:
            account = json.load(fh)['oauthAccount']
        return account['accountUuid'], account['organizationUuid'], account.get('emailAddress', '?')
    except (KeyError, ValueError) as exc:
        raise Abort(f'Could not read the signed-in account from {CLAUDE_JSON}: {exc}\n'
                    'Open Claude, make sure you are signed in, then try again.')


def app_is_running():
    """True if Claude still holds its local database.

    Fails CLOSED: when nothing can be checked, returns True. Migrating while
    the app runs loses the edit silently, so "unknown" must mean "refuse".
    Deliberately independent of PATH: the Finder launches .command files with
    a short PATH, and lsof lives in /usr/sbin.
    """
    if os.path.exists(LEVELDB_LOCK):
        try:
            fd = os.open(LEVELDB_LOCK, os.O_RDWR)
        except OSError:
            return True
        try:
            fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.lockf(fd, fcntl.LOCK_UN)
            return False
        except OSError:
            return True
        finally:
            os.close(fd)
    # No lock file: fall back to the process table. pgrep is NOT used here --
    # its exit code cannot distinguish "no such process" from "cannot read the
    # process table", and those two need opposite answers.
    try:
        proc = subprocess.run(['/bin/ps', '-Ao', 'command'], capture_output=True, text=True)
    except OSError:
        return True
    out = proc.stdout or ''
    if proc.returncode != 0 or len(out.splitlines()) < 2:
        return True
    return 'Claude.app/Contents/MacOS/Claude' in out


def scope_key(account, org):
    return f'{account}/{org}'


def store_dir(store, account, org):
    return os.path.join(APP_SUPPORT, store, account, org)


def count_cards(store, account, org):
    """(chat cards, deleted markers) present for this account+org."""
    path = store_dir(store, account, org)
    if not os.path.isdir(path):
        return 0, 0
    names = os.listdir(path)
    cards = sum(1 for n in names if n.startswith('local_') and n.endswith('.json'))
    deleted = sum(1 for n in names if n.startswith('deleted_'))
    return cards, deleted


def read_group_scopes():
    if not os.path.exists(CONFIG):
        return {}
    try:
        with open(CONFIG) as fh:
            config = json.load(fh)
        return config.get('preferences', {}).get('epitaxyPrefs', {}).get(GROUP_SCOPES_KEY, {})
    except ValueError:
        return {}


def discover_accounts():
    """Every account/org pair that has data on this machine."""
    found = []
    root = os.path.join(APP_SUPPORT, 'claude-code-sessions')
    if not os.path.isdir(root):
        return found
    for account in sorted(os.listdir(root)):
        account_path = os.path.join(root, account)
        if not os.path.isdir(account_path):
            continue
        for org in sorted(os.listdir(account_path)):
            if not os.path.isdir(os.path.join(account_path, org)):
                continue
            cards, deleted = count_cards('claude-code-sessions', account, org)
            found.append({'account': account, 'org': org, 'cards': cards, 'deleted': deleted})
    return found


def short(uuid):
    return uuid.split('-')[0] if uuid else '?'


# -------------------------------------------------------------------- record
def cmd_record(_args):
    account, org, email = signed_in_account()
    cards, deleted = count_cards('claude-code-sessions', account, org)
    scope = read_group_scopes().get(scope_key(account, org), {})
    state = {
        'accountUuid': account,
        'organizationUuid': org,
        'email': email,
        'cards': cards,
        'deletedMarkers': deleted,
        'groups': len(scope.get('groups', [])),
        'assignments': len(scope.get('assignments', {})),
        'recordedAt': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, 'w') as fh:
        json.dump(state, fh, indent=2)
    print('Recorded the current account as the migration SOURCE:\n')
    print(f'  account       {email}')
    print(f'  account/org   {short(account)}/{short(org)}')
    print(f'  chat cards    {cards}   (+{deleted} deleted markers)')
    print(f'  groups        {state["groups"]}   with {state["assignments"]} chats assigned')
    print(f'\nSaved to {STATE_FILE}')
    print('\nNext: switch accounts in the app, quit it completely, then run "apply".')
    return 0


# -------------------------------------------------------------------- status
def cmd_status(_args):
    try:
        account, org, email = signed_in_account()
    except Abort:
        account = org = None
        email = '(not signed in)'
    print(f'Signed in now : {email}')
    if account:
        print(f'                {short(account)}/{short(org)}')
    print(f'App running   : {"yes (refuse to migrate)" if app_is_running() else "no"}')
    print(f'Recorded source: {STATE_FILE if os.path.exists(STATE_FILE) else "(none yet -- run record)"}')
    print('\nAccounts with data on this machine:')
    scopes = read_group_scopes()
    for entry in discover_accounts():
        key = scope_key(entry['account'], entry['org'])
        groups = len(scopes.get(key, {}).get('groups', []))
        current = '  <- signed in' if entry['account'] == account and entry['org'] == org else ''
        print(f'  {short(entry["account"])}/{short(entry["org"])}  '
              f'cards={entry["cards"]:<5} deleted={entry["deleted"]:<4} groups={groups}{current}')
    return 0


# --------------------------------------------------------------------- apply
def make_backup():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = os.path.join(BACKUP_DIR, f'cowork-{time.strftime("%Y%m%d-%H%M%S")}.tar.gz')
    with tarfile.open(path, 'w:gz') as tar:
        for store in STORES:
            source = os.path.join(APP_SUPPORT, store)
            if os.path.isdir(source):
                tar.add(source, arcname=store)
        if os.path.exists(CONFIG):
            tar.add(CONFIG, arcname=os.path.basename(CONFIG))
    with tarfile.open(path) as tar:                     # verify it reads back
        members = len(tar.getnames())
    return path, members


def copy_cards(store, src, dst, dry_run):
    """Copy chat cards and deleted markers. Never overwrites, never deletes."""
    src_dir, dst_dir = store_dir(store, *src), store_dir(store, *dst)
    if not os.path.isdir(src_dir):
        return None
    if not dry_run:
        os.makedirs(dst_dir, exist_ok=True)
    copied = skipped = 0
    for name in sorted(os.listdir(src_dir)):
        if not (name.startswith('local_') or name.startswith('deleted_')):
            continue
        if os.path.exists(os.path.join(dst_dir, name)):
            skipped += 1
            continue
        if not dry_run:
            shutil.copy2(os.path.join(src_dir, name), os.path.join(dst_dir, name))
        copied += 1
    # scheduled tasks: only when the destination has none of its own
    src_tasks = os.path.join(src_dir, 'scheduled-tasks.json')
    dst_tasks = os.path.join(dst_dir, 'scheduled-tasks.json')
    tasks_copied = False
    if os.path.exists(src_tasks):
        destination_empty = True
        if os.path.exists(dst_tasks):
            try:
                with open(dst_tasks) as fh:
                    destination_empty = not json.load(fh).get('scheduledTasks')
            except ValueError:
                destination_empty = True
        if destination_empty:
            if not dry_run:
                shutil.copy2(src_tasks, dst_tasks)
            tasks_copied = True
    return {'copied': copied, 'skipped': skipped, 'tasks': tasks_copied}


def copy_groups(src, dst, dry_run):
    """Copy sidebar groups, assignments and per-group order."""
    if not os.path.exists(CONFIG):
        return 'no config file; nothing to copy'
    with open(CONFIG) as fh:
        config = json.load(fh)
    scopes = config.setdefault('preferences', {}).setdefault('epitaxyPrefs', {}) \
                   .setdefault(GROUP_SCOPES_KEY, {})
    source = scopes.get(scope_key(*src))
    if not source:
        return 'source account had no groups'
    existing = scopes.get(scope_key(*dst)) or {}
    if existing.get('groups'):
        return (f'destination already has {len(existing["groups"])} groups; '
                'left untouched')
    summary = (f'{len(source.get("groups", []))} groups, '
               f'{len(source.get("assignments", {}))} chats')
    if dry_run:
        return f'would copy {summary}'
    shutil.copy2(CONFIG, CONFIG + time.strftime('.bak-%Y%m%d-%H%M%S'))
    scopes[scope_key(*dst)] = json.loads(json.dumps(source))
    tmp = CONFIG + '.tmp'
    with open(tmp, 'w') as fh:
        json.dump(config, fh, indent=2, ensure_ascii=False)
    with open(tmp) as fh:                               # validate before swap
        json.load(fh)
    os.replace(tmp, CONFIG)
    return f'copied {summary}'


def cmd_apply(args):
    if not os.path.exists(STATE_FILE):
        raise Abort('No recorded source account.\n'
                    'Step 1 ("record") has to run BEFORE switching accounts.\n'
                    f'You can still write {STATE_FILE} by hand: see the README.')
    with open(STATE_FILE) as fh:
        previous = json.load(fh)
    src = (previous['accountUuid'], previous['organizationUuid'])
    dst_account, dst_org, dst_email = signed_in_account()
    dst = (dst_account, dst_org)

    print(f'SOURCE      {previous.get("email", "?")}  ({short(src[0])}/{short(src[1])})')
    print(f'DESTINATION {dst_email}  ({short(dst[0])}/{short(dst[1])})')
    if args.dry_run:
        print('MODE        dry run, nothing will be written\n')
    else:
        print()

    if src == dst:
        raise Abort('Source and destination are the same account/org.\n'
                    'Did you actually switch accounts in the app before running this?')
    if app_is_running() and not args.dry_run:
        raise Abort('Claude is still running (its database is locked).\n'
                    'Quit the app completely, then run this again.')

    if args.dry_run:
        backup = 'skipped (dry run)'
    else:
        path, members = make_backup()
        backup = f'{path} ({members} files)'
    print(f'[1/4] Backup: {backup}\n')

    for store in STORES:
        result = copy_cards(store, src, dst, args.dry_run)
        if result is None:
            continue
        verb = 'would copy' if args.dry_run else 'copied'
        extra = ', scheduled tasks too' if result['tasks'] else ''
        print(f'[2/4] {store}: {verb} {result["copied"]}, '
              f'{result["skipped"]} already there{extra}')

    print(f'[3/4] Groups: {copy_groups(src, dst, args.dry_run)}\n')

    ok = True
    for store in STORES:
        src_cards, _ = count_cards(store, *src)
        dst_cards, _ = count_cards(store, *dst)
        if src_cards and dst_cards < src_cards and not args.dry_run:
            ok = False
        print(f'[4/4] {store}: source={src_cards} destination={dst_cards}')
    scopes = read_group_scopes()
    destination_scope = scopes.get(scope_key(*dst), {})
    print(f'      groups at destination: {len(destination_scope.get("groups", []))} '
          f'({len(destination_scope.get("assignments", {}))} chats)')
    print(f'      source preserved: {scope_key(*src) in scopes}')

    if args.dry_run:
        print('\nDry run finished. Re-run without --dry-run to apply.')
        return 0
    print('\nDone. Reopen Claude.' if ok else
          '\nWARNING: destination ended up with fewer cards than the source. '
          'Check before continuing.')
    print('\nTo undo everything:')
    for store in STORES:
        print(f'  rm -rf "{os.path.join(APP_SUPPORT, store)}"')
    print(f'  tar -xzf "{backup.split(" (")[0]}" -C "{APP_SUPPORT}"')
    return 0 if ok else 1


# ---------------------------------------------------------------------- main
def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='migrate.py',
        description='Preserve local Claude Cowork work across account switches.')
    sub = parser.add_subparsers(dest='command')
    sub.add_parser('record', help='before switching: remember the current account')
    apply_parser = sub.add_parser('apply', help='after switching, with the app quit')
    apply_parser.add_argument('--dry-run', action='store_true',
                              help='report what would happen, change nothing')
    sub.add_parser('status', help='show accounts found on this machine')
    args = parser.parse_args(argv)
    handlers = {'record': cmd_record, 'apply': cmd_apply, 'status': cmd_status}
    if args.command not in handlers:
        parser.print_help()
        return 2
    try:
        return handlers[args.command](args)
    except Abort as exc:
        print(f'\nERROR: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
