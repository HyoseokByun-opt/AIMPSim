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
from aimpsim.planner import Planner, merge  # noqa: E402

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
        # both ends of two sweeps written as two copies of the filler: one filler, both factors
        ("에폭시에 구형 알루미나 함량 30~55%, 크기 5~30um로 바꿔가며 열전도도 최대 조건 찾아줘, 빠르게",
         {"matrix": {"material": "epoxy"}, "fillers": [{"material": "al2o3", "percent": 30, "shape": "sphere", "size_um": 5},
                                                      {"material": "al2o3", "percent": 55, "shape": "sphere", "size_um": 30}],
          "analyses": ["thermal"], "task": "doe", "settings": {"quality": "fast"}},
         lambda it, rep, r: len(it["fillers"]) == 1 and sorted(f["what"] for f in it["doe"]["factors"]) == ["content", "size"]
         and len((r.get("payload") or {}).get("doe", {}).get("parameters", [])) == 2, "a swept filler written twice lost its size sweep"),
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


DESIGN_TEXT = ("10um 두께의 에폭시필름에서 알루미나함량을 가장 낮게하면서 z방향 열전도도를 3w/mk로 할수있는 알루미나의 크기와 "
               "배합비율을 알려주세요. 알루미나의 크기 topcut은 3um로하고 실제 배합시 점도나 패킹문제가 있을수있어서 비슷한 "
               "열전도도 수준이라면 점도는 낮고 패킹은 잘되는 조합이면 좋겟어요. 입자 크기 distribution은 고려하지않고 가장 작은 "
               "입자의 크기는 200nm예요. 예전해석에서 필러-레진, 필러-필러간 열저항은 1E-8을 사용했어요. 필러의 최대함량은 62vol%입니다")
# (request, expected: task, target (property, op, value, direction), content bounds, size bounds, DOE parameter roles, n cases)
DESIGN_CASES = [
    (DESIGN_TEXT, {"target": ("k", ">=", 3.0, "z"), "cmax": 62.0, "size": (0.2, 3.0), "roles": {"content", "share", "size0", "size1"},
                   "n": 40, "film": 10.0, "r": (1e-8, 1e-8), "mono": True, "prefer": {"low_viscosity", "high_packing"}}),
    ("In a 10 um thick epoxy film, which alumina sizes and blend give a through-plane k of 3 W/mK with the least filler? "
     "Topcut 3 um, smallest particle 0.2 um, ignore the size distribution, at most 62 vol%, filler-resin and filler-filler "
     "resistance 1e-8 m2K/W, prefer low viscosity and good packing",
     {"target": ("k", ">=", 3.0, "z"), "cmax": 62.0, "size": (0.2, 3.0), "roles": {"content", "share", "size0", "size1"},
      "n": 40, "film": 10.0, "r": (1e-8, 1e-8), "mono": True, "prefer": {"low_viscosity", "high_packing"}}),
    # the AI tab's own example
    ("10um 에폭시 필름에서 알루미나를 가장 적게 넣고 z방향 열전도도 3 W/mK가 되는 크기와 배합비율 알려줘. topcut 3um, 가장 작은 "
     "입자 200nm, 최대 62vol%, 분포는 고려하지 않음, 필러-레진·필러-필러 열저항 1E-8, 비슷하면 점도 낮고 패킹 잘되는 조합",
     {"target": ("k", ">=", 3.0, "z"), "cmax": 62.0, "size": (0.2, 3.0), "roles": {"content", "share", "size0", "size1"},
      "n": 40, "film": 10.0, "r": (1e-8, 1e-8), "mono": True, "prefer": {"low_viscosity", "high_packing"}}),
    ("실리콘에 구형 질화알루미늄 10um 넣어서 열전도도 5 W/mK 이상 되는 최소 함량 찾아줘. 최대 70vol%",
     {"target": ("k", ">=", 5.0, None), "cmax": 70.0, "roles": {"content"}, "n": 9}),
    ("에폭시에 구형 실리카 넣어서 CTE 20ppm/K 이하가 되는 최소 함량과 입자 크기 알려줘. 입자는 1~20um, 최대 65vol%",
     {"target": ("alpha", "<=", 20.0, None), "cmax": 65.0, "size": (1.0, 20.0), "roles": {"content", "size0"}, "n": 36}),
]
NOT_DESIGN = [
    ("에폭시에 실리카 20%일 때 0.45 W/mK, 40%일 때 0.8 W/mK 측정됐어. 계면저항 보정해줘", "calibration"),
    ("에폭시에 알루미나 함량을 40~60%로 바꿔가며 열전도도가 최대가 되는 조건 찾아줘", "optimization"),
    ("에폭시에 알루미나 55% 열전도도 구해줘", None),
]


