#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${JAMBOREE_REPO:-https://github.com/askjake/JAMboreeLite.git}"
REF="${JAMBOREE_REF:-main}"
INSTALL="${JAMBOREE_INSTALL_DIR:-$HOME/Documents/JAMboreeLite}"
VENV="$INSTALL/venv"
DATA_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/JAMboreeLite"
TMP="$(mktemp -d -t jamboreelite-update.XXXXXX)"
SOURCE="$TMP/source"

cleanup() {
  rm -rf "$TMP"
}
trap cleanup EXIT

echo "=== JAMboreeLite installer/updater ==="
echo "Repository: $REPO"
echo "Ref       : $REF"
echo "Install   : $INSTALL"

echo
echo "=== Checking prerequisites ==="
PKGS=(git python3 python3-venv python3-pip rsync)
MISSING=()
if command -v dpkg >/dev/null 2>&1; then
  for pkg in "${PKGS[@]}"; do
    if ! dpkg -s "$pkg" &>/dev/null; then
      MISSING+=("$pkg")
    fi
  done
  if (( ${#MISSING[@]} )); then
    echo "Installing: ${MISSING[*]}"
    sudo apt-get update
    sudo apt-get install -y "${MISSING[@]}"
  fi
fi
for cmd in git python3 rsync; do
  command -v "$cmd" >/dev/null 2>&1 || {
    echo "ERROR: required command '$cmd' is unavailable" >&2
    exit 1
  }
done

PY="$(command -v python3)"
"$PY" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' || {
  echo "ERROR: Python 3.11 or newer is required" >&2
  exit 1
}
echo "Using Python: $($PY --version)"

echo
echo "=== Staging exact source ref ==="
git clone --no-checkout --depth 1 "$REPO" "$SOURCE"
git -C "$SOURCE" fetch --depth 1 origin "$REF"
git -C "$SOURCE" checkout --detach FETCH_HEAD
SOURCE_COMMIT="$(git -C "$SOURCE" rev-parse HEAD)"
echo "Staged commit: $SOURCE_COMMIT"

echo
echo "=== Backing up existing application ==="
if [[ -f "$INSTALL/jamboree/app.py" && "${JAMBOREE_SKIP_CODE_BACKUP:-0}" != "1" ]]; then
  BACKUP="$DATA_ROOT/update-backups/backup-$(date +%Y%m%d-%H%M%S)-$$"
  mkdir -p "$BACKUP"
  rsync -a \
    --exclude='.git/' \
    --exclude='venv/' \
    --exclude='.venv/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='base.txt.lock' \
    "$INSTALL/" "$BACKUP/"
  echo "Backup: $BACKUP"
else
  echo "No existing runtime backup required."
fi

echo
echo "=== Synchronizing application ==="
mkdir -p "$INSTALL"
# --delete makes the installed source match the requested ref. Excluded runtime
# state is protected from deletion and remains in place.
rsync -a --delete \
  --exclude='.git/' \
  --exclude='.github/' \
  --exclude='.agent_payload/' \
  --exclude='venv/' \
  --exclude='.venv/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='base.txt' \
  --exclude='base.txt.bak' \
  --exclude='base.txt.backup' \
  --exclude='base.txt.lock' \
  --exclude='.jamboree_source_commit' \
  --exclude='.jamboree_source_ref' \
  "$SOURCE/" "$INSTALL/"

if [[ ! -f "$INSTALL/base.txt" ]]; then
  printf '{"stbs": {}}\n' > "$INSTALL/base.txt"
  echo "Created a new empty base.txt."
else
  echo "Preserved existing base.txt."
fi
printf '%s\n' "$SOURCE_COMMIT" > "$INSTALL/.jamboree_source_commit"
printf '%s\n' "$REF" > "$INSTALL/.jamboree_source_ref"

echo
echo "=== Virtual environment + dependencies ==="
if [[ -x "$VENV/bin/python" ]]; then
  if ! "$VENV/bin/python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
    echo "Existing venv uses unsupported Python; recreating it."
    rm -rf "$VENV"
  fi
fi
if [[ ! -x "$VENV/bin/python" ]]; then
  "$PY" -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install --upgrade pip
if [[ -f "$INSTALL/requirements_new.txt" ]]; then
  "$VENV/bin/python" -m pip install -r "$INSTALL/requirements_new.txt"
else
  "$VENV/bin/python" -m pip install \
    'flask>=3.0,<4' 'keyring>=24.2,<26' 'numpy>=1.26,<3' \
    'opencv-python-headless>=4.9,<6' 'paramiko>=3.4,<6' 'Pillow>=10,<13' \
    'pytesseract>=0.3.10,<0.4' 'pyserial>=3.5,<4' 'requests>=2.31,<3'
fi

echo
echo "=== Verifying installed application ==="
(
  cd "$INSTALL"
  "$VENV/bin/python" -c "import jamboree.app; print('JAMboreeLite import check passed')"
  "$VENV/bin/python" - <<'PY'
from pathlib import Path
root = Path('.')
print('Installed ref:', root.joinpath('.jamboree_source_ref').read_text().strip())
print('Installed commit:', root.joinpath('.jamboree_source_commit').read_text().strip())
PY
)

if ! command -v tesseract >/dev/null 2>&1; then
  echo
  echo "WARNING: tesseract was not found on PATH."
  echo "Normal SGS and DART controls work without it; OCR recovery/autopair needs it."
fi

if [[ "${JAMBOREE_SKIP_SHORTCUTS:-0}" != "1" ]]; then
  echo
echo "=== Desktop shortcut ==="
  DESKTOP="$HOME/Desktop"
  [[ -d "$DESKTOP" ]] || DESKTOP="$HOME"
  cat > "$DESKTOP/JAMboreeLite.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=JAMboreeLite
Exec=$VENV/bin/python -m jamboree.app
Path=$INSTALL
Icon=utilities-terminal
Terminal=false
Categories=Utility;
EOF
  chmod +x "$DESKTOP/JAMboreeLite.desktop"
  echo "Shortcut created at $DESKTOP/JAMboreeLite.desktop"

  if [[ "${JAMBOREE_SKIP_STARTUP:-0}" != "1" && -t 0 ]]; then
    read -r -p "Add JAMboreeLite to start automatically at login? [y/N] " yn
    if [[ $yn =~ ^[Yy]$ ]]; then
      AUTOSTART_DIR="$HOME/.config/autostart"
      mkdir -p "$AUTOSTART_DIR"
      cp "$DESKTOP/JAMboreeLite.desktop" "$AUTOSTART_DIR/"
      echo "Autostart entry placed in $AUTOSTART_DIR"
    fi
  fi
fi

echo
echo "============================================================"
echo "JAMboreeLite installation/update completed successfully."
echo "Ref   : $REF"
echo "Commit: $SOURCE_COMMIT"
echo "Run   : $VENV/bin/python -m jamboree.app"
echo "============================================================"
