#!/usr/bin/env bash
set -euo pipefail

REPO="https://github.com/askjake/JAMboreeLite.git"
INSTALL="$HOME/Documents/JAMboreeLite"
VENV="$INSTALL/venv"

echo "=== Checking prerequisites ==="
# Debian-style install if missing
PKGS=(git python3 python3-venv python3-pip rsync)
MISSING=()
for pkg in "${PKGS[@]}"; do
  if ! dpkg -s "$pkg" &>/dev/null; then
    MISSING+=("$pkg")
  fi
done
if (( MISSING )); then
  echo "Installing: ${MISSING[*]}"
  sudo apt-get update
  sudo apt-get install -y "${MISSING[@]}"
fi

PY=$(which python3)
echo "Using Python: $("$PY" --version)"

TMP=$(mktemp -d)
echo
echo "=== Clone / update repo ==="
if [ ! -d "$INSTALL" ]; then
  echo "First-time install → cloning into $INSTALL"
  git clone "$REPO" "$INSTALL"
else
  echo "Updating existing install…"
  echo "→ cloning fresh copy into temp dir…"
  git clone "$REPO" "$TMP"
  echo "→ syncing only newer files into $INSTALL…"
  rsync -a --update --exclude='.git' "$TMP/" "$INSTALL/"
  rm -rf "$TMP"
fi

echo
echo "=== Virtual-env + dependencies ==="
if [ ! -x "$VENV/bin/python" ]; then
  "$PY" -m venv "$VENV"
fi
"$VENV/bin/pip" install --upgrade pip >/dev/null
"$VENV/bin/pip" install flask pyserial paramiko requests >/dev/null

echo
echo "=== Desktop shortcut ==="
DESKTOP="$HOME/Desktop"
[ -d "$DESKTOP" ] || DESKTOP="$HOME"
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

echo
read -p "Add JAMboreeLite to start automatically at login? [y/N] " yn
if [[ $yn =~ ^[Yy]$ ]]; then
  AUTOSTART_DIR="$HOME/.config/autostart"
  mkdir -p "$AUTOSTART_DIR"
  cp "$DESKTOP/JAMboreeLite.desktop" "$AUTOSTART_DIR/"
  echo "Autostart entry placed in $AUTOSTART_DIR"
fi

echo
echo "✅  Installation/update complete!"
echo "👉  To run: $VENV/bin/python -m jamboree.app"
