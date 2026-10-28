"""An optional local language model for the sentences the rules leave
unread.

AIMPSim reads requests by rules first (parser.py); a local model is only
asked when the rules leave the matrix, the fillers or the analyses open. It
runs offline: llama.cpp's server (llama-server, MIT licence) on 127.0.0.1
with a GGUF model file, either already running (url) or started by
AIMPSim (server_exe + model). Its answer is held to a JSON schema, and then
treated as a hint, never as a fact:

- material and analysis names go through the same lexicon as typed words
  (a name the library does not hold stays a question);
- a number is kept only if it appears in the sentence (the model may move
  a number to the right material; it may not make one up);
- everything it filled is marked "AI guess - check it" in the summary.

Configuration: aimpsim_config.json next to the aimpsim package, or the
environment variable AIMPSIM_LLM_URL:
    {"llm": {"url": "http://127.0.0.1:8089", "server_exe": "C:/llama/llama-server.exe",
             "model": "C:/models/model.gguf", "threads": 4, "timeout_s": 60}}
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request

SCHEMA = {
    "type": "object",
    "properties": {
        "matrix": {"type": ["string", "null"]},
        "fillers": {"type": "array", "items": {"type": "object", "properties": {
            "material": {"type": "string"}, "percent": {"type": ["number", "null"]},
            "basis": {"type": ["string", "null"], "enum": ["vol", "wt", None]},
            "shape": {"type": ["string", "null"]}, "size_um": {"type": ["number", "null"]}},
            "required": ["material"]}},
        "properties": {"type": "array", "items": {"type": "string"}},
        "task": {"type": ["string", "null"], "enum": ["run", "doe", "calibration", "optimization", None]},
    },
    "required": ["matrix", "fillers", "properties"],
}
PROMPT = ("Extract the composite-material simulation request as JSON. matrix: the resin or matrix material as "
          "written. fillers: each filler material as written, its content in percent if stated (0.55 means 55), "
          "basis vol or wt if stated, shape and size in micrometres if stated. properties: the properties to compute "
          "as written. Use null for anything not stated. Never invent a number.\nRequest: ")


def config_path():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "aimpsim_config.json")


def load_config():
    cfg = {}
    try:
        with open(config_path(), encoding="utf-8") as fh:
            cfg = json.load(fh).get("llm") or {}
    except (OSError, ValueError):
        cfg = {}
    if os.environ.get("AIMPSIM_LLM_URL"):
        cfg["url"] = os.environ["AIMPSIM_LLM_URL"]
    return cfg


class LocalLLM:
    def __init__(self, cfg=None):
        self.cfg = cfg if cfg is not None else load_config()
        self.proc = None
        port = int(self.cfg.get("port") or 8089)
        self.url = (self.cfg.get("url") or (f"http://127.0.0.1:{port}" if self.cfg.get("server_exe") else "")).rstrip("/")

    @property
    def configured(self):
        return bool(self.url)

    def status(self):
        if not self.configured:
            return {"enabled": False, "reason": "no local model configured (aimpsim_config.json); the rules alone read requests"}
        ok = self._ping()
        if not ok and self.cfg.get("server_exe") and self.cfg.get("model"):
            return {"enabled": True, "running": False, "url": self.url, "reason": "starts on first use"}
        return {"enabled": True, "running": ok, "url": self.url}

    def _ping(self):
        try:
            with urllib.request.urlopen(self.url + "/health", timeout=2) as r:
                return r.status == 200
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def _start(self):
        """llama-server on 127.0.0.1 only, with a few threads, so that it does
        not take the cores the solvers use."""
        exe, model = self.cfg.get("server_exe"), self.cfg.get("model")
        if not exe or not model or not os.path.exists(exe) or not os.path.exists(model):
            return False
        port = self.url.rsplit(":", 1)[-1]
        args = [exe, "-m", model, "--host", "127.0.0.1", "--port", port, "-t", str(int(self.cfg.get("threads") or 4)),
                "-c", "2048"]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        t0 = time.time()
        while time.time() - t0 < float(self.cfg.get("start_timeout_s") or 90):
            if self._ping():
                return True
            time.sleep(1.0)
        return False

    def ask(self, text):
        """The model's JSON for a request, or None."""
        if not self.configured:
            return None
        if not self._ping() and not self._start():
            return None
        body = {"messages": [{"role": "user", "content": PROMPT + text}], "temperature": 0, "max_tokens": 400,
                "response_format": {"type": "json_object", "schema": SCHEMA}}
        req = urllib.request.Request(self.url + "/v1/chat/completions", data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=float(self.cfg.get("timeout_s") or 60)) as r:
                out = json.loads(r.read().decode("utf-8"))
            content = out["choices"][0]["message"]["content"]
            return json.loads(content)
        except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError):
            return None

    def close(self):
        if self.proc is not None:
            try:
                self.proc.terminate()
            except OSError:
                pass
            self.proc = None