def test_design(lex, host, read=None):
    """Design requests ("as little filler as possible for k_z = 3"): read,
    planned into a DOE MPSim accepts case by case, and the recipe chosen
    from finished runs (here a closed-form stand-in for the solver)."""
    import numpy as np
    from aimpsim import design as DZ
    errs = []
    planner = Planner(lex, host)
    for text, exp in DESIGN_CASES:
        it = read(text) if read else parse(text, lex)
        d = it.get("design") or {}
        tg = (d.get("targets") or [{}])[0]
        if it.get("task") != "design" or (tg.get("property"), tg.get("op"), tg.get("value"), tg.get("direction")) != exp["target"]:
            errs.append(f"design read: {text[:40]}: task {it.get('task')} target {tg}")
            continue
        if d.get("content_max") != exp["cmax"] or ("size" in exp and (d.get("size_min_um"), d.get("size_max_um")) != exp["size"]):
            errs.append(f"design bounds: {text[:40]}: {d.get('content_max')} {d.get('size_min_um')} {d.get('size_max_um')}")
        if "film" in exp and it.get("film") != exp["film"]:
            errs.append(f"design film: {text[:40]}: {it.get('film')}")
        if "r" in exp and ((it.get("interface") or {}).get("r_int"), (it.get("interface") or {}).get("r_contact")) != exp["r"]:
            errs.append(f"design resistances: {text[:40]}: {it.get('interface')}")
        if exp.get("mono") and not d.get("mono"):
            errs.append(f"design mono: {text[:40]}")
        if "prefer" in exp and set(d.get("prefer") or []) != exp["prefer"]:
            errs.append(f"design prefer: {text[:40]}: {d.get('prefer')}")
        if any((f.get("content") or {}).get("value") is not None for f in it["fillers"]) or \
                any((f.get("props") or {}).get("k") for f in it["fillers"]):
            errs.append(f"design numbers on the filler: {text[:40]}: {[(f.get('content'), f.get('props')) for f in it['fillers']]}")
        r = planner.resolve(copy.deepcopy(it), {"_auto": True})
        p = r["payload"]
        if r["problems"] or not p or p["kind"] != "design":
            errs.append(f"design plan: {text[:40]}: {r['problems']} {[q['id'] for q in r['questions'] if q['essential']]}")
            continue
        roles = set(p["design"]["roles"].values())
        if roles != exp["roles"] or p["doe"]["n_cases"] != exp["n"]:
            errs.append(f"design DOE: {text[:40]}: {roles} {p['doe']['n_cases']}")
        if not host.get("validate"):
            continue
        sys.path.insert(0, find_mpsim())
        from mpsim import doe as DOE
        from mpsim import spec as S
        from mpsim.calibrate import fill_props
        base = fill_props(p["form"])
        if DOE.check_links(p["doe"]["parameters"], base):
            errs.append(f"design links: {DOE.check_links(p['doe']['parameters'], base)}")
        cases = DOE.expand(p["doe"]["parameters"], p["doe"]["design"], p["doe"]["samples"], 1)
        rows = []
        for c in cases:
            fm = DOE.apply_case(base, c, parameters=p["doe"]["parameters"])
            try:
                S.normalize(copy.deepcopy(fm))
            except ValueError as e:
                errs.append(f"design case refused: {c['label']}: {e}")
                break
            ph = fm["phases"]
            phi = sum(x["fraction"]["value"] for x in ph) / 100.0
            if "content" in exp["roles"] and abs(100 * phi - c["values"]["phases.0.fraction.value"]) > 1e-6:
                errs.append(f"design total content: {c['label']} -> {100 * phi}")
                break
            deff = sum(x["fraction"]["value"] * x["size"]["d"] for x in ph) / max(100 * phi, 1e-9)
            k = 0.2 * (1 - phi) ** -3 / (1 + 0.15 / deff)
            alpha = 60.0 * (1 - phi) ** 1.5
            rows.append({"state": "done", "values": c["values"], "label": c["label"], "job_id": "x",
                         "metrics": {"k": k, "alpha": alpha, "real_filler": 100 * phi - 0.2}})
        out = DZ.recommend({"parameters": p["doe"]["parameters"], "base_form": base}, rows, p["design"])
        rec = out.get("recommended")
        if not out.get("ok") or not out.get("reached") or not rec:
            errs.append(f"design recipe: {text[:40]}: {out.get('error')} reached={out.get('reached')}")
            continue
        tgv = exp["target"]
        if (tgv[1] == ">=" and rec["predicted"] < tgv[2] - 1e-9) or (tgv[1] == "<=" and rec["predicted"] > tgv[2] + 1e-9):
            errs.append(f"design recipe misses the target: {rec}")
        low = out.get("lowest")
        if low and rec["content"] > low["content"] + p["design"]["tol"] + 1e-6:
            errs.append(f"design recipe beyond the tolerance: {rec['content']} vs {low['content']}")
        if p["design"]["prefer"] and low and rec.get("mu_r") is not None and low.get("mu_r") is not None \
                and rec["mu_r"] > low["mu_r"] + 1e-9:
            errs.append(f"design recipe not the lowest viscosity: {rec['mu_r']} > {low['mu_r']}")
        try:
            S.normalize(copy.deepcopy(out["check_form"]))
        except (KeyError, ValueError) as e:
            errs.append(f"design check run refused: {e}")
        if p["design"]["check_analyses"] and not all(out["check_form"]["analyses"].get(a) for a in p["design"]["check_analyses"]):
            errs.append(f"design check run without {p['design']['check_analyses']}")
        if not np.isfinite(rec["predicted"]):
            errs.append("design prediction not finite")
    for text, task in NOT_DESIGN:
        it = read(text) if read else parse(text, lex)
        if it.get("task") != task:
            errs.append(f"not a design: {text[:40]} -> {it.get('task')}")
    # out of reach, and the structures held less than the cases were set to (the user's request in MPSim 5.6.5:
    # cases set to 59.6-61.8 vol% held 59.1-59.9 vol% in the 10 µm film): the answer says so and does not
    # suggest a higher content
    p = planner.resolve(parse(DESIGN_TEXT, lex), {"_auto": True})["payload"]
    if host.get("validate") and p and p.get("design"):
        from mpsim import doe as DOE
        from mpsim.calibrate import fill_props
        base = fill_props(p["form"])
        rows = []
        for c in DOE.expand(p["doe"]["parameters"], p["doe"]["design"], p["doe"]["samples"], 1):
            set_ = c["values"]["phases.0.fraction.value"]
            real = min(set_, 59.6) - 0.1
            rows.append({"state": "done", "values": c["values"], "label": c["label"], "job_id": "x",
                         "metrics": {"k": 0.2 * (1 - real / 100.0) ** -2.5, "real_filler": real}})
        out = DZ.recommend({"parameters": p["doe"]["parameters"], "base_form": base}, rows, p["design"])
        hd = out.get("held") or {}
        if out.get("reached") or "packing_limit" not in out.get("notes", []) or not hd.get("n") or hd.get("held_max", 99) > 59.6:
            errs.append(f"design out of reach, packing short: reached={out.get('reached')} notes={out.get('notes')} held={hd}")
    # a follow-up changes the bound
    it = merge(parse(DESIGN_TEXT, lex), parse("최대 함량은 60vol%로 바꿔줘", lex))
    r = planner.resolve(it, {"_auto": True})
    cp = next((x for x in (r["payload"] or {}).get("doe", {}).get("parameters", []) if x["path"] == "phases.0.fraction.value"), None)
    if not cp or cp["max"] != 60.0:
        errs.append(f"design follow-up: {cp}")
    # a size that varies: each case its own grid (a voxel set stays, the edge per case); no size: one grid
    for text, edge in ((DESIGN_TEXT, "own"),
                       ("에폭시에 구형 알루미나 함량 30~55%, 크기 5~30um로 바꿔가며 열전도도 최대 조건 찾아줘, 빠르게", "own"),
                       ("에폭시에 구형 알루미나 10um 함량 30~55%로 바꿔가며 열전도도 최대 조건 찾아줘, 빠르게", "fixed"),
                       ("에폭시에 구형 알루미나 50% 크기 5~30um, 복셀 0.5um, 열전도도", "adaptive")):
        d = (planner.resolve(parse(text, lex), {"_auto": True})["payload"] or {}).get("doe") or {}
        if d.get("edge") != edge:
            errs.append(f"study grid: {d.get('edge')} != {edge}: {text[:40]}")
    return errs


