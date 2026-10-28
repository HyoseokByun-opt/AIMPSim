"""The local language model: llama.cpp's server (llama-server, MIT licence)
on 127.0.0.1 with a GGUF model file, either already running (url) or
started by AIMPSim (server_exe + model). It runs offline. reader.py builds
the chat and checks the answer; this module only starts the server and
returns the answer, held to a JSON schema, or None.

The model shipped with AIMPSim is found without any setting: llama-server
in AIMPSim/llm/bin/ and the model (one .gguf, or the first part of a split
one) in AIMPSim/llm/models/. aimpsim_config.json next to the aimpsim
package, or the environment variable AIMPSIM_LLM_URL, overrides it; "off"
in the file turns the model off:
    {"llm": {"url": "http://127.0.0.1:8089", "server_exe": "C:/llama/llama-server.exe",
             "model": "C:/models/model.gguf", "threads": 6, "timeout_s": 120}}
    {"llm": "off"}
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request


def config_path():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "aimpsim_config.json")


def bundled():
    """llama-server and the model shipped in AIMPSim/llm/, or {}."""
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "llm")
    exe = os.path.join(base, "bin", "llama-server.exe" if os.name == "nt" else "llama-server")
    mdir = os.path.join(base, "models")
    if not os.path.isfile(exe) or not os.path.isdir(mdir):
        return {}
    # every model there, a split one only with all its parts; the largest is used (the 4B over the 2B)
    files = [f for f in os.listdir(mdir) if f.endswith(".gguf") and not f.startswith("mmproj")]
    models = []
    for f in files:
        m = re.match(r"(.*)-00001-of-(\d{5})\.gguf$", f)
        if m:
            parts = [f"{m.group(1)}-{i:05d}-of-{m.group(2)}.gguf" for i in range(1, int(m.group(2)) + 1)]
            if all(p in files for p in parts):
                models.append((sum(os.path.getsize(os.path.join(mdir, p)) for p in parts), f))
        elif "-of-" not in f:
            models.append((os.path.getsize(os.path.join(mdir, f)), f))
    if not models:
        return {}
    cores = os.cpu_count() or 4
    return {"server_exe": exe, "model": os.path.join(mdir, max(models)[1]), "threads": max(2, min(4, cores // 2))}


def load_config():
    cfg = None
    try:
        with open(config_path(), encoding="utf-8") as fh:
            cfg = json.load(fh).get("llm")
    except (OSError, ValueError):
        cfg = None
    if cfg == "off":
        return {}
    cfg = dict(cfg) if isinstance(cfg, dict) else bundled()
    if os.environ.get("AIMPSIM_LLM_URL"):
        cfg["url"] = os.environ["AIMPSIM_LLM_URL"]
    return cfg


def _free_port():
    import socket
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        return so.getsockname()[1]


def _tie_to_parent(proc):
    """Windows: put the server in a job that ends with this process, so that
    it never outlives MPSim (closed, crashed or killed). Returns the job
    handle, which must stay open; None elsewhere or when it fails."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class Io(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ("r", "w", "o", "rb", "wb", "ob")]

        class Extended(ctypes.Structure):
            _fields_ = [("Basic", Basic), ("Io", Io), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        job = k32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = Extended()
        info.Basic.LimitFlags = 0x2000                  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            return None
        if not k32.AssignProcessToJobObject(job, wintypes.HANDLE(int(proc._handle))):
            return None
        return job
    except (OSError, AttributeError, ValueError):
        return None


class LocalLLM:
    def __init__(self, cfg=None):
        self.cfg = cfg if cfg is not None else load_config()
        self.proc = None
        self.job = None
        self.last = {}
        self.lock = threading.Lock()
        self.state = "off"
        self.used = time.time()
        self.idle_s = 60.0 * float(self.cfg.get("idle_minutes", 15) or 0)
        # a server already running (url), or one AIMPSim starts on a free port of its own
        port = self.cfg.get("port")
        self.url = (self.cfg.get("url") or (f"http://127.0.0.1:{int(port)}" if port and self.cfg.get("server_exe")
                                            else "")).rstrip("/")

    @property
    def configured(self):
        return bool(self.url or (self.cfg.get("server_exe") and self.cfg.get("model")))

    def status(self):
        if not self.configured:
            return {"enabled": False, "reason": "no local model (AIMPSim/llm/ or aimpsim_config.json); the rules alone read requests"}
        ok = self._ping()
        if not ok and self.cfg.get("server_exe") and self.cfg.get("model"):
            return {"enabled": True, "running": False, "state": self.state, "url": self.url,
                    "model": os.path.basename(self.cfg.get("model") or "") or None, "reason": "starts on first use"}
        return {"enabled": True, "running": ok, "state": self.state if self.state != "off" or not ok else "ready",
                "url": self.url,
                "model": os.path.basename(self.cfg.get("model") or "") or None}

    def _ping(self):
        if not self.url:
            return False
        try:
            with urllib.request.urlopen(self.url + "/health", timeout=2) as r:
                return r.status == 200
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def _start(self):
        with self.lock:
            if self._ping():
                return True
            ok = self._start_locked()
            self.state = "ready" if ok else "failed"
            return ok

    def _start_locked(self):
        """llama-server on 127.0.0.1 only, with a few threads, so that it does
        not take the cores the solvers use."""
        exe, model = self.cfg.get("server_exe"), self.cfg.get("model")
        if not exe or not model or not os.path.exists(exe) or not os.path.exists(model):
            return False
        if not self.cfg.get("port"):
            self.url = f"http://127.0.0.1:{_free_port()}"
        port = self.url.rsplit(":", 1)[-1]
        args = [exe, "-m", model, "--host", "127.0.0.1", "--port", port, "-t", str(int(self.cfg.get("threads") or 4)),
                "-c", str(int(self.cfg.get("ctx") or 8192)), "-np", "1", "--no-webui"]
        args += [str(a) for a in self.cfg.get("args") or []]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        log = self.cfg.get("log")
        out = open(log, "ab") if log else subprocess.DEVNULL
        self.proc = subprocess.Popen(args, stdout=out, stderr=out, creationflags=flags)
        self.job = _tie_to_parent(self.proc)
        self.used = time.time()
        if self.idle_s > 0:
            threading.Thread(target=self._watch_idle, args=(self.proc,), daemon=True).start()
        t0 = time.time()
        while time.time() - t0 < float(self.cfg.get("start_timeout_s") or 180):
            if self._ping():
                return True
            if self.proc.poll() is not None:
                return False
            time.sleep(0.5)
        return False

    def _watch_idle(self, proc):
        """End the server when it has not been asked for idle_minutes (its
        memory goes back to the solvers); the next request starts it again."""
        while self.proc is proc and proc.poll() is None:
            time.sleep(min(30.0, self.idle_s))
            if self.proc is proc and time.time() - self.used > self.idle_s:
                with self.lock:
                    if self.proc is proc:
                        self.close()
                        self.state = "off"
                return

    def chat_json(self, msgs, schema, max_tokens=600):
        """The model's answer to a chat, held to a JSON schema; None when
        there is no model or no usable answer."""
        if not self.configured:
            return None
        self.used = time.time()
        if not self._ping() and not self._start():
            return None
        self.used = time.time()
        body = {"messages": msgs, "temperature": 0, "max_tokens": max_tokens, "cache_prompt": True,
                "response_format": {"type": "json_object", "schema": schema},
                "chat_template_kwargs": {"enable_thinking": False}}
        req = urllib.request.Request(self.url + "/v1/chat/completions", data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=float(self.cfg.get("timeout_s") or 120)) as r:
                out = json.loads(r.read().decode("utf-8"))
            self.last = {"seconds": round(time.time() - t0, 2), "usage": out.get("usage"),
                         "timings": out.get("timings")}
            content = out["choices"][0]["message"]["content"]
            return json.loads(content)
        except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError, TypeError):
            self.last = {"seconds": round(time.time() - t0, 2), "error": True}
            return None

    def warm(self, msgs):
        """Start the server and read the fixed part of the chat (instructions
        and examples) once, so that the first request is answered as fast as
        the next ones. Runs in the background; self.state tells how far."""
        if not self.configured or self.state in ("starting", "ready"):
            return

        def go():
            self.state = "starting"
            if not (self._ping() or self._start()):
                self.state = "failed"
                return
            self.state = "starting"          # up, but still reading its instructions
            body = {"messages": msgs, "temperature": 0, "max_tokens": 1, "cache_prompt": True,
                    "chat_template_kwargs": {"enable_thinking": False}}
            req = urllib.request.Request(self.url + "/v1/chat/completions", data=json.dumps(body).encode("utf-8"),
                                         headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=600) as r:
                    r.read()
                self.state = "ready"
            except (urllib.error.URLError, OSError, ValueError):
                self.state = "failed"
        threading.Thread(target=go, daemon=True).start()

    def close(self):
        if self.proc is not None:
            try:
                self.proc.terminate()
            except OSError:
                pass
            self.proc = None
