"""Design requests: what to use to reach a target.

"With as little alumina as possible, reach k_z = 3 W/mK in a 10 um epoxy
film; tell me the sizes and the blend; topcut 3 um, smallest 200 nm, at
most 62 vol%; at a similar conductivity, lower viscosity and better
packing; R filler-resin and filler-filler 1E-8."

Read (read): the rules find the explicit parts - the target with its unit
and direction, what is minimised, the bounds of size and content, one size
per class (no distribution), the interface resistances, what is to be
found and the preferences. The model's reading (reader.py) fills only what
they leave open, every number checked against the sentence.

Planned (planner.py, factors): a DOE over what is to be found - the total
filler content, the coarse and the fine size, the fine share of the filler
- with the fixed conditions (film, R_int, R_c, direction) in its base case.

Chosen after the runs (recommend): a Gaussian-process surrogate of the
target property (MPSim's optimise.py, cross-validated) over the design
space; the lowest content whose prediction meets the target; among the
recipes within a tolerance of that content, the lowest viscosity. Packing
and viscosity are not fitted: the random close packing of the blend
(Farr-Groot) and Krieger-Dougherty with it are the closed forms MPSim's
viscosity analysis uses for spheres, evaluated exactly at every candidate.
The recipe is then run once - thermal and the full viscosity analysis - to
check the prediction.
"""
from __future__ import annotations

import math
import re

from .numbers import quantities, to_um
from .textnorm import normalize

# the property a target names, its analysis, its key among MPSim's headline numbers
PROP_ANALYSIS = {"k": "thermal", "sigma": "electrical", "eps_r": "dielectric", "alpha": "cte", "E": "cte"}
PROP_RESPONSE = {"k": "k", "sigma": "sigma", "eps_r": "eps", "alpha": "alpha", "E": "E"}
PROP_UNIT = {"k": "W/m·K", "sigma": "S/m", "eps_r": "", "alpha": "ppm/K", "E": "GPa"}
UNIT_PROP = {"W/mK": "k", "S/m": "sigma", "S/cm": "sigma", "ppm/K": "alpha", "GPa": "E"}
# what more filler usually does: a target of k is a floor, a target of CTE a ceiling
DEFAULT_OP = {"k": ">=", "sigma": ">=", "E": ">=", "alpha": "<=", "eps_r": "="}
PROP_WORDS = {
    "k": r"열\s*전도\s*(?:도|율)?|thermal\s+conductivity|(?<![a-z])k\s*_?\s*(?:z|zz|eff)?(?![a-z])|\btc\b",
    "sigma": r"전기\s*전도\s*(?:도|율)?|electrical\s+conductivity|도전율",
    "eps_r": r"유전\s*(?:율|상수)|\bdk\b|permittivity|dielectric\s+constant",
    "alpha": r"열\s*팽창\s*(?:계수|율)?|\bcte\b|thermal\s+expansion",
    "E": r"탄성\s*(?:계수|률)|모듈러스|영\s*률|young'?s?\s+modulus|\bmodulus\b|강성|stiffness",
}
TARGET_CUE = (r"(?:로|으로)\s*(?:할|하는|하려|만들|맞추|맞출|올리|올릴|낮추|되|나오|달성|확보)|이상|이하|넘|미만|초과|목표|타겟|"
              r"target|reach|achiev|at\s+least|at\s+most|≥|>=|≤|<=|만족|도달|되도록|되게|나오게|나오는|되는|될|"
              r"할\s*수\s*있|to\s+get|to\s+hit|or\s+more|or\s+less|over\b|above\b|below\b|under\b|minimum\s+of|maximum\s+of|"
              r"되려면|하려면|위해|for\s+a|for\s+an|meet|가까운|가깝게|가장\s*가까|closest|nearest|close\s+to|keeps?\s+the")
OP_GE = r"이상|넘|초과|at\s+least|≥|>=|or\s+more|over\b|above\b|more\s+than|minimum\s+of|not\s+(?:less|below)"
OP_LE = r"이하|미만|at\s+most|≤|<=|or\s+less|below\b|under\b|less\s+than|넘지\s*않|maximum\s+of|not\s+(?:more|above)"
OP_EQ = r"맞추|맞출|정확히|exactly|딱\s|가장\s*가까|가까운|정도|closest|nearest|close\s+to|as\s+near"
DIR_Z = (r"z\s*-?\s*(?:방향|축|direction|axis)|두께\s*방향|수직\s*방향|through[- ]?(?:plane|thickness)|out[- ]of[- ]plane"
         r"|(?<![a-z])k\s*_?\s*zz?(?![a-z])|\bin\s+z\b|along\s+z")
DIR_XY = r"면\s*내|면\s*방향|in[- ]?plane|x\s*-?\s*(?:방향|direction)|수평\s*방향|lateral"
MIN_CONTENT = (r"(?:함량|충전량|충진량|첨가량|사용량|투입량|loading|content|amount|fraction)\s*(?:을|를|은|는|이|가)?\s*"
               r"(?:가장|최대한|최소한|되도록|제일|최소로|최저로|더)?\s*(?:낮|적|줄|최소|최저|덜|아끼)"
               r"|(?:최소|최저|가장\s*적은|가장\s*낮은|최소한의)\s*(?:의\s*)?(?:[가-힣A-Za-z0-9]{1,8}\s*)?(?:함량|충전량|충진량|loading|양)"
               r"|(?:least|lowest|minimum|minimal|smallest)\s+(?:\w+\s+){0,2}?(?:loading|content|amount|fraction|filler)"
               r"|minimi[sz]e\s+(?:the\s+)?(?:\w+\s+)?(?:loading|content|amount|filler)|as\s+little\s+(?:[\w-]+\s+){0,3}as\s+possible"
               # "최소 wt%", "최소 몇 프로", "몇 % 넣어야", "the lowest total vol%"
               r"|(?:최소|최저|가장\s*적은|가장\s*낮은)\s*(?:총\s*)?(?:몇\s*)?(?:vol|wt)?\s*(?:%|프로|퍼센트)"
               r"|몇\s*(?:%|프로|퍼센트|vol\s*%|wt\s*%)\s*(?:를|을|나|이나|정도)?\s*(?:넣|써|사용|필요|첨가)"
               r"|(?:least|lowest|minimum)\s+(?:total\s+)?(?:vol|wt|volume|weight)\s*(?:%|percent|fraction)"
               r"|how\s+(?:much|little)\s+(?:\w+\s+){0,3}(?:do\s+i|should\s+i|is)\s+(?:need|needed|add|use)"
               r"|아끼|적게\s*넣|덜\s*넣")
MIN_VISC = r"점도\s*(?:를|가|는)?\s*(?:가장|최대한|최소)\s*(?:로|낮|최소)|최소\s*점도|lowest\s+viscosity|minimi[sz]e\s+(?:the\s+)?viscosity"
LOW_VISC = (r"점도\s*(?:는|가|를|도)?\s*(?:더\s*)?(?:낮|작|적|최소)|저\s*점도|흐름성|유동성\s*(?:이|은)?\s*(?:좋|우수)|잘\s*흐르"
            r"|low(?:er)?\s+viscosity|less\s+viscous|flows?\s+(?:well|better|easily)")
