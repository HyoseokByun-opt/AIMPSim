"""A sentence -> an intent: what to analyse, with which materials, how much
of each, and how.

The parser reads; it does not decide what was not said. Every value it
fills carries where it came from ("text", "fuzzy" for a word matched by
spelling or sound, "rule" for a unit rule such as 0.55 -> 55 %), so that the
summary can show it and the planner can ask about what is missing.

Which number belongs to which material: every content (a percent, a
fraction, a bare number said of a material) goes to the nearest material
mention - before it ("실리카 60%") or after it ("60 vol% silica") - with a
penalty for a material or a joining word (와, 과, and, ',') between them;
each material takes one. Sizes go to the nearest filler the same way, and
so do shape words.

Matrix or filler: a resin word next to it (레진, 수지, matrix, resin), or the
library group (polymers are matrices); without either, the material that
has no content while the others have one is the matrix ("알루미늄에 SiC
50%").
"""
from __future__ import annotations

import re

from . import lexicon_data as L
from .numbers import as_content, quantities, to_um
from .phonetic import has_hangul, squash
from .textnorm import normalize

_JOIN = re.compile(r"(?:,|;|\band\b|\bwith\b|와|과|랑|하고|및|그리고)", re.IGNORECASE)

CTX = {
    "step": r"(?:in\s+steps?\s+of|steps?\s+of|every|interval\s+of|간격(?:은|는|이)?)\s*$",
    "repeat": r"(?:realisations?|realizations?|repeats?|반복\s*횟수(?:는|은)?)\s*(?:=|:)?\s*$",
    "film": r"(?:필름|박막|film|층|layer)\s*(?:두께|thickness)?\s*(?:은|는|이|가|=|:)?\s*$",
    "size": r"(?:입경|지름|직경|크기|사이즈|입자\s*크기|평균\s*입경|입도|d50|d\s*50|size|diameter|dia\.?)\s*(?:은|는|이|가|=|:)?\s*$",
    "length": r"(?:길이|length|long)\s*(?:은|는|이|가|=|:)?\s*$",
    "thickness": r"(?:두께|thickness|thick)\s*(?:은|는|이|가|=|:)?\s*$",
    "aspect": r"(?:종횡비|형상비|aspect\s*ratio|\bar\b|l\s*/\s*d)\s*(?:은|는|이|가|=|:)?\s*$",
    "std": r"(?:표준\s*편차|편차|std\.?|sigma|σ|stdev)\s*(?:은|는|이|가|=|:)?\s*$",
    "cv": r"(?:cv|변동\s*계수)\s*(?:은|는|이|가|=|:)?\s*$",
    "rve": r"(?:rve|한\s*변|도메인|domain|box|박스)\s*(?:크기|size|edge)?\s*(?:은|는|이|가|=|:)?\s*$",
    "voxel": r"(?:복셀|voxel|격자\s*크기|해상도)\s*(?:크기|size)?\s*(?:은|는|이|가|=|:)?\s*$",
    "grid": r"(?:격자|grid|복셀\s*수)\s*(?:수)?\s*(?:은|는|이|가|=|:)?\s*$",
    "seed": r"(?:seed|시드|난수)\s*(?:은|는|이|가|=|:)?\s*$",
    "cores": r"(?<![가-힣A-Za-z])(?:코어|core|cores|스레드|thread|threads)\s*(?:를|을|는|은|=|:)?\s*$",
    "parallel": r"(?:동시에|동시|병렬로|병렬|parallel|at\s*once)\s*(?:로)?\s*$",
    "measured": r"(?:측정값|측정치|실측|measured|measurement)\s*(?:은|는|이|가|=|:)?\s*$",
}
AFTER = {
    "step": r"^\s*(?:간격|씩|단위|step|steps\b|increments?|interval)",
    "cores": r"^\s*(?:코어|cores?|threads?|스레드)",
    "parallel": r"^\s*(?:씩\s*(?:동시|병렬)|at\s*a\s*time|in\s*parallel|동시|병렬)",
    "levels": r"^\s*(?:단계|수준|레벨|levels?|points?|cases?|케이스)",
}
PROPERTY_UNITS = {"W/mK": "k", "S/m": "sigma", "S/cm": "sigma", "ohm_m": "sigma", "ohm_cm": "sigma",
                  "ppm/K": "alpha", "GPa": "E", "Pa.s": "mu"}


