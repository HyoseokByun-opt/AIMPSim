"""Material values said for one request: "알루미나 열전도도는 20 W/mK로",
"k가 300인 BN", "알루미나 k를 라이브러리보다 10 낮게", "BN 열전도도 20% 낮춰서",
"use k = 20 for the alumina", "silica's modulus halved".

They hold for this request (and its follow-ups) only: they go into the
phases of the case MPSim runs, never into the material library, so the next
request starts from the library values again.

A value is a material's only when the material is named right beside its
property ("알루미나 열전도도 20", "열전도도 20인 알루미나"); the composite's
target ("열전도도를 3 W/mK로 할 수 있는") is not one.
"""
from __future__ import annotations

import re

from .numbers import quantities
from .textnorm import normalize

PROP_WORDS = {
    "k": r"열\s*전도\s*(?:도|율|계수)?|thermal\s+conductivity|(?<![a-z])k(?![a-z/])|\btc\b",
    "sigma": r"전기\s*전도\s*(?:도|율)|electrical\s+conductivity|(?<![a-z])sigma(?![a-z])|σ",
    "eps_r": r"유전\s*(?:율|상수)|\bdk\b|permittivity|dielectric\s+constant|ε\s*r?",
    "tan_d": r"유전\s*손실|손실\s*(?:탄젠트|계수)|\bdf\b|loss\s+tangent|tan\s*δ",
    "E": r"탄성\s*(?:률|계수)|영\s*률|모듈러스|young'?s?\s+modulus|\bmodulus\b|(?<![a-z])E(?![a-z])",
    "nu": r"푸아송\s*비|포아송\s*비|poisson'?s?\s+ratio|(?<![a-z])nu(?![a-z])|ν",
    "alpha": r"열\s*팽창\s*(?:계수|율)?|\bcte\b|thermal\s+expansion",
    "rho": r"밀도|density",
    "cp": r"비열|specific\s+heat",
}
UNIT_PROP = {"W/mK": "k", "S/m": "sigma", "S/cm": "sigma", "GPa": "E", "ppm/K": "alpha"}
# what the property's unit says the number is, when a unit is written
_SET_AFTER = (r"^\s*(?:으로|로|인|이고|짜리|이라고|라고|로\s*(?:해|두|놓|바꿔|잡|설정)|을\s*써|를\s*써|사용|으로\s*(?:해|두|바꿔|설정)"
              r"|for\b|as\b|,|\.|\)|$|\s+(?:and|in|instead|this|for|with|으로|로))")
_TARGET_AFTER = (r"\s*(?:이상|이하|미만|초과|넘|이\s*되|가\s*되|되는|되게|되도록|되려면|나오|달성|에\s*(?:맞추|가까)|로\s*(?:만들|맞추|할\s*수)"
                 r"|or\s+(?:more|higher|less|lower|above|below)|at\s+(?:least|most))")
_LOWER = r"낮|줄|빼|감소|작게|적게|떨어|lower|less|reduc|decreas|smaller|minus|below"
_HIGHER = r"높|올|늘|더해|증가|크게|많게|raise|higher|more|increas|larger|plus|above"
_BASE = r"(?:라이브러리|기본\s*값?|기존\s*값?|원래\s*값?|library|default|nominal)\s*(?:값)?\s*(?:보다|에서|대비|than|by)?"


def _mentions(text, lex):
    """(start, end, id) of each material named in the text."""
    out = []
    for m in lex.scan(text):
        if m.get("kind") == "material" and isinstance(m.get("key"), str):
            out.append((m["start"], m["end"], m["key"]))
    return out


