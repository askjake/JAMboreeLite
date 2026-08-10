#!/usr/bin/env bash
set -Eeuo pipefail

# Safe updater for an existing Linux/Raspberry Pi JAMboreeLite installation.
# Run this file from the installed JAMboreeLite directory.  The shared installer
# stages a clean Git ref, backs up the current tree, preserves runtime state, and
# applies the requested source back to this same directory.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
INSTALL="${JAMBOREE_INSTALL_DIR:-$SCRIPT_DIR}"

if [[ ! -f "$INSTALL/jamboree/app.py" ]]; then
  echo "ERROR: JAMboreeLite runtime not found at: $INSTALL" >&2
  echo "Run this updater from the installed JAMboreeLite directory, or set JAMBOREE_INSTALL_DIR." >&2
  exit 2
fi

export JAMBOREE_INSTALL_DIR="$INSTALL"
export JAMBOREE_REF="${JAMBOREE_REF:-main}"

exec bash "$SCRIPT_DIR/install_jamboreeLite.sh" "$@"
