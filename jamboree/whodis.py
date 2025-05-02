# --- jamboree/whodis.py ----------------------------------------
"""
Clone askjake/whodis and execute ssh.vbs.
The repo is cached at  %USERPROFILE%/.jamboree/whodis  (Windows) or
$HOME/.jamboree/whodis  (Linux/mac).  Returns whatever the VBS prints.
"""
import subprocess, sys, os, logging, pathlib, platform

GIT_URL  = "https://github.com/askjake/whodis.git"
DEST_DIR = pathlib.Path.home() / ".jamboree" / "whodis"

def _ensure_repo():
    if DEST_DIR.exists():
        logging.info("whodis repo already present → git pull")
        subprocess.run(["git", "-C", str(DEST_DIR), "pull", "--ff-only"],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    else:
        DEST_DIR.parent.mkdir(parents=True, exist_ok=True)
        logging.info("Cloning whodis repo → %s", DEST_DIR)
        subprocess.run(["git", "clone", "--depth", "1", GIT_URL, str(DEST_DIR)],
                       check=True)

def run() -> str:
    """
    Clone/update then execute ssh.vbs.
    Uses *cscript //nologo* on Windows so stdout is captured. On non‑Windows
    hosts, returns a clear message (the VBS can’t run there).
    """
    _ensure_repo()
    vbs = DEST_DIR / "ssh.vbs"
    if not vbs.exists():
        return f"error: {vbs} not found"

    if platform.system() != "Windows":
        return "ssh.vbs requires Windows (cscript). Skipped."

    logging.info("Launching ssh.vbs via cscript")
    try:
        out = subprocess.check_output(
            ["cscript", "//nologo", str(vbs)],
            cwd=str(DEST_DIR),
            stderr=subprocess.STDOUT,
            text=True,
            timeout=60,
        )
        logging.info("ssh.vbs completed: %s", out.strip())
        return out.strip() or "ssh.vbs executed (no output)"
    except subprocess.CalledProcessError as exc:
        logging.error("ssh.vbs exited %s\n%s", exc.returncode, exc.output)
        return f"error: ssh.vbs exited {exc.returncode}"
    except Exception as exc:
        logging.exception(exc)
        return f"error: {exc}"
