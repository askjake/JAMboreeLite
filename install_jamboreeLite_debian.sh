#!/usr/bin/env bash
set -e

REPO="https://github.com/askjake/JAMboreeLite.git"
INSTALL="$HOME/JAMboreeLite"
VENV="$INSTALL/venv"

echo "=== Checking prerequisites ==="
# git
command -v git >/dev/null 2>&1 || {
  echo "git not found; installing…"
  sudo apt-get update
  sudo apt-get install -y git
}
# python3 + venv support
command -v python3 >/dev/null 2>&1 || {
  echo "python3 not found; installing…"
  sudo apt-get update
  sudo apt-get install -y python3
}
# make sure python3-venv and distutils (ensurepip) are installed
dpkg -s python3-venv >/dev/null 2>&1 || {
  echo "Installing python3-venv (for venv/ensurepip)…"
  sudo apt-get install -y python3-venv python3-distutils
}

# ─── Clone or Update ──────────────────────────────────────────────────────────
echo "=== Clone / update repo ==="
if [ -d "$INSTALL/.git" ]; then
  echo "→ Pulling latest changes in $INSTALL…"
  git -C "$INSTALL" pull --ff-only || echo "[WARN] git pull failed; you may need to resolve conflicts"
else
  if [ -e "$INSTALL" ]; then
    echo "[WARN] $INSTALL exists but isn't a git repo; backing it up"
    mv "$INSTALL" "${INSTALL}.backup-$(date +%F-%T)"
  fi
  echo "→ Cloning into $INSTALL…"
  git clone "$REPO" "$INSTALL"
fi

# ─── Virtual-env & Dependencies ────────────────────────────────────────────────
echo "=== Setting up virtual environment & dependencies ==="
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip

if [ -f "$INSTALL/requirements.txt" ]; then
  "$VENV/bin/pip" install -r "$INSTALL/requirements.txt"
else
  "$VENV/bin/pip" install flask pyserial paramiko requests
fi

# ─── Finish ───────────────────────────────────────────────────────────────────
cat <<EOF

✅ Installation/update complete!

To start the JAMboreeLite server:
  $VENV/bin/python -m jamboree.app

You can add this to your ~/.bashrc or a systemd unit for auto-start if you like.

EOF