def apply_hints(intent, hints, lex):
    """Fill what the rules left open from the model's answer, under the
    rules in the module docstring. Returns the names of what was filled."""
    if not isinstance(hints, dict) or not hints:
        return []
    # an answer of the wrong shape is read only where it has the right one
    hints = {"matrix": hints.get("matrix") if isinstance(hints.get("matrix"), str) else None,
             "fillers": [h for h in (hints.get("fillers") if isinstance(hints.get("fillers"), list) else [])
                         if isinstance(h, dict) and isinstance(h.get("material"), str)],
             "properties": [p for p in (hints.get("properties") if isinstance(hints.get("properties"), list) else [])
                            if isinstance(p, str)],
             "task": hints.get("task") if isinstance(hints.get("task"), str) else None}
    for h in hints["fillers"]:
        for k in ("percent", "size_um"):
            if not isinstance(h.get(k), (int, float)) or isinstance(h.get(k), bool):
                h[k] = None
    text = intent.get("norm") or ""
    numbers = {float(x) for x in re.findall(r"\d+(?:\.\d+)?", text)}
    filled = []

    def resolve(word):
        word = (word or "").strip()
        if not word:
            return None, None
        ms = [m for m in lex.scan(word) if m["kind"] == "material" and not isinstance(m["key"], tuple)]
        if ms:
            return ms[0]["key"], ms[0]
        best = lex.fuzzy_material(word)
        if best and best[0][1] >= 0.8:
            return best[0][0], None
        return None, None

    def said(v):
        return v is not None and (v in numbers or round(v / 100.0, 6) in numbers or round(v * 100.0, 6) in numbers)

    if (intent.get("matrix") is None or not intent["matrix"].get("id")) and hints.get("matrix"):
        mid, _ = resolve(hints["matrix"])
        if mid:
            intent["matrix"] = {"id": mid, "choices": [], "spans": [], "text": hints["matrix"], "how": "llm", "score": 0.0,
                                "kind": "material", "alts": [], "role": "matrix", "content": None}
            filled.append("matrix")
    named = [f for f in intent.get("fillers") or [] if f.get("id")]
    unnamed = [f for f in intent.get("fillers") or [] if not f.get("id")]
    have = {f.get("id") for f in named}
    for h in hints.get("fillers") or []:
        mid, _ = resolve(h.get("material"))
        if not mid or mid in have or (intent.get("matrix") or {}).get("id") == mid:
            continue
        pct = h.get("percent")
        if pct is not None and pct <= 1.0:
            pct = 100.0 * pct
        content = None
        if pct is not None and said(pct):
            content = {"value": float(pct), "basis": h.get("basis") if h.get("basis") in ("vol", "wt") else None,
                       "how": "llm", "raw": str(h.get("percent"))}
        size = h.get("size_um") if h.get("size_um") is not None and said(h["size_um"]) else None
        shape = None
        if h.get("shape"):
            sm = [m for m in lex.scan(h["shape"]) if m["kind"] == "shape"]
            shape = sm[0]["key"] if sm else None
        if unnamed:                    # the model names a filler the rules saw but could not name
            gone = unnamed.pop(0)
            intent["fillers"] = [f for f in intent["fillers"] if f is not gone]
            if content is None and gone.get("content") is not None:
                content = gone["content"]
        intent["fillers"].append({"id": mid, "choices": [], "spans": [], "text": h.get("material"), "how": "llm",
                                  "score": 0.0, "kind": "material", "alts": [], "role": "filler", "content": content,
                                  "size_um": size, "shape": shape, "size_src": "llm" if size else None,
                                  "shape_src": "llm" if shape else None, "aspect": None, "length_um": None,
                                  "thickness_um": None, "std_um": None, "cv": None})
        have.add(mid)
        filled.append("filler")
    if not intent.get("analyses"):
        for p in hints.get("properties") or []:
            best = lex.fuzzy_term(p, "analysis")
            ms = [m for m in lex.scan(p) if m["kind"] == "analysis"]
            key = ms[0]["key"] if ms else (best[0][0] if best and best[0][1] >= 0.8 else None)
            if key and key not in intent["analyses"]:
                intent["analyses"].append(key)
                filled.append("analysis")
    if not intent.get("task") and hints.get("task") in ("doe", "calibration", "optimization"):
        intent["task"] = hints["task"]
    return filled
