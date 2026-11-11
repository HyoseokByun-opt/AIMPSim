"""A through via in a request: the hole, the board, the plating of its wall
and the vias around it, read before the parser looks at sizes and contents.

A via request is full of lengths that are not particles: "홀 100um",
"1.8T", "pitch 300um", "도금 5~25um". Each is read by the word next to it
and taken out of the sentence's quantities, so that none becomes the
filler's size or a content. What is read:

- the via itself: 비아, 관통홀, 스루홀, through via, through hole, PTH, a
  hybrid filling (in English "via" only with a via word beside it - hole,
  plating, pitch, board, impedance, paste - since it is also a preposition);
- the hole's diameter: a length next to 홀 / 구멍 / hole / drill;
- the board's thickness: "1.8T", or a length in mm next to 기판 / board /
  PCB / 두께; the aspect ratio "AR 18:1" (with the hole it gives the board,
  with the board the hole);
- the pitch to the return vias: a length next to 피치 / pitch;
- the plating of the wall: a length next to 도금 / plating / wall, one value,
  a range or a list (a range or a list is a DOE factor);
- the return vias: GSG, one return via (S-G), 4 or 8 around;
- the frequency the results are read at: "10GHz";
- a paste ("paste", "페이스트"): the particles of the fill may overlap (the
  necks a cure forms);
- a glass core ("유리 기판", "glass core", "TGV"): the substrate is glass - its
  εr and tan δ, and for the stress its stiffness and expansion; the words are
  the substrate's, not a filler (5.8.0);
- the thermal stress ("열응력", "응력", "균열", "crack", "thermal stress"): the
  via's stress in its substrate (MPSim 5.8.0), not the warpage of a film.

Words of the wall's metal ("Cu 도금", "copper plating") are not a filler,
nor is "AR" (argon by its formula): their spans are returned so that the
parser drops the material there.
"""
from __future__ import annotations

import re

WORD = re.compile(r"비아|관통\s*홀|관통\s*vias?|스루\s*홀|도금\s*홀|홀\s*(?:충전|필링|채움|플러깅)|하이브리드\s*(?:필링|충전)"
                  r"|(?<![a-z])(?:through[\s-]*(?:glass[\s-]*)?(?:holes?|vias?)|pths?|tgvs?|plated[\s-]*through[\s-]*holes?"
                  r"|hybrid[\s-]*fill(?:ing|ed)?)(?![a-z])", re.IGNORECASE)
EN_VIA = re.compile(r"(?<![a-z])vias?(?![a-z])", re.IGNORECASE)
# English "via" is a via only with one of these beside it in the sentence
EN_CONTEXT = re.compile(r"hole|plat(?:ing|ed)|pitch|board|pcb|impedance|s-?parameter|paste|laminate|drill|barrel"
                        r"|홀|도금|피치|기판|페이스트|임피던스|구멍", re.IGNORECASE)
RESPONSE = re.compile(r"임피던스|impedance|s\s*-?\s*파라미터|s-?parameters?|\bs21\b|\bs11\b|삽입\s*손실|반사\s*손실"
                      r"|insertion\s+loss|return\s+loss", re.IGNORECASE)
PASTE = re.compile(r"페이스트|(?<![a-z])pastes?(?![a-z])|소결|sinter", re.IGNORECASE)
# a glass core: the substrate, never a filler
GLASS = re.compile(r"(?:유리|글라스|glass)\s*(?:기판|코어|core|substrate|interposer|인터포저|웨이퍼|wafer|패널|panel)?"
                   r"|(?<![a-z])tgvs?(?![a-z])|through[\s-]*glass[\s-]*vias?", re.IGNORECASE)
STRESS = re.compile(r"열\s*응력|응력|균열|크랙|깨짐|파손|(?:thermal\s*)?stress(?:es)?|cracks?|cracking", re.IGNORECASE)
# the wall's metal, never a filler of the composite
WALL_METAL = re.compile(r"(?:cu|copper|구리|동)\s*(?:전해\s*)?(?:도금|plating|plated|wall)"
                        r"|(?:electro)?plated\s+(?:cu|copper)", re.IGNORECASE)

