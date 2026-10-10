#!/bin/sh
# Sets Tessera up for your user (no sudo):
#   - checks what Tessera needs, and shows the install command if anything's missing
#   - Tessera in your apps menu, with its icon
#   - Tessera runs quietly from login, so your iPhone can unlock the laptop
#
#   ./install-integration.sh            set it all up
#   ./install-integration.sh --remove   undo all of it
here=$(cd "$(dirname "$0")" && pwd)
if [ "$1" = "--remove" ]; then
  exec python3 "$here/tools/integrate.py" remove
fi
exec python3 "$here/tools/integrate.py" install
