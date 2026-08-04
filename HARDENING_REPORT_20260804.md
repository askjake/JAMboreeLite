# JAMboreeLite transport hardening — 2026-08-04

## Fixed

- Atomic, additive `base.txt` writes with a process lock and valid backup recovery.
- UI table saves preserve credentials, DART wiring, MAC identity, and pairing metadata.
- Lock timeout now fails instead of proceeding unlocked.
- Serial worker no longer shadows `threading.Thread._stop`.
- DART writes fail closed when no worker is open and ready.
- Unsupported protocols and DART actions fail explicitly.
- SGS failures are classified; only transport failures trigger IP recovery.
- IP recovery requires a unique RxID-verified candidate and rolls back the actual old IP.
- RF/OCR fallback is dependency-injected for later integration of the recovered navigator.
- SGS commands no longer pass credentials in subprocess arguments or debug curl strings.
- Pairing stores credentials in the OS keyring; plaintext fallback is explicit opt-in.
- Joey pairing and control resolve the exact host Hopper.
- Unpair always issues a safety `allup` in `finally`.
- API binds to loopback by default and exposes explicit recovery/fallback controls.
- Example configuration no longer contains credentials.

## Verification

- `python -m compileall -q jamboree tests` — PASS
- `python -m pytest -q` — 13 passed
- Source scan confirms no subprocess use in `sgs_bridge.py` and no credentials in `base_blank.txt`.

## Hardware boundary

No Hopper, Joey, DART board, serial port, or pyAuto/MagiQ instance was available in this environment. Hardware-in-loop verification remains required.

## Firmware

`patches/fix-dart-reset-type.patch` fixes the confirmed C++ type error (`"80"` -> `80`). Apply it to the Arduino sketch before compiling with the board's production toolchain.