_TOPIC = r"\s*(?:은|는|이|가|을|를|=|:|of|is)?\s*"
B = {
    "hole_d_um": re.compile(r"(?:홀|구멍|hole|drill|드릴|비아\s*홀|via\s*hole|비아|via)\s*(?:의\s*)?"
                            r"(?:직경|지름|크기|사이즈|diameter|dia\.?|size)?" + _TOPIC + r"$", re.IGNORECASE),
    "length_mm": re.compile(r"(?:기판|보드|board|pcb|substrate|적층판|laminate|코어|패널|panel)\s*(?:의\s*)?"
                            r"(?:두께|thickness)?" + _TOPIC + r"$|(?<!도금)(?<!도금\s)(?<!plating\s)(?:두께|thickness)"
                            + _TOPIC + r"$", re.IGNORECASE),
    "pitch_um": re.compile(r"(?:피치|pitch|비아\s*간격|via\s*spacing)" + _TOPIC + r"$", re.IGNORECASE),
    "plating_um": re.compile(r"(?:도금|plating|plated|wall|벽)\s*(?:층)?\s*(?:의\s*)?(?:두께|thickness)?" + _TOPIC + r"$",
                             re.IGNORECASE),
    "throw": re.compile(r"(?:throwing\s*power|균일\s*전착성|전착성|tp)" + _TOPIC + r"$", re.IGNORECASE),
}
A = {
    "hole_d_um": re.compile(r"^\s*(?:의\s*)?(?:짜리\s*)?(?:홀|구멍|hole|drill|드릴|via\s*hole|비아\s*홀)", re.IGNORECASE),
    "length_mm": re.compile(r"^\s*(?:두께의?\s*|thick\s*)?(?:(?:유리|글라스|glass)\s*)?(?:기판|보드|board|pcb|substrate|적층판|laminate|패널|panel"
                            r"|코어|core|웨이퍼|wafer)",
                            re.IGNORECASE),
    "pitch_um": re.compile(r"^\s*(?:의\s*)?(?:피치|pitch)", re.IGNORECASE),
    "plating_um": re.compile(r"^\s*(?:두께의?\s*|thick\s*)?(?:(?:cu|copper|구리|동)\s*)?(?:도금|plating|wall)", re.IGNORECASE),
}
LENGTH = {"um": 1.0, "nm": 1e-3, "mm": 1e3}


def _um(q):
    f = LENGTH.get(q.get("unit"))
    return None if f is None else f


# a follow-up in a conversation about a via ("도금은 10um로", "pitch 250 um"): read without the via's own word
FOLLOW = re.compile(r"도금|피치|홀|구멍|기판|리턴|plating|pitch|hole|board|return\s+via|gsg", re.IGNORECASE)


def active(t, open_=False):
    """Whether the sentence asks about a through via (or, with open_, adds to one)."""
    if open_ and FOLLOW.search(t):
        return True
    if WORD.search(t):
        return True
    return bool(EN_VIA.search(t) and EN_CONTEXT.search(t))