MATPROP_CASES = [
    ("에폭시에 구형 알루미나 10um 50vol%, 알루미나 열전도도는 20 W/mK로 해서 열전도도 계산해줘", "al2o3", "k", 20.0),
    ("에폭시에 구형 알루미나 10um 50vol%, 알루미나 k를 라이브러리보다 10 낮게 해서 열전도도", "al2o3", "k", "lib-10"),
    ("epoxy with 50 vol% alumina spheres 10 um, use k = 20 W/mK for the alumina this time, thermal conductivity", "al2o3", "k", 20.0),
    ("실리콘에 판상 BN 10um 30vol%, BN 열전도도를 기존보다 30% 높게 해서 열전도도", "hbn", "k", "lib*1.3"),
    ("에폭시에 구형 알루미나 10um 50vol%, 알루미나 열전도도 절반으로 해서 열전도도", "al2o3", "k", "lib*0.5"),
    ("에폭시 열전도도 0.3으로 두고 구형 알루미나 5um 50vol% 열전도도", "epoxy", "k", 0.3),
]


def test_matprops(lex, host):
    """A material value said for one request ("알루미나 열전도도 20으로",
    "라이브러리보다 10 낮게"): in the case's phase only, never in the library,
    and gone from the next request."""
    errs = []
    planner = Planner(lex, host)
    lib = {m["id"]: dict(m.get("props") or {}) for m in host.get("library") or []}
    for text, mid, prop, want in MATPROP_CASES:
        r = planner.resolve(parse(text, lex), {"_auto": True})
        if not r["payload"]:
            errs.append(f"values: no payload: {text[:40]} {r['problems']}")
            continue
        f = r["payload"]["form"]
        ent = f["matrix"] if f["matrix"]["material_id"] == mid else next((p for p in f["phases"] if p["material_id"] == mid), {})
        base = lib.get(mid, {}).get(prop)
        exp = want if isinstance(want, float) else base - 10 if want == "lib-10" else base * float(want.split("*")[1])
        got = (ent.get("props") or {}).get(prop)
        if got is None or abs(got - exp) > 1e-9 * max(1.0, abs(exp)):
            errs.append(f"values: {text[:40]}: {prop} = {got}, expected {exp}")
        if not any("라이브러리는 바꾸지 않음" in n or "library is not changed" in n for n in r["notes"]):
            errs.append(f"values: no note that only this request uses it: {text[:40]}")
        # the next request starts from the library
        r2 = planner.resolve(parse("에폭시에 구형 알루미나 10um 50vol% 열전도도", lex), {"_auto": True})
        k2 = (r2["payload"]["form"]["phases"][0].get("props") or {}).get("k")
        if k2 is not None:
            errs.append(f"values: carried into the next request: {k2}")
    if {m["id"]: dict(m.get("props") or {}) for m in host.get("library") or []} != lib:
        errs.append("values: the library itself was changed")
    return errs


