"""Fetch the local language model of the AI tab into AIMPSim/llm/.

    python AIMPSim/get_model.py              llama-server and the default model
    python AIMPSim/get_model.py --list       the models it knows
    python AIMPSim/get_model.py --model qwen3.5-4b
    python AIMPSim/get_model.py --from D:/usb/AIMPSim-model     copy instead of download (no internet)

Every file is checked against its SHA-256 before it is used. The offline
package already holds both; this script is for an installation from the
source (1_INSTALL.bat) or for another model. Without a model the AI tab
reads requests by rules alone.

llama.cpp (llama-server) is MIT-licensed; the models are Apache 2.0. Their
licences are written next to them.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
LLM = os.path.join(HERE, "llm")

LLAMA = {"build": "b11606",
         "url": "https://github.com/ggml-org/llama.cpp/releases/download/b11606/llama-b11606-bin-win-cpu-x64.zip",
         "sha256": "8c0f4f2a1b808eebe00e738edf027cceea1aa9e6c883618bd37151666093f1b4",
         "license": "https://raw.githubusercontent.com/ggml-org/llama.cpp/b11606/LICENSE"}
# the files llama-server needs (the CPU back ends are chosen at start for the processor)
LLAMA_KEEP = ("llama-server.exe", "llama-server-impl.dll", "llama.dll", "llama-common.dll", "mtmd.dll", "ggml.dll",
              "ggml-base.dll", "ggml-rpc.dll", "libomp.dll", "LICENSE-LLVM-OpenMP")

MODELS = {
    "qwen3.5-2b": {"file": "Qwen3.5-2B-Q4_K_M.gguf", "size": 1280835840,
                   "url": "https://huggingface.co/unsloth/Qwen3.5-2B-GGUF/resolve/main/Qwen3.5-2B-Q4_K_M.gguf",
                   "sha256": "aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223",
                   "license": "https://huggingface.co/Qwen/Qwen3.5-2B/resolve/main/LICENSE",
                   "source": "Qwen/Qwen3.5-2B (Qwen team, Alibaba Cloud), Apache 2.0; GGUF by unsloth"},
    "qwen3.5-4b": {"file": "Qwen3.5-4B-Q4_K_M.gguf", "size": 2740937888,
                   "url": "https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/main/Qwen3.5-4B-Q4_K_M.gguf",
                   "sha256": "00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4",
                   "license": "https://huggingface.co/Qwen/Qwen3.5-4B/resolve/main/LICENSE",
                   "source": "Qwen/Qwen3.5-4B (Qwen team, Alibaba Cloud), Apache 2.0; GGUF by unsloth"},
    "gemma-4-e2b": {"file": "gemma-4-E2B-it-Q4_0.gguf", "size": 2841481184,
                    "url": "https://huggingface.co/ggml-org/gemma-4-E2B-it-GGUF/resolve/main/gemma-4-E2B-it-Q4_0.gguf",
                    "sha256": "8e30dff3ac4c8434c49a7036fa15564bdbb6044e42bf04550bf1a096ad7e6a52",
                    "license": None,
                    "source": "google/gemma-4-E2B-it (Google), Apache 2.0; GGUF by ggml-org"},
    "granite-4.2-3b": {"file": "granite-4.2-3b-Q4_K_M.gguf", "size": 2244011552,
                       "url": "https://huggingface.co/ibm-granite/granite-4.2-3b-GGUF/resolve/main/granite-4.2-3b-Q4_K_M.gguf",
                       "sha256": "e0406663965846ae22a403456eb826ccce5f450840491f71952f18a7cb78e7d5",
                       "license": None,
                       "source": "ibm-granite/granite-4.2-3b (IBM), Apache 2.0"},
}
DEFAULT = "qwen3.5-2b"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch(url, dst, sha=None, size=None):
    """Download url to dst (resuming a broken download), checked."""
    part = dst + ".part"
    have = os.path.getsize(part) if os.path.exists(part) else 0
    req = urllib.request.Request(url, headers={"Range": f"bytes={have}-"} if have else {})
    with urllib.request.urlopen(req, timeout=60) as r:
        if have and r.status != 206:
            have = 0
        total = (size or int(r.headers.get("Content-Length") or 0) + have)
        with open(part, "ab" if have else "wb") as fh:
            done, last = have, -1
            while True:
                block = r.read(1 << 20)
                if not block:
                    break
                fh.write(block)
                done += len(block)
                pct = int(100 * done / total) if total else 0
                if pct != last and pct % 5 == 0:
                    print(f"\r  {os.path.basename(dst)}: {pct:3d} % of {total / 2**20:,.0f} MB", end="", flush=True)
                    last = pct
    print()
    if sha and sha256(part) != sha:
        os.remove(part)
        sys.exit(f"{os.path.basename(dst)}: the SHA-256 does not match - removed, run again")
    os.replace(part, dst)


def get_llama(src=None):
    bindir = os.path.join(LLM, "bin")
    if os.path.isfile(os.path.join(bindir, "llama-server.exe")) and not src:
        print("llama-server: already in AIMPSim/llm/bin")
        return
    os.makedirs(bindir, exist_ok=True)
    if src:
        for f in os.listdir(os.path.join(src, "bin")):
            shutil.copy2(os.path.join(src, "bin", f), os.path.join(bindir, f))
        print("llama-server: copied")
        return
    z = os.path.join(LLM, "llama.zip")
    print(f"llama.cpp {LLAMA['build']} (MIT):")
    fetch(LLAMA["url"], z, LLAMA["sha256"])
    with zipfile.ZipFile(z) as zf:
        for n in zf.namelist():
            b = os.path.basename(n)
            if b in LLAMA_KEEP or (b.startswith("ggml-cpu-") and b.endswith(".dll")):
                with zf.open(n) as fi, open(os.path.join(bindir, b), "wb") as fo:
                    shutil.copyfileobj(fi, fo)
    os.remove(z)
    try:
        fetch(LLAMA["license"], os.path.join(bindir, "LICENSE-llama.cpp"))
    except OSError:
        pass


def get_model(key, src=None):
    m = MODELS[key]
    mdir = os.path.join(LLM, "models")
    os.makedirs(mdir, exist_ok=True)
    for f in os.listdir(mdir):         # one model at a time: the AI tab uses the first it finds
        if f.endswith(".gguf") and f != m["file"]:
            os.remove(os.path.join(mdir, f))
    dst = os.path.join(mdir, m["file"])
    if os.path.exists(dst) and os.path.getsize(dst) == m["size"]:
        print(f"{m['file']}: already there")
    elif src:
        print(f"{m['file']}: copying and checking")
        shutil.copy2(os.path.join(src, "models", m["file"]), dst + ".part")
        if sha256(dst + ".part") != m["sha256"]:
            os.remove(dst + ".part")
            sys.exit(f"{m['file']}: the SHA-256 does not match")
        os.replace(dst + ".part", dst)
    else:
        print(f"{m['file']} ({m['size'] / 2**30:.1f} GB), {m['source']}:")
        fetch(m["url"], dst, m["sha256"], m["size"])
    with open(os.path.join(mdir, "MODEL.txt"), "w", encoding="utf-8") as fh:
        fh.write(f"{m['file']}\n{m['source']}\nSHA-256 {m['sha256']}\n{m['url']}\n")
    if m.get("license") and not src:
        try:
            fetch(m["license"], os.path.join(mdir, "LICENSE-" + key))
        except OSError:
            pass


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=DEFAULT, choices=sorted(MODELS))
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--from", dest="src", help="a folder holding bin/ and models/ to copy from")
    a = ap.parse_args()
    if a.list:
        for k, m in MODELS.items():
            print(f"{k:16s} {m['size'] / 2**30:4.1f} GB  {m['source']}" + ("  (default)" if k == DEFAULT else ""))
        return 0
    get_llama(a.src)
    get_model(a.model, a.src)
    print("Done. Restart MPSim; the AI tab uses the model (AIMPSim/llm/).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
