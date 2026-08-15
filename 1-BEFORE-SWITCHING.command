#!/bin/bash
# Double-click me BEFORE switching accounts in Claude.
cd "$(dirname "$0")"
echo "== Step 1 of 2: remember the account you are leaving =="
echo
/usr/bin/python3 migrate.py record
echo
read -r -p "Press Enter to close..."
