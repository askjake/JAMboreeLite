#!/usr/bin/env bash
set -Eeuo pipefail

# Debian compatibility wrapper. Keep deployment behavior in one implementation
# so Windows/Linux/Debian do not drift in ref selection, backup, dependency, or
# verification semantics.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export JAMBOREE_INSTALL_DIR="${JAMBOREE_INSTALL_DIR:-$HOME/JAMboreeLite}"
exec "$SCRIPT_DIR/install_jamboreeLite.sh" "$@"