HIGH_PACK = (r"패킹\s*(?:은|이|도|성)?\s*(?:이\s*)?(?:잘|좋|높|우수)|충(?:진|전)\s*(?:성|율|밀도)?\s*(?:이|은)?\s*(?:잘|좋|높)"
             r"|packs?\s+(?:well|better|densely)|(?:good|better|high(?:er)?|dens(?:e|er|est))\s+packing"
             r"|packing\s+(?:density|fraction)\s+(?:is\s+)?high|packing\s+(?:should\s+be|is|must\s+be)\s+(?:good|high|dense)")
SIZE_MAX = (r"top\s*-?\s*cut|탑\s*컷|최대\s*(?:입경|입자\s*(?:크기|사이즈)|크기|사이즈|입도)|가장\s*큰\s*입자(?:의)?\s*(?:크기|입경|사이즈)?"
            r"|max(?:imum)?\s+(?:particle\s+)?(?:size|diameter)|largest\s+(?:particles?|size)|\bd\s*max\b|\bd100\b"
            r"|upper\s+(?:size\s+)?(?:limit|bound)")
SIZE_MIN = (r"가장\s*작은\s*입자(?:의)?\s*(?:크기|입경|사이즈)?|최소\s*(?:입경|입자\s*(?:크기|사이즈)|크기|사이즈|입도)"
            r"|smallest\s+(?:particles?|size)|min(?:imum)?\s+(?:particle\s+)?(?:size|diameter)|\bd\s*min\b"
            r"|lower\s+(?:size\s+)?(?:limit|bound)|bottom\s*-?\s*cut")
CONTENT_MAX = (r"(?:최대|최고|상한|max(?:imum)?|upper\s+limit(?:\s+of)?|at\s+most|up\s+to|no\s+more\s+than)\s*(?:의\s*)?"
               r"(?:필러\s*)?(?:함량|충전량|충진량|loading|content|filler\s+(?:loading|content))?"
               r"|(?:함량|충전량|loading|content)\s*(?:은|는|의)?\s*(?:최대|상한|max(?:imum)?)")
CONTENT_MIN = r"(?:최소|하한|min(?:imum)?|lower\s+limit(?:\s+of)?)\s*(?:의\s*)?(?:필러\s*)?(?:함량|충전량|loading|content)"
MONO = (r"(?:distribution|분포|산포)\s*(?:은|는|을|를)?\s*(?:고려\s*(?:하지|안\s*하|않|x)|무시|없|빼)|단분산|단일\s*(?:크기|입경|사이즈)"
        r"|mono\s*-?\s*(?:disperse|dispersed|sized?|modal)|(?:no|without|ignore\s+the|ignoring\s+the|not\s+considering\s+the)\s+"
        r"(?:size\s+)?distribution|single\s+size|균일\s*(?:크기|입경)|분포\s*없이")
FIND_VERB = (r"알려|찾아|추천|정해|제안|구해|뭐|무엇|어떤|얼마|몇|골라|설계|find|recommend|suggest|what|which|determine|tell\s+me"
             r"|give\s+me|design|choose|pick|optimi")
FIND_SIZE = r"크기|사이즈|입경|입도|\bsizes?\b|diameters?"
FIND_RATIO = (r"배합\s*비(?:율)?|혼합\s*비(?:율)?|블렌딩|조합\s*비|비율|blend(?:ing)?(?:\s+ratio)?|mix(?:ing)?\s+ratio|ratio|proportion"
              r"|배합")
FIND_CONTENT = r"함량|충전량|loading|content|얼마나\s*넣|몇\s*(?:%|퍼|프로|vol|wt)|how\s+much"
TWO_SIZES = (r"두\s*가지\s*(?:크기|입경|사이즈|입자)|2\s*가지\s*(?:크기|입경|사이즈|입자)|bimodal|바이모달|two\s+sizes|대\s*/\s*소\s*입자"
             r"|큰\s*입자와\s*작은|coarse\s+and\s+fine|대입자|소입자|2\s*종\s*(?:블렌딩|혼합|배합)"
             r"|(?:두|2)\s*가지(?:를|의)?\s*(?:섞|혼합|배합|블렌)|blend\s+of\s+two|two\s+(?:grades|particle\s+sizes)")
COARSE = r"대\s*입자|대입경|조대\s*입자|굵은\s*입자|큰\s*입자|coarse(?:\s+particles?|\s+fraction)?|large(?:r)?\s+particles?"
FINE = r"소\s*입자|소입경|미세\s*입자|작은\s*입자|미립자|fine(?:\s+particles?|\s+fraction)?|small(?:er)?\s+particles?"
THREE_SIZES = (r"세\s*가지\s*(?:크기|입경|사이즈|입자)|3\s*가지\s*(?:크기|입경|사이즈|입자)|trimodal|three\s+sizes"
               r"|(?:세|3)\s*가지(?:를|의)?\s*(?:섞|혼합|배합|블렌)")
RINT_CUE = (r"필러\s*[-–/와과]\s*(?:레진|수지|매트릭스|기지)|(?:레진|수지|매트릭스)\s*[-–/와과]\s*필러"
            r"|filler\s*[-–/]\s*(?:resin|matrix|polymer)|(?:resin|matrix)\s*[-–/]\s*filler|계면\s*(?:열)?\s*저항"
            r"|interfac(?:e|ial)\s+(?:thermal\s+)?resistance|kapitza|\br_?int\b|\btbr\b|boundary\s+(?:thermal\s+)?resistance")
RC_CUE = (r"필러\s*[-–/와과]\s*필러|입자\s*(?:간|사이|끼리)?\s*(?:의\s*)?접촉|filler\s*[-–/]\s*filler|particle\s*[-–/]\s*particle"
          r"|접촉\s*(?:열)?\s*저항|contact\s+(?:thermal\s+)?resistance|\br_?c\b|\br_?contact\b")
TOL = r"(\d+(?:\.\d+)?)\s*(?:vol\s*)?%\s*p?\s*(?:이내|안쪽|차이\s*(?:까지|이내)|within)|within\s+(\d+(?:\.\d+)?)\s*(?:vol\s*)?%"
MEASURED = r"측정|실측|measur"

SHARE_SAME = (0.0, 50.0)        # the fine share of one material's two sizes, % of the filler
SHARE_TWO = (0.0, 100.0)        # the second material's share of two
CONTENT_SPAN = 22.0             # the content range below the maximum when no lower bound is said
TOL_DEFAULT = 1.0               # vol%: contents this close count as the same


def empty():
    return {"objective": None, "targets": [], "content_max": None, "content_min": None, "basis": None,
            "size_max_um": None, "size_min_um": None, "mono": False, "prefer": [], "find": [], "classes": None,
            "r_int": None, "r_contact": None, "tol": None, "class_sizes": None, "sizes_said": None, "said": {}}


