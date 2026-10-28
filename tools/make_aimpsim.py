"""Assemble the AI edition, AIMPSim: MPSim with the AI tab.

    python tools\\make_aimpsim.py             the repository in GitHubAI\\
    python tools\\make_aimpsim.py --release   also the offline package in ReleaseAI\\

AIMPSim is MPSim (every file make_github.py publishes) plus the folder
AIMPSim\\ - the reading engine of the AI tab, its tests and its Korean guide -
with the AIMPSim README in place of MPSim's. MPSim finds the folder at start-up
and shows the AI tab; without it (the standard edition) the tab is not there.
Every change of MPSim is published to both repositories.

The same scan as make_github.py runs on the result; Korean is allowed only in
AIMPSim\\ (the lexicon, the tests and the Korean guide) and in the README's
examples of requests.

The offline package is MPSim's (tools\\make_download.py) with AIMPSim\\ added,
zipped as AIMPSim-<version>-offline-win64.zip; the release also carries
MPSim's user guides and SHA256SUMS.txt.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "GitHubAI")
REL = os.path.join(ROOT, "ReleaseAI")
AI = os.path.join(ROOT, "AIMPSim")
sys.path.insert(0, os.path.join(ROOT, "tools"))
import make_github as MG  # noqa: E402

AI_SKIP = {"aimpsim_config.json", "README.md"}
STORED = (".whl", ".zip", ".7z", ".gz", ".png", ".jpg", ".pdf")


def version():
    with open(os.path.join(AI, "aimpsim", "__init__.py"), encoding="utf-8") as fh:
        return re.search(r'__version__\s*=\s*"([^"]+)"', fh.read()).group(1)


def copy_ai(dst):
    n = 0
    for base, dirs, files in os.walk(AI):
        dirs[:] = [d for d in dirs if d not in MG.SKIP_DIRS]
        rel = os.path.relpath(base, AI)
        os.makedirs(os.path.join(dst, rel), exist_ok=True)
        for f in files:
            if f.endswith(MG.SKIP_EXT) or (rel == "." and f in AI_SKIP):
                continue
            shutil.copy2(os.path.join(base, f), os.path.join(dst, rel, f))
            n += 1
    return n


def repository():
    os.makedirs(OUT, exist_ok=True)
    for name in os.listdir(OUT):
        if name == ".git":
            continue
        p = os.path.join(OUT, name)
        if os.path.isdir(p) and not os.path.islink(p):
            shutil.rmtree(p)
        else:
            os.remove(p)
    for f in MG.TOP:
        if f in ("README.md", "CITATION.cff"):
            continue
        shutil.copy2(os.path.join(ROOT, f), os.path.join(OUT, f))
    shutil.copy2(os.path.join(AI, "README.md"), os.path.join(OUT, "README.md"))
    n_app = MG.copytree(os.path.join(ROOT, "app"), os.path.join(OUT, "app"))
    os.makedirs(os.path.join(OUT, "tools"))
    for f in MG.TOOLS + ["make_aimpsim.py", "make_github.py"]:
        shutil.copy2(os.path.join(ROOT, "tools", f), os.path.join(OUT, "tools", f))
    n_ai = copy_ai(os.path.join(OUT, "AIMPSim"))
    with open(os.path.join(AI, "README.md"), encoding="utf-8") as fh:
        used = sorted(set(re.findall(r"docs/images/([A-Za-z0-9_.-]+)", fh.read())))
    os.makedirs(os.path.join(OUT, "docs", "images"))
    for f in used:
        shutil.copy2(os.path.join(ROOT, "docs", "images", f), os.path.join(OUT, "docs", "images", f))
    with open(os.path.join(OUT, ".gitignore"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(MG.GITIGNORE.replace("/GitHub/\n", "/GitHub/\n/GitHubAI/\n/ReleaseAI/\n")
                 + "\n# the local model's settings of this PC\nAIMPSim/aimpsim_config.json\n")
    with open(os.path.join(OUT, ".gitattributes"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(MG.GITATTRIBUTES)
    MG.HANGUL_OK = ("AIMPSim", "README.md")
    hits = MG.scan(OUT)
    if hits:
        print("\n".join(hits[:40]))
        sys.exit(f"{len(hits)} line(s) must not be published")
    size = sum(os.path.getsize(os.path.join(b, f)) for b, ds, fs in os.walk(OUT) if ".git" not in b for f in fs)
    print(f"GitHubAI: {n_app} files in app, {n_ai} in AIMPSim, {len(used)} README images; {size / 2**20:.0f} MB")
    print("scan: no local user path, no e-mail address; Korean only in AIMPSim/ and the README's examples")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def release():
    import make_download
    if make_download.main():
        return 1
    v = version()
    os.makedirs(REL, exist_ok=True)
    src = os.path.join(ROOT, "Download")
    zname = f"AIMPSim-{v}-offline-win64.zip"
    zpath = os.path.join(REL, zname)
    top = "AIMPSim-" + v
    with zipfile.ZipFile(zpath + ".part", "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for base, dirs, files in os.walk(src):
            dirs.sort()
            for f in sorted(files):
                p = os.path.join(base, f)
                z.write(p, f"{top}/" + os.path.relpath(p, src).replace(os.sep, "/"),
                        compress_type=zipfile.ZIP_STORED if f.lower().endswith(STORED) else zipfile.ZIP_DEFLATED)
        for base, dirs, files in os.walk(AI):
            dirs[:] = sorted(d for d in dirs if d not in MG.SKIP_DIRS)
            for f in sorted(files):
                rel = os.path.relpath(os.path.join(base, f), AI)
                if f.endswith(MG.SKIP_EXT) or rel == "aimpsim_config.json":
                    continue
                z.write(os.path.join(base, f), f"{top}/AIMPSim/" + rel.replace(os.sep, "/"))
        z.write(os.path.join(AI, "README.md"), f"{top}/README_AIMPSim.md")
    os.replace(zpath + ".part", zpath)
    with zipfile.ZipFile(zpath) as z:
        bad = z.testzip()
    if bad:
        sys.exit(f"{zname}: damaged entry {bad}")
    names = [zname]
    for lang in ("EN", "KO"):
        name = f"MPSim-User-Guide-{lang}.pdf"
        shutil.copy2(os.path.join(ROOT, "docs", f"USER_GUIDE_{lang}.pdf"), os.path.join(REL, name))
        names.append(name)
    with open(os.path.join(REL, "SHA256SUMS.txt"), "w", encoding="ascii", newline="\n") as fh:
        for n in names:
            fh.write(f"{sha256(os.path.join(REL, n))}  {n}\n")
    for n in names + ["SHA256SUMS.txt"]:
        print(f"  {n:38s} {os.path.getsize(os.path.join(REL, n)) / 2**20:8.1f} MB")
    print(f"AIMPSim {v}: release files in {REL}")
    return 0


if __name__ == "__main__":
    repository()
    if "--release" in sys.argv:
        sys.exit(release())
