"""AIMPSim self-test: every request of tests/corpus.py read and planned, the
result checked against what it must be read as; then the local-model
adapter against a stand-in server (no model needed); then, when MPSim is
found beside AIMPSim, every ready payload validated by MPSim itself.

    python tests/run_tests.py            (from the AIMPSim folder)
    python tests/run_tests.py --only 실리카
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from aimpsim.lexicon import Lexicon  # noqa: E402
from aimpsim.parser import parse  # noqa: E402
from aimpsim.planner import Planner  # noqa: E402

sys.path.insert(0, HERE)
from corpus import CASES  # noqa: E402


def find_mpsim():
    for p in (os.environ.get("MPSIM_APP"), os.path.join(os.path.dirname(ROOT), "v5", "app"),
              os.path.join(os.path.dirname(ROOT), "MPSim", "app"), os.path.join(ROOT, "..", "app")):
        if p and os.path.isfile(os.path.join(p, "mpsim", "spec.py")):
            return os.path.abspath(p)
    return None


def host_for(app_dir):
    if not app_dir:
        return {"cores": 18}
    sys.path.insert(0, app_dir)
    from mpsim import materials as M
    from mpsim import spec as S
    from mpsim.calibrate import fill_props

    def validate(form):
        try:
            S.normalize(fill_props(form))
            return None
        except ValueError as e:
            return str(e)
    return {"library": M.load_library()["materials"], "validate": validate, "cores": 18}


def close(a, b, tol=0.01):
    return a is not None and b is not None and abs(float(a) - float(b)) <= tol * max(1.0, abs(float(b)))


def check(text, exp, lex, planner, read=None):
    it = read(text) if read else parse(text, lex)
    r = planner.resolve(it, {})
    errs = []
    mx = (it.get("matrix") or {}).get("id")
    if "matrix" in exp and mx != exp["matrix"]:
        errs.append(f"matrix {mx} != {exp['matrix']}")
    if "fillers" in exp:
        got = it.get("fillers") or []
        if len(got) != len(exp["fillers"]):
            errs.append(f"{len(got)} fillers {[(f.get('id'), (f.get('content') or {}).get('value')) for f in got]} "
                        f"!= {len(exp['fillers'])}")
        for f, e in zip(got, exp["fillers"]):
            fid, val, basis, shape, size = e
            c = f.get("content") or {}
            if fid != "*" and f.get("id") != fid:
                errs.append(f"filler {f.get('id')} != {fid}")
            if val != "*":
                v = c.get("value")
                if "range" in c:
                    v = c["range"][0]
                if val is None and v is not None or val is not None and not close(v, val):
                    errs.append(f"content {v} != {val}")
            if basis != "*" and c.get("basis") != basis:
                errs.append(f"basis {c.get('basis')} != {basis}")
            if shape != "*" and f.get("shape") != shape:
                errs.append(f"shape {f.get('shape')} != {shape}")
            if size != "*" and not ((size is None and f.get("size_um") is None) or close(f.get("size_um"), size)):
                errs.append(f"size {f.get('size_um')} != {size}")
    if "analyses" in exp and set(it.get("analyses") or []) != set(exp["analyses"]):
        errs.append(f"analyses {it.get('analyses')} != {sorted(exp['analyses'])}")
    if "task" in exp and (it.get("task") or "run") != exp["task"]:
        errs.append(f"task {it.get('task')} != {exp['task']}")
    for k in ("quality", "auto", "directions", "seeds", "seed"):
        if k in exp and it.get(k) != exp[k]:
            errs.append(f"{k} {it.get(k)} != {exp[k]}")
    for k, v in (exp.get("parallel") or {}).items():
        if (it.get("parallel") or {}).get(k) != v:
            errs.append(f"parallel {it.get('parallel')} lacks {k}={v}")
    qids = [q["id"] for q in r["questions"]]
    for q in exp.get("ask") or []:
        if not any(x.startswith(q) for x in qids):
            errs.append(f"no question {q} (open: {qids})")
    for q in exp.get("noask") or []:
        if any(x.startswith(q) for x in qids):
            errs.append(f"question {q} asked")
    for e in exp.get("doe") or []:
        what, lo, hi, n = e
        fs = [f for f in it["doe"]["factors"] if f["what"] == what]
        if not fs:
            errs.append(f"no DOE factor {what}")
            continue
        lv = planner._levels(fs[0], it["doe"].get("steps") or (5 if n == "*" else None), it["doe"].get("step"))
        if not close(min(lv), lo) or not close(max(lv), hi) or (n != "*" and len(lv) != n):
            errs.append(f"DOE {what} {lv} != {lo}..{hi} x{n}")
    if "measurements" in exp:
        got = [(m["property"], m["value"], m.get("content")) for m in it["calibration"]["measurements"]]
        if len(got) != len(exp["measurements"]) or any(g[0] != e[0] or not close(g[1], e[1]) or
                                                      (e[2] is not None and not close(g[2], e[2]))
                                                      for g, e in zip(got, exp["measurements"])):
            errs.append(f"measurements {got} != {exp['measurements']}")
    if "unknowns" in exp and it["calibration"]["unknowns"] != exp["unknowns"]:
        errs.append(f"unknowns {it['calibration']['unknowns']} != {exp['unknowns']}")
    if exp.get("problems") and not planner.resolve(it, {"_auto": True})["problems"]:
        errs.append("no problem reported")
    if exp.get("ready") and r["payload"] is None:
        errs.append(f"not ready: {qids} {r['problems']}")
    if exp.get("ready_auto"):
        r2 = planner.resolve(it, {"_auto": True})
        if r2["payload"] is None:
            errs.append("not ready with auto: " + str([q["id"] for q in r2["questions"]]))
    return errs, r


def test_conversation(host):
    """A request answered over several messages and clicks, as in the AI tab
    (the rules alone: the model's turn is test_model_first)."""
    from aimpsim.llm import LocalLLM
    from aimpsim.web import Assistant
    a = Assistant(host)
    a.llm = LocalLLM({})
    errs = []
    r = a.interpret("에폭시에 알루미나 넣은거 열전도도")
    if r["status"] != "need" or not any(q["id"] == "content:0" for q in r["questions"]):
        errs.append(f"turn 1: {r['status']} {[q['id'] for q in r['questions']]}")
    r = a.interpret("55%", r["session_id"])
    if r["status"] != "ready" or any(q["id"] == "content:0" for q in r["questions"]):
        errs.append(f"turn 2 (55%): {r['status']} {[q['id'] for q in r['questions']]}")
    r = a.interpret("구형이고 입경 5마이크로", r["session_id"])
    ph = (r["payload"] or {}).get("form", {}).get("phases", [{}])[0]
    if ph.get("shape") != "sphere" or ph.get("size", {}).get("d") != 5.0:
        errs.append(f"turn 3 (shape, size): {ph}")
    r = a.answer(r["session_id"], {"basis": "wt", "quality": "fast"})
    ph = (r["payload"] or {}).get("form", {}).get("phases", [{}])[0]
    if ph.get("fraction", {}).get("basis") != "wt" or r["payload"]["form"]["rve"]["quality"] != "fast":
        errs.append(f"clicks (wt, fast): {ph.get('fraction')} {r['payload']['form']['rve']}")
    r = a.answer(r["session_id"], {}, auto=True)
    if r["questions"] or r["status"] != "ready":
        errs.append(f"decide for me: {[q['id'] for q in r['questions']]}")
    # changes in later messages
    c = a.interpret("에폭시에 구형 알루미나 50 vol% 10um 열전도도 알아서", new=True)
    sid = c["session_id"]

    def form(r):
        return (r.get("payload") or {}).get("form") or {}
    steps = [("알루미나 말고 질화붕소로", lambda f: [p["material_id"] for p in f["phases"]] == ["hbn"]
              and f["phases"][0]["fraction"]["value"] == 50),
             ("CTE도 추가해줘", lambda f: set(k for k, v in f["analyses"].items() if v) == {"thermal", "cte"}),
             ("CTE는 빼줘", lambda f: set(k for k, v in f["analyses"].items() if v) == {"thermal"}),
             ("함량은 40%로", lambda f: f["phases"][0]["fraction"]["value"] == 40),
             ("매트릭스는 실리콘 수지로", lambda f: f["matrix"]["material_id"] == "silicone"),
             ("정확하게", lambda f: f["rve"]["quality"] == "accurate"),
             ("use aluminium nitride instead of boron nitride", lambda f: [p["material_id"] for p in f["phases"]] == ["aln"])]
    for text, ok in steps:
        c = a.interpret(text, sid)
        if not ok(form(c)):
            f = form(c)
            errs.append(f"follow-up '{text}': matrix {f.get('matrix', {}).get('material_id')}, "
                        f"phases {[(p['material_id'], p['fraction']['value']) for p in f.get('phases', [])]}, "
                        f"analyses {f.get('analyses')}, quality {f.get('rve', {}).get('quality')}, status {c['status']}")
    # a new conversation starts clean
    r2 = a.interpret("silicone with 40% alumina, permittivity", new=True)
    if r2["session_id"] == r["session_id"] or (r2["payload"] or {}).get("form", {}).get("matrix", {}).get("material_id") != "silicone" \
            and r2["status"] == "ready":
        errs.append("a new request kept the old conversation")
    return errs


def test_reader_checks(lex, host):
    """The model's answer checked against the sentence (reader.py): what the
    sentence holds is kept - also when it takes a calculation - and what the
    model brought in itself is dropped, so that it is asked for."""
    from aimpsim import reader
    planner = Planner(lex, host)
    errs = []

    def run(text, js):
        it, rep = reader.build_intent(js, text, lex, parse(text, lex))
        return it, rep, planner.resolve(it, {})

    def fl(it):
        return [(f.get("id"), (f.get("content") or {}).get("value")) for f in it["fillers"]]
    cases = [
        # a filler the sentence does not name, and a number it does not hold
        ("열전도 높은 방열 패드 만들고 싶은데 뭘 넣어야 할지 모르겠어",
         {"matrix": {"material": "silicone"}, "fillers": [{"material": "al2o3", "percent": 60}], "analyses": ["thermal"],
          "task": "run"},
         lambda it, rep, r: it.get("matrix") is None and not any(f.get("id") for f in it["fillers"])
         and any(q["id"] in ("matrix", "filler_new") for q in r["questions"]), "an invented material was kept"),
        ("에폭시에 알루미나 넣고 열전도도",
         {"matrix": {"material": "epoxy"}, "fillers": [{"material": "al2o3", "percent": 55}], "analyses": ["thermal"],
          "task": "run"},
         lambda it, rep, r: fl(it) == [("al2o3", None)] and any(q["id"] == "content:0" for q in r["questions"]),
         "an invented content was kept"),
        # calculations from the sentence's numbers
        ("에폭시랑 알루미나 비율을 4대6으로 해서 열전도도",
         {"matrix": {"material": "epoxy"}, "fillers": [{"material": "al2o3", "percent": 60}], "analyses": ["thermal"],
          "task": "run"},
         lambda it, rep, r: fl(it) == [("al2o3", 60.0)], "4:6 -> 60 % was not kept"),
        ("수지 100g에 알루미나 150g 넣으면 열전도도는?",
         {"matrix": None, "fillers": [{"material": "al2o3", "percent": 60, "basis": "wt"}], "analyses": ["thermal"],
          "task": "run"},
         lambda it, rep, r: fl(it) == [("al2o3", 60.0)] and it["fillers"][0]["content"]["basis"] == "wt"
         and any(q["id"] == "matrix" for q in r["questions"]), "150 g in 100 g -> 60 wt% was not kept"),
        ("epoxy with about half alumina by volume, heat",
         {"matrix": {"material": "epoxy"}, "fillers": [{"material": "al2o3", "percent": 50, "basis": "vol"}],
          "analyses": ["thermal"], "task": "run"},
         lambda it, rep, r: fl(it) == [("al2o3", 50.0)], "half -> 50 % was not kept"),
        # a correction and a word taken back: the model's reading wins, the difference is shown
        ("에폭시에 알루미나 55%, 아니 60%로 해줘. 열전도도",
         {"matrix": {"material": "epoxy"}, "fillers": [{"material": "al2o3", "percent": 60}], "analyses": ["thermal"],
          "task": "run"},
         lambda it, rep, r: fl(it) == [("al2o3", 60.0)] and any("60" in n and "55" in n for n in r["notes"]),
         "the correction was not used or not shown"),
        ("알루미나는 아니고 질화붕소를 에폭시에 30% 넣은 경우 열전도도",
         {"matrix": {"material": "epoxy"}, "fillers": [{"material": "hbn", "percent": 30}], "analyses": ["thermal"],
          "task": "run"},
         lambda it, rep, r: fl(it) == [("hbn", 30.0)], "the filler taken back stayed"),
        ("열전도도는 필요없고 CTE만 봐줘, 에폭시에 실리카 50%",
         {"matrix": {"material": "epoxy"}, "fillers": [{"material": "sio2", "percent": 50}], "analyses": ["cte"],
          "task": "run"},
         lambda it, rep, r: it["analyses"] == ["cte"], "the analysis taken back stayed"),
        # material values: the user's own, never the model's
        ("에폭시에 알루미나 55%, 알루미나 열전도도는 우리 제품 기준 200으로, 열전도도 계산",
         {"matrix": {"material": "epoxy"}, "fillers": [{"material": "al2o3", "percent": 55, "props": {"k": 200}}],
          "analyses": ["thermal"], "task": "run"},
         lambda it, rep, r: (it["fillers"][0].get("props") or {}).get("k") == 200.0
         and (r["payload"] is None or r["payload"]["form"]["phases"][0]["props"]["k"] == 200.0), "a given k was not used"),
        ("에폭시에 알루미나 55% 열전도도",
         {"matrix": {"material": "epoxy", "props": {"k": 0.2}}, "fillers": [{"material": "al2o3", "percent": 55,
                                                                             "props": {"k": 30, "E": 380}}],
          "analyses": ["thermal"], "task": "run"},
         lambda it, rep, r: not it["fillers"][0].get("props") and not (it.get("matrix") or {}).get("props"),
         "a material value the sentence does not give was kept"),
        # one-syllable names: silver as a word, not the particle
        ("은가루를 에폭시에 20% 정도 넣었을 때 전기가 통하는지 봐줘",
         {"matrix": {"material": "epoxy"}, "fillers": [{"material": "ag", "percent": 20}], "analyses": ["electrical"],
          "task": "run"},
         lambda it, rep, r: fl(it) == [("ag", 20.0)], "silver powder (은가루) was dropped"),
        ("이것은 에폭시에 실리카 20% 넣은 거야, 유전율",
         {"matrix": {"material": "epoxy"}, "fillers": [{"material": "ag", "percent": 20}], "analyses": ["dielectric"],
          "task": "run"},
         lambda it, rep, r: not any(f.get("id") == "ag" for f in it["fillers"]), "silver was read from the particle 은"),
        # units and sizes
        ("에폭시에 500nm 실리카 30% 넣고 유전율",
         {"matrix": {"material": "epoxy"}, "fillers": [{"material": "sio2", "percent": 30, "size_um": 0.5}],
          "analyses": ["dielectric"], "task": "run"},
         lambda it, rep, r: it["fillers"][0].get("size_um") == 0.5, "500 nm -> 0.5 um was not kept"),
        ("에폭시에 실리카 30% 유전율",
         {"matrix": {"material": "epoxy"}, "fillers": [{"material": "sio2", "percent": 30, "size_um": 8}],
          "analyses": ["dielectric"], "task": "run"},
         lambda it, rep, r: it["fillers"][0].get("size_um") is None, "an invented size was kept"),
        # a DOE with steps the sentence does not give: the steps are asked
        ("에폭시에 알루미나를 40에서 60까지 바꿔가며 열전도도",
         {"matrix": {"material": "epoxy"}, "fillers": [{"material": "al2o3", "percent": None}], "analyses": ["thermal"],
          "task": "doe", "doe": [{"filler": 0, "what": "content", "from": 40, "to": 60, "steps": 7}]},
         lambda it, rep, r: it["task"] == "doe" and it["doe"]["factors"][0]["range"] == (40.0, 60.0)
         and it["doe"]["steps"] is None, "the DOE range was lost or invented steps kept"),
        # amounts instead of percents: the weight percent from them
        ("수지 100g에 알루미나 150g 넣으면 열전도도는?",
         {"matrix": {"material": None, "amount": 100}, "fillers": [{"material": "al2o3", "percent": None, "amount": 150}],
          "analyses": ["thermal"], "task": "run"},
         lambda it, rep, r: fl(it) == [("al2o3", 60.0)] and it["fillers"][0]["content"]["basis"] == "wt",
         "150 g in 100 g of resin was not 60 wt%"),
        ("100 parts epoxy, 150 parts alumina, thermal conductivity please",
         {"matrix": {"material": "epoxy"}, "fillers": [{"material": "al2o3", "percent": 150}], "analyses": ["thermal"],
          "task": "run"},
         lambda it, rep, r: not any((f.get("content") or {}).get("value") == 150 for f in it["fillers"]),
         "150 parts was used as 150 %"),
        # an analysis the sentence gives no reason for is asked; a stiffness is not a test
        ("에폭시에 필러 많이 넣으면 어떻게 돼?",
         {"matrix": {"material": "epoxy"}, "fillers": [], "analyses": ["thermal"], "task": "run"},
         lambda it, rep, r: not it["analyses"], "an analysis the sentence does not point to was kept"),
        ("silicone with boron nitride flakes, 25%, how stiff does it get",
         {"matrix": {"material": "silicone"}, "fillers": [{"material": "hbn", "percent": 25}], "analyses": ["mechtest"],
          "task": "run"},
         lambda it, rep, r: "mechtest" not in it["analyses"], "a mechanical test without a test word was kept"),
        # a comparison: separate runs, never one mixture
        ("Compare alumina vs boron nitride at 30% in epoxy for thermal conductivity",
         {"matrix": {"material": "epoxy"}, "fillers": [{"material": "al2o3", "percent": 30}, {"material": "hbn", "percent": 30}],
          "analyses": ["thermal"], "task": "run"},
         lambda it, rep, r: any(q["id"] == "compare" and q["essential"] for q in r["questions"])
         and planner.resolve(it, {"compare": "each", "_auto": True})["payload"]["more_forms"][0]["phases"][0]["material_id"] == "hbn"
         and len(planner.resolve(it, {"compare": "each", "_auto": True})["payload"]["form"]["phases"]) == 1,
         "a comparison was mixed or not asked"),
        # a material outside the library is asked, not replaced
        ("에폭시에 그래핀옥사이드 5% 넣고 열전도도",
         {"matrix": {"material": "epoxy"}, "fillers": [{"material": "graphene oxide", "percent": 5}],
          "analyses": ["thermal"], "task": "run"},
         lambda it, rep, r: not any(f.get("id") for f in it["fillers"]) and any(q["id"] == "filler:0" for q in r["questions"]),
         "a material outside the library was replaced"),
    ]
    for text, js, ok, what in cases:
        try:
            it, rep, r = run(text, js)
            if not ok(it, rep, r):
                errs.append(f"{what}: {text} -> {fl(it)} {it['analyses']} {rep}")
        except Exception as e:                                             # noqa: BLE001
            errs.append(f"{what}: {text} raised {type(e).__name__}: {e}")
    # broken answers fall back to the rules
    for bad in (None, "not json", {"fillers": "x"}, {"matrix": 5, "fillers": [{"material": 3}], "analyses": "thermal"},
                {"fillers": [{"material": "al2o3", "percent": "55"}], "doe": [{"filler": 9, "what": "content", "from": "a"}]}):
        try:
            text = "에폭시에 알루미나 55% 열전도도"
            it, rep = reader.build_intent(bad, text, lex, parse(text, lex))
            planner.resolve(it, {})
        except Exception as e:                                             # noqa: BLE001
            errs.append(f"a broken answer {bad!r} raised {type(e).__name__}: {e}")
    from aimpsim.llm import LocalLLM
    llm = LocalLLM({"url": "http://127.0.0.1:9", "timeout_s": 2})
    if llm.chat_json([{"role": "user", "content": "x"}], reader.SCHEMA) is not None:
        errs.append("an unreachable model gave an answer")
    return errs


def test_model_first(host):
    """The AI tab with a model (a stand-in server answering by script): the
    model reads every message, a follow-up gets the request so far and is
    restated whole, clicked answers survive it."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from aimpsim.llm import LocalLLM
    from aimpsim.textnorm import normalize
    from aimpsim.web import Assistant
    script = {
        "에폭시랑 알루미나 반반 섞어서 열 얼마나 잘 빠지는지":
            {"matrix": {"material": "epoxy"}, "fillers": [{"material": "al2o3", "percent": 50}], "analyses": ["thermal"],
             "task": "run"},
        "아 알루미나 말고 질화붕소로, 판상":
            {"matrix": {"material": "epoxy"}, "fillers": [{"material": "hbn", "percent": 50, "shape": "platelet"}],
             "analyses": ["thermal"], "task": "run"},
        "CTE도":
            {"matrix": {"material": "epoxy"}, "fillers": [{"material": "hbn", "percent": 50, "shape": "platelet"}],
             "analyses": ["thermal", "cte"], "task": "run"},
    }
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n))
            last = body["messages"][-1]["content"]
            seen.append(last)
            key = last.split("The person now says: ")[-1].split("\n")[0]
            # the model gets the sentence with its numbers normalised
            ans = next((v for k, v in script.items() if normalize(k) == key), {})
            out = {"choices": [{"message": {"content": json.dumps(ans)}}]}
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(out).encode())
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    errs = []
    try:
        a = Assistant(host)
        a.llm = LocalLLM({"url": f"http://127.0.0.1:{srv.server_port}"})

        def form(r):
            return (r.get("payload") or {}).get("form") or {}
        r = a.interpret("에폭시랑 알루미나 반반 섞어서 열 얼마나 잘 빠지는지")
        sid = r["session_id"]
        if r["llm_used"] != ["model"]:
            errs.append("the model was not asked")
        r = a.answer(sid, {"size:0": "5", "quality": "fast"}, auto=True)
        f = form(r)
        if not f or f["phases"][0]["material_id"] != "al2o3" or f["phases"][0]["fraction"]["value"] != 50 \
                or f["analyses"] != {"thermal": True} or f["phases"][0]["size"]["d"] != 5.0:
            errs.append(f"turn 1: {f.get('phases')} {f.get('analyses')}")
        r = a.interpret("아 알루미나 말고 질화붕소로, 판상", sid)
        if "The request so far" not in seen[-1] or "al2o3" not in seen[-1]:
            errs.append("the follow-up did not carry the request so far")
        f = form(r)
        if not f or [p["material_id"] for p in f["phases"]] != ["hbn"] or f["phases"][0]["shape"] != "spheroid" \
                or f["phases"][0]["size"]["d"] != 5.0 or f["rve"]["quality"] != "fast":
            errs.append(f"turn 2: {f.get('phases')} {f.get('rve')}")
        r = a.interpret("CTE도", sid)
        f = form(r)
        if set(k for k, v in (f.get("analyses") or {}).items() if v) != {"thermal", "cte"}:
            errs.append(f"turn 3: {f.get('analyses')}")
        # the model gone: the rules read on
        a.llm = LocalLLM({"url": "http://127.0.0.1:9", "timeout_s": 2})
        r = a.interpret("에폭시에 실리카 60% 열전도도", new=True)
        if r["llm_used"] or not r["summary"]:
            errs.append("without the model the rules did not read the request")
    except Exception:                                                      # noqa: BLE001
        import traceback
        errs.append("model-first conversation raised " + traceback.format_exc(limit=3))
    finally:
        srv.shutdown()
    return errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("-v", action="store_true")
    ap.add_argument("--llm", nargs=2, metavar=("SERVER_EXE", "MODEL"),
                    help="the requests read with the local model first (reader.py), as in the AI tab")
    ap.add_argument("--threads", type=int, default=6)
    a = ap.parse_args()
    sys.stdout.reconfigure(line_buffering=True)
    app = find_mpsim()
    host = host_for(app)
    lex = Lexicon(host.get("library") or [])
    planner = Planner(lex, host)
    read = None
    if a.llm:
        from aimpsim.llm import LocalLLM
        from aimpsim.web import Assistant
        asst = Assistant(host)
        asst.llm = LocalLLM({"server_exe": a.llm[0], "model": a.llm[1], "threads": a.threads, "timeout_s": 300})
        if not asst.llm._start():
            sys.exit("the model server did not start")
        memo = {}

        def read(text):
            if text not in memo:
                r = asst.interpret(text, new=True)
                memo[text] = asst.sessions[r["session_id"]]["intent"]
            return copy.deepcopy(memo[text])
    n = bad = 0
    for text, exp in CASES:
        if a.only and a.only not in text:
            continue
        n += 1
        errs, r = check(text, exp, lex, planner, read)
        if errs:
            bad += 1
            print(f"FAIL  {text}\n      " + "\n      ".join(errs))
        elif a.v:
            print(f"ok    {text}")
    # every payload of the corpus that can be made, made with "decide for me", is accepted by MPSim
    nval = badval = 0
    if host.get("validate") and not a.only:
        for text, exp in CASES:
            it = read(text) if read else parse(text, lex)
            r = planner.resolve(it, {"_auto": True})
            if r["payload"] is None:
                continue
            nval += 1
            if exp.get("mpsim_refuses"):
                if not r["problems"]:
                    badval += 1
                    print(f"MPSIM {text}\n      accepted, but MPSim must refuse it")
                continue
            if r["problems"]:
                badval += 1
                print(f"MPSIM {text}\n      {r['problems']}")
    llm_errs, conv_errs = [], []
    if not a.only:
        llm_errs = test_reader_checks(lex, host) + test_model_first(host)
        for e in llm_errs:
            print("LLM   " + e)
        conv_errs = test_conversation(host)
        for e in conv_errs:
            print("CONV  " + e)
    print(f"\n{n - bad}/{n} requests read as expected"
          + (f"; {nval - badval}/{nval} payloads accepted by MPSim ({app})" if nval else "")
          + ("" if a.only else f"; conversation {'passed' if not conv_errs else 'FAILED'}"
             f"; local-model adapter {'passed' if not llm_errs else 'FAILED'}"))
    return 1 if bad or badval or llm_errs or conv_errs else 0


if __name__ == "__main__":
    sys.exit(main())