def _sentences(low):
    """(start, end) of each sentence: a target's words stay in its own."""
    out, a = [], 0
    for m in re.finditer(r"[.!?\n;]+(?:\s|$)|다\.\s*", low):
        out.append((a, m.end()))
        a = m.end()
    out.append((a, len(low)))
    return out


def _sentence_of(spans, pos):
    return next(((a, b) for a, b in spans if a <= pos < b), (0, 10 ** 9))


def read(text, claimed=()):
    """The design parts of a request, read by the rules. `said` maps each
    part to the raw text it came from (for the summary and the checks).
    claimed: (property, value) a material was given ("알루미나 k 20"): not a target."""
    t = normalize(text or "")
    low = t.lower()
    d = empty()
    qs = quantities(t)
    sents = _sentences(low)
    said = d["said"]
    claimed = {(p, round(v, 9)) for p, v in claimed}
    loose = []

    # ---- targets: a property value with a word that makes it a goal
    for q in qs:
        prop = UNIT_PROP.get(q.get("unit"))
        a, b = _sentence_of(sents, q["start"])
        before = low[max(a, q["start"] - 28):q["start"]]
        pw = None
        for p, rx in PROP_WORDS.items():
            ms = list(re.finditer(rx, before))
            if ms:
                if pw is None or ms[-1].end() > pw[1]:
                    pw = (p, ms[-1].end(), ms[-1].start())
        if prop is None and pw and pw[0] == "eps_r" and q.get("unit") is None and q["value"] < 100:
            prop = "eps_r"
        # "열전도 3 넘기려면": a bare number right after a property word, in that property's unit
        if prop is None and pw and q.get("unit") is None and pw[1] - len(before) >= -6 \
                and not re.match(r"\s*(?:배|times|x\b|%|퍼|프로|방향|축|direction|단계|level|가지|개|번)", low[q["end"]:q["end"] + 9]):
            prop = pw[0]
            said.setdefault("unit_assumed", []).append(q["raw"])
        if prop is None or (pw and pw[0] != prop and prop != "k"):
            continue
        after = low[q["end"]:min(b, q["end"] + 16)]
        near = (before[pw[1] - len(before):] if pw and pw[1] - len(before) < 0 else "") + " " + after
        val = q["value"] * (100.0 if q.get("unit") == "S/cm" else 1.0)
        if (prop, round(val, 9)) in claimed:
            continue
        if not re.search(TARGET_CUE, near):
            loose.append((q, prop, val, near, a, b))
            continue
        op = ">=" if re.search(OP_GE, near) else "<=" if re.search(OP_LE, near) else "=" if re.search(OP_EQ, near) \
            else DEFAULT_OP.get(prop, ">=")
        dirs = low[max(a, q["start"] - 30):q["start"]]
        direction = "z" if re.search(DIR_Z, dirs) else "xy" if re.search(DIR_XY, dirs) else None
        if direction is None and re.search(DIR_Z, low[a:b]):
            direction = "z"
        d["targets"].append({"property": prop, "value": float(val), "op": op, "direction": direction,
                             "raw": q["raw"], "start": q["start"]})
    # a sentence about measured values is a calibration, not a goal
    if d["targets"] and re.search(MEASURED, low) and not re.search(MIN_CONTENT, low):
        d["targets"] = []

    # ---- what is minimised, preferred and found
    if re.search(MIN_CONTENT, low):
        d["objective"] = "content"
    elif re.search(MIN_VISC, low):
        d["objective"] = "viscosity"
    # "which sizes give a k of 3 W/mK with the least filler": in a request to minimise or find, a property
    # value no material was given is the target
    if not d["targets"] and loose and (d["objective"] or re.search(FIND_VERB, low)) and not re.search(MEASURED, low):
        q, prop, val, near, a, b = loose[0]
        dirs = low[max(a, q["start"] - 30):q["start"]]
        op = ">=" if re.search(OP_GE, near) else "<=" if re.search(OP_LE, near) else "=" if re.search(OP_EQ, near) \
            else DEFAULT_OP.get(prop, ">=")
        d["targets"].append({"property": prop, "value": float(val), "op": op,
                             "direction": "z" if re.search(DIR_Z, dirs) else "xy" if re.search(DIR_XY, dirs) else None,
                             "raw": q["raw"], "start": q["start"]})
    if re.search(LOW_VISC, low):
        d["prefer"].append("low_viscosity")
    if re.search(HIGH_PACK, low):
        d["prefer"].append("high_packing")
    for a, b in sents:
        s = low[a:b]
        m = re.search(FIND_VERB, s)
        if not m:
            continue
        head = s            # what is asked for: before the verb in Korean, after it in English ("which sizes")
        if re.search(FIND_SIZE, head) and not re.search(r"(?:크기|사이즈|입경|size)\s*(?:는|은)?\s*\d", head):
            d["find"].append("size")
        if re.search(FIND_RATIO, head):
            d["find"].append("ratio")
        if re.search(FIND_CONTENT, head):
            d["find"].append("content")
    if d["objective"] == "content" and "content" not in d["find"]:
        d["find"].append("content")
    d["find"] = list(dict.fromkeys(d["find"]))
    if re.search(THREE_SIZES, low):
        d["classes"] = 3
    elif re.search(TWO_SIZES, low):
        d["classes"] = 2
    if re.search(MONO, low):
        d["mono"] = True

    # ---- bounds of size and content
    film = [q for q in qs if q.get("unit") in ("um", "nm", "mm") and re.match(
        r"\s*-?\s*(?:두께|thick)", t[q["end"]:], re.IGNORECASE)]
    lengths = [q for q in qs if q.get("unit") in ("um", "nm", "mm") and q not in film]
    for key, rx in (("size_max_um", SIZE_MAX), ("size_min_um", SIZE_MIN)):
        for m in re.finditer(rx, low):
            a, b = _sentence_of(sents, m.start())
            nxt = [q for q in lengths if m.end() <= q["start"] <= min(b, m.end() + 30)]
            prv = [q for q in lengths if max(a, m.start() - 14) <= q["end"] <= m.start()]
            q = nxt[0] if nxt else (prv[-1] if prv else None)
            if q is not None and d[key] is None:
                d[key] = to_um(q["value"], q["unit"])
                said[key] = q["raw"]
    # the bounds of each class of a blend ("대입자 20~70um과 소입자 0.5~5um", "대입자 topcut 80um, 소입자 최소 1um",
    # "coarse 20-70 um and fine 0.5-5 um"); "가장 작은 입자" is the smallest of all, not a class
    cls = {}
    for tag, rx in (("coarse", COARSE), ("fine", FINE)):
        for m in re.finditer(rx, low):
            if re.search(r"가장\s*$", low[max(0, m.start() - 4):m.start()]):
                continue
            a, b = _sentence_of(sents, m.start())
            stop = re.search(COARSE if tag == "fine" else FINE, low[m.end():b])
            end = min(b, m.end() + 30, m.end() + stop.start() if stop else b)
            nxt = [q for q in lengths if m.end() <= q["start"] < end]
            if not nxt or tag in cls:
                continue
            q = nxt[0]
            lo_, hi_ = to_um(q["value"], q["unit"]), to_um(q["hi"], q["unit"]) if "hi" in q else None
            between = low[m.end():q["start"]]
            if hi_ is not None:
                cls[tag] = [min(lo_, hi_), max(lo_, hi_)]
            elif re.search(SIZE_MAX + r"|최대|이하|까지|\bmax|up\s+to|at\s+most", between) or re.match(r"\s*(?:이하|까지|max)", low[q["end"]:q["end"] + 6]):
                cls[tag] = [None, lo_]
            elif re.search(SIZE_MIN + r"|최소|이상|\bmin|at\s+least", between) or re.match(r"\s*(?:이상|min)", low[q["end"]:q["end"] + 6]):
                cls[tag] = [lo_, None]
            else:
                cls[tag] = [lo_, lo_]
            said["class_" + tag] = q["raw"]
    if cls:
        d["class_sizes"] = cls
        d["classes"] = max(d.get("classes") or 0, 2)
    for q in lengths:
        after = low[q["end"]:q["end"] + 10]
        if "hi" in q and d["size_min_um"] is None and d["size_max_um"] is None and re.search(FIND_VERB, low):
            lo_, hi_ = to_um(q["value"], q["unit"]), to_um(q["hi"], q["unit"])
            d["size_min_um"], d["size_max_um"] = min(lo_, hi_), max(lo_, hi_)
            said["size_min_um"] = said["size_max_um"] = q["raw"]
        elif d["size_max_um"] is None and re.match(r"\s*(?:이하|까지|미만|or\s+less|or\s+smaller|max)", after):
            d["size_max_um"], said["size_max_um"] = to_um(q["value"], q["unit"]), q["raw"]
        elif d["size_min_um"] is None and re.match(r"\s*(?:이상|or\s+more|or\s+larger|min)", after):
            d["size_min_um"], said["size_min_um"] = to_um(q["value"], q["unit"]), q["raw"]
    # the sizes of a blend said one by one ("알루미나 70um, 5um, 0.5um 세 가지 크기 섞어서"): one class each
    if d["classes"] and not cls:
        bound_raw = {said.get("size_max_um"), said.get("size_min_um")}
        singles = sorted({round(to_um(q["value"], q["unit"]), 9) for q in lengths
                          if "hi" not in q and not q.get("levels") and q["raw"] not in bound_raw}, reverse=True)
        if len(singles) >= 2:
            d["sizes_said"] = singles[:3]
            d["classes"] = max(d["classes"], min(len(singles), 3))
            # the sizes are given: "세 가지 크기를 섞어서 ... 찾아줘" finds the content and the shares, not sizes
            d["find"] = [x for x in d["find"] if x != "size"]
    if cls:
        # the bounds of all sizes: those of the classes, with a topcut or smallest size said apart from them
        craw = {said.get("class_coarse"), said.get("class_fine")}
        vals = [v for p in cls.values() for v in p if v is not None]
        lo0 = d["size_min_um"] if d["size_min_um"] is not None and said.get("size_min_um") not in craw else None
        hi0 = d["size_max_um"] if d["size_max_um"] is not None and said.get("size_max_um") not in craw else None
        d["size_min_um"] = min(vals + ([lo0] if lo0 is not None else []))
        d["size_max_um"] = max(vals + ([hi0] if hi0 is not None else []))
        if "size" not in d["find"] and not all(p[0] is not None and p[0] == p[1] for p in cls.values()):
            d["find"].append("size")
    pct = [q for q in qs if q.get("unit") in ("vol", "wt", "pct")]
    for key, rx in (("content_max", CONTENT_MAX), ("content_min", CONTENT_MIN)):
        other = r"최소|최저|하한|\bmin|at\s+least|,|;" if key == "content_max" else r"최대|최고|상한|\bmax|at\s+most|up\s+to|,|;"
        for m in re.finditer(rx, low):
            a, b = _sentence_of(sents, m.start())
            # "최소 함량, 최대 60vol%": the number after another bound word is that bound's
            nxt = [q for q in pct if m.end() <= q["start"] <= min(b, m.end() + 22) and not re.search(other, low[m.end():q["start"]])]
            if nxt and d[key] is None:
                q = nxt[0]
                d[key] = q.get("hi") if key == "content_max" and "hi" in q else q["value"]
                said[key] = q["raw"]
                d["basis"] = d["basis"] or {"vol": "vol", "wt": "wt"}.get(q["unit"])
    for q in pct:
        after = low[q["end"]:q["end"] + 12]
        if d["content_max"] is None and re.match(r"\s*(?:이하|까지|미만|를?\s*넘지|or\s+less|max|at\s+most)", after):
            d["content_max"], said["content_max"] = q["value"], q["raw"]
            d["basis"] = d["basis"] or {"vol": "vol", "wt": "wt"}.get(q["unit"])
        if "hi" in q and d["content_max"] is None and (d["objective"] or d["targets"]):
            d["content_min"], d["content_max"] = min(q["value"], q["hi"]), max(q["value"], q["hi"])
            said["content_min"] = said["content_max"] = q["raw"]
            d["basis"] = d["basis"] or {"vol": "vol", "wt": "wt"}.get(q["unit"])
    # a range of the total content said ("총 함량 60~70vol%"): the study varies it
    if d["content_min"] is not None and d["content_max"] is not None and d["content_max"] > d["content_min"] \
            and "content" not in d["find"]:
        d["find"].append("content")
    m = re.search(TOL, low)
    if m and (d["objective"] or d["targets"]):
        d["tol"] = float(m.group(1) or m.group(2))
        said["tol"] = m.group(0)

    # ---- interface resistances: the cue words before a number of that size
    for q in qs:
        if not (0.0 < q["value"] < 1e-3 or q.get("unit") == "m2K/W"):
            continue
        a, b = _sentence_of(sents, q["start"])
        win = low[max(a, q["start"] - 60):q["start"]]
        hit = []
        for key, rx in (("r_int", RINT_CUE), ("r_contact", RC_CUE)):
            ms = list(re.finditer(rx, win))
            if ms:
                hit.append((ms[-1].end(), key))
        # "필러-레진, 필러-필러간 열저항은 1E-8": both before one number
        for _, key in sorted(hit, reverse=True):
            if d[key] is None:
                d[key], said[key] = q["value"], q["raw"]
        if not hit and re.search(r"열\s*저항|thermal\s+resistance|계면", win) and d["r_int"] is None:
            d["r_int"], said["r_int"] = q["value"], q["raw"]
    return d