def read(t, qs, open_=False):
    """The via of a normalised sentence t with its quantities qs (numbers.quantities),
    or None; open_: the conversation is already about a via.
    -> {options, factors, used (indices of qs), wall_spans, paste, said, ar}"""
    if not active(t, open_):
        return None
    low = t.lower()
    out = {"options": {}, "factors": [], "used": set(), "said": {}, "paste": bool(PASTE.search(t)),
           "wall_spans": [(m.start(), m.end()) for m in WALL_METAL.finditer(t)], "ar": None,
           "responses": bool(RESPONSE.search(t)), "glass": False, "stress": bool(STRESS.search(t))}
    for m in GLASS.finditer(t):
        out["glass"] = True
        out["wall_spans"].append((m.start(), m.end()))         # the substrate, not a filler
    # the board as "1.8T" (a thickness in mm, as boards are named)
    # ("1.8T" alone or with a Korean particle: "1.8T에", "1.8T의"; not "1.8 톤")
    for m in re.finditer(r"(?<![\w.])(\d+(?:\.\d+)?)\s*t(?![a-z])(?!(?![에의는은이가를을로와과])[가-힣])", low):
        v = float(m.group(1))
        if 0.05 <= v <= 20:
            out["options"]["length_mm"] = v
            out["said"]["length_mm"] = m.group(0).strip()
            out["used"] |= {i for i, q in enumerate(qs) if m.start() <= q["start"] < m.end()}
            break
    # the aspect ratio "AR 18:1", "18:1"
    m = re.search(r"(?:ar|aspect\s*ratio|종횡비|형상비)?\s*(?:은|는|=|:)?\s*(\d+(?:\.\d+)?)\s*:\s*1(?![\d.])", low)
    if m:
        out["ar"] = float(m.group(1))
        out["said"]["ar"] = m.group(0).strip()
        out["wall_spans"].append((m.start(), m.end()))          # "AR" is no material (argon)
        out["used"] |= {i for i, q in enumerate(qs) if m.start() <= q["start"] < m.end()}
    for i, q in enumerate(qs):
        if i in out["used"]:
            continue
        before, after = low[max(0, q["start"] - 28):q["start"]], low[q["end"]:q["end"] + 24]
        f = _um(q)
        key = None
        if f is not None:
            for k in ("plating_um", "pitch_um", "hole_d_um", "length_mm"):
                if B[k].search(before) or (k in A and A[k].match(after)):
                    key = k
                    break
            if key == "length_mm" and q.get("unit") != "mm":
                key = None if f * q["value"] < 100 else key        # a board is at least 0.1 mm
        elif q.get("unit") in ("pct", None) and B["throw"].search(before):
            key = "throw"
        if key is None:
            continue
        out["used"].add(i)
        out["said"][key] = q["raw"].strip()
        if key == "throw":
            v = q["value"] / 100.0 if q.get("unit") == "pct" or q["value"] > 1 else q["value"]
            out["options"]["throw"] = v
            continue
        scale = f / 1e3 if key == "length_mm" else f
        vals = q.get("levels") or ([q["value"], q["hi"]] if "hi" in q else None)
        if vals and key == "plating_um":
            # a range or a list of walls: the study's factor
            out["factors"].append({"what": "via", "key": key, "levels": [v * scale for v in q["levels"]] if q.get("levels") else None,
                                   "range": (q["value"] * scale, q["hi"] * scale) if "hi" in q else None})
            out["options"][key] = (q["levels"][0] if q.get("levels") else q["value"]) * scale
        else:
            out["options"].setdefault(key, q["value"] * scale)
    # the frequency the results are read at
    m = re.search(r"(\d+(?:\.\d+)?)\s*(ghz|mhz)", low)
    if m:
        out["options"]["f_ref"] = float(m.group(1)) * (1e9 if m.group(2) == "ghz" else 1e6)
        out["said"]["f_ref"] = m.group(0)
        out["used"] |= {i for i, q in enumerate(qs) if m.start() <= q["start"] < m.end()}
    # the return vias
    if re.search(r"\bgsg\b|g-s-g|ground[\s-]*signal[\s-]*ground|그라운드[\s-]*신호[\s-]*그라운드", low):
        out["options"]["returns"] = "gsg"
    elif re.search(r"\bs-?g\b(?!\w)|signal[\s-]*ground(?![\s-]*signal)|리턴\s*비아\s*(?:1|하나|한)\s*개?|"
                   r"(?:one|a single)\s+(?:return|ground)\s+via", low):
        out["options"]["returns"] = "sg"
    else:
        m = re.search(r"(?:리턴|그라운드|return|ground)\s*(?:비아|vias?)?\s*(\d)\s*(?:개)?|(\d)\s*(?:개의\s*)?"
                      r"(?:리턴|그라운드|return|ground)\s*(?:비아|vias?)", low)
        n = int(m.group(1) or m.group(2)) if m else None
        if n in (4, 8):
            out["options"]["returns"] = f"coax{n}"
        if m:
            out["used"] |= {i for i, q in enumerate(qs) if m.start() <= q["start"] < m.end()}
    # the aspect ratio fills in the hole or the board
    ar, o = out["ar"], out["options"]
    if ar:
        if o.get("hole_d_um") and not o.get("length_mm"):
            o["length_mm"] = round(ar * o["hole_d_um"] / 1e3, 6)
            out["said"]["length_mm"] = f"AR {ar:g}:1 × {o['hole_d_um']:g} µm"
        elif o.get("length_mm") and not o.get("hole_d_um"):
            o["hole_d_um"] = round(o["length_mm"] * 1e3 / ar, 4)
            out["said"]["hole_d_um"] = f"{o['length_mm']:g} mm / AR {ar:g}"
    return out


def numbers(v):
    """The values the via took from the sentence (to keep them out of sizes and contents)."""
    if not v:
        return set()
    vals = {round(x, 6) for k, x in v["options"].items() if isinstance(x, (int, float))}
    for f in v["factors"]:
        vals |= {round(x, 6) for x in (f.get("levels") or f.get("range") or [])}
    if v.get("ar"):
        vals.add(round(v["ar"], 6))
    return vals
