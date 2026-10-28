"""Quantities in a sentence: numbers with their units, ranges and lists.

The rules for a content (what fills a phase):

- "55%", "55 퍼센트", "55프로", "55 percent", "55 pct" - percent; the basis
  is the unit's when it has one ("55 vol%", "55 wt%", "55 부피%", "55 중량%",
  "55%(v/v)") or a basis word nearby ("부피비로", "by weight"), else open;
- "0.55", "0.55만큼", "부피분율 0.55", "a fraction of 0.55" - a number of 1
  or less without a unit is a fraction: 55 %;
- a number above 1 and up to 100 without a unit, said of a material, is a
  percent ("실리카 60 넣고");
- "1/3", "삼분의 일" - a fraction: 33.3 %; "절반" - 50 %;
- "30 phr" - parts per hundred resin, by weight: 30/(100 + all phr) as wt%;
- "40~60%", "40-60%", "40에서 60%까지", "from 40 to 60%", "between 40 and
  60%" - a range; "40, 50, 60%" or "40/50/60%" - a list of levels;
- "5단계", "5 levels", "5 points", "5 cases" - the number of levels; "10%
  간격", "10%씩", "in steps of 10", "every 10%" - the step.

Sizes: um, µm, micron, 마이크로(미터), 마이크론, 미크론; nm, 나노(미터);
mm, 밀리(미터). A number after a size word ("입경 5", "D50 5") without a
unit is taken in µm and said so.
"""
from __future__ import annotations

import re

NUM = r"(\d+(?:\.\d+)?|\.\d+)"
# basis-bearing percent units, longest first
_VOL = (r"(?:vol(?:ume)?\.?\s*%|v\s*/\s*v\s*%?|%\s*\(?\s*(?:vol|v\s*/\s*v)\.?\s*\)?|vol(?:ume)?\.?\s*(?:percent|pct)"
        r"|부피\s*(?:%|퍼센트|프로|퍼)|체적\s*(?:%|퍼센트|프로|퍼)|vol%|vol\b|부피비|부피분율|체적분율|v%)")
_WT = (r"(?:wt\.?\s*%|w\s*/\s*w\s*%?|%\s*\(?\s*(?:wt|w\s*/\s*w|mass)\.?\s*\)?|(?:weight|mass)\s*(?:%|percent|pct)"
       r"|wt\.?\s*(?:percent|pct)|중량\s*(?:%|퍼센트|프로|퍼)|무게\s*(?:%|퍼센트|프로|퍼)|질량\s*(?:%|퍼센트|프로|퍼)"
       r"|wt%|wt\b|중량비|무게비|질량비|중량분율|질량분율|w%)")
_PCT = r"(?:%|퍼센트|프로(?![가-힣])|퍼(?![가-힣])|percent|per\s*cent|pct)"
UNITS = [
    ("vol", _VOL), ("wt", _WT), ("pct", _PCT), ("phr", r"phr"),
    ("um", r"(?:um|microns?|micrometers?|micrometres?|마이크로\s*미터|마이크로미터|마이크로|마이크론|미크론|미크로)"),
    ("nm", r"(?:nm|nanometers?|nanometres?|나노\s*미터|나노미터|나노)"),
    ("mm", r"(?:mm|millimeters?|millimetres?|밀리\s*미터|밀리미터|밀리|미리)"),
    ("W/mK", r"(?:w\s*/\s*\(?\s*m\s*[·.*]?\s*k\s*\)?|w/mk)"),
    ("S/cm", r"s\s*/\s*cm"), ("S/m", r"s\s*/\s*m"),
    ("ohm_m", r"(?:ohm|Ω|ω)\s*[·.*]?\s*m(?!m)"), ("ohm_cm", r"(?:ohm|Ω|ω)\s*[·.*]?\s*cm"),
    ("ppm/K", r"ppm\s*/\s*(?:k|°c|℃|c)\b|ppm"),
    ("GPa", r"gpa"), ("MPa", r"mpa(?!\s*[·.]?\s*s)"), ("Pa.s", r"(?:m?pa\s*[·.*]?\s*s|cps?|센티포아즈)"),
    ("C", r"(?:°\s*c|℃|도(?![가-힣]))"),
    ("levels", r"(?:단계|수준|레벨|levels?|points?|케이스|cases?|조건|가지)"),
    ("repeat", r"(?:번\s*반복|회\s*반복|번|회|times|realisations?|realizations?|repeats?)"),
    ("cores", r"(?:코어|cores?|threads?|스레드|쓰레드)"),
    ("count", r"개"),
]
_UNIT_RE = [(k, re.compile(r"\s*" + p, re.IGNORECASE)) for k, p in UNITS]
_NUM_RE = re.compile(r"(?<![A-Za-z\d.\-_])" + NUM + r"(?:\s*/\s*" + NUM + r"(?![\d.])(?!\s*/\s*\d))?(?![\d])")
_NUM_ONLY = re.compile(r"(?<![A-Za-z\d.\-_])" + NUM + r"(?![\d])")
_RANGE_SEP = re.compile(r"\s*(?:~|to|에서|부터|and)\s*", re.IGNORECASE)
_LIST_SEP = re.compile(r"\s*[,/]\s*|\s+(?:or|and|와|과|및)\s+")