def active(d):
    """A design request: a target to reach, or a content to minimise, with
    something to find."""
    return bool(d) and bool(d.get("targets")) and bool(d.get("objective") or d.get("find"))


def wanted(d):
    """A design asked for without its target ("최소 함량으로 설계해줘"): the target is asked."""
    return bool(d) and not d.get("targets") and d.get("objective") == "content"


# ---------------------------------------------------------------------- the model's reading
def from_model(md, nums, derivable):
    """The design part of the model's JSON, each number checked like every
    other one (derivable from the sentence)."""
    d = empty()
    if not isinstance(md, dict):
        return d
    if md.get("minimize") in ("content", "viscosity"):
        d["objective"] = md["minimize"]
    p = md.get("target_property")
    v = md.get("target_value")
    if p in PROP_ANALYSIS and isinstance(v, (int, float)) and not isinstance(v, bool) and derivable(v, nums, "prop"):
        op = md.get("target_op") if md.get("target_op") in (">=", "<=", "=") else DEFAULT_OP.get(p, ">=")
        d["targets"].append({"property": p, "value": float(v), "op": op,
                             "direction": md.get("direction") if md.get("direction") in ("z", "xy") else None,
                             "raw": f"{v:g}"})
    for key, kind in (("content_max", "pct"), ("content_min", "pct"), ("size_max_um", "len"), ("size_min_um", "len")):
        x = md.get(key)
        if isinstance(x, (int, float)) and not isinstance(x, bool) and derivable(x, nums, kind) in ("said", "unit"):
            d[key] = float(x)
    for k in ("find", "prefer"):
        allowed = ("content", "size", "ratio") if k == "find" else ("low_viscosity", "high_packing")
        d[k] = [x for x in (md.get(k) or []) if x in allowed] if isinstance(md.get(k), list) else []
    if md.get("single_size") is True:
        d["mono"] = True
    return d


