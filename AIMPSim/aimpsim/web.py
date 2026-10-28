"""The AI tab's server side: a Flask blueprint that MPSim registers when
AIMPSim is installed beside it.

POST /api/ai/interpret {text, session_id?}  a request, or a follow-up to one
POST /api/ai/answer {session_id, answers, auto}  answers to the questions
GET  /api/ai/status                         version, lexicon and local model
GET  /ai/static/<file>                      the tab's script and style

Each reply: {session_id, lang, status ('need' - questions with no answer
that only the user can give; 'ready' - the summary can run, questions with
a recommended answer may still be changed; 'invalid' - MPSim refused the
inputs), questions, summary, payload, problems}.
"""
from __future__ import annotations

import copy
import os
import threading
import time
import uuid

from . import __version__
from .lexicon import Lexicon
from . import reader
from .llm import LocalLLM
from .parser import parse
from .planner import Planner, merge

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


class Assistant:
    def __init__(self, host):
        self.host = host
        self.lex = Lexicon(host.get("library") or [])
        self.planner = Planner(self.lex, host)
        self.llm = LocalLLM()
        self.sessions = {}
        self.lock = threading.Lock()

    def _session(self, sid):
        with self.lock:
            now = time.time()
            for k in [k for k, v in self.sessions.items() if now - v["t"] > 6 * 3600]:
                del self.sessions[k]
            if sid and sid in self.sessions:
                s = self.sessions[sid]
                s["t"] = now
                return sid, s
            sid = uuid.uuid4().hex[:12]
            self.sessions[sid] = {"t": now, "intent": None, "answers": {}, "history": []}
            return sid, self.sessions[sid]

    def interpret(self, text, sid=None, new=False):
        """A request or a follow-up. With a local model, the model reads it
        first (the whole request as it is now) and the rules check what it
        read (reader.py); without one, the rules read it alone."""
        sid, s = self._session(None if new else sid)
        rule_it = parse(text, self.lex)
        base = rule_it if s["intent"] is None else merge(s["intent"], rule_it)
        it, llm_used = None, []
        if self.llm.configured:
            state = reader.state_of(s["intent"], s["answers"]) if s["intent"] is not None else None
            js = self.llm.chat_json(reader.messages(self.lex, text, state), reader.SCHEMA)
            if js is not None:
                said = [h["text"] for h in s["history"] if h["role"] == "user"] + [text]
                said += [str(v) for k, v in s["answers"].items() if not k.startswith("_") and isinstance(v, (str, int, float))]
                try:
                    it, rep = reader.build_intent(js, text, self.lex, base, " | ".join(said))
                    if state:
                        self._carry(it, state)
                    self.planner.resolve(copy.deepcopy(it), dict(s["answers"]))
                except Exception as e:                                     # noqa: BLE001
                    # an answer the checks cannot use: the rules read this message alone
                    it, rep, js = None, {"error": f"{type(e).__name__}: {e}"}, js
                llm_used = ["model"] if it is not None else []
                s["llm_raw"], s["llm_report"] = js, rep
                if s["intent"] is not None and it is not None:
                    # the model restated the whole request, answers included
                    for k in list(s["answers"]):
                        if k in ("matrix", "filler_new", "analyses") or k.split(":")[0] in (
                                "filler", "content", "shape", "size", "analysis_pick"):
                            del s["answers"][k]
        s["intent"] = it if it is not None else base
        if s["intent"].get("lang") != rule_it.get("lang") and rule_it.get("text", "").strip():
            s["intent"]["lang"] = rule_it["lang"]
        s["history"].append({"role": "user", "text": text})
        s["llm_used"], s["llm_seconds"] = llm_used, (self.llm.last or {}).get("seconds") if llm_used else None
        return self._reply(sid, s, llm_used)

    def _carry(self, it, state):
        """What a follow-up does not restate stays as it was: a filler keeps
        the content, shape and size it had (the same material, or the one it
        replaces at the same place)."""
        old = state.get("fillers") or []
        new = it.get("fillers") or []
        for i, f in enumerate(new):
            prev = next((o for o in old if reader.resolve_material(str(o.get("material") or ""), "", self.lex) == f.get("id")),
                        None)
            if prev is None and len(old) == len(new):
                prev = old[i]
            if prev is None:
                continue
            if f.get("content") is None and prev.get("percent") not in (None, ""):
                c = self.planner._content_answer(prev["percent"])
                if c:
                    c["basis"] = c.get("basis") or prev.get("basis")
                    c["how"] = "carried"
                    f["content"] = c
            if not f.get("shape") and prev.get("shape"):
                f["shape"], f["shape_src"] = prev["shape"], "text"
            if not f.get("size_um") and prev.get("size_um") not in (None, ""):
                v = self.planner._size_answer(prev["size_um"])
                if v:
                    f["size_um"], f["size_src"] = v, "text"

    def answer(self, sid, answers=None, auto=False):
        sid, s = self._session(sid)
        if s["intent"] is None:
            return {"ok": False, "error": "no request in this conversation"}
        for k, v in (answers or {}).items():
            s["answers"][k] = v
        if auto:
            s["answers"]["_auto"] = True
        return self._reply(sid, s, s.get("llm_used") or [])    # the reading of the request still stands

    def _reply(self, sid, s, llm_used):
        it = s["intent"]
        r = self.planner.resolve(it, s["answers"])
        status = ("invalid" if r["problems"] else "need" if any(q["essential"] for q in r["questions"])
                  else "ready")
        return {"ok": True, "session_id": sid, "lang": it["lang"], "status": status, "task": r["task"],
                "questions": r["questions"], "summary": r["summary"], "payload": r["payload"],
                "problems": r["problems"], "auto": r["auto"], "llm_used": llm_used,
                "llm_seconds": s.get("llm_seconds") if llm_used else None,
                "unresolved": [{k: v for k, v in u.items() if k != "slot"} for u in it.get("unresolved") or []]}

    def warm(self):
        """The AI tab was opened: have the model ready before the first request."""
        self.llm.warm(reader.messages(self.lex, "-"))
        return {"ok": True, "state": self.llm.state}

    def status(self):
        return {"ok": True, "version": __version__, "materials": len(self.lex.library),
                "llm": self.llm.status(), "mpsim": self.host.get("version")}


def blueprint(assistant):
    from flask import Blueprint, jsonify, request, send_from_directory
    bp = Blueprint("aimpsim", __name__)

    @bp.post("/api/ai/interpret")
    def ai_interpret():
        b = request.get_json(force=True, silent=True) or {}
        text = str(b.get("text") or "").strip()
        if not text:
            return jsonify({"ok": False, "error": "empty request"}), 400
        return jsonify(assistant.interpret(text, b.get("session_id"), bool(b.get("new"))))

    @bp.post("/api/ai/answer")
    def ai_answer():
        b = request.get_json(force=True, silent=True) or {}
        return jsonify(assistant.answer(b.get("session_id"), b.get("answers") or {}, bool(b.get("auto"))))

    @bp.post("/api/ai/warm")
    def ai_warm():
        return jsonify(assistant.warm())

    @bp.get("/api/ai/status")
    def ai_status():
        return jsonify(assistant.status())

    @bp.get("/ai/static/<path:fn>")
    def ai_static(fn):
        return send_from_directory(STATIC, fn, max_age=0)

    return bp
