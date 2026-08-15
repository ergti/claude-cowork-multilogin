#!/bin/bash
# Double-click me AFTER switching accounts, with Claude fully quit (Cmd+Q).
cd "$(dirname "$0")"
echo "== Step 2 of 2: bring your work to the new account =="
echo
/usr/bin/python3 migrate.py apply
echo
read -r -p "Press Enter to close..."
