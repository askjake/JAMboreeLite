# JAMboreeLite

Headless Flask bundle that drives DISH/Sling set‑tops via **RF/DART** (serial) and **SGS** (HTTP/HTTPS), with a simple web UI for a virtual remote and an STB manager.

This README is tuned for the Sling setup Jake helped with: **Hopper vs Joey accounting, SGS pairing, and common gotchas**.

---

## TL;DR – Quick Setup

1. **Install (Windows or Linux)**

* **Windows**: open **PowerShell (Run as Admin)** and run:

  ```powershell
  iwr -useb https://raw.githubusercontent.com/askjake/JAMboreeLite/main/install_jamboreeLite.cmd | ni "$env:TEMP\install_jamboreeLite.cmd" -Force; & "$env:TEMP\install_jamboreeLite.cmd"
  ```

  The script installs Git & Python 3.11 (via Chocolatey if missing), clones to `Documents\JAMboreeLite`, creates a venv, installs deps, and makes a desktop shortcut.

* **Linux/Debian**:

  ```bash
  curl -fsSL https://raw.githubusercontent.com/askjake/JAMboreeLite/main/install_jamboreeLite.sh | bash
  ```

2. **Create your `base.txt`**

* Copy **`base_blank.txt` → `base.txt`** and fill in your boxes. (Or set `JAMBOREE_BASE=/path/to/base.txt` to point at a different file.)

3. **Launch the server**

```bash
# Windows
%USERPROFILE%\Documents\JAMboreeLite\venv\Scripts\python.exe -m jamboree.app

# Linux/mac
~/Documents/JAMboreeLite/venv/bin/python -m jamboree.app
```

* Web UI opens at **`http://<this-host>:5003/`** (Remote) and **`/settops`** (STB manager).

4. **Mark Hoppers vs Joeys** in `base.txt`

* Hopper entries: `"role": "hopper"` and their own `ip`.
* Joey entries: `"role": "joey"` **and** `"host": "<HopperAlias>"` (we send SGS to the Hopper on their behalf).

5. **Pair each Hopper via SGS** (once per Hopper)

* Go to **`/settops`** → click **Pair** on the Hopper row → TV shows a 6‑digit PIN → enter it → **Complete**.
* Credentials (login + password) are saved back into `base.txt` automatically for future **HTTPS /www/sgs** calls.

6. **Drive boxes**

* Use **`/` (JAMboRemote)** to click buttons.
* Toggle between **DART (serial)** and **SGS** in the upper‑right switch.

That’s it.

---

## What’s in the box

* **Flask app** with two pages:

  * **`/`** – virtual remote (clickable buttons; press/hold supported)
  * **`/settops`** – STB Manager (view/edit `base.txt`, start/complete SGS pairing)
* **Serial/DART bridge** (`jamboree/serial_bridge.py`) for Nano‑Every Quick‑DART and legacy timed DART
* **SGS bridge** (`jamboree/sgs_bridge.py`, `jamboree/sgs_lib.py`) that:

  * Does **no‑auth pairing** via `http://<stb>/sgs_noauth` (tries your configured port first, then **falls back to :8080**)
  * After pairing, uses **HTTPS mutual‑TLS** to `https://<hopper>/www/sgs` with digest‑auth (auto‑fallback to HTTP if the image allows it)
  * **Joey routing**: if an STB has `"role": "joey"` and `"host": "<HopperAlias>"`, commands are sent to the host Hopper’s IP
* **Base file store** (`jamboree/stb_store.py`) – edits to `/settops` persist to `base.txt`

---

## Requirements

* Python **3.11+** (installer ensures this)
* For RF/DART: an Arduino Nano Every (or your DART board) at **115200 baud**, and a **COM port** per STB entry
* Network access from the JAMboreeLite host to each Hopper/Joey IP

Dependencies are minimal: `flask`, `pyserial`, `paramiko`, `requests` (see `pyproject.toml`).

---

## `base.txt` – schema & examples