def combine(rule_d, model_d):
    """The rules' explicit reading stands; the model fills what they left open."""
    out = empty()
    rule_d = rule_d or empty()
    model_d = model_d or empty()
    for k in out:
        if k == "said":
            out[k] = dict(rule_d.get("said") or {})
        elif k in ("targets",):
            out[k] = list(rule_d.get(k) or []) or list(model_d.get(k) or [])
        elif k in ("find", "prefer"):
            out[k] = list(dict.fromkeys(list(rule_d.get(k) or []) + list(model_d.get(k) or [])))
        elif k == "mono":
            out[k] = bool(rule_d.get(k) or model_d.get(k))
        else:
            out[k] = rule_d.get(k) if rule_d.get(k) is not None else model_d.get(k)
    # a content to minimise is a content to find
    if out["objective"] == "content" and "content" not in out["find"]:
        out["find"].append("content")
    return out


def design_numbers(d):
    """The numbers the design uses (bounds and targets): a filler's own
    content or size equal to one of them was read from the wrong place."""
    pct = [x for x in (d.get("content_max"), d.get("content_min")) if x is not None]
    pct += [100.0 - x for x in pct]
    size = [x for x in (d.get("size_max_um"), d.get("size_min_um")) if x is not None]
    prop = {}
    for tg in d.get("targets") or []:
        prop.setdefault(tg["property"], []).append(tg["value"])
    return pct, size, prop


# ---------------------------------------------------------------------- the study
def _nice(x):
    """A round number near x for a size split (0.775 -> 0.8)."""
    if x <= 0:
        return x
    e = 10 ** math.floor(math.log10(x))
    for m in (1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0):
        if m * e >= x * 0.92:
            return round(m * e, 6)
    return x


def plan_factors(d, classes, sizes_fixed, content_fixed):
    """The DOE parameters of a design: (parameters, centre values, notes).

    classes: [{"name", "same": bool}] - one or two phases (two sizes of one
    material, or two materials); sizes_fixed: per phase, a size said or
    None; content_fixed: the total content said (when it is not found)."""
    params, centre, notes = [], {}, []
    two = len(classes) == 2
    # total content
    if "content" in d["find"] or content_fixed is None:
        hi = d.get("content_max") or 60.0
        lo = d.get("content_min")
        if lo is None:
            lo = max(5.0, hi - CONTENT_SPAN)
        p = {"path": "phases.0.fraction.value", "label": "Total filler content", "unit": "%", "min": round(lo, 4),
             "max": round(hi, 4), "steps": 9, "scale": "lin", "role": "content"}
        if len(classes) >= 2:
            p["links"] = [{"path": f"phases.{i}.fraction.value", "expr": "0"} for i in range(1, len(classes))]
        params.append(p)
        centre["content"] = 0.5 * (lo + hi)
    else:
        centre["content"] = content_fixed
    if len(classes) == 3:
        # three sizes of one material said: the medium share of the filler, then the fine share (mix.1, mix.2: the
        # second keeps the first two in their proportion, so the pair covers every blend)
        params.append({"path": "mix.1", "label": "Medium share of the filler", "unit": "% of filler", "min": 0.0,
                       "max": 50.0, "steps": 6, "scale": "lin", "role": "share"})
        params.append({"path": "mix.2", "label": "Fine share of the filler", "unit": "% of filler", "min": 0.0,
                       "max": 50.0, "steps": 6, "scale": "lin", "role": "share2"})
        centre["share"], centre["share2"] = 25.0, 15.0
        for i, v in enumerate(sizes_fixed or []):
            centre[f"size{i}"] = v
        return params, centre, notes
    # the share of the second phase
    if two:
        lo_s, hi_s = SHARE_SAME if classes[1].get("same") else SHARE_TWO
        if "ratio" in d["find"] or classes[1].get("same"):
            params.append({"path": "mix.1", "label": ("Fine share of the filler" if classes[1].get("same")
                                                      else f"{classes[1]['name']}: share of the filler"),
                           "unit": "% of filler", "min": lo_s, "max": hi_s, "steps": 6, "scale": "lin", "role": "share"})
            centre["share"] = 0.5 * (lo_s + hi_s) if not classes[1].get("same") else 25.0
        else:
            centre["share"] = 50.0
    # sizes: a size said stays; the others are found within the bounds
    smin, smax = d.get("size_min_um"), d.get("size_max_um")
    fixed = {i: v for i, v in enumerate(sizes_fixed or []) if v}
    for i, v in fixed.items():
        centre[f"size{i}"] = v
    if len(fixed) < len(classes) and ("size" in d["find"] or (two and classes[1].get("same"))):
        if smin is None or smax is None:
            return None, None, ["size range"]
        if two and classes[1].get("same") and not fixed:
            split = _nice(math.sqrt(smin * smax))
            split = min(max(split, smin * 1.25), smax / 1.25)
            # each class within its own bounds when they were said ("대입자 20~70um, 소입자 0.5~5um")
            cs = d.get("class_sizes") or {}
            c_lo, c_hi = (cs.get("coarse") or [None, None])
            f_lo, f_hi = (cs.get("fine") or [None, None])
            rng = [("coarse", 0, c_lo if c_lo is not None else max(split, f_hi or 0.0), c_hi if c_hi is not None else smax),
                   ("fine", 1, f_lo if f_lo is not None else smin, f_hi if f_hi is not None else min(split, c_lo or 1e9))]
            for tag, i, a, b in rng:
                if a is not None and b is not None and abs(a - b) <= 1e-12:
                    fixed[i] = centre[f"size{i}"] = a                  # a class said with one size keeps it
        elif two and classes[1].get("same"):
            # one of the two sizes said: the other one is on its own side of it
            k = next(iter(fixed))
            v = fixed[k]
            rng = [("coarse", 0, max(v, smin), smax)] if k == 1 else [("fine", 1, smin, min(v, smax))]
        elif two:
            rng = [("a", 0, smin, smax), ("b", 1, smin, smax)]
        else:
            rng = [("one", 0, smin, smax)]
        for tag, i, a, b in rng:
            if i in fixed or b <= a:
                continue
            params.append({"path": f"phases.{i}.size.d",
                           "label": {"coarse": "Coarse size", "fine": "Fine size"}.get(tag, f"{classes[i]['name']}: diameter"),
                           "unit": "µm", "min": round(a, 6), "max": round(b, 6), "steps": 5,
                           "scale": "log" if b / max(a, 1e-9) >= 3.0 else "lin", "role": f"size{i}"})
            centre[f"size{i}"] = math.sqrt(a * b) if b / max(a, 1e-9) >= 3.0 else 0.5 * (a + b)
    return params, centre, notes


