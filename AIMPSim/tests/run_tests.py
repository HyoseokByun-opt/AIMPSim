"""AIMPSim self-test: every request of tests/corpus.py read and planned, the
result checked against what it must be read as; then the local-model
adapter against a stand-in server (no model needed); then, when MPSim is
found beside AIMPSim, every ready payload validated by MPSim itself.

    python tests/run_tests.py            (from the AIMPSim folder)
    python tests/run_tests.py --only 실리카
"""
from __future__ import annotations

import argparse
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


def check(text, exp, lex, planner):
    it = parse(text, lex)
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
    """A request answered over several messages and clicks, as in the AI tab."""
    from aimpsim.web import Assistant
    a = Assistant(host)
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


def test_llm_bad(lex):
    """The local model answering badly: numbers it made up, materials the
    library lacks, broken JSON, no answer - none of it may enter the input."""
    from aimpsim.llm import LocalLLM, apply_hints
    errs = []
    text = "the usual mould compound with 55 of the white ceramic, heat transport"
    cases = [
        ({"matrix": "epoxy", "fillers": [{"material": "alumina", "percent": 62, "size_um": 3}], "properties": []},
         lambda it: not any((f.get("content") or {}).get("value") == 62 for f in it["fillers"])
         and not any(f.get("size_um") == 3 for f in it["fillers"]), "a made-up content or size was kept"),
        ({"matrix": "epoxy", "fillers": [{"material": "unobtainium", "percent": 55}], "properties": []},
         lambda it: not any(f.get("how") == "llm" for f in it["fillers"]), "a material outside the library was used"),
        ({"matrix": None, "fillers": [], "properties": ["teleportation"]},
         lambda it: "teleportation" not in it["analyses"], "an unknown property was used"),
        ({"matrix": "alumina", "fillers": [{"material": "epoxy", "percent": 55}], "properties": []},
         lambda it: (it.get("matrix") or {}).get("id") == "epoxy", "the model's swapped roles replaced the rules' matrix"),
    ]
    for hints, ok, what in cases:
        it = parse(text, lex)
        apply_hints(it, hints, lex)
        if not ok(it):
            errs.append(what)
    for bad in (None, "not json", {"fillers": "x"}):
        it = parse(text, lex)
        try:
            apply_hints(it, bad if isinstance(bad, dict) else None, lex)
        except Exception as e:                                         # noqa: BLE001
            errs.append(f"a broken answer raised {type(e).__name__}")
    # no server at all: no answer, no wait beyond the timeout
    llm = LocalLLM({"url": "http://127.0.0.1:9", "timeout_s": 2})
    if llm.ask(text) is not None:
        errs.append("an unreachable model gave an answer")
    return errs


def test_llm(lex):
    """The adapter against a stand-in llama-server: the answer's materials go
    through the lexicon, a number not in the sentence is dropped."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from aimpsim.llm import LocalLLM, apply_hints
    answer = {"matrix": "the epoxy resin", "fillers": [{"material": "alumina", "percent": 55, "basis": "vol",
                                                         "shape": "spherical", "size_um": 7}],
              "properties": ["heat conductivity"], "task": "run"}

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
            assert body["response_format"]["schema"]["required"]
            out = {"choices": [{"message": {"content": json.dumps(answer)}}]}
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(out).encode())
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        llm = LocalLLM({"url": f"http://127.0.0.1:{srv.server_port}"})
        text = "I need the heat transport of the usual mould compound with 55 of the white ceramic"
        it = parse(text, lex)
        filled = apply_hints(it, llm.ask(text), lex)
        f = it["fillers"][0] if it["fillers"] else {}
        errs = []
        if (it.get("matrix") or {}).get("id") != "epoxy":
            errs.append(f"matrix {it.get('matrix')}")
        if f.get("id") != "al2o3" or (f.get("content") or {}).get("value") != 55:
            errs.append(f"filler {f.get('id')} {f.get('content')}")
        if f.get("size_um") is not None:
            errs.append("a size the sentence does not hold was kept")
        if "thermal" not in it["analyses"]:
            errs.append(f"analyses {it['analyses']}")
        return errs, filled
    finally:
        srv.shutdown()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("-v", action="store_true")
    a = ap.parse_args()
    app = find_mpsim()
    host = host_for(app)
    lex = Lexicon(host.get("library") or [])
    planner = Planner(lex, host)
    n = bad = 0
    for text, exp in CASES:
        if a.only and a.only not in text:
            continue
        n += 1
        errs, r = check(text, exp, lex, planner)
        if errs:
            bad += 1
            print(f"FAIL  {text}\n      " + "\n      ".join(errs))
        elif a.v:
            print(f"ok    {text}")
    # every payload of the corpus that can be made, made with "decide for me", is accepted by MPSim
    nval = badval = 0
    if host.get("validate") and not a.only:
        for text, exp in CASES:
            it = parse(text, lex)
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
        llm_errs, filled = test_llm(lex)
        llm_errs += test_llm_bad(lex)
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