Set `JAMBOREE_BASE` env var to move the file; otherwise it’s `./base.txt` in the working directory. Shape:

```jsonc
{
  "stbs": {
    "Hopper-01": {
      "alias": "Hopper-01",      // human name (key is also the alias)
      "stb":   "R1911748782-84", // Receiver ID used by SGS
      "ip":    "192.168.2.171",  // device IP (Hopper IP for Hoppers; Joey IPs are okay too)
      "protocol": "SGS",          // SGS or RF (remote page toggle decides live mode)
      "remote": "14",             // DART remote number (if you use RF)
      "com_port": "COM11",        // serial port for DART
      "role": "hopper",           // hopper | joey
      "host": "Hopper-01",        // for Hoppers, host can be self/alias
      "lname": "USER",            // filled after a successful pair_complete
      "passwd": "<saved>"         // filled after pair_complete
    },
    "Joey-1": {
      "alias": "Joey-1",
      "stb":   "R1971349703-16",
      "ip":    "192.168.2.65",
      "protocol": "SGS",
      "remote": "",
      "com_port": "",
      "role": "joey",
      "host": "Hopper-01"         // ← this tells JAMboreeLite to send SGS to the Hopper
    }
  }
}
```

> **Important**
>
> * Hoppers must be paired once; Joeys inherit control through their Hopper (`host`).
> * If you only use RF/DART, you can skip SGS fields—but keep `remote` and `com_port`.

---

## Using the Web UI

### `/settops` – STB Manager

* **Edit table inline** and **Save** → writes `base.txt`.
* **Pair** (Hoppers only):

  1. Click **Pair** on the Hopper row → TV shows a 6‑digit PIN
  2. Enter PIN in the row → **Complete**
  3. `lname`/`passwd` get stored into `base.txt` for secure SGS calls

If your image exposes no‑auth on `:8080` only, the code retries there automatically.

### `/` – JAMboRemote

* Dropdown lets you select an STB alias.
* **Toggle** in the top‑right switches between **SGS** and **DART**.
* **Press/hold** behaviors are supported; on release, the UI sends either the `…/up` DART call or the timed SGS with the measured duration.

---

## REST API (for automation)

> Base URL is your JAMboreeLite host, e.g. `http://10.0.0.100:5003`.

**Discovery & config**

* `GET /hostname` → `{ hostname }`
* `GET /get-stb-list` → `{ stbs: {…} }` (current `base.txt`)
* `POST /save-stb-list` → body is the full `{ stbs: … }` object to persist

**SGS pairing** (Hopper only)

* `POST /sgs/pair/start` with JSON: `{ "ip":"192.168.2.171", "stb":"R1911748782-84" }`
* `POST /sgs/pair/complete` with JSON: `{ "ip":"192.168.2.171", "stb":"R1911748782-84", "pin":"123456" }`

  On success, `ok: true` and the Hopper’s credentials are saved into `base.txt`.

**DART (serial) – Quick‑DART and legacy timed**

* `GET /dart/<alias>/<button>/<action>` → action is `down` or `up` (Quick‑DART)

  * Example: `GET /dart/Hopper-01/guide/down`
* `GET /auto/<remote>/<alias>/<button>/<delay_ms>` → legacy “press for N ms”

  * Example: `GET /auto/14/Hopper-01/guide/400`

**Utilities**

* `GET /unpair/<alias>` → Sends the SAT/DVR/Guide “unpair” combo over DART

---

## Pairing notes (Sling / Hopper & Joey)

* **Always pair the Hopper** (one‑time): Joeys use the Hopper as their SGS gateway.
* If pairing via cURL, **call JAMboreeLite** (the Flask API), not the box directly—JAMboreeLite handles fallbacks, TLS, and persistence:

  ```bash
  curl -X POST http://<jamhost>:5003/sgs/pair/start \
       -H "Content-Type: application/json" \
       -d '{"ip":"192.168.2.171","stb":"R1911748782-84"}'

  # after the PIN appears on the TV
  curl -X POST http://<jamhost>:5003/sgs/pair/complete \
       -H "Content-Type: application/json" \
       -d '{"ip":"192.168.2.171","stb":"R1911748782-84","pin":"123456"}'
  ```
