"""Assemble the source repository in GitHub\\ - what is published on GitHub:
the program, its installers and the documentation. No binaries (runtime,
wheels, openEMS), no results (workspace), no local settings or caches.

    python tools\\make_github.py

Copied: the batch files, README.md, LICENSE, CITATION.cff, the environment
and requirement files, app\\ (without caches), tools\\ (the offline-package
builders) and docs\\images\\ with only the images the README shows.
The user guides are not part of the repository: their PDFs are attached to
each release (tools\\make_release.py) and the offline package carries them
with the HTML version, while the chapter sources and figures stay in
docs\\guide\\ here - every edit would otherwise add tens of MB to the history.
Written: .gitignore and .gitattributes.

Before it finishes, every text file is scanned for what must not be published
(a local user path, an e-mail address) and for Korean text (only the Korean
guide carries it, and it is not published here); a hit stops the script
with the file and line.
"""
from __future__ import annotations

import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "GitHub")
TOP = [f for f in sorted(os.listdir(ROOT))
       if f.lower().endswith((".bat", ".yml")) or f in ("README.md", "LICENSE", "CITATION.cff")
       or (f.lower().endswith(".txt") and f.lower().startswith(("requirements", "constraints")))]
TOOLS = ["build_offline.py", "check_imports.py", "make_download.py", "make_release.py"]
# app/logs: the solver logs a run started from app/ writes (run_cli.py)
SKIP_DIRS = {"__pycache__", ".pytest_cache", ".ipynb_checkpoints", "logs"}
SKIP_FILES = {"settings.json", ".session_secret"}
SKIP_EXT = (".pyc", ".pyo", ".nbi", ".nbc")
TEXT_EXT = (".py", ".js", ".css", ".html", ".md", ".txt", ".bat", ".yml", ".json", ".csv", ".cff", "")

GITIGNORE = """# Python
__pycache__/
*.py[cod]
*.nbi
*.nbc

# environments and the offline package (tools/build_offline.py writes them)
/env/
/python/
/runtime/
/wheels/
/tools/openEMS/
/Download/
/GitHub/
/Release/
/docs/*.pdf

# results, solver logs and local settings
/workspace/
logs/
settings.json
.session_secret

# editors and the operating system
.vscode/
.idea/
Thumbs.db
desktop.ini
"""

GITATTRIBUTES = """* text=auto
*.bat text eol=crlf
*.png binary
*.pdf binary
*.gz binary
*.zip binary
"""

# what must not be published: a local user folder, an e-mail address
FORBIDDEN = [
    (re.compile(r"[A-Za-z]:\\\\?Users\\\\?[A-Za-z0-9._-]+", re.I), "local user path"),
    (re.compile(r"/[a-z]/Users/", re.I), "local user path"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}"), "e-mail address"),
]
# Korean belongs only to the Korean guide, which is not published here
HANGUL = re.compile("[\uac00-\ud7a3\u3131-\u318e]")
HANGUL_OK = ()


def copytree(src, dst):
    n = 0
    for base, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        rel = os.path.relpath(base, src)
        os.makedirs(os.path.join(dst, rel), exist_ok=True)
        for f in files:
            if f.endswith(SKIP_EXT) or f in SKIP_FILES:
                continue
            shutil.copy2(os.path.join(base, f), os.path.join(dst, rel, f))
            n += 1
    return n


def scan(out):
    hits = []
    for base, dirs, files in os.walk(out):
        dirs[:] = [d for d in dirs if d != ".git"]   # git's own records are not published files
        for f in files:
            p = os.path.join(base, f)
            if not f.lower().endswith(TEXT_EXT) or "vendor" in p:
                continue
            try:
                with open(p, encoding="utf-8") as fh:
                    lines = fh.read().splitlines()
            except UnicodeDecodeError:
                continue
            rel = os.path.relpath(p, out)
            korean_ok = rel.startswith(HANGUL_OK)
            for k, line in enumerate(lines, 1):
                for rx, what in FORBIDDEN:
                    m = rx.search(line)
                    if m:
                        hits.append(f"{rel}:{k}: {what}: {m.group(0)}")
                if not korean_ok and HANGUL.search(line):
                    hits.append(f"{rel}:{k}: Korean text")
    return hits


def main():
    # empty the folder but keep it: an explorer window or a shell may have it
    # open, and Windows does not remove a folder in use
    os.makedirs(OUT, exist_ok=True)
    for name in os.listdir(OUT):
        if name == ".git":
            continue                  # the repository history stays; only the files are replaced
        p = os.path.join(OUT, name)
        if os.path.isdir(p) and not os.path.islink(p):
            shutil.rmtree(p)
        else:
            os.remove(p)
    for f in TOP:
        shutil.copy2(os.path.join(ROOT, f), os.path.join(OUT, f))
    n_app = copytree(os.path.join(ROOT, "app"), os.path.join(OUT, "app"))
    os.makedirs(os.path.join(OUT, "tools"))
    for f in TOOLS:
        shutil.copy2(os.path.join(ROOT, "tools", f), os.path.join(OUT, "tools", f))
    # only the images the README shows; the guides go out with the releases
    images = os.path.join(ROOT, "docs", "images")
    with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
        used = sorted(set(re.findall(r"docs/images/([A-Za-z0-9_.-]+)", fh.read())))
    missing = [f for f in used if not os.path.exists(os.path.join(images, f))]
    if missing:
        sys.exit("README images missing: " + ", ".join(missing))
    os.makedirs(os.path.join(OUT, "docs", "images"))
    for f in used:
        shutil.copy2(os.path.join(images, f), os.path.join(OUT, "docs", "images", f))
    with open(os.path.join(OUT, ".gitignore"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(GITIGNORE)
    with open(os.path.join(OUT, ".gitattributes"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(GITATTRIBUTES)
    hits = scan(OUT)
    if hits:
        print("\n".join(hits))
        sys.exit(f"{len(hits)} line(s) must not be published - fix them in the v5 sources and run this again")
    size, files, big = 0, 0, []
    for base, dirs, fs in os.walk(OUT):
        dirs[:] = [d for d in dirs if d != ".git"]
        for f in fs:
            s = os.path.getsize(os.path.join(base, f))
            size += s
            files += 1
            big.append((s, os.path.relpath(os.path.join(base, f), OUT)))
    big.sort(reverse=True)
    print(f"GitHub: {files} files, {size / 2**20:.0f} MB ({n_app} in app, {len(used)} README images); "
          f"largest: " + ", ".join(f"{p} {s / 2**20:.1f} MB" for s, p in big[:3]))
    print("scan: no local user path, no e-mail address, no Korean text")


if __name__ == "__main__":
    main()
