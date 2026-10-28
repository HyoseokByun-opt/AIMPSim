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

import os
import threading
import time
import uuid

from . import __version__
from .lexicon import Lexicon
from .llm import LocalLLM, apply_hints
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
        sid, s = self._session(None if new else sid)
        it = parse(text, self.lex)
        llm_used = []
        needs_help = (it.get("matrix") is None or not it.get("fillers") or not it.get("analyses")
                      or any(u["kind"] in ("material", "content") for u in it.get("unresolved") or []))
        if needs_help and self.llm.configured and s["intent"] is None:
            llm_used = apply_hints(it, self.llm.ask(text), self.lex)
        s["intent"] = it if s["intent"] is None else merge(s["intent"], it)
        if s["intent"].get("lang") != it.get("lang") and it.get("text", "").strip():
            s["intent"]["lang"] = it["lang"]
        s["history"].append({"role": "user", "text": text})
        return self._reply(sid, s, llm_used)

    def answer(self, sid, answers=None, auto=False):
        sid, s = self._session(sid)
        if s["intent"] is None:
            return {"ok": False, "error": "no request in this conversation"}
        for k, v in (answers or {}).items():
            s["answers"][k] = v
        if auto:
            s["answers"]["_auto"] = True
        return self._reply(sid, s, [])

    def _reply(self, sid, s, llm_used):
        it = s["intent"]
        r = self.planner.resolve(it, s["answers"])
        status = ("invalid" if r["problems"] else "need" if any(q["essential"] for q in r["questions"])
                  else "ready")
        return {"ok": True, "session_id": sid, "lang": it["lang"], "status": status, "task": r["task"],
                "questions": r["questions"], "summary": r["summary"], "payload": r["payload"],
                "problems": r["problems"], "auto": r["auto"], "llm_used": llm_used,
                "unresolved": [{k: v for k, v in u.items() if k != "slot"} for u in it.get("unresolved") or []]}

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

    @bp.get("/api/ai/status")
    def ai_status():
        return jsonify(assistant.status())

    @bp.get("/ai/static/<path:fn>")
    def ai_static(fn):
        return send_from_directory(STATIC, fn, max_age=0)

    return bp
