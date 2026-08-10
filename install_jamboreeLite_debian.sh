#!/usr/bin/env bash
set -Eeuo pipefail

# Debian compatibility wrapper. Keep deployment behavior in one implementation
# so Windows/Linux/Debian do not drift in ref selection, backup, dependency, or
# verification semantics.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export JAMBOREE_INSTALL_DIR="${JAMBOREE_INSTALL_DIR:-$HOME/JAMboreeLite}"

# Invoke the common installer through bash instead of executing it directly.
# Some archive/copy workflows do not preserve the executable bit, especially on
# Raspberry Pi bootstrap checkouts. Requiring only readable script contents
# avoids a needless "Permission denied" failure while preserving strict bash
# execution semantics.
exec bash "$SCRIPT_DIR/install_jamboreeLite.sh" "$@"