def class_fractions(n, s1, s2=0.0):
    """Each class's part of the filler from the shares the study sets: mix.1 = s1, then mix.2 = s2 with the
    first two kept in their proportion (MPSim's doe.set_filler_share, in that order)."""
    if n == 3:
        return [(1.0 - s1) * (1.0 - s2), s1 * (1.0 - s2), s2]
    if n == 2:
        return [1.0 - s1, s1]
    return [1.0]


def doe_design(params):
    """Full factorial for one or two factors, a Latin hypercube above."""
    n = len(params)
    if n == 1:
        params[0]["steps"] = 9
        return "full", 9
    if n == 2:
        for p in params:
            p["steps"] = 6
        return "full", 36
    return "lhs", min(64, max(24, 10 * n))


# ---------------------------------------------------------------------- choosing the recipe
# a recipe meets the target with its prediction one standard deviation on the safe side; a surrogate whose
# cross-validated R² is below WEAK_R2 does not choose the recipe - the lowest-content run that met the target does
MARGIN_SD = 1.0
WEAK_R2 = 0.7
# vol%: a run whose structure holds this much less filler than it was set to has met the packing's limit
SHORT_VOL = 0.5


def _meets_sure(mean, std, tg):
    import numpy as np
    mean, std = np.asarray(mean, float), np.asarray(std, float)
    if tg["op"] == ">=":
        return _meets(mean - MARGIN_SD * std, tg)
    if tg["op"] == "<=":
        return _meets(mean + MARGIN_SD * std, tg)
    return _meets(mean, tg, MARGIN_SD * std)


def _meets(y, tg, tol=0.0):
    import numpy as np
    y = np.asarray(y, float)
    if tg["op"] == ">=":
        return y >= tg["value"] - tol
    if tg["op"] == "<=":
        return y <= tg["value"] + tol
    return np.abs(y - tg["value"]) <= np.maximum(tol, 0.02 * abs(tg["value"]))


