# aBotTesty SGS recovery integration — JAMboreeLite

Source integrated from `askjake/aBotTesty` branch `montjac`:

- RF-only Diagnostics/Network navigation while SGS is unavailable
- multi-pass OpenCV/Tesseract PIN OCR with cross-frame voting
- automatic pairing start, PIN read, completion, verification, and status
- MAC/ARP and SGS identity discovery
- SGS failure classification and RF fallback
- external aBot frame/status endpoint support

Hardening applied during the port:

- exact RxID matches are required; ambiguous receiver sweeps fail closed
- a failed candidate verification restores the exact pre-write IP
- 401/403 from a verified receiver triggers pairing instead of an IP hunt
- credentials are stored in the OS keyring and are never logged or returned
- plaintext credential compatibility is explicit opt-in only
- no hardcoded backup-controller URL remains
- forced SGS and RF calls never silently change transport
- DART success means an open worker wrote and flushed the command, not merely queued it
- UI table saves preserve hidden pairing/DART fields while allowing intentional row deletion

## Runtime frame integration

Point JAMboreeLite at aBotTesty's existing endpoints:

```bash
export JAMBOREE_FRAME_URL=http://<abot-host>:8502/snapshot.jpg
export JAMBOREE_FRAME_STATUS_URL=http://<abot-host>:8502/api/active-video
python -m jamboree.app
```

OpenCV, NumPy, and pytesseract are installed by the package. The host must also
provide a Tesseract executable for OCR-assisted recovery/pairing.

## Verification

- `python -m compileall -q jamboree tests` — PASS
- offline pytest suite — 24 passed, 1 Flask-dependent test module skipped locally
- original aBot RF-fallback behavioral scripts — previously PASS
- GitHub Actions performs the complete dependency-backed Flask test run

Physical Hopper/Joey, DART, capture, and MagiQ acceptance remains a lab gate.
