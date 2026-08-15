#!/usr/bin/env python3
"""Tests for migrate.py, on synthetic data only.

Every test builds a throwaway HOME with a fake Claude layout, so nothing here
touches a real installation. Run with:

    python3 tests/test_migrate.py          (stdlib unittest, no dependencies)
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OLD = ('11111111-1111-1111-1111-111111111111', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
NEW = ('22222222-2222-2222-2222-222222222222', 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb')


def build_home(root, signed_in, cards=3, with_groups=True, locked=False):
    """Create a fake HOME and return the freshly imported module bound to it."""
    app = os.path.join(root, 'Library/Application Support/Claude')
    old_dir = os.path.join(app, 'claude-code-sessions', *OLD)
    os.makedirs(old_dir)
    os.makedirs(os.path.join(app, 'Local Storage/leveldb'))
    open(os.path.join(app, 'Local Storage/leveldb/LOCK'), 'w').close()

    for i in range(cards):
        with open(os.path.join(old_dir, f'local_card{i}.json'), 'w') as fh:
            json.dump({'sessionId': f'local_card{i}', 'title': f'chat {i}'}, fh)
    open(os.path.join(old_dir, 'deleted_gone1'), 'w').close()
    with open(os.path.join(old_dir, 'scheduled-tasks.json'), 'w') as fh:
        json.dump({'scheduledTasks': [{'id': 'nightly'}]}, fh)

    agent_dir = os.path.join(app, 'local-agent-mode-sessions', *OLD)
    os.makedirs(agent_dir)
    with open(os.path.join(agent_dir, 'local_agent1.json'), 'w') as fh:
        json.dump({'sessionId': 'local_agent1'}, fh)

    scopes = {}
    if with_groups:
        scopes[f'{OLD[0]}/{OLD[1]}'] = {
            'groups': [{'id': 'cg-1', 'name': 'alpha'}, {'id': 'cg-2', 'name': 'beta'}],
            'assignments': {'code:local_card0': 'cg-1', 'code:local_card1': 'cg-2'},
            'order': {'cg-1': ['code:local_card0'], 'cg-2': ['code:local_card1']},
        }
    with open(os.path.join(app, 'claude_desktop_config.json'), 'w') as fh:
        json.dump({'preferences': {'epitaxyPrefs': {'dframe-group-scopes': scopes},
                                   'unrelated': {'keep': True}}}, fh)

    with open(os.path.join(root, '.claude.json'), 'w') as fh:
        json.dump({'oauthAccount': {'accountUuid': signed_in[0],
                                    'organizationUuid': signed_in[1],
                                    'emailAddress': 'someone@example.com'}}, fh)

    os.environ['HOME'] = root
    for name in list(sys.modules):
        if name == 'migrate':
            del sys.modules[name]
    import migrate                                  # noqa: E402  (needs HOME set)
    return migrate


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.real_home = os.environ.get('HOME')

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)
        if self.real_home:
            os.environ['HOME'] = self.real_home

    def run_apply(self, migrate, dry_run=False):
        class Args:
            pass
        args = Args()
        args.dry_run = dry_run
        return migrate.cmd_apply(args)


class TestRecordAndApply(Base):
    def test_full_migration_moves_cards_groups_and_tasks(self):
        migrate = build_home(self.root, signed_in=OLD)
        migrate.cmd_record(None)
        self.assertTrue(os.path.exists(migrate.STATE_FILE))

        # simulate the account switch
        with open(migrate.CLAUDE_JSON) as fh:
            data = json.load(fh)
        data['oauthAccount'].update(accountUuid=NEW[0], organizationUuid=NEW[1],
                                    emailAddress='other@example.com')
        with open(migrate.CLAUDE_JSON, 'w') as fh:
            json.dump(data, fh)

        self.assertEqual(self.run_apply(migrate), 0)

        dst = migrate.store_dir('claude-code-sessions', *NEW)
        names = os.listdir(dst)
        self.assertEqual(sum(1 for n in names if n.startswith('local_')), 3)
        self.assertIn('deleted_gone1', names)          # deletions stay deleted
        with open(os.path.join(dst, 'scheduled-tasks.json')) as fh:
            self.assertEqual(len(json.load(fh)['scheduledTasks']), 1)

        agent = migrate.store_dir('local-agent-mode-sessions', *NEW)
        self.assertEqual(len(os.listdir(agent)), 1)

        scopes = migrate.read_group_scopes()
        self.assertEqual(scopes[f'{NEW[0]}/{NEW[1]}'], scopes[f'{OLD[0]}/{OLD[1]}'])
        self.assertIn(f'{OLD[0]}/{OLD[1]}', scopes)     # source preserved

    def test_source_files_are_never_removed(self):
        migrate = build_home(self.root, signed_in=OLD)
        migrate.cmd_record(None)
        before = sorted(os.listdir(migrate.store_dir('claude-code-sessions', *OLD)))
        with open(migrate.CLAUDE_JSON) as fh:
            data = json.load(fh)
        data['oauthAccount'].update(accountUuid=NEW[0], organizationUuid=NEW[1])
        with open(migrate.CLAUDE_JSON, 'w') as fh:
            json.dump(data, fh)
        self.run_apply(migrate)
        after = sorted(os.listdir(migrate.store_dir('claude-code-sessions', *OLD)))
        self.assertEqual(before, after)

    def test_running_twice_changes_nothing_extra(self):
        migrate = build_home(self.root, signed_in=OLD)
        migrate.cmd_record(None)
        with open(migrate.CLAUDE_JSON) as fh:
            data = json.load(fh)
        data['oauthAccount'].update(accountUuid=NEW[0], organizationUuid=NEW[1])
        with open(migrate.CLAUDE_JSON, 'w') as fh:
            json.dump(data, fh)
        self.run_apply(migrate)
        first = sorted(os.listdir(migrate.store_dir('claude-code-sessions', *NEW)))
        scopes_first = json.dumps(migrate.read_group_scopes(), sort_keys=True)
        self.run_apply(migrate)
        second = sorted(os.listdir(migrate.store_dir('claude-code-sessions', *NEW)))
        self.assertEqual(first, second)
        self.assertEqual(scopes_first, json.dumps(migrate.read_group_scopes(), sort_keys=True))

    def test_dry_run_writes_nothing(self):
        migrate = build_home(self.root, signed_in=OLD)
        migrate.cmd_record(None)
        with open(migrate.CLAUDE_JSON) as fh:
            data = json.load(fh)
        data['oauthAccount'].update(accountUuid=NEW[0], organizationUuid=NEW[1])
        with open(migrate.CLAUDE_JSON, 'w') as fh:
            json.dump(data, fh)
        self.run_apply(migrate, dry_run=True)
        self.assertFalse(os.path.isdir(migrate.store_dir('claude-code-sessions', *NEW)))
        self.assertNotIn(f'{NEW[0]}/{NEW[1]}', migrate.read_group_scopes())


class TestRefusals(Base):
    """Negative controls: each guard must actually refuse."""

    def test_refuses_when_source_equals_destination(self):
        migrate = build_home(self.root, signed_in=OLD)
        migrate.cmd_record(None)
        with self.assertRaises(migrate.Abort) as ctx:
            self.run_apply(migrate)
        self.assertIn('same account', str(ctx.exception))

    def test_refuses_without_a_recorded_source(self):
        migrate = build_home(self.root, signed_in=NEW)
        with self.assertRaises(migrate.Abort) as ctx:
            self.run_apply(migrate)
        self.assertIn('No recorded source', str(ctx.exception))

    def test_refuses_while_the_app_holds_the_database(self):
        """The lock must be held by ANOTHER process to mean anything.

        POSIX record locks belong to the process, so a process can always
        re-acquire its own lock: locking from inside the test would prove
        nothing and would quietly pass. Claude is a separate process, so the
        test spawns one.
        """
        import subprocess
        import time as _time
        migrate = build_home(self.root, signed_in=OLD)
        migrate.cmd_record(None)
        with open(migrate.CLAUDE_JSON) as fh:
            data = json.load(fh)
        data['oauthAccount'].update(accountUuid=NEW[0], organizationUuid=NEW[1])
        with open(migrate.CLAUDE_JSON, 'w') as fh:
            json.dump(data, fh)

        ready = os.path.join(self.root, 'holder-ready')
        holder = subprocess.Popen([sys.executable, '-c', (
            'import fcntl, os, sys, time\n'
            'fd = os.open(sys.argv[1], os.O_RDWR)\n'
            'fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n'
            'open(sys.argv[2], "w").close()\n'
            'time.sleep(30)\n'), migrate.LEVELDB_LOCK, ready])
        try:
            deadline = _time.time() + 10
            while not os.path.exists(ready) and _time.time() < deadline:
                _time.sleep(0.02)
            self.assertTrue(os.path.exists(ready), 'lock holder failed to start')

            self.assertTrue(migrate.app_is_running())
            with self.assertRaises(migrate.Abort) as ctx:
                self.run_apply(migrate)
            self.assertIn('still running', str(ctx.exception))
        finally:
            holder.kill()
            holder.wait()

        # control: with the holder gone, the same check must say "not running"
        self.assertFalse(migrate.app_is_running())

    def test_lock_check_fails_closed_when_nothing_is_verifiable(self):
        migrate = build_home(self.root, signed_in=OLD)
        os.remove(migrate.LEVELDB_LOCK)
        original = migrate.subprocess.run

        def explode(*_args, **_kwargs):
            raise OSError('ps unavailable')

        migrate.subprocess.run = explode
        try:
            self.assertTrue(migrate.app_is_running())   # unknown must mean "refuse"
        finally:
            migrate.subprocess.run = original

    def test_existing_groups_at_destination_are_not_overwritten(self):
        migrate = build_home(self.root, signed_in=OLD)
        migrate.cmd_record(None)
        with open(migrate.CONFIG) as fh:
            config = json.load(fh)
        mine = {'groups': [{'id': 'cg-9', 'name': 'destination-own'}],
                'assignments': {}, 'order': {}}
        config['preferences']['epitaxyPrefs']['dframe-group-scopes'][f'{NEW[0]}/{NEW[1]}'] = mine
        with open(migrate.CONFIG, 'w') as fh:
            json.dump(config, fh)
        with open(migrate.CLAUDE_JSON) as fh:
            data = json.load(fh)
        data['oauthAccount'].update(accountUuid=NEW[0], organizationUuid=NEW[1])
        with open(migrate.CLAUDE_JSON, 'w') as fh:
            json.dump(data, fh)
        self.run_apply(migrate)
        self.assertEqual(migrate.read_group_scopes()[f'{NEW[0]}/{NEW[1]}'], mine)

    def test_existing_card_at_destination_is_not_overwritten(self):
        migrate = build_home(self.root, signed_in=OLD)
        migrate.cmd_record(None)
        dst = migrate.store_dir('claude-code-sessions', *NEW)
        os.makedirs(dst)
        with open(os.path.join(dst, 'local_card0.json'), 'w') as fh:
            json.dump({'sessionId': 'local_card0', 'title': 'destination version'}, fh)
        with open(migrate.CLAUDE_JSON) as fh:
            data = json.load(fh)
        data['oauthAccount'].update(accountUuid=NEW[0], organizationUuid=NEW[1])
        with open(migrate.CLAUDE_JSON, 'w') as fh:
            json.dump(data, fh)
        self.run_apply(migrate)
        with open(os.path.join(dst, 'local_card0.json')) as fh:
            self.assertEqual(json.load(fh)['title'], 'destination version')


class TestConfigSafety(Base):
    def test_unrelated_config_keys_survive(self):
        migrate = build_home(self.root, signed_in=OLD)
        migrate.cmd_record(None)
        with open(migrate.CLAUDE_JSON) as fh:
            data = json.load(fh)
        data['oauthAccount'].update(accountUuid=NEW[0], organizationUuid=NEW[1])
        with open(migrate.CLAUDE_JSON, 'w') as fh:
            json.dump(data, fh)
        self.run_apply(migrate)
        with open(migrate.CONFIG) as fh:
            config = json.load(fh)
        self.assertEqual(config['preferences']['unrelated'], {'keep': True})

    def test_missing_groups_in_source_is_not_fatal(self):
        migrate = build_home(self.root, signed_in=OLD, with_groups=False)
        migrate.cmd_record(None)
        with open(migrate.CLAUDE_JSON) as fh:
            data = json.load(fh)
        data['oauthAccount'].update(accountUuid=NEW[0], organizationUuid=NEW[1])
        with open(migrate.CLAUDE_JSON, 'w') as fh:
            json.dump(data, fh)
        self.assertEqual(self.run_apply(migrate), 0)
        self.assertEqual(len(os.listdir(migrate.store_dir('claude-code-sessions', *NEW))), 5)


if __name__ == '__main__':
    unittest.main(verbosity=2)