def recommend(study, rows, spec, seed=0, n_combo=1500, ctx_out=None):
    """The recipe for a finished design study (see the module docstring).
    spec: the payload's "design" part. Returns a dict for the AI tab."""
    import numpy as np

    from mpsim import doe as DOE
    from mpsim import optimise as OPT
    from mpsim.solvers import viscosity as VI

    params = [p for p in study.get("parameters") or [] if p.get("path")]
    paths = [p["path"] for p in params]
    roles = spec.get("roles") or {}
    # every target the design must meet ("유전율 3.0 이하이면서 CTE 30 이하"): one surrogate each; the recipe
    # meets them all, and the one that sets its content is the binding target the loop judges
    tgs = [dict(t, response=t.get("response") or PROP_RESPONSE.get(t["property"], t["property"]))
           for t in (spec.get("targets") or [spec["target"]])]
    ci = next((i for i, p in enumerate(paths) if roles.get(p) == "content"), None)
    si = next((i for i, p in enumerate(paths) if roles.get(p) == "share"), None)
    zi = {roles[p]: i for i, p in enumerate(paths) if str(roles.get(p, "")).startswith("size")}
    out = {"ok": True, "target": tgs[0], "targets": tgs, "objective": spec.get("objective") or "content", "notes": [],
           "prefer": spec.get("prefer") or [], "tol": spec.get("tol") or TOL_DEFAULT}

    # the finished runs (those with every target's response): the realised content where the run says it
    X, Y, used, short, held = [], [], [], [], []
    for r in rows:
        if r.get("state") != "done":
            continue
        met_ = r.get("metrics") or {}
        vs = [met_.get(t["response"]) for t in tgs]
        xs = [(r.get("values") or {}).get(p) for p in paths]
        if any(v is None for v in vs) or any(x is None for x in xs) or not all(np.isfinite(float(v)) for v in vs):
            continue
        xs = [float(x) for x in xs]
        real = met_.get("real_filler")
        if ci is not None and real is not None and np.isfinite(float(real)):
            short.append(xs[ci] - float(real))
            held.append((xs[ci], float(real)))
            xs[ci] = float(real)
        X.append(xs)
        Y.append([float(v) for v in vs])
        used.append(r)
    out["n_runs"] = len(Y)
    out["n_cases"] = len(rows)
    if len(Y) < 5:
        out.update(ok=False, error=f"{len(Y)} finished runs; at least 5 are needed for the surrogate")
        return out
    X, Y = np.asarray(X), np.asarray(Y)
    bounds = OPT._bounds(params)
    if ci is not None:
        bounds[ci] = (min(bounds[ci][0], float(X[:, ci].min())), max(bounds[ci][1], float(X[:, ci].max())))
    # a response over decades (electrical conductivity across percolation) is fitted as its logarithm
    fits = []
    for k, t in enumerate(tgs):
        yk = Y[:, k]
        lg = t["property"] == "sigma" and bool((yk > 0).all())
        yt = np.log10(yk) if lg else yk
        if lg and t["value"] > 0:
            # the decades below percolation are a step no smooth fit follows: held at 4 decades about the target
            yt = np.clip(yt, math.log10(t["value"]) - 4.0, math.log10(t["value"]) + 4.0)
        m_ = OPT.fit_surrogate(X, yt, bounds, seed)
        cv_ = OPT.cross_validate(X, yt, bounds, seed)
        fits.append({"tg": t, "tgt": dict(t, value=math.log10(t["value"]) if lg and t["value"] > 0 else t["value"]),
                     "model": m_, "cv": cv_, "log": lg, "y": yt})
    model, cv = fits[0]["model"], fits[0]["cv"]
    out["surrogate"] = {"kind": model["kind"], "r2": (cv or {}).get("r2"), "rmse": (cv or {}).get("rmse"),
                        "log": fits[0]["log"]}
    if len(fits) > 1:
        out["surrogates"] = [{"property": f["tg"]["property"], "r2": (f["cv"] or {}).get("r2"),
                              "rmse": (f["cv"] or {}).get("rmse"), "log": f["log"]} for f in fits]

    def back(f, mu, sd_):
        """a prediction in the response's own unit, its standard deviation as the upper side"""
        if not f["log"]:
            return mu, sd_
        return 10.0 ** mu, 10.0 ** (mu + sd_) - 10.0 ** mu

    # candidates: combinations of the other inputs, each with the lowest content that meets the target
    rng = np.random.default_rng(seed)
    others = [i for i in range(len(paths)) if i != ci]
    M = n_combo if others else 1
    combos = np.zeros((M, len(paths)))
    for i in others:
        lo, hi = bounds[i]
        u = (rng.permutation(M) + rng.random(M)) / M
        if params[i].get("scale") == "log" and lo > 0:
            combos[:, i] = np.exp(np.log(lo) + u * (np.log(hi) - np.log(lo)))
        else:
            combos[:, i] = lo + u * (hi - lo)
    # the runs' own combinations are candidates too
    if others:
        combos = np.vstack([combos, X.copy()])
    # the fine phase is the smaller one: a coarse size below the fine one is the same blend, named the other way
    if "size0" in zi and "size1" in zi and spec.get("same_material"):
        bad = combos[:, zi["size0"]] < combos[:, zi["size1"]]
        combos = combos[~bad]
    if ci is not None:
        # a content limit set during the study ("최대 함량은 55%로") narrows the search, not the runs already made
        cap = float(spec["content_cap"]) if spec.get("content_cap") is not None else bounds[ci][1]
        grid = np.arange(bounds[ci][0], min(bounds[ci][1], cap) + 1e-9, 0.25)
        n, g = len(combos), len(grid)
        Q = np.repeat(combos, g, axis=0)
        Q[:, ci] = np.tile(grid, n)
        means, stds, oks = [], [], []
        for f in fits:
            mu_, sd_ = f["model"]["predict"](Q, std=True)
            mu_, sd_ = np.asarray(mu_).reshape(n, g), np.asarray(sd_).reshape(n, g)
            means.append(mu_)
            stds.append(sd_)
            oks.append(_meets_sure(mu_, sd_, f["tgt"]))
        ok = np.logical_and.reduce(oks)
        first = np.where(ok.any(axis=1), ok.argmax(axis=1), -1)
        feas = first >= 0
        phi_min = np.where(feas, grid[np.maximum(first, 0)], np.inf)
        # the binding target of each combination: the one whose own lowest content is the highest
        own = np.vstack([np.where(o.any(axis=1), o.argmax(axis=1), g) for o in oks])
        bind = np.argmax(own, axis=0)
        sel = np.maximum(first, 0)
        pred = np.array([means[bind[i]][i, sel[i]] for i in range(n)])
        sd = np.array([stds[bind[i]][i, sel[i]] for i in range(n)])
        combos = combos.copy()
        combos[:, ci] = np.where(feas, phi_min, grid[-1])
        # where nothing meets the targets: the best each combination reaches at the highest content, for the
        # target met least often
        hard = int(np.argmin([o.any(axis=1).sum() for o in oks]))
        best_at_max = means[hard][:, -1]
        sd_at_max = stds[hard][:, -1]
    else:
        means, stds, oks = [], [], []
        for f in fits:
            mu_, sd_ = f["model"]["predict"](combos, std=True)
            means.append(np.asarray(mu_))
            stds.append(np.asarray(sd_))
            oks.append(_meets_sure(means[-1], stds[-1], f["tgt"]))
        feas = np.logical_and.reduce(oks)
        bind = np.zeros(len(combos), int)
        hard = int(np.argmin([o.sum() for o in oks]))
        pred, sd = means[0], stds[0]
        phi_min = np.full(len(combos), np.nan)
        best_at_max, sd_at_max = means[hard], stds[hard]

    def content_of(x):
        return float(x[ci]) if ci is not None else float(spec.get("content_fixed") or 0.0)

    s2i = next((i for i, p in enumerate(paths) if roles.get(p) == "share2"), None)

    def share_of(x):
        return float(x[si]) / 100.0 if si is not None else float(spec.get("share_fixed", 0.0)) / 100.0

    def parts_of(x):
        """each class's part of the filler"""
        return class_fractions(len(spec.get("phases") or [1]), share_of(x), float(x[s2i]) / 100.0 if s2i is not None else 0.0)

    def sizes_of(x):
        out_ = []
        for k, f in enumerate(spec.get("phases") or []):
            out_.append(float(x[zi[f"size{k}"]]) if f"size{k}" in zi else float(f.get("d") or 0.0))
        return out_

    def packing(x):
        """phi_m (Farr-Groot) of the blend; None for particles that are not spheres."""
        if not spec.get("spheres"):
            return None
        ds = sizes_of(x)
        vf = parts_of(x)
        dd = np.array([a for a, v in zip(ds, vf) if v > 1e-9 and a > 0])
        ww = np.array([v / a ** 3 for a, v in zip(ds, vf) if v > 1e-9 and a > 0])
        if not len(dd):
            return None
        return float(VI.rcp_farr_groot(dd, ww, n_rods=4000))

    def viscosity(x, pm):
        if pm is None:
            return None
        phi = content_of(x) / 100.0
        if (spec.get("basis") or "vol") != "vol":
            return None
        if phi >= pm:
            return math.inf
        return float(VI.krieger_dougherty(phi, pm, 2.5))

    def describe(i, x, p_, s_, pm=None, mu=None, b=0):
        ds = sizes_of(x)
        p_, s_ = back(fits[b], float(p_), float(s_))
        rec = {"content": round(content_of(x), 2), "sizes_um": [round(v, 3) for v in ds],
               "share": round(100.0 * share_of(x), 1) if len(ds) == 2 else None,
               "shares": [round(100.0 * v, 1) for v in parts_of(x)] if len(ds) == 3 else None,
               "predicted": float(f"{p_:.5g}"), "std": float(f"{s_:.4g}"),
               "phi_m": None if pm is None else round(pm, 4), "mu_r": None if mu is None or not math.isfinite(mu) else round(mu, 3),
               "values": {paths[j]: float(x[j]) for j in range(len(paths))}}
        if len(fits) > 1:
            # every target's prediction at the recipe, and the one that sets its content
            rec["bind"] = fits[b]["tg"]["property"]
            rec["predicted_all"] = []
            for f in fits:
                m_, s2 = f["model"]["predict"](np.atleast_2d(np.asarray(x, float)), std=True)
                pv, sv = back(f, float(np.asarray(m_).ravel()[0]), float(np.asarray(s2).ravel()[0]))
                rec["predicted_all"].append({"property": f["tg"]["property"], "op": f["tg"]["op"], "target": f["tg"]["value"],
                                             "predicted": float(f"{pv:.5g}"), "std": float(f"{sv:.4g}")})
        if ci is not None:
            rec["values"][paths[ci]] = round(content_of(x), 2)
        return rec

    obj = out["objective"]
    if not feas.any():
        j = int(np.argmax(best_at_max) if fits[hard]["tg"]["op"] != "<=" else np.argmin(best_at_max))
        x = combos[j].copy()
        if ci is not None:
            x[ci] = bounds[ci][1]
        out["reached"] = False
        out["best"] = describe(j, x, best_at_max[j], sd_at_max[j], packing(x), b=hard)
        out["notes"].append("not_reached")
        # runs set high that the structure could not hold (the packing stopped short, no overlap allowed): a
        # higher content does not put more of such particles in - the user's 10 µm film of alumina, set to
        # 59.6-61.8 vol%, held 59.1-59.9 vol%
        lost = [(s_, r_) for s_, r_ in held if s_ - r_ > SHORT_VOL]
        if lost:
            out["held"] = {"n": len(lost), "set_min": round(min(s_ for s_, _ in lost), 1),
                           "set_max": round(max(s_ for s_, _ in lost), 1),
                           "held_min": round(min(r_ for _, r_ in lost), 1), "held_max": round(max(r_ for _, r_ in lost), 1)}
            # read before the suggestion it changes
            out["notes"].insert(out["notes"].index("not_reached"), "packing_limit")
    else:
        out["reached"] = True
        idx = np.where(feas)[0]
        tol = out["tol"]
        phi_star = float(phi_min[idx].min()) if ci is not None else None
        if ci is not None and obj == "content":
            near = idx[phi_min[idx] <= phi_star + tol + 1e-9]
            near = near[np.argsort(phi_min[near])][:300]
        elif ci is not None:
            near = idx[np.argsort(phi_min[idx])][:300]
        else:
            near = idx[:300]
        pms = {int(j): packing(combos[j]) for j in near}
        mus = {int(j): viscosity(combos[j], pms[int(j)]) for j in near}
        want_flow = obj == "viscosity" or bool(set(out["prefer"]) & {"low_viscosity", "high_packing"})

        def key(j):
            mu = mus[int(j)]
            if want_flow and mu is not None:
                return (mu, phi_min[j] if ci is not None else 0.0)
            return (phi_min[j] if ci is not None else 0.0, -(pred[j] - fits[bind[j]]["tgt"]["value"]))
        order = sorted(near, key=key)
        best = order[0]
        out["recommended"] = describe(best, combos[best], pred[best], sd[best], pms[int(best)], mus[int(best)], b=int(bind[best]))
        # other recipes of the same content, distinct from it and from each other
        alts, seen = [], set()
        for j in order:
            r_ = describe(j, combos[j], pred[j], sd[j], pms[int(j)], mus[int(j)], b=int(bind[j]))
            # another recipe: a size a third apart or a share ten points apart
            sig = (round(r_["content"]), tuple(round(math.log(max(v, 1e-6)) / 0.3) for v in r_["sizes_um"]),
                   round((r_["share"] or 0) / 10.0), tuple(round(v / 10.0) for v in (r_["shares"] or [])))
            if sig in seen:
                continue
            seen.add(sig)
            alts.append(r_)
            if len(alts) >= 5:
                break
        out["alternatives"] = alts[1:]
        if ci is not None:
            low_j = int(near[np.argmin(phi_min[near])])
            out["lowest"] = describe(low_j, combos[low_j], pred[low_j], sd[low_j], pms[low_j], mus[low_j], b=int(bind[low_j]))
            if abs(phi_star - bounds[ci][0]) < 0.3:
                out["notes"].append("at_lower_bound")
        r = out["recommended"]
        tb = fits[int(bind[best])]["tg"]
        if (tb["op"] == ">=" and r["predicted"] - r["std"] < tb["value"]) or \
                (tb["op"] == "<=" and r["predicted"] + r["std"] > tb["value"]):
            out["notes"].append("within_uncertainty")
    # the runs themselves that met every target, lowest content first
    met = []
    for xs, vs, r in zip(X, Y, used):
        if all(bool(_meets([v], t)[0]) for v, t in zip(vs, tgs)):
            met.append({"label": r.get("label"), "job_id": r.get("job_id"), "value": float(vs[0]),
                        "values_all": {t["response"]: float(v) for v, t in zip(vs, tgs)},
                        "content": float(xs[ci]) if ci is not None else None,
                        "values": {paths[j]: float(xs[j]) for j in range(len(paths))}})
    met.sort(key=lambda m: (m["content"] if m["content"] is not None else 0.0))
    out["runs_met"] = met[:3]
    out["runs_best"] = {"value": float(Y[:, 0].max() if tgs[0]["op"] != "<=" else Y[:, 0].min())}
    # the surrogate the loop judges: the binding target's at the recipe
    bi = int(bind[best]) if out.get("reached") and out.get("recommended") else hard
    if ctx_out is not None:
        f = fits[bi]
        ctx_out.update(model=f["model"], bounds=bounds, params=params, paths=paths, ci=ci, si=si, zi=zi, X=X, y=f["y"],
                       tg=f["tgt"], tg_raw=f["tg"], tgs=tgs, log=f["log"], cv=f["cv"], short=list(short))
    # the weakest of the surrogates decides whether they choose the recipe
    r2s = [(f["cv"] or {}).get("r2") for f in fits]
    r2 = None if any(v is None for v in r2s) else min(r2s)
    if met and (r2 is None or r2 < WEAK_R2):
        # a weak surrogate: the recipe is the run that met the target with the least filler, the surrogate's
        # recipes stay as alternatives
        m0 = met[0]
        x0 = np.array([m0["values"][p_] for p_ in paths])
        pm0 = packing(x0)
        run_rec = describe(None, x0, math.log10(m0["value"]) if fits[0]["log"] and m0["value"] > 0 else m0["value"], 0.0,
                           pm0, viscosity(x0, pm0))
        run_rec["from_run"] = m0.get("label")
        if out.get("recommended"):
            out["alternatives"] = [out["recommended"]] + list(out.get("alternatives") or [])[:3]
        out["recommended"], out["reached"] = run_rec, True
        out["notes"] = [n for n in out["notes"] if n not in ("within_uncertainty", "not_reached", "packing_limit")] + ["weak_surrogate"]
    # the recipe to run once: the study's base case with the recommended values
    pick = out.get("recommended") or out.get("best")
    # the structures held a little less filler than asked (dense packings fall short): the content to ask
    # for in the check run is the recipe's plus the study's median shortfall
    sh = float(np.median(short)) if short else 0.0
    out["shortfall"] = round(sh, 3)
    if pick:
        vals = dict(pick["values"])
        if ci is not None and sh > 0.05:
            vals[paths[ci]] = round(pick["content"] + sh, 2)
            pick["asked"] = vals[paths[ci]]
        case = {"values": vals, "label": "AI recommended recipe"}
        try:
            form = DOE.apply_case(study["base_form"], case, parameters=study.get("parameters"))
            an = dict(form.get("analyses") or {})
            for a in spec.get("check_analyses") or []:
                an[a] = True
            form["analyses"] = an
            # three realisations of the structure: the check sees the scatter of one run, which the
            # surrogate's standard deviation (interpolation only) does not
            form.setdefault("rve", {})["n_seeds"] = max(3, int((form.get("rve") or {}).get("n_seeds") or 0))
            form["name"] = (study.get("base_form") or {}).get("name", "AI").split(" · DOE")[0] + " · recommended recipe"
            form.pop("_doe_index", None)
            out["check_form"] = form
        except Exception as e:                                   # noqa: BLE001
            out["notes"].append(f"check form: {e}")
    return out
