"""Exhaustive check of the inputs AIMPSim makes.

Every sentence below is generated together with what it must become, so the
MPSim input AIMPSim builds from it (with "decide for me": every open
recommendation taken) can be graded:

  ok     the input says what the sentence says
  asked  the input is held back by a question about what the sentence left
         unclear - allowed only where the case allows it (ambiguous names,
         typing errors, contents that cannot be)
  wrong  an input was made, but differs from the sentence - never allowed
  miss   no input and no question about the missing item - never allowed

Sweeps: every alias of every material as matrix and as filler; every way of
writing a content, a size, a shape, an analysis; DOE ranges and steps;
calibration measurements and units; optimisation goals; settings; pairs of
fillers; Korean word orders and particles; typing errors made from every
alias; sentences that are not requests; random combinations of all of them.
Every input made is validated by MPSim as well (when found beside AIMPSim).

    python tests/exhaustive.py [--sweep NAME] [-v]
"""
from __future__ import annotations

import argparse
import collections
import itertools
import os
import random
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from aimpsim import lexicon_data as LD  # noqa: E402
from aimpsim.lexicon import Lexicon  # noqa: E402
from aimpsim.parser import parse  # noqa: E402
from aimpsim.phonetic import CHO, JONG, JUNG, has_hangul  # noqa: E402
from aimpsim.planner import Planner  # noqa: E402
from run_tests import find_mpsim, host_for  # noqa: E402

MS = {"sphere": "sphere", "platelet": "spheroid", "fiber": "cylinder", "irregular": "polyhedron", "cube": "cube",
      "spheroid": "spheroid", "network": "network"}
KO_DIG = "영일이삼사오육칠팔구"


def ko_number(n):
    """55 -> 오십오 (Sino-Korean, up to 99)."""
    n = int(n)
    t, o = divmod(n, 10)
    s = ""
    if t:
        s += ("" if t == 1 else KO_DIG[t]) + "십"
    if o:
        s += KO_DIG[o]
    return s or "영"


