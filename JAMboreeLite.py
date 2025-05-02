"""
JAMboree ‑ Headless Flask Bundle (Python 3.11)
================================================
This single text document contains **all** Python modules needed for the
head‑less version requested for Sling.  Breaklines marked
`# --- <path/filename.py> ---` indicate individual source files you should
save into the same package folder (`jamboree/`).  Nothing here depends on
Tkinter – it is pure Flask + `pyserial` + the existing SGS helpers you
shared.

*Quick start*
------------
```bash
python -m venv venv && source venv/bin/activate
pip install flask pyserial paramiko requests
export JAMBOREE_BASE=./base.txt   # optional – defaults to cwd/base.txt
python jamboree/app.py            # launches on 0.0.0.0:5001
```

"""