* **Ports**: pairing first tries the configured port (often 80), then auto‑retries `:8080` if needed.
* **HTTPS**: after pairing, SGS commands use `https://<hopper>/www/sgs` with client certs (`jamboree/cert.pem`, `jamboree/key.pem`) and digest auth (saved `lname`/`passwd`). If the firmware allows, the bridge can fall back to HTTP.

---

## Troubleshooting (field‑tested with Sling)

**“curl: (28) Failed to connect … :8080”**

* Some images don’t expose `/sgs_noauth` on `:8080`. Use the **Flask API** `/sgs/pair/start` and let it auto‑try the right port.

**“URL rejected: Bad hostname / Malformed input”** (Windows)

* Your quoting/escaping is off. Prefer the **`/settops`** UI, or on Windows use double‑quotes and escape inner quotes: `-d "{\"ip\":\"…\"}"`.

**Joey doesn’t respond to SGS**

* Ensure the Joey entry has `"role": "joey"` and a valid `"host": "<HopperAlias>"` that exists in `stbs`. Commands will be sent to the **Hopper’s** IP.

**No serial output / DART errors**

* Confirm the `com_port` is correct and the device is 115200 baud. Quick‑DART expects discrete `down`/`up`; legacy timed DART uses the `auto` route with milliseconds.

**HTTPS SGS fails with cert/auth errors**

* Verify `jamboree/cert.pem` and `jamboree/key.pem` exist and match your environment. After a successful **pair_complete**, `lname` and `passwd` should be stored in `base.txt` automatically.

**500 from Flask when pairing**

* Check network path from the JAMboreeLite host to the Hopper IP, and that the Receiver ID (`stb`) is correct. Review logs printed in the Flask console (DEBUG enabled).

---

## Security & deployment

* This Flask app is intentionally lightweight and **has no auth**. Run it on a trusted host/network (VPN, lab VLAN, or behind a reverse proxy with auth).
* The installers can register an autostart (Windows Task Scheduler / Linux autostart). You can also run it as a service if desired.

---

## Developer notes

* Package code lives under `jamboree/`. Entrypoints:

  * `jamboree/app.py` (Flask server)
  * `jamboree/serial_bridge.py` (DART / serial)
  * `jamboree/sgs_bridge.py`, `jamboree/sgs_lib.py` (HTTP/HTTPS)
  * `jamboree/stb_store.py` (JSON persistence to `base.txt`)
* Python version is pinned to **3.11+** (`pyproject.toml`).
* You can also run from source without the installer:

  ```bash
  git clone https://github.com/askjake/JAMboreeLite.git
  cd JAMboreeLite/jamboree
  python -m venv ../venv && source ../venv/bin/activate
  pip install -e .
  python -m jamboree.app
  ```

---

## FAQ

**Q: How do I unpair a remote via DART?**

Use the convenience route: `GET /unpair/<alias>` (sends SAT 3s, then DVR+Guide 3s – releases).

**Q: Can I store `base.txt` somewhere else?**

Yes: set `JAMBOREE_BASE=/path/to/base.txt` before starting the app.

**Q: What’s the difference between Quick‑DART and the legacy DART path?**

Quick‑DART emits `down`/`up` edges (two GETs). The legacy path holds buttons for N ms via `GET /auto/<remote>/<alias>/<button>/<delay>`.

**Q: Where are logs?**

Console output (DEBUG). For Windows, check Task Scheduler history if you enabled autostart.

---

## Credits

* Core by Jake (askjake) with Sling‑specific refinements: **Joey → Hopper SGS routing**, pairing helpers, and Quick‑DART integration.
* HTML remotes live under `jamboree/static/`.

Happy automating. Spread the JAM. 🧈🍞