def read(text, lex):
    """[{id, prop, value | delta | factor | percent, raw}] said in the text."""
    t = normalize(text or "")
    low = t.lower()
    mats = _mentions(t, lex)
    qs = quantities(t)
    out = []
    used = set()
    for prop, rx in PROP_WORDS.items():
        flags = 0 if prop == "E" else re.IGNORECASE
        for pm in re.finditer(rx, t if prop == "E" else low, flags):
            a, b = pm.start(), pm.end()
            # the material right before the property ("알루미나(의) 열전도도") or right after its value
            # "알루미나 열전도도", "에폭시(열전도도", "silica with a permittivity", "silicone (k"
            before = [m for m in mats if 0 <= a - m[1] <= 12
                      and re.fullmatch(r"\s*\(?\s*(?:의|은|는|'s|’s|with(?:\s+an?)?|having(?:\s+an?)?|of)?\s*\(?\s*",
                                       t[m[1]:a], re.IGNORECASE)]
            if not before:
                # inside brackets that open right after a material: "epoxy (k 0.2, E 3 GPa)"
                op = t.rfind("(", 0, a)
                if op >= 0 and ")" not in t[op:a]:
                    before = [m for m in mats if 0 <= op - m[1] <= 2]
            nxt = [q for q in qs if 0 <= q["start"] - b <= 14 and q["start"] not in used]
            if not nxt:
                continue
            q = nxt[0]
            mid_txt = low[b:q["start"]]
            if re.search(r"[.;!?]", mid_txt):
                continue
            unit, end = q.get("unit"), q["end"]
            if q.get("levels") or "hi" in q:
                # "3.9, 50%", "0.22 and 55%": a list to the reader of numbers, but the first has no unit of its own
                own = re.match(r"\s*[\d.]+(?:[eE][-+]?\d+)?\s*([^\s\d,~]+)?", q["raw"])
                if not (own and own.group(1) and not own.group(1).startswith(("and", "와", "과"))):
                    unit = None
                    end = q["start"] + len(re.match(r"\s*[\d.]+(?:[eE][-+]?\d+)?", q["raw"]).group(0))
            if unit in UNIT_PROP and UNIT_PROP[unit] != prop:
                continue
            if unit in ("vol", "wt", "um", "nm", "mm", "levels", "repeat", "cores", "count", "phr"):
                continue
            after = low[end:end + 30]
            # the composite's target, not the material's value: "에폭시에서 열전도도 2 W/mK 이상 되는", "for a k of at least"
            if re.match(_TARGET_AFTER, after):
                continue
            # "에폭시에서 열전도도", "에폭시에 ... 열전도도": the resin is where, not whose
            before = [m for m in before if not re.search(r"(?:에서|에서의|에는|에)$", t[m[0]:m[1]])]
            mid = before[-1][2] if before else None
            if mid is None:
                # "열전도도 20 W/mK인 알루미나", "k = 300 BN"
                m2 = [m for m in mats if 0 <= m[0] - end <= 8 and re.fullmatch(r"\s*(?:인|짜리|의|of|for)?\s*", t[end:m[0]])]
                if m2:
                    mid = m2[0][2]
                elif re.match(r"\s*(?:for|of)\s+(?:the\s+)?", after):
                    m3 = [m for m in mats if 0 <= m[0] - end <= 16]
                    mid = m3[0][2] if m3 else None
            if mid is None:
                continue
            rel = re.match(r"\s*(%|퍼센트|프로|percent)?\s*(?:만큼|정도|쯤)?\s*(" + _LOWER + "|" + _HIGHER + ")", after)
            pct = unit == "pct" or (rel and rel.group(1))
            item = {"id": mid, "prop": prop, "raw": t[a:end + (rel.end() if rel else 0)]}
            if rel:
                sign = -1.0 if re.match(_LOWER, rel.group(2)) else 1.0
                if pct:
                    item["percent"] = sign * q["value"]
                else:
                    item["delta"] = sign * q["value"]
            elif unit == "pct" and re.match(r"\s*(?:으로|로|of\s+(?:the\s+)?(?:library|default))", after):
                item["factor"] = q["value"] / 100.0          # "열전도도 80%로", "절반으로" (normalised to 50%)
            elif unit == "pct":
                continue
            elif re.search(r"(?:=|:|은|는|이|가|을|를)?\s*$", mid_txt) and (re.match(_SET_AFTER, after) or unit in UNIT_PROP):
                item["value"] = q["value"] * (100.0 if unit == "S/cm" else 1.0)
            else:
                continue
            used.add(q["start"])
            out.append(item)
    # "알루미나 20 W/mK": the unit names the property
    for q in qs:
        prop = UNIT_PROP.get(q.get("unit"))
        if not prop or q["start"] in used:
            continue
        m1 = [m for m in mats if 0 <= q["start"] - m[1] <= 4 and re.fullmatch(r"\s*(?:의|은|는|=|:)?\s*", t[m[1]:q["start"]])]
        if m1 and not re.match(r"\s*(?:로|으로)?\s*(?:할|만들|맞추|되|나오|이상|이하|달성)", low[q["end"]:q["end"] + 12]):
            used.add(q["start"])
            out.append({"id": m1[-1][2], "prop": prop, "value": q["value"] * (100.0 if q.get("unit") == "S/cm" else 1.0),
                        "raw": t[m1[-1][0]:q["end"]]})
    # "BN 열전도도 절반으로", "silica modulus doubled"
    for prop, rx in PROP_WORDS.items():
        for pm in re.finditer(rx, t if prop == "E" else low, 0 if prop == "E" else re.IGNORECASE):
            before = [m for m in mats if 0 <= pm.start() - m[1] <= 6]
            if not before:
                continue
            after = low[pm.end():pm.end() + 16]
            f = 0.5 if re.match(r"\s*(?:을|를|은|는)?\s*(?:절반|반으로|half|halved)", after) else \
                2.0 if re.match(r"\s*(?:을|를|은|는)?\s*(?:두\s*배|2\s*배|double|twice)", after) else None
            if f and not any(o["id"] == before[-1][2] and o["prop"] == prop for o in out):
                out.append({"id": before[-1][2], "prop": prop, "factor": f, "raw": t[pm.start():pm.end() + 8].strip()})
    return out


def resolve(items, lib_props):
    """{prop: value} for one material: a relative change taken from the
    library value. Returns (values, notes) - notes say how each was found."""
    vals, how = {}, {}
    for it in items:
        p = it["prop"]
        base = lib_props.get(p)
        if "value" in it:
            vals[p], how[p] = float(it["value"]), ("said", None)
        elif base is None:
            continue
        elif "delta" in it:
            vals[p], how[p] = float(base) + float(it["delta"]), ("delta", float(it["delta"]))
        elif "percent" in it:
            vals[p], how[p] = float(base) * (1.0 + float(it["percent"]) / 100.0), ("percent", float(it["percent"]))
        elif "factor" in it:
            vals[p], how[p] = float(base) * float(it["factor"]), ("factor", float(it["factor"]))
    return vals, how
