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

    def loop_answer(self, text, lang="en"):
        """An option id as it is, or the person's words read as one: a material of the library, wt/vol, stop.
        A whole request (a matrix and a filler with a content, or an analysis) is not an answer."""
        import re
        t = text.strip()
        if re.fullmatch(r"(?:material|basis):[\w.-]+|stop", t):
            return t
        low = t.lower()
        if re.search(r"멈춰|멈춤|중지|그만|\bstop\b|취소|cancel", low):
            return "stop"
        it = parse(t, self.lex)
        whole = (bool((it.get("matrix") or {}).get("id")) and any(f.get("content") for f in it.get("fillers") or [])) \
            or bool(it.get("analyses")) or len(t) > 60
        if whole:
            return ""
        if re.search(r"중량|무게|\bwt\b|wt%|weight", low):
            return "basis:wt"
        if re.search(r"부피|체적|\bvol\b|vol%|volume", low):
            return "basis:vol"
        ids = [f.get("id") for f in it.get("fillers") or [] if f.get("id")]
        if (it.get("matrix") or {}).get("id"):
            ids.append(it["matrix"]["id"])
        return f"material:{ids[0]}" if ids else ""

    def loop_command(self, text, kinds=(), lang="en", waiting=False):
        """{command: stop | answer | condition | none, ...} for words typed while loops run.
        kinds: the kinds of the loops running; waiting: a calibration waits for an answer. An answer is
        taken only then, and never from a whole new request (that one is read as a request; the loops go on)."""
        import re
        from . import design as DZ
        if isinstance(kinds, str):
            kinds = (kinds,)
        low = text.lower().strip()
        if re.search(r"^(?:멈춰|멈춤|중지|그만|stop|halt|취소|cancel)|멈춰|중지해|그만해|stop it", low):
            return {"command": "stop"}
        if waiting and "cal" in kinds:
            a = self.loop_answer(text, lang)
            if a and a != "stop":
                return {"command": "answer", "answer": a}
        if "design" in kinds and len(text) <= 80:
            d = DZ.read(text)
            it = parse(text, self.lex)
            if not ((it.get("matrix") or {}).get("id") and it.get("fillers")):
                cond = {}
                if d.get("content_max") is not None:
                    cond["content_cap"] = float(d["content_max"])
                m = re.search(DZ.TOL, low)
                if m:
                    cond["tol"] = float(m.group(1) or m.group(2))
                if cond:
                    return {"command": "condition", "condition": cond}
        return {"command": "none"}

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

    @bp.post("/api/ai/calibration/next")
    def ai_cal_next():
        """After a calibration: done, run again with another range or other
        unknowns, ask the person, or stop - and why (calcheck.next_round).
        With an answer (an option's id or the person's words): the form and
        unknowns that answer leads to (calcheck.apply_answer, precheck)."""
        from . import calcheck as CC
        from .loop import max_rounds
        b = request.get_json(force=True, silent=True) or {}
        cal, result = b.get("cal") or {}, b.get("result") or {}
        lang = b.get("lang") or "en"
        ko = lang == "ko"
        lib = assistant.lex.library
        try:
            form = assistant.planner._filled(b.get("form") or {})
            ans = b.get("answer")
            if ans:
                ans = assistant.loop_answer(str(ans), lang)
                if ans == "stop":
                    return jsonify({"ok": True, "action": "stop", "why": "asked",
                                    "text": "보정을 멈췄습니다." if ko else "The calibration was stopped."})
                if not ans:
                    return jsonify({"ok": True, "action": "ask", "why": "unclear", "options": CC.options(form, cal, lib),
                                    "text": ("어느 쪽인지 알 수 없습니다. 아래에서 고르거나 재료 이름이나 wt%/vol%로 알려 주세요." if ko
                                             else "That is not clear: choose below, or name a material or wt%/vol%.")})
                form2, cal2 = CC.apply_answer(form, cal, ans, lib)
                asked = [u.get("key") or u["path"] for u in cal.get("unknowns") or []]
                chk = CC.precheck(form2, cal2, asked, lang) or {}
                plans = chk.get("plans") or []
                pick = plans[chk.get("choice", 0)] if plans else {"unknowns": cal.get("unknowns"), "keys": asked}
                out = {"action": "rerun", "why": "answer", "form": form2, "unknowns": pick["unknowns"],
                       "keys": "+".join(pick["keys"]), "reachable": chk.get("reachable")}
                kind_, _, val_ = ans.partition(":")
                shown = ((lib.get(val_) or {}).get("name") or val_) if kind_ == "material" else (f"{val_}%" if kind_ == "basis" else ans)
                if ko:
                    out["text"] = (f"{shown}(으)로 바꿔 다시 점검했습니다: "
                                   + ("측정에 닿는 조합으로 보정합니다." if chk.get("reachable")
                                      else "유효매질 점검으로는 아직 닿지 않지만 RVE로 보정해 봅니다."))
                else:
                    out["text"] = (f"Changed to {shown} and checked again: "
                                   + ("calibrating the set that reaches the data." if chk.get("reachable")
                                      else "the mean field does not reach the data yet; the RVE calibration is run."))
                out["ok"] = True
                return jsonify(out)
            if not cal.get("unknowns") or not result.get("unknowns"):
                return jsonify({"ok": False, "error": "a calibration and its result are needed"}), 400
            out = CC.next_round(form, cal, cal["unknowns"], result, list(b.get("tried") or []), lang, lib)
            limit = max_rounds()
            if out["action"] == "rerun" and limit and int(b.get("round") or 0) >= limit:
                out = {"action": "stop", "why": "rounds"}
            out["text"] = CC.explain(out, cal["unknowns"], result, lang, form, lib)
        except Exception as e:                                     # noqa: BLE001
            return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500
        out["ok"] = True
        return jsonify(out)

    @bp.post("/api/ai/design/next")
    def ai_design_next():
        """One round of a design study (loop.design_round)."""
        from flask import current_app
        from . import loop as LP
        b = request.get_json(force=True, silent=True) or {}
        store = getattr(current_app, "doe", None)
        s = store.get(str(b.get("doe_id") or "")) if store is not None else None
        if s is None:
            return jsonify({"ok": False, "error": "DOE study not found"}), 404
        spec = dict(b.get("design") or {})
        rows, _ = store.rows(s, current_app.queue)
        state = dict(b.get("state") or {})
        chk = dict(state.get("check") or {})
        if chk.get("job") and chk.get("value") is not None and chk.get("real") is None:
            # the check asked for more than the recipe (the packing's shortfall): the content it holds
            try:
                import importlib
                import json as _json
                import os as _os
                job = current_app.queue.get(chk["job"])
                with open(_os.path.join(job.out_dir, "result.json"), encoding="utf-8") as fh:
                    got = importlib.import_module(type(store).__module__).realised(s, _json.load(fh))
                if "real_filler" in got:
                    chk["real"] = float(got["real_filler"][2])
                    state["check"] = chk
            except Exception:                                      # noqa: BLE001
                pass
        try:
            out = LP.design_round(s, rows, spec, state)
            unit = {"k": "W/m·K", "sigma": "S/m", "alpha": "ppm/K", "E": "GPa"}.get((spec.get("target") or {}).get("property"), "")
            out["text"] = LP.explain(out, "design", b.get("lang") or "en", unit)
        except Exception as e:                                     # noqa: BLE001
            return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500
        out["ok"] = True
        return jsonify(out)

    @bp.post("/api/ai/opt/next")
    def ai_opt_next():
        """One round of an optimisation study (loop.opt_round)."""
        from flask import current_app
        from . import loop as LP
        b = request.get_json(force=True, silent=True) or {}
        store = getattr(current_app, "doe", None)
        s = store.get(str(b.get("doe_id") or "")) if store is not None else None
        if s is None:
            return jsonify({"ok": False, "error": "DOE study not found"}), 404
        rows, metrics = store.rows(s, current_app.queue)
        keys = [m["key"] for m in metrics if not str(m["key"]).startswith("real_")]
        want = {"thermal": "k", "electrical": "sigma", "dielectric": "eps", "magnetic": "mu", "cte": "alpha",
                "viscosity": "mu_r", "emi": "se", "moisture": "D_w", "thermomech": "warp", "joule": "T_joule"}.get(
            b.get("analysis") or "", "")
        resp = want if want in keys else (keys[0] if keys else None)
        if resp is None:
            return jsonify({"ok": False, "error": "the study gave no response yet"}), 400
        try:
            out = LP.opt_round(s, rows, resp, b.get("goal") or "max", b.get("target"), b.get("state") or {})
            unit = next((m.get("unit") for m in metrics if m["key"] == resp), "")
            out["text"] = LP.explain(out, "opt", b.get("lang") or "en", unit)
            out["response"] = resp
        except Exception as e:                                     # noqa: BLE001
            return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500
        out["ok"] = True
        return jsonify(out)

    @bp.post("/api/ai/loop/command")
    def ai_loop_command():
        """Words typed while a study or a calibration runs: stop it, answer its
        question, or a condition for its next round ("최대 함량은 55%로")."""
        b = request.get_json(force=True, silent=True) or {}
        out = assistant.loop_command(str(b.get("text") or ""), b.get("kinds") or b.get("kind") or (),
                                     b.get("lang") or "en", bool(b.get("waiting")))
        out["ok"] = True
        return jsonify(out)

    @bp.post("/api/ai/design")
    def ai_design():
        """The recipe of a finished design study (design.recommend): the
        study's runs from MPSim's DOE store, the design part of the payload
        that created it."""
        from flask import current_app
        from . import design as DZ
        b = request.get_json(force=True, silent=True) or {}
        store = getattr(current_app, "doe", None)
        s = store.get(str(b.get("doe_id") or "")) if store is not None else None
        if s is None:
            return jsonify({"ok": False, "error": "DOE study not found"}), 404
        spec = b.get("design") or {}
        if not (spec.get("target") or {}).get("property"):
            return jsonify({"ok": False, "error": "no design target"}), 400
        rows, _ = store.rows(s, current_app.queue)
        try:
            out = DZ.recommend(s, rows, spec)
        except Exception as e:                                     # noqa: BLE001
            return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500
        return jsonify(out)

    @bp.get("/ai/static/<path:fn>")
    def ai_static(fn):
        return send_from_directory(STATIC, fn, max_age=0)

    return bp