EN_ONES = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
EN_TENS = ["", "ten", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def en_number(n):
    t, o = divmod(int(n), 10)
    return (EN_TENS[t] + (" " + EN_ONES[o] if o else "")).strip() if t > 1 or (t == 1 and o == 0) else EN_ONES[n] if n < 10 else str(n)


# ---------------------------------------------------------------- expectations
class Case:
    __slots__ = ("sweep", "text", "exp", "allow_ask")

    def __init__(self, sweep, text, exp, allow_ask=False):
        self.sweep, self.text, self.exp, self.allow_ask = sweep, text, exp, allow_ask


def grade(case, planner, validate, read=None):
    it = read(case.text) if read else parse(case.text, planner.lex)
    r = planner.resolve(it, {"_auto": True})
    p = r["payload"]
    e = case.exp
    if p is None:
        if r["questions"] or r["problems"]:
            if case.allow_ask or e.get("ask"):
                return "asked", ""
            return "asked!", "; ".join(q["id"] for q in r["questions"]) + " " + "; ".join(r["problems"])[:120]
        return "miss", "no input and no question"
    if e.get("ask"):
        return "wrong", f"an input was made where a question was due ({e['ask']})"
    f = p["form"]
    errs = []
    if "matrix" in e and f["matrix"]["material_id"] != e["matrix"]:
        errs.append(f"matrix {f['matrix']['material_id']} != {e['matrix']}")
    if "fillers" in e:
        ph = f["phases"]
        if len(ph) != len(e["fillers"]):
            errs.append(f"{len(ph)} phases {[x['material_id'] for x in ph]} != {len(e['fillers'])}")
        for x, ef in zip(ph, e["fillers"]):
            if "id" in ef and x["material_id"] != ef["id"]:
                errs.append(f"filler {x['material_id']} != {ef['id']}")
            if "value" in ef and abs(float(x["fraction"]["value"]) - ef["value"]) > 0.02 * max(1, ef["value"]):
                errs.append(f"content {x['fraction']['value']} != {ef['value']}")
            if "basis" in ef and x["fraction"]["basis"] != ef["basis"]:
                errs.append(f"basis {x['fraction']['basis']} != {ef['basis']}")
            if "shape" in ef and x["shape"] != MS[ef["shape"]]:
                errs.append(f"shape {x['shape']} != {MS[ef['shape']]}")
            if "d" in ef and abs(float(x["size"]["d"]) - ef["d"]) > 1e-6 * max(1, ef["d"]):
                errs.append(f"size {x['size']['d']} != {ef['d']}")
    if "analyses" in e and set(k for k, v in f["analyses"].items() if v) != set(e["analyses"]):
        errs.append(f"analyses {sorted(k for k, v in f['analyses'].items() if v)} != {sorted(e['analyses'])}")
    if "task" in e and p["kind"] != e["task"]:
        errs.append(f"task {p['kind']} != {e['task']}")
    if "quality" in e and f["rve"]["quality"] != e["quality"]:
        errs.append(f"quality {f['rve']['quality']} != {e['quality']}")
    if "directions" in e and f["options"]["directions"] != e["directions"]:
        errs.append(f"directions {f['options']['directions']} != {e['directions']}")
    if "n_seeds" in e and f["rve"].get("n_seeds") != e["n_seeds"]:
        errs.append(f"realisations {f['rve'].get('n_seeds')} != {e['n_seeds']}")
    if "seed" in e and f["rve"].get("seed") != e["seed"]:
        errs.append(f"seed {f['rve'].get('seed')} != {e['seed']}")
    for k, v in (e.get("settings") or {}).items():
        if (p.get("settings") or {}).get(k) != v:
            errs.append(f"settings {p.get('settings')} lacks {k}={v}")
    if "doe" in e:
        pars = (p.get("doe") or {}).get("parameters") or []
        if len(pars) != len(e["doe"]):
            errs.append(f"DOE {len(pars)} parameters != {len(e['doe'])}")
        for q, (path, lo, hi, n) in zip(pars, e["doe"]):
            if q["path"] != path or abs(q["min"] - lo) > 1e-6 or abs(q["max"] - hi) > 1e-6 or q["steps"] != n:
                errs.append(f"DOE {q['path']} {q['min']}..{q['max']} x{q['steps']} != {path} {lo}..{hi} x{n}")
    if "cal" in e:
        ms = (p.get("cal") or {}).get("measurements") or []
        got = [(m["property"], round(m["value"], 6), (m["set"][0]["value"] if m["set"] else None)) for m in ms]
        want = [(a, round(b, 6), c) for a, b, c in e["cal"]]
        if got != want:
            errs.append(f"measurements {got} != {want}")
        # what was read (the AI may then recommend other unknowns for data the read ones cannot reach)
        cal_ = p.get("cal") or {}
        def path_of(k):
            m = re.match(r"(filler|matrix)_(.+)$", k)
            if m:
                return ("phases.0" if m.group(1) == "filler" else "matrix") + ".props." + m.group(2)
            return {"r_int": "phases.0.r_int", "r_contact": "phases.0.r_contact"}.get(k, k)
        read_ = [path_of(k) for k in cal_.get("asked") or []] or [u["path"] if isinstance(u, dict) else u
                                                                   for u in cal_.get("unknowns") or []]
        if "unknowns" in e and read_ != e["unknowns"]:
            errs.append(f"unknowns {read_} != {e['unknowns']}")
    if "goal" in e and (p.get("opt") or {}).get("goal") != e["goal"]:
        errs.append(f"goal {(p.get('opt') or {}).get('goal')} != {e['goal']}")
    if errs:
        return "wrong", "; ".join(errs)
    if validate is not None and not e.get("mpsim_refuses"):
        err = validate(f)
        if err:
            return "mpsim", err[:160]
    return "ok", ""


# ---------------------------------------------------------------- sweeps
def polymer_ids(lex):
    return [m for m in LD.MATERIALS if lex.group(m) == "polymer" and (not lex.library or m in lex.library)]


def filler_ids(lex):
    return [m for m in LD.MATERIALS if lex.group(m) != "polymer" and (not lex.library or m in lex.library)]


def aliases(mid, kinds=("ko", "en", "formula")):
    a = LD.MATERIALS[mid]
    out = []
    for k in kinds:
        for al in a.get(k, []):
            out.append((k, al))
    return out


# a filler of each analysis that MPSim accepts with it
AN_FILLER = {"electrical": "ag", "joule": "ag", "emi": "ag", "magnetic": "nizn_ferrite"}
PORE_AN = {"permeability", "filtration", "tortuosity", "acoustics", "radiation", "porosimetry", "pore_network"}
FILM_AN = {"thermomech", "joule"}
AMBIG_ALIASES = {"실리콘", "silicon", "페라이트", "ferrite", "유리", "glass", "은", "금", "철", "동"}


def sweep_materials(lex):
    out = []
    for mid in polymer_ids(lex):
        for k, al in aliases(mid):
            if k == "ko":
                t = f"{al}에 구형 실리카 30 vol% 10um 열전도도 구해줘"
            else:
                t = f"{al} with 30 vol% spherical silica 10 um, thermal conductivity"
            out.append(Case("materials", t, {"matrix": mid, "fillers": [{"id": "sio2", "value": 30, "basis": "vol"}]},
                            allow_ask=al in AMBIG_ALIASES))
    for mid in filler_ids(lex):
        an = "dielectric" if mid in ("air", "vacuum") else "thermal"
        for k, al in aliases(mid):
            if k == "ko":
                ts = [f"에폭시에 구형 {al} 30 vol% 10um {'유전율' if an == 'dielectric' else '열전도도'} 구해줘",
                      f"에폭시 수지에 {al} 필러를 30 vol% 넣고 구형 10um, {'유전율' if an == 'dielectric' else '열전도도'}"]
            else:
                ts = [f"epoxy with 30 vol% spherical {al} 10 um, {'permittivity' if an == 'dielectric' else 'thermal conductivity'}",
                      f"{'permittivity' if an == 'dielectric' else 'thermal conductivity'} of epoxy filled with 30 vol% {al} spheres of 10 um"]
            for t in ts:
                out.append(Case("materials", t, {"matrix": "epoxy", "fillers": [{"id": mid, "value": 30, "basis": "vol", "d": 10.0}],
                                                 "analyses": [an]}, allow_ask=al in AMBIG_ALIASES))
    return out


def content_formats(v):
    f = v / 100.0
    fs = [(f"{v:g}%", None), (f"{v:g} %", None), (f"{v:g}퍼센트", None), (f"{v:g} 퍼센트", None), (f"{v:g}프로", None),
          (f"{v:g} vol%", "vol"), (f"{v:g}vol%", "vol"), (f"{v:g} vol.%", "vol"), (f"{v:g} 부피%", "vol"),
          (f"{v:g} 부피 퍼센트", "vol"), (f"{v:g} 체적%", "vol"), (f"{v:g} wt%", "wt"), (f"{v:g}wt%", "wt"),
          (f"{v:g} wt.%", "wt"), (f"{v:g} 중량%", "wt"), (f"{v:g} 무게%", "wt"), (f"{v:g} 질량%", "wt"),
          (f"{v:g}%(v/v)", "vol"), (f"{v:g}%(w/w)", "wt"), (f"{f:g}", None), (f"{f:g}만큼", None), (f"{f:g} 정도", None),
          (f"부피분율 {f:g}", "vol"), (f"중량분율 {f:g}", "wt"), (f"{v:g} percent", None), (f"{v:g} pct", None),
          (f"{v:g} vol percent", "vol"), (f"{v:g} weight percent", "wt")]
    if float(v).is_integer():
        fs += [(f"{ko_number(v)} 퍼센트", None), (f"{ko_number(v)}프로", None)]
        if v >= 20 or v in (5,):
            fs += [(f"{en_number(v)} percent", None), (f"{en_number(v)} vol%", "vol")]
        if v < 100 and v % 10 == 0:
            fs += [(f"영점{KO_DIG[int(v) // 10]}", None)]
        elif v < 100:
            fs += [(f"영점{KO_DIG[int(v) // 10]}{KO_DIG[int(v) % 10]}", None)]
    return fs


def sweep_contents(lex):
    out = []
    for v in (5, 12.5, 30, 45, 55, 62):
        for txt, basis in content_formats(v):
            exp = {"value": v, "id": "sio2"}
            exp["basis"] = basis or "vol"
            if has_hangul(txt) or not any(c.isalpha() for c in txt):
                t = f"에폭시에 구형 실리카 {txt} 10um 열전도도"
            else:
                t = f"epoxy with spherical silica {txt}, 10 um, thermal conductivity"
            out.append(Case("contents", t, {"fillers": [dict(exp, d=10.0)], "matrix": "epoxy"}))
    # parts per hundred resin and the content the matrix leaves
    for phr in (10, 30, 60):
        out.append(Case("contents", f"에폭시 100에 구형 실리카 {phr} phr 10um 열전도도",
                        {"fillers": [{"id": "sio2", "value": 100 * phr / (100 + phr), "basis": "wt"}]}))
    for m in (35, 40, 70):
        out.append(Case("contents", f"에폭시 {m}%에 구형 실리카 10um 열전도도", {"fillers": [{"id": "sio2", "value": 100 - m}]}))
        out.append(Case("contents", f"epoxy {m} vol% with spherical silica 10 um, thermal conductivity",
                        {"fillers": [{"id": "sio2", "value": 100 - m, "basis": "vol"}]}))
    for txt, v in (("1/3", 100 / 3), ("삼분의 일", 100 / 3), ("사분의 일", 25), ("절반", 50), ("half", 50)):
        t = (f"에폭시에 구형 실리카 {txt} 10um 열전도도" if has_hangul(txt) or "/" in txt
             else f"epoxy with spherical silica, {txt} of it by volume, 10 um, thermal conductivity")
        out.append(Case("contents", t, {"fillers": [{"id": "sio2", "value": v}]}))
    # contents that cannot be: asked
    for txt in ("0%", "100%", "120%", "1", "150 vol%"):
        out.append(Case("contents", f"에폭시에 구형 실리카 {txt} 10um 열전도도", {"ask": "content"}))
    return out


def sweep_sizes(lex):
    out = []
    for z in (0.5, 2, 5, 12.5, 40):
        fs = [f"{z:g}um", f"{z:g} um", f"{z:g} µm", f"{z:g}μm", f"{z:g} 마이크로", f"{z:g}마이크로미터", f"{z:g} 마이크론",
              f"{z:g}미크론", f"{z:g} micron", f"{z * 1000:g} nm", f"{z * 1000:g}나노", f"입경 {z:g}", f"지름 {z:g}um",
              f"D50 {z:g}", f"평균입경 {z:g} 마이크로", f"직경 {z:g} µm", f"{z:g} micrometers"]
        if z >= 5:
            fs.append(f"{z / 1000:g} mm")
        if float(z).is_integer():
            fs += [f"{ko_number(z)} 마이크로", f"{ko_number(z)}마이크론"]
        for s in fs:
            out.append(Case("sizes", f"에폭시에 구형 알루미나 30 vol% {s} 열전도도",
                            {"fillers": [{"id": "al2o3", "d": float(z), "value": 30}]}))
    return out


def sweep_shapes(lex):
    out = []
    for key, a in LD.SHAPES.items():
        if key == "network":
            for al in a["ko"]:
                out.append(Case("shapes", f"에폭시에 {al} 기공 30 vol% 유전율", {"fillers": [{"id": "air", "shape": "network"}]}))
            continue
        for al in a["ko"]:
            out.append(Case("shapes", f"에폭시에 {al} 알루미나 30 vol% 10um 열전도도", {"fillers": [{"id": "al2o3", "shape": key}]},
                            allow_ask=len(al) == 1))
            out.append(Case("shapes", f"에폭시에 알루미나 {al} 필러 30 vol% 10um 열전도도", {"fillers": [{"id": "al2o3", "shape": key}]},
                            allow_ask=len(al) == 1))
        for al in a["en"]:
            out.append(Case("shapes", f"epoxy with 30 vol% {al} alumina 10 um, thermal conductivity",
                            {"fillers": [{"id": "al2o3", "shape": key}]}))
    return out


def sweep_analyses(lex):
    out = []
    for key, a in LD.ANALYSES.items():
        fid = "air" if key in PORE_AN else AN_FILLER.get(key, "sio2")
        film = " 필름 두께 50um" if key in FILM_AN else ""
        film_en = ", film 50 um thick" if key in FILM_AN else ""
        shape = "다공성" if key in PORE_AN else "구형"
        shape_en = "porous" if key in PORE_AN else "spherical"
        fko = {"air": "기공", "ag": "은 필러", "sio2": "실리카", "nizn_ferrite": "니켈아연페라이트"}[fid]
        fen = {"air": "pores", "ag": "silver", "sio2": "silica", "nizn_ferrite": "NiZn ferrite"}[fid]
        for al in a["ko"]:
            out.append(Case("analyses", f"에폭시에 {shape} {fko} 30 vol% 10um{film} {al} 구해줘",
                            {"analyses": [key], "fillers": [{"id": fid}]}))
        for al in a["en"]:
            out.append(Case("analyses", f"{al} of epoxy with 30 vol% {shape_en} {fen} 10 um{film_en}",
                            {"analyses": [key], "fillers": [{"id": fid}]}))
    # two analyses, and the ambiguous one
    out.append(Case("analyses", "에폭시에 구형 실리카 30 vol% 10um 열전도도랑 유전율", {"analyses": ["thermal", "dielectric"]}))
    out.append(Case("analyses", "epoxy with 30 vol% spherical silica 10 um, thermal conductivity, CTE and permittivity",
                    {"analyses": ["thermal", "cte", "dielectric"]}))
    out.append(Case("analyses", "에폭시에 구형 실리카 30 vol% 10um 전도도", {"ask": "analysis"}))
    return out


def sweep_doe(lex):
    out = []
    ranges = [("{a}~{b}%", None), ("{a}-{b}%", None), ("{a}% ~ {b}%", None), ("{a}에서 {b}%까지", None), ("{a}부터 {b}%까지", None),
              ("{a}~{b} vol%", "vol"), ("{a} to {b} vol%", "vol"), ("from {a} to {b}%", None), ("between {a} and {b}%", None),
              ("{a}~{b} wt%", "wt")]
    steps = [("{n}단계", None), ("{n}수준", None), ("{n} levels", None), ("{n} points", None), ("{s}%씩", "s"), ("{s}% 간격", "s"),
             ("in steps of {s}", "s"), ("", None)]
    a, b = 40, 60
    for (rf, basis), (sf, kind) in itertools.product(ranges, steps):
        n = 5 if kind is None else 3
        s = 10
        rtxt = rf.format(a=a, b=b)
        stxt = sf.format(n=n, s=s)
        ko = has_hangul(rtxt + stxt) or not stxt
        t = (f"에폭시에 구형 알루미나 10um {rtxt} {stxt} 범위로 열전도도" if ko
             else f"epoxy with spherical alumina 10 um {rtxt} {stxt}, thermal conductivity")
        exp = {"task": "doe", "doe": [("phases.0.fraction.value", a, b, n)]}
        out.append(Case("doe", t, exp))
    for lst, n in (("40, 50, 60%", 3), ("40/50/60%", 3), ("30, 40, 50, 60 vol%", 4)):
        lo = float(lst.split(",")[0].split("/")[0])
        hi = 60.0
        out.append(Case("doe", f"에폭시에 구형 알루미나 10um {lst} 열전도도", {"task": "doe", "doe": [("phases.0.fraction.value", lo, hi, n)]}))
    for rng, n in (("입경 2~10um 5단계", 5), ("지름 1에서 5 마이크로까지 3단계", 3), ("size from 2 to 10 um in 5 levels", 5)):
        lo, hi = (2, 10) if "2" in rng.split("~")[0] or "from 2" in rng else (1, 5)
        t = (f"에폭시에 구형 알루미나 30 vol% {rng} 열전도도" if has_hangul(rng)
             else f"epoxy with 30 vol% spherical alumina, {rng}, thermal conductivity")
        out.append(Case("doe", t, {"task": "doe", "doe": [("phases.0.size.d", lo, hi, n)]}))
    return out


def sweep_calibration(lex):
    out = []
    units = [("W/mK", "k", 1.0, "열전도도"), ("W/m·K", "k", 1.0, "열전도도"), ("W/(m·K)", "k", 1.0, "열전도도"),
             ("S/m", "sigma", 1.0, "전기전도도"), ("S/cm", "sigma", 100.0, "전기전도도"), ("ppm/K", "alpha", 1.0, "열팽창계수"),
             ("GPa", "E", 1.0, "탄성계수")]
    unk = [("계면저항", ["phases.0.r_int"]), ("계면 열저항", ["phases.0.r_int"]), ("Kapitza", ["phases.0.r_int"]),
           ("interface resistance", ["phases.0.r_int"]), ("접촉저항", ["phases.0.r_contact"])]
    for (u, prop, f, word), (uw, up) in itertools.product(units, unk):
        fid = "ag" if prop == "sigma" else "sio2"
        fk = "은 필러" if fid == "ag" else "실리카"
        k1, k2 = (0.32, 0.55) if prop == "k" else ((2.5, 40.0) if prop == "sigma" else ((45.0, 30.0) if prop == "alpha" else (6.0, 11.0)))
        t = f"에폭시에 구형 {fk} 10um, 20%일 때 {k1:g} {u}, 40%일 때 {k2:g} {u} 측정됐어. {uw} 보정해줘"
        # an interface or contact resistance acts on the heat flow only (MPSim's thermal solve): for another
        # property the material value that property depends on is fitted instead, and the summary says why
        if prop != "k":
            up = [{"sigma": "phases.0.props.sigma", "alpha": "matrix.props.alpha", "E": "matrix.props.E"}[prop]]
        out.append(Case("calibration", t, {"task": "calibration", "cal": [(prop, k1 * f, 20.0), (prop, k2 * f, 40.0)],
                                           "unknowns": up}))
    out.append(Case("calibration", "measured 0.32 W/mK at 20% and 0.55 W/mK at 40% for epoxy with spherical silica 10 um, "
                    "calibrate the interface resistance",
                    {"task": "calibration", "cal": [("k", 0.32, 20.0), ("k", 0.55, 40.0)], "unknowns": ["phases.0.r_int"]}))
    out.append(Case("calibration", "에폭시에 구형 실리카 10um 30%에서 측정한 열전도도가 0.4 W/mK야. 보정해줘",
                    {"task": "calibration", "cal": [("k", 0.4, 30.0)]}))
    return out


def sweep_optimization(lex):
    out = []
    goals = [("최대가 되는", "max"), ("최대화", "max"), ("가장 높은", "max"), ("최소가 되는", "min"), ("최소화", "min"),
             ("가장 낮은", "min")]
    for (g, goal), (an, key) in itertools.product(goals, (("열전도도", "thermal"), ("열팽창계수", "cte"), ("유전율", "dielectric"))):
        t = f"에폭시에 구형 실리카 10um 함량을 30~60%로 바꿔가며 {an}가 {g} 조건 찾아줘"
        out.append(Case("optimization", t, {"task": "optimization", "goal": goal, "analyses": [key],
                                             "doe": [("phases.0.fraction.value", 30, 60, 5)]}))
    for g, goal in (("maximise", "max"), ("maximize", "max"), ("minimise", "min"), ("minimize", "min")):
        out.append(Case("optimization", f"{g} the thermal conductivity of epoxy with spherical silica 10 um between 30 and 60%",
                        {"task": "optimization", "goal": goal, "doe": [("phases.0.fraction.value", 30, 60, 5)]}))
    return out


def sweep_settings(lex):
    out = []
    base_ko, base_en = "에폭시에 구형 실리카 30 vol% 10um 열전도도", "epoxy with 30 vol% spherical silica 10 um, thermal conductivity"
    for key, a in LD.QUALITY.items():
        for al in a["ko"]:
            out.append(Case("settings", f"{base_ko} {al}", {"quality": key}))
        for al in a["en"]:
            out.append(Case("settings", f"{base_en}, {al}", {"quality": key}))
    for txt, st in (("코어 8개로", {"threads": 8}), ("8코어로", {"threads": 8}), ("스레드 6개", {"threads": 6}),
                    ("8 cores", {"threads": 8}), ("threads 4", {"threads": 4}), ("모든 코어 사용", {"threads": 0}),
                    ("all cores", {"threads": 0})):
        out.append(Case("settings", (f"{base_ko}, {txt}" if has_hangul(txt) else f"{base_en}, {txt}"), {"settings": st}))
    for txt, st in (("동시에 2개씩", {"concurrency": 2}), ("병렬로 3개", {"concurrency": 3}), ("2 at a time", {"concurrency": 2}),
                    ("in parallel 3", {"concurrency": 3})):
        t = (f"에폭시에 구형 실리카 10um 30~50% DOE 열전도도, {txt}" if has_hangul(txt)
             else f"epoxy with spherical silica 10 um from 30 to 50 %, thermal conductivity, {txt}")
        out.append(Case("settings", t, {"settings": st}))
    for txt, n in (("3번 반복", 3), ("3회 반복", 3), ("realisations 3", 3), ("repeat 3 times", 3), ("5 realizations", 5)):
        out.append(Case("settings", (f"{base_ko}, {txt}" if has_hangul(txt) else f"{base_en}, {txt}"), {"n_seeds": n}))
    for txt, n in (("seed 7", 7), ("시드 7", 7), ("random seed 12", 12)):
        out.append(Case("settings", (f"{base_ko}, {txt}" if has_hangul(txt) else f"{base_en}, {txt}"), {"seed": n}))
    dmap = {"z": "z", "x": "x", "xyz": "zxy"}
    for key, a in LD.DIRECTIONS.items():
        for al in a["ko"]:
            out.append(Case("settings", f"{base_ko} {al}", {"directions": dmap[key]}))
        for al in a["en"]:
            out.append(Case("settings", f"{base_en}, {al}", {"directions": dmap[key]}))
    for al in LD.AUTO["ko"]:
        out.append(Case("settings", f"에폭시에 실리카 30 vol% 열전도도 {al}", {"fillers": [{"id": "sio2", "shape": "sphere", "d": 10.0}]}))
    for al in LD.AUTO["en"]:
        out.append(Case("settings", f"epoxy with 30 vol% silica, thermal conductivity, {al}",
                        {"fillers": [{"id": "sio2", "shape": "sphere", "d": 10.0}]}))
    return out


def sweep_pairs(lex):
    out = []
    pick = ["sio2", "al2o3", "aln", "hbn", "mgo", "zno", "cu", "ag", "graphite", "sic", "diamond", "tio2"]
    names = {"sio2": ("실리카", "silica"), "al2o3": ("알루미나", "alumina"), "aln": ("질화알루미늄", "aluminium nitride"),
             "hbn": ("질화붕소", "boron nitride"), "mgo": ("산화마그네슘", "magnesium oxide"), "zno": ("산화아연", "zinc oxide"),
             "cu": ("구리", "copper"), "ag": ("은분말", "silver"), "graphite": ("흑연", "graphite"), "sic": ("탄화규소", "silicon carbide"),
             "diamond": ("다이아몬드", "diamond"), "tio2": ("이산화티타늄", "titania")}
    for x, y in itertools.combinations(pick, 2):
        out.append(Case("pairs", f"에폭시에 구형 {names[x][0]} 30 vol% 10um와 구형 {names[y][0]} 15 vol% 2um 열전도도",
                        {"fillers": [{"id": x, "value": 30, "d": 10.0}, {"id": y, "value": 15, "d": 2.0}]}))
        out.append(Case("pairs", f"epoxy with 30 vol% spherical {names[x][1]} 10 um and 15 vol% spherical {names[y][1]} 2 um, "
                        "thermal conductivity", {"fillers": [{"id": x, "value": 30, "d": 10.0}, {"id": y, "value": 15, "d": 2.0}]}))
    return out


def sweep_orders(lex):
    """Korean word orders and particles of one request."""
    out = []
    parts = {"M": ["에폭시에", "에폭시 수지에", "에폭시 기지에", "에폭시를 매트릭스로"],
             "F": ["구형 알루미나 필러를 55 vol%", "알루미나 55 vol%를 구형으로", "55 vol%의 구형 알루미나를", "구형 알루미나가 55 vol%"],
             "Z": ["입경 5um", "5 마이크로", "크기는 5um"],
             "A": ["열전도도 구해줘", "열전도율을 계산해줘", "열전도도가 궁금해"]}
    for m, f, z, a in itertools.product(*parts.values()):
        for order in ((m, f, z, a), (f, z, m, a), (a.replace(" 구해줘", "").replace("을 계산해줘", "").replace("가 궁금해", ""), m, f, z)):
            t = " ".join(order)
            out.append(Case("orders", t, {"matrix": "epoxy", "fillers": [{"id": "al2o3", "value": 55, "basis": "vol",
                                                                          "shape": "sphere", "d": 5.0}],
                                          "analyses": ["thermal"]}))
    return out


# typing errors made from every alias
_TENSE = {"ㄱ": "ㄲ", "ㄷ": "ㄸ", "ㅂ": "ㅃ", "ㅅ": "ㅆ", "ㅈ": "ㅉ", "ㅋ": "ㄲ", "ㅌ": "ㄸ", "ㅍ": "ㅃ", "ㅊ": "ㅉ"}
_VOW = {"ㅔ": "ㅐ", "ㅐ": "ㅔ", "ㅖ": "ㅒ", "ㅗ": "ㅓ", "ㅓ": "ㅗ", "ㅜ": "ㅡ", "ㅡ": "ㅜ", "ㅣ": "ㅢ"}


def _compose(c, v, j):
    return chr(0xAC00 + (CHO.index(c) * 21 + JUNG.index(v)) * 28 + JONG.index(j))


def ko_typos(word):
    out = set()
    sy = [(ch, divmod(ord(ch) - 0xAC00, 28)) if "가" <= ch <= "힣" else (ch, None) for ch in word]
    for i, (ch, code) in enumerate(sy):
        if code is None:
            continue
        (cv, jong) = code
        c, v, j = CHO[cv // 21], JUNG[cv % 21], JONG[jong]
        if v in _VOW:
            out.add(word[:i] + _compose(c, _VOW[v], j) + word[i + 1:])
        if c in _TENSE:
            out.add(word[:i] + _compose(_TENSE[c], v, j) + word[i + 1:])
        if j == "" and i < len(word) - 1:
            out.add(word[:i] + _compose(c, v, "ㄴ") + word[i + 1:])
    out.discard(word)
    return sorted(out)


def en_typos(word):
    w = word
    out = set()
    for i in range(1, len(w) - 1):
        if w[i].isalpha():
            out.add(w[:i] + w[i + 1:])                       # a letter dropped
            out.add(w[:i] + w[i] + w[i:])                    # a letter doubled
            if w[i + 1].isalpha():
                out.add(w[:i] + w[i + 1] + w[i] + w[i + 2:])  # two letters swapped
    out.discard(w)
    return sorted(out)


def sweep_typos(lex):
    out = []
    for mid in LD.MATERIALS:
        if lex.library and mid not in lex.library:
            continue
        poly = lex.group(mid) == "polymer"
        for k, al in aliases(mid, ("ko", "en")):
            if " " in al or al in AMBIG_ALIASES:
                continue
            if k == "ko" and len(al) >= 3:
                for ty in ko_typos(al)[:6]:
                    t = (f"{ty}에 구형 실리카 30 vol% 10um 열전도도" if poly else f"에폭시에 구형 {ty} 30 vol% 10um 열전도도")
                    out.append(Case("typos", t, {"matrix": mid} if poly else {"fillers": [{"id": mid}]}, allow_ask=True))
            if k == "en" and len(al) >= 7 and al.isalpha():
                for ty in en_typos(al.lower())[:8]:
                    t = (f"{ty} with 30 vol% spherical silica 10 um, thermal conductivity" if poly
                         else f"epoxy with 30 vol% spherical {ty} 10 um, thermal conductivity")
                    out.append(Case("typos", t, {"matrix": mid} if poly else {"fillers": [{"id": mid}]}, allow_ask=True))
    return out


def sweep_noise(lex):
    texts = ["안녕하세요", "오늘 날씨 좋네요", "결과를 빨리 보고 싶어요", "지난번 해석이랑 같은 조건으로 다시 해줘", "이거 왜 이렇게 오래 걸려",
             "고마워요", "그만해", "다시 시작해줘", "hello", "thanks a lot", "please run it again with the same settings",
             "what is the weather today", "how long will it take", "stop", "the previous result looked strange",
             "결과 그래프 좀 보여줘", "메모리가 부족한 것 같아", "속도가 너무 느려", "이 프로그램 이름이 뭐야", "can you explain the result"]
    return [Case("noise", t, {"ask": "everything"}) for t in texts]


def sweep_unknown(lex):
    texts = ["에폭시에 그래핀옥사이드 5% 열전도도", "에폭시에 XYZ필러 30% 열전도도", "에폭시에 산화세륨 20% 열전도도",
             "epoxy with 20% cerium oxide, thermal conductivity", "에폭시에 맥신 10% 전기전도도", "epoxy with 10% MXene, electrical conductivity",
             "에폭시에 유리 30% 열전도도", "에폭시에 페라이트 50% 투자율"]
    out = [Case("unknown", t, {"ask": "material"}) for t in texts]
    # a known name with a shape word joined to it is that material in that shape
    out.append(Case("unknown", "에폭시에 실리콘카바이드위스커 20 vol% 10um 열전도도",
                    {"fillers": [{"id": "sic", "shape": "fiber", "value": 20}]}))
    return out


def sweep_random(lex, n=1500, seed=None):
    """Random combinations of every dimension above, in Korean and English."""
    seed = int(os.environ.get("AIMPSIM_SEED") or 1) if seed is None else seed
    rng = random.Random(seed)
    out = []
    polys = [m for m in polymer_ids(lex) if m not in ("fr4", "sicoh")]
    fills = [m for m in filler_ids(lex) if m not in ("air", "vacuum", "hbn_platelet", "sicoh")]
    an_keys = ["thermal", "dielectric", "cte"]
    an_ko = {"thermal": ["열전도도", "열전도율", "방열 특성"], "dielectric": ["유전율", "유전상수", "Dk"], "cte": ["열팽창계수", "탄성계수", "CTE"]}
    an_en = {"thermal": ["thermal conductivity", "heat conduction"], "dielectric": ["permittivity", "dielectric constant"],
             "cte": ["CTE", "Young's modulus", "thermal expansion"]}
    shapes = {"sphere": (["구형", "구상"], ["spherical"]), "platelet": (["판상", "플레이크"], ["flake", "platelet"]),
              "irregular": (["불규칙", "파쇄형"], ["irregular", "angular"]), "cube": (["큐브"], ["cubic"])}

    def name(mid, ko):
        a = LD.MATERIALS[mid]
        lst = [x for x in (a["ko"] if ko else a["en"] + a.get("formula", [])) if x not in AMBIG_ALIASES and " " not in x.strip()
               or (not ko and x not in AMBIG_ALIASES)]
        lst = [x for x in lst if x not in AMBIG_ALIASES]
        return rng.choice(lst) if lst else None
    tries = 0
    while len(out) < n and tries < 20 * n:
        tries += 1
        ko = rng.random() < 0.6
        m = rng.choice(polys)
        nf = 1 if rng.random() < 0.75 else 2
        fs = rng.sample(fills, nf)
        mn = name(m, ko)
        fnames = [name(f, ko) for f in fs]
        if not mn or not all(fnames):
            continue
        vals = [rng.choice([10, 20, 25, 30, 35, 40, 45, 50, 55, 60])] if nf == 1 else [rng.choice([20, 30, 40]), rng.choice([5, 10, 15])]
        basis = rng.choice(["vol", "wt"])
        sh = [rng.choice(list(shapes)) for _ in fs]
        sz = [rng.choice([1, 2, 5, 10, 20]) for _ in fs]
        ans = rng.sample(an_keys, rng.choice([1, 1, 2]))
        exp_f = []
        frag = []
        for f, fname, v, s, z in zip(fs, fnames, vals, sh, sz):
            if ko:
                unit = rng.choice({"vol": ["vol%", "부피%"], "wt": ["wt%", "중량%"]}[basis])
                sw = rng.choice(shapes[s][0])
                frag.append(rng.choice([f"{sw} {fname} {v}{unit} {z}um", f"{fname} {v} {unit} ({sw}, {z} 마이크로)",
                                        f"{v}{unit}의 {sw} {fname} {z}um"]))
            else:
                unit = rng.choice({"vol": ["vol%", "vol.%"], "wt": ["wt%", "wt.%"]}[basis])
                sw = rng.choice(shapes[s][1])
                frag.append(rng.choice([f"{v} {unit} {sw} {fname} {z} um", f"{v}{unit} of {sw} {fname} ({z} um)"]))
            exp_f.append({"id": f, "value": v, "basis": basis, "shape": s, "d": float(z)})
        if ko:
            joiner = rng.choice(["와 ", ", ", " 그리고 "])
            an_txt = "와 ".join(rng.choice(an_ko[a]) for a in ans)
            t = rng.choice([f"{mn}에 {joiner.join(frag)} 넣은 복합재의 {an_txt} 구해줘", f"{mn} 수지에 {joiner.join(frag)}, {an_txt}"])
        else:
            an_txt = " and ".join(rng.choice(an_en[a]) for a in ans)
            t = rng.choice([f"{mn} with {' and '.join(frag)}, {an_txt}", f"{an_txt} of {mn} filled with {' and '.join(frag)}"])
        if sum(vals) >= 95:
            continue
        out.append(Case("random", t, {"matrix": m, "fillers": exp_f, "analyses": ans}))
    return out


def sweep_particles(lex):
    """Every particle after a material's name, in matrix and filler roles."""
    out = []
    names = {"sio2": "실리카", "al2o3": "알루미나", "aln": "질화알루미늄", "hbn": "질화붕소", "cu": "구리", "ag": "은분말",
             "graphite": "흑연", "diamond": "다이아몬드"}
    for mid, nm in names.items():
        for p, tmpl in (("를", "에폭시에 구형 {n}{p} 30 vol% 넣고 10um 열전도도"), ("을", "에폭시에 구형 {n}{p} 30 vol% 넣고 10um 열전도도"),
                        ("이", "에폭시에 구형 {n}{p} 30 vol% 들어간 10um 열전도도"), ("가", "에폭시에 구형 {n}{p} 30 vol% 들어간 10um 열전도도"),
                        ("은", "구형 {n}{p} 30 vol%, 10um, 에폭시 기지, 열전도도"), ("는", "구형 {n}{p} 30 vol%, 10um, 에폭시 기지, 열전도도"),
                        ("의", "에폭시에 구형 {n}{p} 함량 30 vol% 10um 열전도도"), ("로", "에폭시에 필러는 구형 {n}{p} 30 vol% 10um 열전도도"),
                        ("으로", "에폭시에 필러는 구형 {n}{p} 30 vol% 10um 열전도도"), ("만", "에폭시에 구형 {n}{p} 30 vol% 10um 열전도도"),
                        ("도", "에폭시에 구형 {n}{p} 30 vol% 10um 열전도도"), ("", "에폭시에 구형 {n} 30 vol% 10um 열전도도")):
            if p == "을" and nm[-1] in "카나":
                continue
            out.append(Case("particles", tmpl.format(n=nm, p=p),
                            {"matrix": "epoxy", "fillers": [{"id": mid, "value": 30, "d": 10.0}]}))
        for p in ("에", "에다", "에다가", "에는", "와", "랑", "이랑", "하고"):
            t = f"에폭시{p} 구형 {nm} 30 vol% 10um 열전도도" if p.startswith("에") else f"에폭시 수지{p} 구형 {nm} 30 vol% 10um 섞어서 열전도도"
            out.append(Case("particles", t, {"matrix": "epoxy", "fillers": [{"id": mid, "value": 30, "d": 10.0}]}))
    return out


SWEEPS = {"materials": sweep_materials, "contents": sweep_contents, "sizes": sweep_sizes, "shapes": sweep_shapes,
          "analyses": sweep_analyses, "doe": sweep_doe, "calibration": sweep_calibration, "optimization": sweep_optimization,
          "settings": sweep_settings, "pairs": sweep_pairs, "orders": sweep_orders, "particles": sweep_particles, "typos": sweep_typos, "noise": sweep_noise,
          "unknown": sweep_unknown, "random": sweep_random}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", default="")
    ap.add_argument("-v", action="store_true")
    ap.add_argument("--show", type=int, default=12)
    ap.add_argument("--llm", nargs=2, metavar=("SERVER_EXE", "MODEL"), help="read with the local model first (reader.py)")
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--sample", type=int, default=0, help="a random sample of this many requests per sweep")
    a = ap.parse_args()
    sys.stdout.reconfigure(line_buffering=True)
    host = host_for(find_mpsim())
    lex = Lexicon(host.get("library") or [])
    planner = Planner(lex, {"cores": 18})
    validate = host.get("validate")
    read, asst = None, None
    if a.llm:
        from aimpsim.llm import LocalLLM
        from aimpsim.web import Assistant
        asst = Assistant({"cores": 18, "library": host.get("library")})
        asst.llm = LocalLLM({"server_exe": a.llm[0], "model": a.llm[1], "threads": a.threads, "timeout_s": 300})
        if not asst.llm._start():
            sys.exit("the model server did not start")

        def read(text):
            r = asst.interpret(text, new=True)
            return asst.sessions[r["session_id"]]["intent"]
    rnd = random.Random(int(os.environ.get("AIMPSIM_SEED") or 1))
    t0 = time.time()
    total = collections.Counter()
    bad_all = 0
    for name, fn in SWEEPS.items():
        if a.sweep and a.sweep != name:
            continue
        cases = fn(lex)
        if a.sample and len(cases) > a.sample:
            cases = rnd.sample(cases, a.sample)
        cnt = collections.Counter()
        fails = []
        for c in cases:
            g, why = grade(c, planner, validate, read)
            if g == "asked!" and not c.allow_ask:
                g = "miss" if "noise" not in c.sweep else g
            cnt[g] += 1
            if g in ("wrong", "miss", "mpsim", "asked!"):
                fails.append((g, c.text, why))
        total.update(cnt)
        bad = sum(cnt[k] for k in ("wrong", "miss", "mpsim", "asked!"))
        bad_all += bad
        print(f"{name:13s} {len(cases):5d} cases: ok {cnt['ok']}, asked {cnt['asked']}"
              + (f", ASKED WITHOUT CAUSE {cnt['asked!']}" if cnt['asked!'] else "")
              + (f", WRONG {cnt['wrong']}" if cnt['wrong'] else "") + (f", MISS {cnt['miss']}" if cnt['miss'] else "")
              + (f", MPSIM {cnt['mpsim']}" if cnt['mpsim'] else ""))
        for g, t, why in fails[:a.show]:
            print(f"    {g:7s} {t}\n            {why}")
    n = sum(total.values())
    print(f"\n{n} requests: ok {total['ok']}, asked {total['asked']}, "
          f"wrong {total['wrong']}, missed {total['miss']}, asked without cause {total['asked!']}, refused by MPSim {total['mpsim']} "
          f"({time.time() - t0:.0f} s)")
    if asst is not None:
        asst.llm.close()
    return 1 if bad_all else 0


if __name__ == "__main__":
    sys.exit(main())
