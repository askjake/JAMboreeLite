# JAMboreeLite

JAMboreeLite is a lightweight Flask service and web remote for controlling DISH/Sling set-tops through **SGS** and **RF/DART**.

It supports independent Hopper/Wally/XIP receivers, HopperPlus/Joey-style child routing through a host Hopper, secure SGS pairing persistence, and a browser/API surface for manual and automated control.

## Safe upgrade first

Existing installations should **upgrade in place** rather than creating a new repository or copying files manually. The updater preserves the STB configuration and secure pairing state.

See [`SETUP_INSTRUCTIONS.txt`](SETUP_INSTRUCTIONS.txt) for the full install/upgrade guide.

### Windows: existing install

Default install location:

```text
%USERPROFILE%\Documents\JAMboreeLite
```

PowerShell:

```powershell
$ROOT = "$env:USERPROFILE\Documents\JAMboreeLite"
Set-Location $ROOT
$env:JAMBOREE_NO_PAUSE = '1'
& "$ROOT\update_jamboreeLite.cmd"
```

To install a specific branch/tag/commit:

```powershell
$ROOT = "$env:USERPROFILE\Documents\JAMboreeLite"
Set-Location $ROOT
$env:JAMBOREE_REF = 'YOUR_BRANCH_OR_TAG'
$env:JAMBOREE_NO_PAUSE = '1'
& "$ROOT\update_jamboreeLite.cmd"
```

### Linux / Raspberry Pi: existing install

Run the dedicated updater from the installed tree:

```bash
cd "$HOME/JAMboreeLite"
JAMBOREE_REF=main bash ./update_jamboreeLite.sh
```

or, for a Documents-based install:

```bash
cd "$HOME/Documents/JAMboreeLite"
JAMBOREE_REF=main bash ./update_jamboreeLite.sh
```

`update_jamboreeLite.sh` defaults the target directory to the directory containing the updater, which prevents an existing Pi install under `~/JAMboreeLite` from accidentally being updated into `~/Documents/JAMboreeLite`.

## What upgrades preserve

The install/update flow is deliberately state-safe:

- `base.txt` is preserved during source synchronization.
- The existing Python virtual environment is preserved when it already uses Python 3.11+.
- A pre-update copy of the existing application/configuration tree is created.
- Secure SGS credentials are stored outside the mirrored application source:
  - OS keyring when available.
  - Windows machine-scoped DPAPI fallback when Credential Manager is unavailable in the current logon context.
  - Linux Secret Service/keyring backend when configured.
- Installed source identity is written to:
  - `.jamboree_source_ref`
  - `.jamboree_source_commit`

Windows DPAPI fallback credentials normally live at:

```text
%LOCALAPPDATA%\JAMboreeLite\sgs_credentials.dpapi.json
```

A normal source update does **not** overwrite that file.

## Fresh install

### Windows

Requirements:

- Git for Windows
- Python 3.11+

PowerShell:

```powershell
$SRC = Join-Path $env:TEMP 'JAMboreeLite-install'
Remove-Item $SRC -Recurse -Force -ErrorAction SilentlyContinue
git clone --depth 1 --branch main https://github.com/askjake/JAMboreeLite.git $SRC
cmd.exe /d /c "`"$SRC\install_jamboreeLite.cmd`""
```

Default target:

```text
%USERPROFILE%\Documents\JAMboreeLite
```

### Debian / Raspberry Pi

```bash
set -Eeuo pipefail
sudo apt-get update
sudo apt-get install -y git python3 python3-venv python3-pip rsync

cd "$HOME"
git clone https://github.com/askjake/JAMboreeLite.git JAMboreeLite-bootstrap
cd JAMboreeLite-bootstrap
export JAMBOREE_REF=main
export JAMBOREE_INSTALL_DIR="$HOME/JAMboreeLite"
bash ./install_jamboreeLite_debian.sh
```

Python 3.11 or newer is required.

Tesseract is optional for normal SGS/DART control. It is required only for OCR-assisted IP/PIN recovery features.

## Run JAMboreeLite

Windows:

```powershell
$ROOT = "$env:USERPROFILE\Documents\JAMboreeLite"
Set-Location $ROOT
& "$ROOT\venv\Scripts\python.exe" -m jamboree.app
```

Linux / Pi:

```bash
cd "$HOME/JAMboreeLite"
venv/bin/python -m jamboree.app
```

Default web endpoints:

```text
http://<jamboree-host>:5003/
http://<jamboree-host>:5003/settops
```

Health check:

```bash
curl http://127.0.0.1:5003/api/health
```

## SGS pairing

Pair the **host Hopper** once through `/settops` or the pairing API. Child devices reuse the host Hopper pairing and are addressed through the appropriate attach/CID route.

Current secure storage behavior:

- OS keyring is preferred.
- On Windows, if Credential Manager cannot be reliably read in the current session, JAMboreeLite stores the new pairing with machine-scoped DPAPI and verifies readback before reporting success.
- Plaintext `lname` / `passwd` values in a legacy `base.txt` are compatibility data only. Plaintext use requires explicit opt-in and is not the preferred secure backend.
- `/get-stb-list` does not expose stored credential secrets.

Safe credential status check:

```bash
curl "http://127.0.0.1:5003/sgs/credentials/status?alias=HOPPER3-PROD"
```

Status reports whether credentials are present and which secure backend is active without returning the password.

### Manual pairing API

Start pairing:

```bash
curl -X POST http://<jamboree-host>:5003/sgs/pair/start \
  -H 'Content-Type: application/json' \
  -d '{"alias":"HOPPER3-PROD"}'