def test_calibration_ai(lex, host):
    """A calibration the AI looks at: data no interfacial resistance can
    reach get the unknowns that can (pre-selected, the request's own kept as
    a choice); data it can reach run as asked; after a run, a result that
    did not reach the data gives the next calibration, one that did ends."""
    errs = []
    if not host.get("validate"):
        return errs
    from aimpsim import calcheck as CC
    planner = Planner(lex, host)
    # silica: 0.8 W/mK at 40 vol% is above the parallel bound with fused silica (0.67)
    r = planner.resolve(parse("에폭시에 실리카 20%일 때 0.45 W/mK, 40%일 때 0.8 W/mK 측정됐어. 계면저항 보정해줘", lex), {"_auto": True})
    cal = (r["payload"] or {}).get("cal") or {}
    keys = sorted(u.get("key") for u in cal.get("unknowns") or [])
    if keys != ["filler_k", "matrix_k"] or not any(q["id"] == "cal_plan" for q in r["questions"]):
        errs.append(f"calibration precheck (silica): {keys} {[q['id'] for q in r['questions']]}")
    if not any(row["k"] in ("사전 점검", "Precheck") and "병렬 상한" in row["v"] for row in r["summary"]):
        errs.append("calibration precheck (silica): no bound in the summary")
    # the request's own unknowns stay a choice
    r2 = planner.resolve(parse("에폭시에 실리카 20%일 때 0.45 W/mK, 40%일 때 0.8 W/mK 측정됐어. 계면저항 보정해줘", lex),
                         {"_auto": True, "cal_plan": "r_int"})
    if [u.get("key") for u in r2["payload"]["cal"]["unknowns"]] != ["r_int"]:
        errs.append("calibration precheck: the request's own unknowns could not be kept")
    # alumina: R_int reaches the data, it runs as asked
    r3 = planner.resolve(parse("에폭시에 구형 알루미나 10um 30%일 때 0.55 W/mK, 50%일 때 1.2 W/mK 측정됐어. 계면저항 보정해줘", lex),
                         {"_auto": True})
    u3 = r3["payload"]["cal"]["unknowns"]
    if [u.get("key") for u in u3] != ["r_int"] or any(q["id"] == "cal_plan" for q in r3["questions"]) \
            or u3[0]["links"] != [{"path": "phases.0.r_contact", "expr": "2*x"}]:
        errs.append(f"calibration precheck (alumina): {u3}")
    # after a run: R_int at its lower end and far below the data -> other unknowns; a reached result ends
    form = planner._filled(r2["payload"]["form"])
    cal2 = r2["payload"]["cal"]
    res = {"unknowns": [{"path": "phases.0.r_int", "label": "R_int", "map": 1.5e-9, "lo": 1e-9, "hi": 1e-5, "edge": "low",
                         "unreached": True, "unit": "m²K/W"}],
           "measurements": [{"label": "20%", "measured": 0.45, "direct": 0.294, "residual_sigma": -8.0},
                            {"label": "40%", "measured": 0.8, "direct": 0.428, "residual_sigma": -11.9}]}
    nx = CC.next_round(form, cal2, cal2["unknowns"], res, ["r_int"], "ko")
    if nx["action"] != "rerun" or "r_int" in (nx.get("keys") or "").split("+") and nx.get("why") != "widened" \
            or not CC.explain(nx, cal2["unknowns"], res, "ko"):
        errs.append(f"calibration next round: {nx.get('action')} {nx.get('keys')} {nx.get('why')}")
    res_ok = {"unknowns": [{"path": "phases.0.props.k", "label": "silica k", "map": 6.39, "lo": 0.69, "hi": 41.4, "edge": None,
                            "unit": "W/m·K"}],
              "measurements": [{"label": "20%", "measured": 0.45, "direct": 0.449, "residual_sigma": -0.05}]}
    done = CC.next_round(form, cal2, cal2["unknowns"], res_ok, [], "ko")
    if done["action"] != "done" or "결정질 실리카" not in CC.explain(done, cal2["unknowns"], res_ok, "ko", form, lex.library) \
            and "quartz" not in CC.explain(done, cal2["unknowns"], res_ok, "ko", form, lex.library):
        errs.append(f"calibration done: {done} / {CC.explain(done, cal2['unknowns'], res_ok, 'ko', form, lex.library)}")
    return errs


