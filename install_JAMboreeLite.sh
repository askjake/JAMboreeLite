#!/usr/bin/env bash
set -euo pipefail

REPO="https://github.com/askjake/JAMboreeLite.git"
INSTALL_DIR="$HOME/.local/opt/JAMboreeLite"
VENV_DIR="$INSTALL_DIR/venv"

sudo apt-get update -y
sudo apt-get install -y git python3.11 python3.11-venv

# clone / pull
mkdir -p "$(dirname "$INSTALL_DIR")"
if [ -d "$INSTALL_DIR/.git" ]; then
  git -C "$INSTALL_DIR" pull --ff-only
else
  git clone "$REPO" "$INSTALL_DIR"
fi

# venv + deps
python3.11 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install flask pyserial paramiko requests

# desktop file
DESK="$HOME/.local/share/applications/jamboree.desktop"
cat >"$DESK" <<EOF
[Desktop Entry]
Type=Application
Name=JAMboreeLite
Exec=$VENV_DIR/bin/python -m jamboree.app
Icon=utilities-terminal
Terminal=true
EOF
chmod +x "$DESK"
echo "✓ Desktop launcher at $DESK"

read -rp "Add JAMboreeLite to startup (systemd user service)? [y/N] " yn
if [[ "$yn" =~ ^[Yy]$ ]]; then
  SRV="$HOME/.config/systemd/user/jamboree.service"
  mkdir -p "$(dirname "$SRV")"
  cat >"$SRV" <<EOF
[Unit]
Description=JAMboreeLite Flask service
After=network.target

[Service]
ExecStart=$VENV_DIR/bin/python -m jamboree.app
WorkingDirectory=$INSTALL_DIR
Restart=on-failure

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload
  systemctl --user enable --now jamboree.service
  echo "✓ Enabled systemd user service."
fi

echo "Done. Run with: $VENV_DIR/bin/python -m jamboree.app"