def _unit_at(text, pos):
    """(kind, end) of a unit right after pos, or (None, pos)."""
    for kind, rx in _UNIT_RE:
        m = rx.match(text, pos)
        if m and m.end() > pos:
            return kind, m.end()
    return None, pos


class _Whole:
    """A match of a whole number seen as one without a fraction part."""

    def __init__(self, m):
        self._m = m

    def group(self, i):
        return self._m.group(1) if i == 1 else None

    def start(self):
        return self._m.start()

    def end(self):
        return self._m.end()


def _value(m):
    v = float(m.group(1))
    if m.group(2):
        d = float(m.group(2))
        if d == 0:
            return None
        return v / d, "fraction"
    return v, None


def quantities(text):
    """Every number in the text with its unit: dicts {value, unit, start,
    end, raw, form ('fraction' for a/b), hi (range end), levels (a list)}.
    Numbers inside names (SU-8, Al2O3, SAC305) are skipped."""
    out = []
    taken = 0
    for m in _NUM_RE.finditer(text):
        if m.start() < taken:
            continue
        if m.group(2) and float(m.group(2)) > 12:
            m = _NUM_ONLY.match(text, m.start())   # "30/40": two levels; a fraction has a small denominator (1/3, 3/4)
            if not m:
                continue
            m = _Whole(m)
        vv = _value(m)
        if vv is None:
            continue
        v, form = vv
        unit, end = _unit_at(text, m.end())
        q = {"value": v, "unit": unit, "start": m.start(), "end": end, "form": form}
        # a range: number [unit] sep number [unit]
        sep = _RANGE_SEP.match(text, end)
        if sep:
            m2 = _NUM_RE.match(text, sep.end())
            if m2:
                v2 = _value(m2)
                unit2, end2 = _unit_at(text, m2.end())
                if v2 is not None and (unit2 == unit or unit is None or unit2 is None):
                    q.update(hi=v2[0], unit=unit or unit2, end=end2)
                    tail = re.match(r"\s*(?:까지|사이)", text[end2:])
                    if tail:
                        q["end"] = end2 + tail.end()
        if "hi" not in q:
            # a list: n, n, n unit
            vals, pos, last_unit = [v], end, unit
            while True:
                s = _LIST_SEP.match(text, pos)
                if not s:
                    break
                m3 = _NUM_ONLY.match(text, s.end())          # the items of a list are whole numbers
                if not m3:
                    break
                u3, e3 = _unit_at(text, m3.end())
                if unit is not None and u3 is not None and u3 != unit:
                    break
                vals.append(float(m3.group(1)))
                pos, last_unit = e3, u3 or last_unit
                if u3 is not None:
                    break
            if len(vals) >= 3 or (len(vals) == 2 and last_unit is not None and unit is None):
                q.update(levels=vals, unit=unit or last_unit, end=pos)
        q["raw"] = text[q["start"]:q["end"]]
        taken = q["end"]
        out.append(q)
    return out


PERCENT_UNITS = {"vol": "vol", "wt": "wt", "pct": None}


def as_content(q):
    """A quantity read as a content: (percent, basis or None, how) or None.
    `how` says which rule was applied, for the summary."""
    u = q.get("unit")
    v = q["value"]
    if u in PERCENT_UNITS:
        return v, PERCENT_UNITS[u], "percent"
    if u == "phr":
        return v, "phr", "phr"
    if u is not None:
        return None
    if q.get("form") == "fraction":
        return 100.0 * v, None, "fraction"
    if 0.0 < v <= 1.0:
        return 100.0 * v, None, "fraction"
    if 1.0 < v <= 100.0:
        return v, None, "bare"
    return None


def to_um(v, unit):
    return {"um": v, "nm": v / 1000.0, "mm": v * 1000.0}.get(unit)