```

Complete pairing after the PIN appears:

```bash
curl -X POST http://<jamboree-host>:5003/sgs/pair/complete \
  -H 'Content-Type: application/json' \
  -d '{"alias":"HOPPER3-PROD","pin":"123456"}'
```

The `/settops` UI is usually easier for manual pairing.

## STB topology

A typical independent Hopper/Wally/XIP row is self-contained:

```json
{
  "alias": "HOPPER3-PROD",
  "stb": "XAFxxxxxxxxxxxx",
  "ip": "192.168.1.67",
  "protocol": "SGS",
  "remote": "8",
  "com_port": "COM3",
  "role": "hopper",
  "host": "HOPPER3-PROD"
}
```

A child receiver points to its host Hopper:

```json
{
  "alias": "MOCHAJOEY-HOPPER3-PROD4",
  "stb": "XAFyyyyyyyyyyyy",
  "protocol": "SGS",
  "remote": "4",
  "com_port": "COM3",
  "role": "joey",
  "host": "HOPPER3-PROD4"
}
```

Legacy configuration normalization handles older independent receiver rows with stale/default `host` fields without rewriting `base.txt`.

For true child devices, JAMboreeLite pairs through the host Hopper, attaches using the child receiver ID, then sends `remote_key` to the host Hopper with the child-specific CID.

## Remote control API

### Auto / SGS or configured transport

```text
GET /auto/<remote>/<alias>/<button>/<delay_ms>
```

Example:

```bash
curl "http://127.0.0.1:5003/auto/8/HOPPER3-PROD/Guide/240"
```

Successful SGS result:

```json
{
  "ok": true,
  "stdout": "{\"result\": 1}",
  "via": "sgs"
}
```

Healthy SGS commands return immediately after receiver confirmation. Expensive IP/MAC identity discovery is reserved for the recovery path rather than blocking every successful keypress.

### Quick DART

```text
GET /dart/<alias>/<button>/down
GET /dart/<alias>/<button>/up
```

Example:

```bash
curl "http://127.0.0.1:5003/dart/HOPPER3-PROD/Guide/down"
curl "http://127.0.0.1:5003/dart/HOPPER3-PROD/Guide/up"
```

DART requires the configured serial port to be present and usable. An unavailable serial port is not reported as successful delivery.

## SGS recovery and RF fallback

Normal Auto commands prefer the configured transport. SGS failures are classified before recovery is attempted.

When appropriate, JAMboreeLite can:

- verify the stored receiver identity,
- recover a changed IP through identity/MAC discovery,
- optionally use RF/DART navigation plus OCR when configured,
- retry SGS after recovery,
- fall back to RF/DART if that transport is healthy.

If both configured transports are unavailable, the API returns a structured `503 all_transports_unavailable` response instead of an unhandled Flask traceback.

## Linux/Pi keyring note

On desktop Linux, the Secret Service session may already be available.

For a headless SSH session, the application must run in the same unlocked D-Bus/keyring session that provides the Secret Service backend. The updater does not delete or rewrite the OS keyring.

## Backups and rollback

Windows update backups:

```text
%LOCALAPPDATA%\JAMboreeLite\update-backups\
```

Linux/Pi update backups:

```text
${XDG_DATA_HOME:-$HOME/.local/share}/JAMboreeLite/update-backups/
```

To reinstall a known ref/tag/commit, set `JAMBOREE_REF` and run the same updater again.

Example Windows:

```powershell
$ROOT = "$env:USERPROFILE\Documents\JAMboreeLite"
$env:JAMBOREE_REF = 'KNOWN_GOOD_REF'
$env:JAMBOREE_NO_PAUSE = '1'
& "$ROOT\update_jamboreeLite.cmd"
```

Example Linux/Pi:

```bash
cd "$HOME/JAMboreeLite"
JAMBOREE_REF=KNOWN_GOOD_REF bash ./update_jamboreeLite.sh
```

## Installed-version verification

Windows:

```powershell
$ROOT = "$env:USERPROFILE\Documents\JAMboreeLite"
Get-Content "$ROOT\.jamboree_source_ref"
Get-Content "$ROOT\.jamboree_source_commit"
& "$ROOT\venv\Scripts\python.exe" -c "import jamboree.app; print('JAMBOREE_IMPORT=PASS')"
```

Linux/Pi:

```bash
cat .jamboree_source_ref
cat .jamboree_source_commit
venv/bin/python -c 'import jamboree.app; print("JAMBOREE_IMPORT=PASS")'
```

## Requirements

- Python 3.11+
- `flask`
- `keyring`
- `numpy`
- `opencv-python-headless`
- `paramiko`
- `Pillow`
- `pytesseract`
- `pyserial`
- `requests`

The shared dependency manifest is `requirements_new.txt` and is consumed by both main installers.

## Security

JAMboreeLite is intended for a trusted lab network. The Flask service itself does not provide user authentication.

Do not expose port 5003 directly to an untrusted network. Use appropriate network isolation or an authenticated reverse proxy when needed.

## Repository/versioning policy

Keep one repository:

```text
https://github.com/askjake/JAMboreeLite
```

If this generation should be called “JAMboreeLite v2”, create a **tag/release in this repository** after acceptance rather than creating `JAMboreeLite_v2`. That keeps every lab host on the same upgrade path.

Happy automating. Spread the JAM. 🧈🍞