def test_loops(lex, host):
    """Studies and calibrations run until they answer (loop.py, calcheck.py),
    on synthetic data: the design loop under run-to-run noise ends with a
    recipe that meets the target; the optimisation loop ends at the optimum;
    a calibration with nothing left to try asks, and an answer changes the
    case; words typed during a loop are read as stop, answer or condition."""
    errs = []
    if not host.get("validate"):
        return errs
    import numpy as np
    sys.path.insert(0, find_mpsim())
    from mpsim import doe as DOE
    from mpsim.calibrate import fill_props
    from aimpsim import calcheck as CC
    from aimpsim import loop as LP
    planner = Planner(lex, host)
    for text, noise in ((DESIGN_TEXT, 0.12), ("에폭시에 구형 알루미나 20um 넣어서 열전도도 1 W/mK 이상 되는 최소 함량 찾아줘. 최대 50vol%, 빠르게", 0.06)):
        p = planner.resolve(parse(text, lex), {"_auto": True})["payload"]
        base, params = fill_props(p["form"]), p["doe"]["parameters"]
        rng = np.random.default_rng(7)

        def k_of(values):
            f = DOE.apply_case(base, {"values": values, "label": ""}, parameters=params)
            ph = f["phases"]
            phi = sum(x["fraction"]["value"] for x in ph) / 100
            deff = sum(x["fraction"]["value"] * x["size"]["d"] for x in ph) / max(100 * phi, 1e-9)
            return 0.2 * (1 - phi) ** -3 / (1 + 0.15 / deff)
        rows = [{"state": "done", "values": c["values"], "label": c["label"], "job_id": "x",
                 "metrics": {"k": k_of(c["values"]) * (1 + noise * rng.standard_normal())}}
                for c in DOE.expand(params, p["doe"]["design"], p["doe"]["samples"], 1)]
        state, final, short = {}, None, None
        for _ in range(LP.MAX_ROUNDS + 2):
            out = LP.design_round({"parameters": params, "base_form": base}, rows, p["design"], state)
            state = out.get("state") or state
            if not LP.explain(out, "design", "ko"):
                errs.append("loop: no words for a round")
            if out["action"] == "refine":
                rows += [{"state": "done", "values": v, "label": "added", "job_id": "x",
                          "metrics": {"k": k_of(v) * (1 + noise * rng.standard_normal())}} for v in out["points"]]
            elif out["action"] == "check":
                v = state["check"]["values"]
                if short is not None and all(abs(v[q] - short[q]) < 1e-9 for q in v):
                    errs.append(f"design loop checks a recipe again that fell short: {v}")
                seeds = [k_of(v) * (1 + noise * rng.standard_normal()) for _ in range(3)]
                state["check"].update(value=float(np.mean(seeds)), ci=float(np.std(seeds)))
                tgt = p["design"]["target"]["value"]
                short = dict(v) if state["check"]["value"] < tgt else None
            else:
                final = out
                break
        # a check that falls short joins the data before the recipe is chosen again
        if final and final["action"] == "done":
            st = dict(final["state"], check=dict(final["state"]["check"], value=0.5 * p["design"]["target"]["value"]))
            o2 = LP.design_round({"parameters": params, "base_form": base}, rows, p["design"], st)
            if o2.get("why_check") != "check_short" or not any(e.get("label") == "check" for e in o2["state"].get("extra") or []):
                errs.append(f"design loop: a short check was not taken into the data first ({o2.get('action')} {o2.get('why_check')})")
        if not final or final["action"] != "done":
            errs.append(f"design loop did not finish: {text[:30]} {final and final.get('why')}")
            continue
        rec = final["result"]["recommended"]
        target = p["design"]["target"]["value"]
        if k_of(rec["values"]) < 0.97 * target:
            errs.append(f"design loop recipe misses the target: {k_of(rec['values']):.3f} < {target}")
    # optimisation: k rises with the content and falls with a small size; the optimum is the corner.
    # Two factors, and one (its runs fill the line at the points' spacing after a round); a rise
    # with a peak inside the range, brought to a value; the optimum is run before it stands
    def k2(v):
        phi = v.get("phases.0.fraction.value", 40) / 100
        d = v.get("phases.0.size.d", 10)
        return 0.2 * (1 - phi) ** -3 / (1 + 2.0 / d)

    def peak(v):
        phi = v.get("phases.0.fraction.value", 40)
        return 3.0 - 0.004 * (phi - 47.0) ** 2

    def no_size(v):                  # no interfacial resistance: the size does not matter
        return 0.2 * (1 - v.get("phases.0.fraction.value", 40) / 100) ** -3
    two = "에폭시에 구형 알루미나 함량 30~55%, 크기 5~30um로 바꿔가며 열전도도 최대 조건 찾아줘, 빠르게"
    for text, f, goal, target, ok in (
            (two, k2, "max", None,
             lambda b: b["values"].get("phases.0.fraction.value", 0) >= 52),
            (two, no_size, "max", None,
             lambda b: b["values"].get("phases.0.fraction.value", 0) >= 52),
            ("에폭시에 구형 알루미나 10um 함량 30~55%로 바꿔가며 열전도도 최대 조건 찾아줘, 빠르게", k2, "max", None,
             lambda b: b["values"].get("phases.0.fraction.value", 0) >= 52),
            ("에폭시에 구형 알루미나 10um 함량 30~55%로 바꿔가며 열전도도 최대 조건 찾아줘, 빠르게", peak, "max", None,
             lambda b: abs(b["values"].get("phases.0.fraction.value", 0) - 47.0) <= 2.0),
            ("에폭시에 구형 알루미나 10um 함량 30~55%로 바꿔가며 열전도도 최대 조건 찾아줘, 빠르게", k2, "target", 1.0,
             lambda b: abs(k2(b["values"]) - 1.0) <= 0.05)):
        p = planner.resolve(parse(text, lex), {"_auto": True})["payload"]
        params = p["doe"]["parameters"]
        rng = np.random.default_rng(3)
        cases = DOE.expand(params, p["doe"]["design"], p["doe"]["samples"], 1)
        rows = [{"state": "done", "values": c["values"], "label": c["label"], "job_id": "x",
                 "metrics": {"k": f(c["values"]) * (1 + 0.03 * rng.standard_normal())}} for c in cases]
        state, final, seen = {}, None, []
        for _ in range(LP.MAX_ROUNDS + 2):
            out = LP.opt_round({"parameters": params}, rows, "k", goal, target, state)
            state = out.get("state") or state
            seen.append((out["action"], out.get("why")))
            if not LP.explain(out, "opt", "ko"):
                errs.append("loop: no words for an optimisation round")
            if out["action"] in ("refine", "check"):
                rows += [{"state": "done", "values": v, "label": "added", "job_id": "x",
                          "metrics": {"k": f(v) * (1 + 0.03 * rng.standard_normal())}} for v in out["points"]]
            else:
                final = out
                break
        if not final or final["action"] != "done" or "measured" not in final["best"] or not ok(final["best"]):
            errs.append(f"optimisation loop ({len(params)} factor(s), {f.__name__}, {goal}): "
                        f"{final and final.get('action')} {final and final.get('why')} {final and final.get('best')} {seen}")
        elif len(params) == 2:
            # a size that does not matter is said so; one that does is not
            flat = [x["path"] for x in final.get("flat") or []]
            if ("phases.0.size.d" in flat) != (f is no_size) or "phases.0.fraction.value" in flat:
                errs.append(f"optimisation loop ({f.__name__}): factors within the scatter {flat}")
    # a calibration with nothing left to try asks; an answer changes the material
    r = planner.resolve(parse("에폭시에 실리카 20%일 때 3 W/mK, 40%일 때 5 W/mK 측정됐어. 계면저항 보정해줘", lex), {"_auto": True})
    form, cal = planner._filled(r["payload"]["form"]), r["payload"]["cal"]
    res = {"unknowns": [{"path": u["path"], "label": u["label"], "map": u["lo"], "lo": u["lo"], "hi": u["hi"], "edge": None,
                         "unreached": True, "unit": u.get("unit", "")} for u in cal["unknowns"]],
           "measurements": [{"label": "20%", "measured": 3.0, "direct": 0.45, "residual_sigma": -20},
                            {"label": "40%", "measured": 5.0, "direct": 0.8, "residual_sigma": -20}]}
    tried = ["+".join(p_) for p_ in CC.PLANS] + [cal.get("plan_keys") or ""]
    nx = CC.next_round(form, cal, cal["unknowns"], res, tried, "ko", lex.library)
    ids = [o["id"] for o in nx.get("options") or []]
    if nx["action"] != "ask" or "material:quartz" not in ids or "basis:wt" not in ids or "stop" not in ids:
        errs.append(f"calibration ask: {nx.get('action')} {ids}")
    f2, _ = CC.apply_answer(form, cal, "material:quartz", lex.library)
    if f2["phases"][0]["material_id"] != "quartz" or abs(f2["phases"][0]["props"]["k"] - 6.5) > 1e-9:
        errs.append(f"calibration answer: {f2['phases'][0].get('material_id')}")
    from aimpsim.web import Assistant
    a = Assistant(host)
    # (loop words are read by rules; the model is not needed)
    for text, kind, waiting, want in (
            ("멈춰", "design", False, "stop"), ("stop it", "cal", False, "stop"), ("결정질 실리카로 해봐", "cal", True, "answer"),
            ("결정질 실리카로 해봐", "cal", False, "none"), ("최대 함량은 55%로", "design", False, "condition"),
            ("1% 이내면 같은 걸로", "design", False, "condition"), ("에폭시에 알루미나 50% 열전도도", "design", False, "none"),
            # a whole new request typed while a calibration waits is a request, not an answer
            ("에폭시에 구형 알루미나 20um 넣어서 열전도도 1 W/mK 이상 되는 최소 함량 찾아줘", "cal", True, "none")):
        c = a.loop_command(text, [kind], "ko", waiting)
        if c["command"] != want:
            errs.append(f"loop words: {text} -> {c}")
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
    llm_errs, conv_errs, des_errs = [], [], []
    if not a.only:
        llm_errs = test_reader_checks(lex, host) + test_model_first(host)
        for e in llm_errs:
            print("LLM   " + e)
        conv_errs = test_conversation(host)
        for e in conv_errs:
            print("CONV  " + e)
        des_errs = test_design(lex, host, read) + test_matprops(lex, host) + test_calibration_ai(lex, host) + test_loops(lex, host)
        for e in des_errs:
            print("DESIGN " + e)
    print(f"\n{n - bad}/{n} requests read as expected"
          + (f"; {nval - badval}/{nval} payloads accepted by MPSim ({app})" if nval else "")
          + ("" if a.only else f"; conversation {'passed' if not conv_errs else 'FAILED'}"
             f"; local-model adapter {'passed' if not llm_errs else 'FAILED'}"
             f"; design, material values, calibration checks and loops {'passed' if not des_errs else 'FAILED'}"))
    return 1 if bad or badval or llm_errs or conv_errs or des_errs else 0


if __name__ == "__main__":
    sys.exit(main())