def _before(text, q, n=24):
    return text[max(0, q["start"] - n):q["start"]].lower()


def _after(text, q, n=16):
    return text[q["end"]:q["end"] + n].lower()


def _ctx(text, q):
    b, a = _before(text, q), _after(text, q)
    if q.get("unit") in ("vol", "wt", "pct", "phr"):
        # a percent is a content, or the step of a range
        return "step" if re.search(AFTER["step"], a, re.IGNORECASE) else None
    for k, rx in CTX.items():
        if re.search(rx, b, re.IGNORECASE):
            return k
    for k, rx in AFTER.items():
        if re.search(rx, a, re.IGNORECASE):
            return k
    return None


def parse(text, lex):
    raw = text or ""
    lang = "ko" if has_hangul(raw) else "en"
    t = normalize(raw)
    low = t.lower()
    ms = lex.scan(t)
    qs = quantities(t)
    notes = []
    intent = {"lang": lang, "text": raw, "norm": t, "task": None, "matrix": None, "fillers": [], "analyses": [],
              "analysis_choices": [], "quality": None, "auto": False, "directions": None, "orientation": None,
              "dist": None, "parallel": {}, "seeds": None, "seed": None, "rve": {}, "film": None,
              "doe": {"factors": [], "steps": None, "step": None}, "calibration": {"measurements": [], "unknowns": []},
              "optimization": {}, "unresolved": [], "notes": notes, "basis": None, "matrix_pct": None,
              "orphan": {}}

    # ---- settings words --------------------------------------------------
    for m in ms:
        k = m["kind"]
        if k == "quality":
            intent["quality"] = m["key"]
        elif k == "auto":
            intent["auto"] = True
        elif k == "direction":
            intent["directions"] = m["key"]
        elif k == "orientation":
            intent["orientation"] = m["key"]
        elif k == "dist":
            intent["dist"] = {"type": m["key"]}
    if re.search(r"(?:부피\s*(?:비|분율|기준|%|퍼센트)|체적\s*(?:비|분율|기준)|by\s*volume|volume\s*fraction|vol\s*%|v/v)", low):
        intent["basis"] = "vol"
    if re.search(r"(?:중량\s*(?:비|분율|기준|%|퍼센트)|무게\s*(?:비|기준|%|퍼센트)|질량\s*(?:비|분율|기준)|by\s*(?:weight|mass)"
                 r"|weight\s*fraction|mass\s*fraction|wt\s*%|w/w)", low):
        intent["basis"] = "wt" if intent["basis"] is None else "mixed"

    # ---- tasks -------------------------------------------------------------
    tasks = {m["key"] for m in ms if m["kind"] == "task"}

    # ---- materials -----------------------------------------------------------
    slots = []
    for m in ms:
        if m["kind"] not in ("material", "material?", "unknown"):
            continue
        key = m["key"]
        if m["kind"] == "material" and not isinstance(key, tuple):
            same = next((s for s in slots if s["id"] == key), None)
            if same:
                same["spans"].append((m["start"], m["end"]))
                continue
        s = {"id": key if m["kind"] == "material" and not isinstance(key, tuple) else None,
             "choices": list(key) if isinstance(key, tuple) else [], "spans": [(m["start"], m["end"])],
             "text": m["text"], "how": m["how"], "score": m["score"], "kind": m["kind"], "alts": m["alts"],
             "role": None, "content": None, "size_um": None, "shape": None, "size_src": None, "shape_src": None,
             "aspect": None, "length_um": None, "thickness_um": None, "std_um": None, "cv": None}
        if m["kind"] == "material" and m["how"] == "fuzzy":
            notes.append({"type": "fuzzy", "text": m["text"], "id": key, "score": round(m["score"], 2)})
        slots.append(s)
    # roles from the words next to each mention
    for m in ms:
        if m["kind"] != "role":
            continue
        best, bd = None, 99
        for s in slots:
            for a, b in s["spans"]:
                d = m["start"] - b if m["start"] >= b else 99      # a role word follows its material
                if m["start"] >= a and m["end"] <= b:
                    d = 0
                if 0 <= d < bd and d <= 3:
                    best, bd = s, d
        if best is not None and best["role"] is None:
            best["role"] = m["key"]

    # clauses split at joining words and commas, never inside brackets
    depth, marks = 0, []
    for m in re.finditer(r"[()\[\]]|,|;|\band\b|\bwith\b|\bplus\b|(?<=\S)(?:와|과|랑|하고)(?=\s)|\s및\s|그리고", t,
                         re.IGNORECASE):
        g = m.group(0)
        if g in "([":
            depth += 1
        elif g in ")]":
            depth = max(0, depth - 1)
        elif depth == 0:
            marks.append(m.start())

    def clause(pos):
        return sum(1 for x in marks if x < pos)

    def dist(s, a, b):
        """characters between a span and the nearest mention of a slot, with
        a penalty for another material or a joining word in between"""
        best = 10 ** 6
        for sa, sb in s["spans"]:
            if b <= sa:
                gap, lo, hi = sa - b, b, sa
                after = False
            elif a >= sb:
                gap, lo, hi = a - sb, sb, a
                after = True
            else:
                return 0
            between = t[lo:hi]
            pen = 0
            if clause(sa) != clause(a):
                pen += 25                  # another clause: "epoxy with | 30 vol% silica", "..와 | 알루미나 15%"
            if after and (re.match(r"\s*(?:에|에는|에다|에다가)\s", between)
                          or re.search(r"(?:에|에는|에다|에다가)$", t[sa:sb])):
                pen += 12                  # "에폭시에 30% ...": the receiving matrix
            if after and re.match(r"\s*의(?=\s)", t[b:b + 3]):
                pen += 15                  # "55 vol%의 알루미나": the number is the next material's
            if not after and not has_hangul(t):
                pen -= 3                   # English reads "30 vol% silica"
            if any(o is not s and any(lo <= x < hi for x, _ in o["spans"]) for o in slots):
                pen += 40
            if _JOIN.search(between):
                pen += 4
            # Korean reads "MAT 60%": a number after its material is the closer reading
            if has_hangul(t) and not after:
                pen += 1
            best = min(best, gap + pen)
        return best

    # ---- quantities ----------------------------------------------------------
    contents, sizes, measured = [], [], []
    # a number inside a known word ("3방향", "SU-8") is part of that word
    spans = [(m["start"], m["end"]) for m in ms if m["kind"] not in ("unknown", "role")]
    qs = [q for q in qs if not any(a <= q["start"] < b for a, b in spans)]
    for q in qs:
        c = _ctx(t, q)
        u = q.get("unit")
        q["ctx"] = c
        if u in ("um", "nm", "mm") or c in ("size", "length", "thickness", "std", "film"):
            if c == "rve":
                intent["rve"]["L_um"] = to_um(q["value"], u or "um")
            elif c == "voxel":
                intent["rve"]["voxel_um"] = to_um(q["value"], u or "um")
            elif c == "film":
                intent["film"] = to_um(q["value"], u or "um")
            else:
                if u is None:
                    notes.append({"type": "unit", "text": q["raw"], "rule": "size_um"})
                sizes.append(q)
            continue
        if c == "rve":
            intent["rve"]["L_um"] = q["value"]
            continue
        if c == "voxel":
            intent["rve"]["voxel_um"] = q["value"]
            continue
        if c == "grid" and u is None:
            intent["rve"]["N"] = int(q["value"])
            continue
        if c == "aspect":
            sizes.append(q)
            continue
        if c == "cv":
            sizes.append(q)
            continue
        if c == "seed":
            intent["seed"] = int(q["value"])
            continue
        if u == "cores" or c == "cores":
            intent["parallel"]["threads"] = int(q["value"])
            continue
        if c == "parallel":
            intent["parallel"]["concurrency"] = int(q["value"])
            continue
        if u == "repeat" or c == "repeat":
            intent["seeds"] = int(q["value"])
            continue
        if u == "levels" or c == "levels":
            intent["doe"]["steps"] = int(q["value"])
            continue
        if c == "step":
            intent["doe"]["step"] = q["value"]
            continue
        if u == "count":
            b = _before(t, q, 12)
            if re.search(r"(?:코어|core|스레드|thread)\s*$", b):
                intent["parallel"]["threads"] = int(q["value"])
            elif re.search(r"(?:동시에|병렬)\s*$", b):
                intent["parallel"]["concurrency"] = int(q["value"])
            continue
        if u in PROPERTY_UNITS or c == "measured":
            measured.append(q)
            continue
        if u == "C":
            continue
        if as_content(q) is not None:
            contents.append(q)

    # contents -> materials, one each, nearest first
    pairs = sorted(((dist(s, q["start"], q["end"]), i, j) for j, q in enumerate(contents) for i, s in enumerate(slots)),
                   key=lambda x: x[0])
    used_q, used_s = set(), set()
    for d, i, j in pairs:
        if i in used_s or j in used_q or d > 60:
            continue
        q, s = contents[j], slots[i]
        val, basis, how = as_content(q)
        s["content"] = {"value": val, "basis": basis, "how": how, "raw": q["raw"]}
        if "hi" in q:
            s["content"]["range"] = (val, as_content(dict(q, value=q["hi"]))[0] if as_content(dict(q, value=q["hi"])) else q["hi"])
        if q.get("levels"):
            s["content"]["levels"] = [as_content(dict(q, value=v))[0] for v in q["levels"]]
        if how in ("fraction", "bare"):
            notes.append({"type": "unit", "text": q["raw"], "rule": how, "value": val})
        used_q.add(j)
        used_s.add(i)
    for j, q in enumerate(contents):
        if j not in used_q:
            if not slots and "content" not in intent["orphan"]:
                # an answer with no material in it ("55%", "0.55"): for the filler asked about
                val, basis, how = as_content(q)
                intent["orphan"]["content"] = {"value": val, "basis": basis, "how": how, "raw": q["raw"]}
                continue
            intent["unresolved"].append({"kind": "content", "text": q["raw"], "value": as_content(q)[0]})

    # roles and the matrix
    for s in slots:
        if s["id"] and s["role"] is None:
            if lex.is_void(s["id"]):
                s["role"] = "filler"
    polymer = [s for s in slots if s["id"] and lex.group(s["id"]) == "polymer" and s["role"] != "filler"]
    explicit = [s for s in slots if s["role"] == "matrix"]
    matrix = None
    if len(explicit) == 1:
        matrix = explicit[0]
    elif len(polymer) == 1:
        matrix = polymer[0]
    elif len(polymer) > 1:
        matrix = polymer[0]
        notes.append({"type": "two_resins", "ids": [s["id"] for s in polymer]})
    else:
        amb = [s for s in slots if s["kind"] == "material" and s["choices"]
               and any(lex.group(c) == "polymer" for c in s["choices"])]
        if len(amb) == 1 and len([s for s in slots if s is not amb[0]]) >= 1:
            matrix = amb[0]
            matrix["id"] = next(c for c in matrix["choices"] if lex.group(c) == "polymer")
            notes.append({"type": "ambiguous_resolved", "text": matrix["text"], "id": matrix["id"], "as": "matrix"})
            matrix["choices"] = []
        else:
            no_content = [s for s in slots if s["content"] is None and s["kind"] == "material"]
            with_content = [s for s in slots if s["content"] is not None]
            if len(no_content) == 1 and with_content:
                matrix = no_content[0]
                notes.append({"type": "matrix_by_content", "id": matrix["id"]})
    fillers = [s for s in slots if s is not matrix]
    # an ambiguous filler word: the non-polymer reading when a matrix is known
    for s in fillers:
        if s["choices"] and matrix is not None and s["kind"] == "material":
            non = [c for c in s["choices"] if lex.group(c) != "polymer"]
            if len(non) == 1:
                s["id"] = non[0]
                notes.append({"type": "ambiguous_resolved", "text": s["text"], "id": s["id"], "as": "filler"})
                s["choices"] = []

    # sizes, aspect, std -> fillers
    for q in sizes:
        cand = [s for s in fillers] or slots
        if not cand:
            key = {"aspect": "aspect", "length": "length_um", "thickness": "thickness_um", "std": "std_um"}.get(q["ctx"], "size_um")
            intent["orphan"][key] = q["value"] if key == "aspect" else to_um(q["value"], q.get("unit") or "um")
            continue
        s = min(cand, key=lambda s: dist(s, q["start"], q["end"]))
        c, v = q["ctx"], q["value"]
        um = to_um(v, q.get("unit") or "um")
        if c == "aspect":
            s["aspect"] = v
        elif c == "cv":
            s["cv"] = as_content(q)[0] / 100.0 if as_content(q) else v
        elif c == "std":
            s["std_um"] = um
        elif c == "length":
            s["length_um"] = um
        elif c == "thickness":
            s["thickness_um"] = um
        elif s["size_um"] is None:
            s["size_um"] = um
            s["size_src"] = "text"
            if "hi" in q:
                s["size_range"] = (um, to_um(q["hi"], q.get("unit") or "um"))
            if q.get("levels"):
                s["size_levels"] = [to_um(x, q.get("unit") or "um") for x in q["levels"]]
    # shapes -> fillers
    for m in ms:
        if m["kind"] != "shape":
            continue
        cand = fillers or slots
        if m["key"] == "network":
            vo = [s for s in cand if s["id"] and lex.is_void(s["id"])]
            cand = vo or cand
        if not cand:
            intent["orphan"]["shape"] = m["key"]
            continue
        s = min(cand, key=lambda s: dist(s, m["start"], m["end"]))
        if s["shape"] is None:
            s["shape"], s["shape_src"] = m["key"], "text"

    intent["matrix"] = matrix
    intent["fillers"] = fillers
    if matrix is not None and matrix["content"] is not None:
        intent["matrix_pct"] = matrix["content"]
    # a basis said once ("부피분율 0.55", "by weight") for the contents that have none
    if intent["basis"] in ("vol", "wt"):
        for s in slots:
            if s["content"] and s["content"].get("basis") is None:
                s["content"]["basis"] = intent["basis"]
    # parts per hundred resin: by weight, of the resin and every phr filler together
    phr = [s for s in fillers if s["content"] and s["content"].get("basis") == "phr"]
    if phr:
        tot = sum(s["content"]["value"] for s in phr)
        for s in phr:
            v = s["content"]["value"]
            s["content"] = dict(s["content"], value=100.0 * v / (100.0 + tot), basis="wt", how="phr")
            notes.append({"type": "phr", "text": f"{v:g} phr", "value": 100.0 * v / (100.0 + tot)})
        if intent["matrix_pct"] and abs(intent["matrix_pct"]["value"] - 100.0) < 1e-9:
            intent["matrix_pct"] = None                   # "에폭시 100에 ... phr": the resin's 100 parts
    # the content the matrix leaves to a single filler ("에폭시 40%에 실리카")
    if intent["matrix_pct"] and len(fillers) == 1 and fillers[0]["content"] is None:
        mp = intent["matrix_pct"]
        fillers[0]["content"] = {"value": 100.0 - mp["value"], "basis": mp.get("basis"), "how": "derived",
                                 "raw": f"100 - {mp['raw']}"}
        notes.append({"type": "derived", "value": 100.0 - mp["value"], "matrix": mp["value"]})
    for s in fillers:
        if s["shape"] is None and s["id"] in L.MATERIAL_SHAPE:
            s["shape"], s["shape_src"] = L.MATERIAL_SHAPE[s["id"]], "text"

    # ---- analyses --------------------------------------------------------------
    intent["analysis_spans"] = [(m["key"], m["start"], m["end"]) for m in ms if m["kind"] == "analysis"]
    for m in ms:
        if m["kind"] == "analysis" and m["key"] not in intent["analyses"]:
            intent["analyses"].append(m["key"])
            if m["how"] == "fuzzy":
                notes.append({"type": "fuzzy_analysis", "text": m["text"], "key": m["key"], "score": round(m["score"], 2)})
        elif m["kind"] == "analysis?":
            near = t[max(0, m["start"] - 4):m["start"]]
            keys = list(m["key"])
            if re.search(r"열|thermal|heat", near, re.IGNORECASE) and "thermal" in keys:
                pick = "thermal"
            elif re.search(r"전기|electric", near, re.IGNORECASE) and "electrical" in keys:
                pick = "electrical"
            elif "magnetic" in keys and any(s["id"] in ("ni", "carbonyl_iron", "sendust", "nizn_ferrite", "mnzn_ferrite")
                                            for s in fillers):
                pick = "magnetic"
            elif "permeability" in keys and any(s["id"] and lex.is_void(s["id"]) for s in fillers):
                pick = "permeability"
            else:
                pick = None
            if pick and pick not in intent["analyses"]:
                intent["analyses"].append(pick)
            elif not pick:
                intent["analysis_choices"].append({"text": m["text"], "keys": keys})
        elif m["kind"] == "analysis_group":
            for k in m["key"]:
                if k not in intent["analyses"]:
                    intent["analyses"].append(k)
            notes.append({"type": "analysis_group", "text": m["text"], "keys": list(m["key"])})
        elif m["kind"] == "analysis_all":
            intent["analysis_choices"].append({"text": m["text"], "keys": ["thermal", "electrical", "dielectric", "cte"]})

    # ---- measurements (calibration) and targets (optimisation) ------------------------
    prop_words = {"k": "thermal", "sigma": "electrical", "eps_r": "dielectric", "alpha": "cte", "E": "cte", "mu": "viscosity"}
    for q in measured:
        prop = PROPERTY_UNITS.get(q.get("unit"))
        val = q["value"]
        if q.get("unit") == "S/cm":
            val *= 100.0
        elif q.get("unit") == "ohm_m":
            prop, val = "sigma", 1.0 / val if val else None
        elif q.get("unit") == "ohm_cm":
            prop, val = "sigma", 100.0 / val if val else None
        if prop is None:
            b = _before(t, q, 16)
            for word, p in (("유전", "eps_r"), ("dk", "eps_r"), ("permittivity", "eps_r"), ("열전도", "k"),
                            ("모듈러스", "E"), ("modulus", "E"), ("cte", "alpha"), ("열팽창", "alpha")):
                if word in b:
                    prop = p
                    break
        if prop is None or val is None:
            continue
        # the condition: the content said just before it ("20%일 때 0.45")
        cond = None
        prev = [c for c in qs if c["end"] <= q["start"] and as_content(c) is not None and c.get("unit") not in PROPERTY_UNITS]
        if prev and q["start"] - prev[-1]["end"] <= 14:
            cond = as_content(prev[-1])[0]
        nxt = [c for c in qs if c["start"] >= q["end"] and as_content(c) is not None and c.get("unit") not in PROPERTY_UNITS]
        if nxt and re.match(r"\s*(?:at|@|for|에서|에)\s*$", t[q["end"]:nxt[0]["start"]], re.IGNORECASE):
            cond = as_content(nxt[0])[0]
        intent["calibration"]["measurements"].append({"property": prop, "value": val, "content": cond, "raw": q["raw"],
                                                      "analysis": prop_words.get(prop)})
        if cond is not None:
            intent["unresolved"] = [u for u in intent["unresolved"]
                                    if not (u["kind"] == "content" and u.get("value") == cond)]
        if prop_words.get(prop) and prop_words[prop] not in intent["analyses"]:
            intent["analyses"].append(prop_words[prop])
    # a measurement-like value said as a goal
    if re.search(r"(?:최대|높게|높은|maxim|highest|max\b)", low):
        intent["optimization"]["goal"] = "max"
    if re.search(r"(?:최소|낮게|낮은|minim|lowest|min\b)", low):
        intent["optimization"]["goal"] = "min"
    if re.search(r"(?:목표|타겟|target|맞추)", low) and intent["calibration"]["measurements"]:
        intent["optimization"]["goal"] = "target"
        intent["optimization"]["target"] = intent["calibration"]["measurements"][-1]["value"]
    # unknowns of a calibration
    for m in ms:
        if m["kind"] == "unknown_param" and m["key"] not in intent["calibration"]["unknowns"]:
            intent["calibration"]["unknowns"].append(m["key"])
    if re.search(r"(?:필러|filler).{0,6}(?:열전도|conductivity)", low):
        intent["calibration"]["unknowns"].append("filler_k")

    # ---- the task --------------------------------------------------------------------
    ranged = any(s["content"] and ("range" in s["content"] or "levels" in s["content"]) for s in slots) \
        or any(s.get("size_range") or s.get("size_levels") for s in slots)
    if "calibration" in tasks or (intent["calibration"]["measurements"] and re.search(r"측정|실측|measur", low)):
        intent["task"] = "calibration"
    elif "optimization" in tasks or (intent["optimization"].get("goal") in ("max", "min") and ranged):
        intent["task"] = "optimization"
    elif "doe" in tasks or ranged:
        intent["task"] = "doe"
    elif "structure" in tasks:
        intent["task"] = "structure"
    # DOE factors
    for i, s in enumerate(fillers):
        c = s["content"] or {}
        if "range" in c or "levels" in c:
            intent["doe"]["factors"].append({"filler": i, "what": "content", "range": c.get("range"),
                                             "levels": c.get("levels")})
        if s.get("size_range") or s.get("size_levels"):
            intent["doe"]["factors"].append({"filler": i, "what": "size", "range": s.get("size_range"),
                                             "levels": s.get("size_levels")})
    if intent["seed"] is None:
        m = re.search(r"(?:seed|시드)\s*(\d+)\s*~\s*(\d+)", low)
        if m:
            intent["doe"]["factors"].append({"what": "seed", "range": (int(m.group(1)), int(m.group(2)))})
    # parallel words without numbers
    if re.search(r"(?:모든\s*코어|전체\s*코어|코어\s*(?:전부|모두|최대)|all\s*cores|every\s*core|max(?:imum)?\s*cores)", low):
        intent["parallel"]["threads"] = 0
    # words that name a material nobody knows
    for s in slots:
        if s["kind"] == "unknown":
            intent["unresolved"].append({"kind": "material", "text": s["text"],
                                         "candidates": [a[0] for a in s["alts"]][:3]})
        elif s["kind"] == "material?":
            intent["unresolved"].append({"kind": "material?", "text": s["text"], "candidates": s["choices"][:3],
                                         "slot": s})
    return intent


def squash_all(*a):
    return [squash(x) for x in a]


_ = L  # the lexicon module is imported for its tables in callers
