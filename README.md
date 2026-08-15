# claude-cowork-multilogin

A safe CLI tool to switch between multiple accounts in Claude Cowork without
losing local context, memory, or file indexation.

*[Versão em português](README.pt-BR.md)*

## The problem

You switch accounts in the Claude desktop app, open the Code tab, and the chat
list is empty. Your sidebar groups are gone. Scheduled routines stopped firing.

**Nothing was deleted.** The conversations are still on your disk, untouched.
What happened is that the *catalog* around them is scoped per account and
organization, so signing in as someone else shows you an empty catalog.

There are three layers, and only the first is safe:

| Layer | Where it lives | Account-scoped? |
|---|---|---|
| Conversations (the actual transcripts) | `~/.claude/projects/<folder>/<uuid>.jsonl` | No, never lost |
| Chat cards: title, folder, model, deletions, scheduled tasks | `claude-code-sessions/<account>/<org>/` | **Yes** |
| Sidebar groups, chat-to-group assignments, order inside each group | `claude_desktop_config.json` → `preferences.epitaxyPrefs["dframe-group-scopes"]` | **Yes** |

This tool copies layers 2 and 3 to your new account. Layer 1 needs nothing.

> A trap worth knowing: the same group structure also appears in the Electron
> `localStorage` (`Local Storage/leveldb`), which is what a `grep` finds first.
> That copy is only a mirror. Writing to it appears to work, survives a
> re-read, and is silently discarded on the next app start. The config file is
> the source of truth.

## Requirements

macOS, Python 3.9 or newer (the system `/usr/bin/python3` is enough). No
third-party packages, no install step.

## Usage

Order matters. **Step 1 has to run before you switch accounts**, because that
is the only moment when the account you are leaving can still be identified.

```bash
git clone https://github.com/ergti/claude-cowork-multilogin.git
cd claude-cowork-multilogin

python3 migrate.py record       # 1. while still signed in to the OLD account
                                # 2. now switch accounts in the app
                                # 3. quit Claude completely (Cmd+Q)
python3 migrate.py apply        # 4. bring everything over
                                # 5. reopen Claude
```

Prefer double-clicking? Use `1-BEFORE-SWITCHING.command` and
`2-AFTER-SWITCHING.command` in Finder, in that order.

Two extra commands:

```bash
python3 migrate.py status          # what accounts exist on this machine
python3 migrate.py apply --dry-run # report what would happen, change nothing
```

### If you already switched and forgot step 1

Nothing is lost, the old account's data is still on disk. Run
`python3 migrate.py status` to list the accounts it can see, pick the one that
holds your chats, and write the state file by hand:

```bash
mkdir -p ~/.claude-cowork-multilogin
cat > ~/.claude-cowork-multilogin/previous-account.json <<'JSON'
{
  "accountUuid": "PASTE-THE-OLD-ACCOUNT-UUID",
  "organizationUuid": "PASTE-THE-OLD-ORG-UUID"
}
JSON
```

Then quit the app and run `apply`.

## What it will not do

- **It never deletes anything from the source account.** Signing back in always
  gets you the original state, which makes rollback trivial.
- **It never overwrites a chat card that already exists** at the destination.
- **It leaves the destination's own groups alone** if it already has some.
- **It refuses to run while Claude is open.** The app holds its database and
  would discard the edit. This check *fails closed*: if it cannot determine
  whether the app is running, it refuses.
- **It does not resurrect chats you deleted on purpose.** Deletion markers are
  carried over, so deleted stays deleted.
- **It does not touch your conversations.** Layer 1 is never opened for writing.

Before changing anything, it writes a verified backup to
`~/.claude-cowork-multilogin/backups/` and prints the exact command to undo.

## Tests

```bash
python3 tests/test_migrate.py
```

12 tests, standard library only, entirely on synthetic fixtures in a temporary
directory: they never read or write a real Claude installation.

Six of them are negative controls, one per guard. Each was validated by
reverting the protection it covers and confirming that exactly that test fails,
because a test that has never seen the bug proves nothing.

## Scope and honesty about coverage

Written for macOS and verified there, on the real execution path: launched the
way Finder launches it, with a short `PATH` and the system Python. The layout
it depends on is Claude's local application data as of August 2026; a future
version of the app may move things, and then `status` is the first thing to
run.

Cards whose transcript is already missing (for example a chat whose folder was
on an unmounted volume) stay missing. That is a pre-existing condition, not
something the migration causes.

## License

MIT. See [LICENSE](LICENSE).
