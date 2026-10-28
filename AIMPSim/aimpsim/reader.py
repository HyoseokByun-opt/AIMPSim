"""Model-first reading of a request.

The local model reads the whole sentence - roundabout wording, a word
taken back ("not alumina", "55%, no, 60%"), a property described instead
of named ("how well heat gets out"), spacing and typing errors, Korean and
English mixed - and answers in a fixed JSON form (SCHEMA). The rules then
check that answer before anything of it is used:

- a material must be in the sentence (by name, by spelling or sound, or as
  the rules found it); a material the model brought in itself is dropped;
- every number must come from the sentence, as said or by a calculation
  that is shown (4:6 -> 60 %, 150 g in 100 g of resin -> 60 wt%, 0.55 ->
  55 %, nm -> um, MPa -> GPa); a number the model made up is dropped and
  asked for;
- a material value (k, E, CTE ...) is the user's own, from the sentence,
  over the library's; it is never estimated;
- where the rules read the same sentence differently, the model's reading
  is used and the difference is shown in the summary.

Without a model (or when it fails) the rules read the request alone, as
before.
"""
from __future__ import annotations

import copy
import json
import re

from . import lexicon_data as L
from .phonetic import has_hangul, squash

ANALYSIS_KEYS = list(L.ANALYSES.keys())
PROP_KEYS = ["k", "sigma", "eps_r", "tan_d", "E", "nu", "alpha", "rho", "cp", "mu_r"]
PROP_UNITS = {"k": "W/m·K", "sigma": "S/m", "eps_r": "-", "tan_d": "-", "E": "GPa", "nu": "-", "alpha": "ppm/K",
              "rho": "g/cm³", "cp": "J/kg·K", "mu_r": "-"}
MEAS_PROPS = ["k", "sigma", "eps_r", "alpha", "E", "mu"]
# a library variant and the material it is a form of: the model may name either
FAMILY = {"hbn_platelet": "hbn", "diamond_grit": "diamond", "sic_grit": "sic", "a356": "al6061"}
_BASIS_WORDS = {
    "vol": r"vol|부피|체적|volume|v/v",
    "wt": r"wt|중량|무게|질량|weight|mass|w/w|\d\s*(?:g|kg|mg|그램)(?![A-Za-z])",
    "phr": r"phr|(?<![A-Za-z])parts?(?![A-Za-z])|중량부|\d\s*부(?!피)",
}
MEAS_ANALYSIS = {"k": "thermal", "sigma": "electrical", "eps_r": "dielectric", "alpha": "cte", "E": "cte",
                 "mu": "viscosity"}
# an analysis the model chose needs a word of the sentence that points to it (a name, a property,
# a purpose): one the sentence gives no reason for is asked, not run
ANALYSIS_CUES = {
    "thermal": r"열(?!\s*팽|\s*응력|\s*변형|\s*적\s*팽)|heat|therm|방열|냉각|cool|\btim\b|(?<![a-z])k(?![a-z])|w/m|전도|conduct|spread|갭\s*필러|gap\s*fill|패드|\bpad",
    "electrical": r"전기|전류|통하|도전|저항|conduct|current|resist|electr|ohm|s/m|페이스트|paste|퍼콜",
    "dielectric": r"유전|\bdk\b|\bdf\b|손실|loss|신호|5g|고주파|주파수|\brf\b|permittiv|dielectric|기판|substrate|capacit|커패시|high-?k|low-?k|ε",
    "magnetic": r"자기|자성|투자|magnet|permeab|인덕|inductor|μ|\bmu\b",
    "emi": r"전자파|\bemi\b|차폐|shield|막",
    "cte": r"팽창|\bcte\b|탄성|강성|모듈|modul|stiff|딱딱|단단|hard|young|poisson|푸아송|expan|늘어|수축|shrink|\be\b|gpa|기계",
    "mechtest": r"인장|압축|시험|\btest|\butm\b|하중|변위|\bload|displace|curve|곡선|파단|strength|강도",
    "thermomech": r"휨|휘|warp|\bbow|curv|응력|stress|뒤틀|굽",
    "joule": r"줄\s*(?:발열|열)|joule|발열|뜨거|\bhot\b|가열|heating|전류",
    "viscosity": r"점도|흐르|흐름|흘러|\bflow|viscos|rheol|언더필|underfill|충전성",
    "moisture": r"흡습|수분|물을|물\s|습|moist|water|humid|swell|팽윤",
    "permeability": r"투과|permea|darcy|기체|\bgas\b",
    "filtration": r"여과|필터|filtr|filter",
    "tortuosity": r"확산|굴곡|tortu|diffus",
    "acoustics": r"흡음|소리|음향|acoust|sound|noise|소음",
    "radiation": r"복사|radiat",
    "morphology": r"기공|비표면|\bpore|surface\s*area|morpholog",
    "percolation": r"퍼콜|연결|percol|connect|네트워크|network",
    "porosimetry": r"포로시|수은|porosim|mercury",
    "pore_network": r"기공\s*네트워크|pore\s*network",
    "grains": r"입자\s*분석|구형도|grain|particle\s*analy|spheric",
}
# an orientation needs a word that says it
ORIENT_CUES = {"z": r"수직|세로|세워|vertical|through[- ]?(?:plane|thickness)|두께\s*방향|z\s*(?:방향|축|정렬|align)",
               "xy": r"수평|면내|눕혀|눕힌|in[- ]?plane|lateral|가로\s*방향|\bxy\b",
               "iso": r"무작위|랜덤|등방|random|isotrop"}
COMPARE = re.compile(r"비교|중\s*(?:에|에서)?\s*(?:어느|뭐가|뭐|어떤\s*게|무엇이)|어느\s*(?:쪽|것|게)|\bvs\.?\b|versus|\bcompare|"
                     r"which\s+(?:one|is|of|works|gives)|뭐가\s*(?:더\s*)?(?:나아|낫|좋)|무엇이\s*(?:더\s*)?(?:나아|낫|좋)|"
                     r"or\s+\w+(?:\s+\w+)?\s*,?\s*which", re.IGNORECASE)
MIXED = re.compile(r"같이|함께|섞|혼합|\btogether\b|\bmix|\bblend|\bcombined?\b|\bplus\b|\+", re.IGNORECASE)

_NUM = {"type": ["number", "null"]}
_PROPS = {"type": ["object", "null"], "properties": {k: _NUM for k in PROP_KEYS}}
SCHEMA = {
    "type": "object",
    "properties": {
        "matrix": {"type": ["object", "null"], "properties": {"material": {"type": ["string", "null"]},
                                                              "amount": _NUM, "props": _PROPS}},
        "fillers": {"type": "array", "items": {"type": "object", "properties": {
            "material": {"type": "string"},
            "percent": _NUM, "amount": _NUM,
            "basis": {"enum": ["vol", "wt", "phr", None]},
            "shape": {"enum": ["sphere", "platelet", "fiber", "irregular", "cube", None]},
            "size_um": _NUM, "size_std_um": _NUM, "aspect": _NUM, "length_um": _NUM, "thickness_um": _NUM,
            "props": _PROPS},
            "required": ["material", "percent"]}},
        "analyses": {"type": "array", "items": {"enum": ANALYSIS_KEYS}},
        "task": {"enum": ["run", "doe", "calibration", "optimization", "structure"]},
        "doe": {"type": "array", "items": {"type": "object", "properties": {
            "filler": {"type": "integer"}, "what": {"enum": ["content", "size"]},
            "from": _NUM, "to": _NUM, "steps": {"type": ["integer", "null"]}, "step": _NUM,
            "levels": {"type": ["array", "null"], "items": {"type": "number"}}},
            "required": ["filler", "what"]}},
        "measurements": {"type": "array", "items": {"type": "object", "properties": {
            "property": {"enum": MEAS_PROPS}, "value": {"type": "number"}, "percent": _NUM},
            "required": ["property", "value"]}},
        "unknowns": {"type": "array", "items": {"enum": ["r_int", "r_contact", "filler_k"]}},
        "goal": {"enum": ["max", "min", None]},
        "settings": {"type": "object", "properties": {
            "quality": {"enum": ["fast", "standard", "accurate", None]},
            "decide_for_me": {"type": "boolean"},
            "directions": {"enum": ["z", "xyz", None]},
            "orientation": {"enum": ["z", "xy", "iso", None]},
            "cores": {"type": ["integer", "null"]}, "parallel_runs": {"type": ["integer", "null"]},
            "seeds": {"type": ["integer", "null"]}, "rve_um": _NUM, "voxel_um": _NUM, "film_um": _NUM}},
    },
    "required": ["matrix", "fillers", "analyses", "task"],
}

_AN_HELP = {
    "thermal": "thermal conductivity, heat dissipation, how well heat gets through or out, TIM, heat spreading",
    "electrical": "electrical conductivity or resistance, whether current flows, conductive adhesive or paste",
    "dielectric": "permittivity Dk, dielectric loss Df, signal loss, low-k / 5G substrate",
    "magnetic": "magnetic permeability",
    "emi": "EMI shielding, blocking electromagnetic waves",
    "cte": "elastic properties and thermal expansion: Young's modulus, stiffness, how stiff or hard, Poisson's "
           "ratio, CTE",
    "mechtest": "a simulated tensile or compression TEST with a load-displacement curve - only when a test, UTM or "
                "a curve is asked (stiffness or modulus alone is cte)",
    "thermomech": "warpage, bending of a chip or film, thermal stress",
    "joule": "Joule heating, how hot it gets when current flows",
    "viscosity": "viscosity, flow, whether it flows / fills (underfill)",
    "moisture": "moisture or water uptake, swelling in humidity",
    "permeability": "gas or flow permeability (Darcy)",
    "filtration": "filter efficiency",
    "tortuosity": "diffusion, tortuosity",
    "acoustics": "sound absorption",
    "radiation": "radiative heat transfer",
    "morphology": "pore size, specific surface",
    "percolation": "percolation, connectivity of particles",
    "porosimetry": "mercury porosimetry",
    "pore_network": "pore network",
    "grains": "particle / grain analysis, sphericity",
}

RULES = """You turn a request for a composite-material simulation into JSON. Requests are casual: Korean, English or
both mixed, with spacing and typing errors, roundabout wording and corrections. Find what the person finally wants.

Rules:
- matrix: the resin or base material. fillers: the particles put into it, in the order said.
- material: the id from the list below; if the material is not in the list, write its name as said.
- Never add a material, number or property value that the request does not give. If an amount is vague ("a bit
  more than half", "많이", "조금"), percent is null.
- percent: the filler content as said: 55% -> 55; 0.55 -> 55; half / 반 / 절반 -> 50; a quarter / 4분의 1 -> 25;
  a ratio matrix:filler 4:6 or 4대6 -> 60; 30 phr -> 30 with basis phr; "matrix 45, filler 55" -> 55. If only the
  matrix share is given and there is one filler, the filler takes the rest. basis: vol (부피, volume, vol%), wt (중량,
  무게, weight, wt%), phr, or null if not said.
- amount: masses or parts instead of percents ("수지 100g에 알루미나 150g", "100 parts epoxy, 150 parts alumina"):
  the matrix's in matrix.amount and each filler's in its amount, percent null. Never compute them yourself.
- A correction wins: "55%, 아니 60%" / "55%, actually 60%" -> 60. "A 말고 B", "A 아니고 B", "not A, B",
  "B instead of A" -> only B. "X는 필요없고 Y만" / "skip X, only Y" -> only Y.
- shape: sphere (구형, 동그란, ball), platelet (판상, 플레이크, 판 모양, flake), fiber (섬유, 막대, rod, whisker),
  irregular (불규칙, 파쇄, 각진), cube. size_um: particle diameter in micrometres (5 nm = 0.005, 1 mm = 1000);
  size_std_um: its spread if given; aspect: aspect ratio; length_um, thickness_um for fibres and plates.
- Two sizes of the same material ("큰 거 40%, 작은 거 20%") are two fillers.
- props: a material value the person gives for that material: k (W/mK), sigma (S/m), eps_r, tan_d, E (GPa),
  nu, alpha (CTE, ppm/K), rho (g/cm3), cp, mu_r. Only values said in the request.
- analyses: what to compute, from the list below; a purpose implies it (TIM, 방열 -> thermal; 5G 기판 손실 ->
  dielectric; 언더필이 잘 흐를까 -> viscosity; 휨 -> thermomech; 얼마나 딱딱한지, stiffness -> cte). If the request
  does not say or imply what to compute, analyses is empty.
- A comparison of alternatives ("A랑 B 중 어느 쪽", "A vs B", "compare A and B"): each one a filler with its
  percent; the program runs them separately.
- task: run (one case); doe (a range or several levels to sweep: "40에서 60까지", "40, 50, 60%", "from 40 to 60");
  calibration (measured values to fit); optimization (a range and a best value wanted); structure (only the
  structure). doe: one item per swept quantity, filler = index of the filler (0 = first).
- measurements: measured values for calibration, property k/sigma/eps_r/alpha/E/mu, with the filler percent of
  the sample. unknowns: what to fit: r_int (interface resistance), r_contact (particle contact), filler_k.
- settings: quality fast/standard/accurate (빠르게/대충 -> fast, 정확하게/정밀 -> accurate); decide_for_me true
  for "알아서", "자동으로", "decide for me"; directions z or xyz (3방향, all directions); orientation z (aligned
  vertically), xy (in plane), iso (random); cores; parallel_runs (runs at the same time); seeds (repeats);
  rve_um (RVE size); voxel_um; film_um (film thickness).

Materials (id: names):
{materials}

Analyses (id: meaning):
{analyses}
"""

EXAMPLES = [
    ("PI 필름에 탄화규소 넣을건데 한 35프로? 열 잘빠지는지 + 휘는것도 봐줘. 필름은 30마이크로",
     {"matrix": {"material": "polyimide"}, "fillers": [{"material": "sic", "percent": 35}],
      "analyses": ["thermal", "thermomech"], "task": "run", "settings": {"film_um": 30}}),
    ("니켈말고 구리플레이크로 바꿔서 , 실리콘베이스에 20vol% 넣으면 전류 잘흐르나",
     {"matrix": {"material": "silicone"}, "fillers": [{"material": "cu", "percent": 20, "basis": "vol",
                                                        "shape": "platelet"}],
      "analyses": ["electrical"], "task": "run"}),
    ("glass fiber 넣은 PPE 기판인데 비율은 수지:필러 7대3, 섬유 지름 10um 길이 200um. Dk Df 궁금",
     {"matrix": {"material": "ppe"}, "fillers": [{"material": "eglass", "percent": 30, "shape": "fiber",
                                                   "size_um": 10, "length_um": 200}],
      "analyses": ["dielectric"], "task": "run"}),
    ("silicone with magnesia, 45%, wait no make it 50%. the magnesia I use is 40 W/mK, about 20um +-5",
     {"matrix": {"material": "silicone"}, "fillers": [{"material": "mgo", "percent": 50, "size_um": 20,
                                                        "size_std_um": 5, "props": {"k": 40}}],
      "analyses": ["thermal"], "task": "run"}),
    ("에폭시에 질화규소를 꽤 많이 넣어서 CTE 낮추고 싶은데",
     {"matrix": {"material": "epoxy"}, "fillers": [{"material": "si3n4", "percent": None}],
      "analyses": ["cte"], "task": "run"}),
    ("BCB에 산화아연 10에서 40퍼까지 4단계로 돌려보고 유전율 어떻게 되는지, 대충 빠르게",
     {"matrix": {"material": "bcb"}, "fillers": [{"material": "zno", "percent": None}], "analyses": ["dielectric"],
      "task": "doe", "doe": [{"filler": 0, "what": "content", "from": 10, "to": 40, "steps": 4}],
      "settings": {"quality": "fast"}}),
    ("measured k = 0.9 at 30% and 1.6 at 45% for epoxy/SiC, fit the interface resistance, decide the rest yourself",
     {"matrix": {"material": "epoxy"}, "fillers": [{"material": "sic", "percent": None}], "analyses": ["thermal"],
      "task": "calibration", "measurements": [{"property": "k", "value": 0.9, "percent": 30},
                                              {"property": "k", "value": 1.6, "percent": 45}],
      "unknowns": ["r_int"], "settings": {"decide_for_me": True}}),
    ("열전도 좋은 방열시트 만들고 싶은데 뭐 넣어야됨?",
     {"matrix": None, "fillers": [], "analyses": ["thermal"], "task": "run"}),
    ("LCP 100g에 BN 25g, 판상 15마이크로, 열전도 수직방향으로 정렬시켜서",
     {"matrix": {"material": "lcp", "amount": 100}, "fillers": [{"material": "hbn", "percent": None, "amount": 25,
                                                                  "shape": "platelet", "size_um": 15}],
      "analyses": ["thermal"], "task": "run", "settings": {"orientation": "z"}}),
    ("실리콘에 니켈 플레이크 반쯤 넣으면 얼마나 뻣뻣해지는지랑 전기 통하는지",
     {"matrix": {"material": "silicone"}, "fillers": [{"material": "ni", "percent": 50, "shape": "platelet"}],
      "analyses": ["cte", "electrical"], "task": "run"}),
    ("SiC랑 AlN 중에 PI에 20% 넣으면 어느 게 열 더 잘 빼?",
     {"matrix": {"material": "polyimide"}, "fillers": [{"material": "sic", "percent": 20},
                                                        {"material": "aln", "percent": 20}],
      "analyses": ["thermal"], "task": "run"}),
    ("BT 레진에 실리카 넣으면 어떻게 될까",
     {"matrix": {"material": "bt"}, "fillers": [{"material": "sio2", "percent": None}], "analyses": [], "task": "run"}),
]


def system_prompt(lex):
    mats = []
    for mid, a in L.MATERIALS.items():
        if lex.library and mid not in lex.library:
            continue
        names = (a.get("en") or [])[:2] + (a.get("ko") or [])[:2] + (a.get("formula") or [])[:1]
        mats.append(f"{mid}: " + ", ".join(dict.fromkeys(names)))
    ans = [f"{k}: {_AN_HELP.get(k, k)}" for k in ANALYSIS_KEYS]
    return RULES.replace("{materials}", "\n".join(mats)).replace("{analyses}", "\n".join(ans))


def _compact(d):
    if isinstance(d, dict):
        return {k: _compact(v) for k, v in d.items() if v not in (None, [], {}, "")}
    if isinstance(d, list):
        return [_compact(v) for v in d]
    return d


def messages(lex, text, state=None):
    """The chat for one request; state is the request so far (a follow-up).
    The model gets the sentence with its spoken numbers already in digits
    (오십오 -> 55, sixty -> 60, 4분의 1 -> 1/4): the normaliser is tested on
    every way of writing them, a small model is not."""
    from .textnorm import normalize
    text = normalize(text)
    msgs = [{"role": "system", "content": system_prompt(lex)}]
    for q, a in EXAMPLES:
        msgs.append({"role": "user", "content": q})
        msgs.append({"role": "assistant", "content": json.dumps(_compact(a), ensure_ascii=False)})
    if state:
        msgs.append({"role": "user", "content": "The request so far:\n" + json.dumps(_compact(state), ensure_ascii=False)
                     + "\nThe person now says: " + text + "\nGive the whole request as it is now."})
    else:
        msgs.append({"role": "user", "content": text})
    return msgs


# ---------------------------------------------------------------------- checks
def numbers_in(text):
    """Every number the sentence holds, after the normaliser has turned
    spoken numbers into digits, plus half and quarter."""
    from .textnorm import normalize
    t = normalize(text or "")
    nums = set()
    seen = {}
    for s in (t, text or ""):
        for m in re.finditer(r"(?<![A-Za-z0-9.])-?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?", s):
            try:
                x = float(m.group(0).replace(",", "."))
            except ValueError:
                continue
            nums.add(x)
            if s is t:
                seen[x] = seen.get(x, 0) + 1
        for m in re.finditer(r"(\d+(?:\.\d+)?)(?=\s*%)", s):
            nums.add(float(m.group(1)))
        for m in re.finditer(r"(\d+)\s*/\s*(\d+)", s):
            if float(m.group(2)):
                nums.add(float(m.group(1)) / float(m.group(2)))
        for m in re.finditer(r"(\d+)\s*분의\s*(\d+)", s):
            if float(m.group(1)):
                nums.add(float(m.group(2)) / float(m.group(1)))
    low = t.lower()
    if re.search(r"\bhalf\b|절반|(?:^|\s)반(?:\s|정도|쯤|가량|만|$)", low):
        nums.add(0.5)
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(quarters?|thirds?|fifths?|tenths?)\b", low):
        nums.add(float(m.group(1)) / {"q": 4.0, "t": 3.0, "f": 5.0}.get(m.group(2)[0], 10.0)
                 if not m.group(2).startswith("ten") else float(m.group(1)) / 10.0)
    if re.search(r"\bquarter\b|4분의\s*1", low):
        nums.add(0.25)
    if re.search(r"\bthird\b|3분의\s*1", low):
        nums.add(1.0 / 3.0)
    if re.search(r"\b(?:a\s+)?dozen\b", low):
        nums.add(12.0)
    return _Nums(nums, seen)


class _Nums(set):
    """The numbers of a sentence, and how often each was said (a ratio 5:5
    needs the 5 twice)."""
    def __init__(self, nums, seen):
        super().__init__(nums)
        self.seen = seen


def _close(v, cands, rel=0.011):
    return any(abs(v - c) <= rel * max(1.0, abs(c)) for c in cands)


def derivable(v, nums, kind):
    """How v comes from the sentence's numbers: 'said', a calculation, or
    None (made up)."""
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    v = float(v)
    if _close(v, nums):
        return "said"
    ns = [n for n in nums if n > 0]
    if kind == "pct":
        if _close(v, [100.0 * n for n in ns if n <= 1.0]):
            return "fraction"
        if _close(v, [100.0 - n for n in ns if n < 100.0]):
            return "rest"
        seen = getattr(nums, "seen", {})
        pairs = [(a, b) for a in ns for b in ns if a != b or seen.get(a, 0) >= 2]
        if _close(v, [100.0 * a / (a + b) for a, b in pairs]):
            return "ratio"
        if _close(v, [100.0 * a / b for a, b in pairs if a < b]):
            return "ratio"
    elif kind == "len":
        if _close(v, [n / 1000.0 for n in ns] + [n * 1000.0 for n in ns] + [n * 25.4 for n in ns]):
            return "unit"
    elif kind == "prop":
        if _close(v, [n * f for n in ns for f in (1e3, 1e-3, 100.0, 0.01, 1e6, 1e-6)] + [1.0 / n for n in ns]):
            return "unit"
    elif kind == "count":
        return None
    return None


def _words(text, lex):
    """The words of the sentence without particles and form words, and the
    pairs and triples of them written together ("질화 알루미늄")."""
    toks = [t for t in re.split(r"[\s,;:()\[\]/+·|]+", text) if t]
    clean = []
    for t in toks:
        t = re.sub(r"[.?!~]+$", "", t)
        t = re.sub(r"^\d+(?:\.\d+)?\s*(?:%|vol%|wt%)?", "", t) or t
        c = lex.strip(t) if hasattr(lex, "strip") else t
        c = re.sub(_FORM_WORDS, "", c, flags=re.IGNORECASE) or c
        clean.append(squash(c))
    out = set(clean)
    for n in (2, 3):
        for i in range(len(clean) - n + 1):
            out.add("".join(clean[i:i + n]))
    return out


def _partial_texts(rule_it):
    """Words the rules found to hold a known name inside an unknown one
    ("그래핀옥사이드") or to name nothing they know."""
    out = []
    for s in list(rule_it.get("fillers") or []) + ([rule_it["matrix"]] if rule_it.get("matrix") else []):
        if s.get("how") == "partial" or (s.get("kind") == "unknown" and not s.get("alts")):
            out.append(squash(s.get("text") or ""))
    for u in rule_it.get("unresolved") or []:
        if u.get("kind") == "material" and u.get("text") and not u.get("candidates"):
            out.append(squash(u["text"]))
    return [p for p in out if p]


def _at_boundary(n, word):
    """The name stands as a word of its own inside a word written without
    spaces: a particle or a number (or nothing) before and after it
    ("실리콘에다이아몬드40%"), not more letters ("그래핀옥사이드")."""
    i = word.find(n)
    if i < 0:
        return False
    before, after = word[:i], word[i + len(n):]
    ok_before = not before or before[-1].isdigit() or before.endswith(tuple(L.PARTICLES)) or not has_hangul(before[-1])
    ok_after = not after or after[0].isdigit() or after.startswith(tuple(L.PARTICLES)) or not has_hangul(after[0])
    return ok_before and ok_after


def strong_by_sound(mid, text, lex):
    """A word of the sentence is clearly this material by spelling or sound
    (0.85 or more, and clearly ahead of the next name)."""
    for tok in re.findall(r"[A-Za-z][A-Za-z\-]{2,}|[가-힣]{2,}", text):
        for cand in {tok, lex.strip(tok) if hasattr(lex, "strip") else tok}:
            best = lex.fuzzy_material(cand)
            if best and best[0][0] == mid and best[0][1] >= 0.85 and (len(best) < 2 or best[0][1] - best[1][1] >= 0.05):
                return True
    return False


def material_evidence(mid, text, lex, rule_it):
    """How the sentence names this material: 'rules' (the rules read it),
    'name' (one of its names is a word of the sentence), 'fuzzy' (only by
    spelling or sound), or None."""
    if not mid:
        return None
    strong = {s.get("id") for s in list(rule_it.get("fillers") or []) + [rule_it.get("matrix") or {}] if s.get("id")}
    if mid in strong:
        return "rules"
    words = _words(text, lex)
    partial = _partial_texts(rule_it)
    sq = squash(text)
    names = {squash(al) for al, m, k in lex.mat_alias if m == mid} | {squash(mid)}
    names |= {squash(k) for k, m in lex.mat_short.items() if m == mid}
    names |= {k for k, m in L.SHORT_KO.items() if m == mid}
    names |= {squash(w) for w, ids in L.AMBIGUOUS.items() if mid in ids and len(squash(w)) >= 2}
    if names & words:
        return "name"
    for k, m in lex.mat_short.items():          # Ag, BN, SiC as written
        if m == mid and re.search(r"(?<![A-Za-z])" + re.escape(k) + r"(?![a-z])", text):
            return "name"
    for k, m in L.SHORT_KO.items():             # 은, 금, 동, 철 as a word of their own, not a particle
        if m == mid and re.search(r"(?:^|[\s,(/+])" + k + r"(?:\s|가루|분말|필러|입자|파우더|플레이크|나노|와이어|으로|로|을|이|과|와|도|만|의|에|이랑|하고|$|[,.)])", text):
            return "name"
    for n in names:                              # inside a word written without spaces
        if len(n) >= 3 or (len(n) >= 2 and has_hangul(n)):
            if n in sq and not any(n in p and not _at_boundary(n, p) for p in partial):
                return "name"
    weak = {c for s in list(rule_it.get("fillers") or []) + [rule_it.get("matrix") or {}]
            for c in list(s.get("choices") or []) + [a[0] if isinstance(a, (list, tuple)) else a for a in s.get("alts") or []]}
    for u in rule_it.get("unresolved") or []:
        weak |= {c[0] if isinstance(c, (list, tuple)) else c for c in u.get("candidates") or []}
    if mid in weak:
        return "fuzzy"
    for tok in re.findall(r"[A-Za-z][A-Za-z\-]{2,}|[가-힣]{2,}", text):
        for cand in {tok, lex.strip(tok) if hasattr(lex, "strip") else tok}:
            best = lex.fuzzy_material(cand)
            if best and best[0][0] == mid and best[0][1] >= 0.6:
                return "fuzzy"
    return None


def material_said(mid, text, lex, rule_it):
    return material_evidence(mid, text, lex, rule_it) is not None


_FORM_WORDS = (r"\s*(?:powders?|particles?|fillers?|flakes?|platelets?|beads?|spheres?|grains?|nanoparticles?"
               r"|가루|분말|필러|입자|파우더|플레이크|알갱이|비드|나노입자)\s*$")


def _said_form(mid, text, lex, rule_it):
    """The model's material, or the form of it the sentence names (boron
    nitride said, the anisotropic variant chosen: boron nitride)."""
    if not mid or material_said(mid, text, lex, rule_it):
        return mid
    for a, b in FAMILY.items():
        other = b if mid == a else a if mid == b else None
        if other and material_said(other, text, lex, rule_it):
            return other
    return mid


def resolve_material(name, text, lex):
    """A library id for the model's name, or None."""
    if not isinstance(name, str) or not name.strip():
        return None
    n = name.strip()
    if n in lex.library or (not lex.library and n in L.MATERIALS):
        return n
    # the whole name, never a part of it ("graphene oxide" is not graphene)
    ids = lex.mat.get(squash(n)) or {}
    if len(ids) == 1:
        return next(iter(ids))
    k = re.sub(r"[\s\-]", "", n)
    if k in lex.mat_short:
        return lex.mat_short[k]
    if squash(n) in L.SHORT_KO:
        return L.SHORT_KO[squash(n)]
    # the name without the words for its form ("silver flake", "은가루", "copper powder")
    bare = re.sub(_FORM_WORDS, "", n, flags=re.IGNORECASE).strip()
    for cand in (lex.strip(n) if hasattr(lex, "strip") else n, bare):
        ids = lex.mat.get(squash(cand)) or {}
        if len(ids) == 1:
            return next(iter(ids))
        if squash(cand) in L.SHORT_KO:
            return L.SHORT_KO[squash(cand)]
        k = re.sub(r"[\s\-]", "", cand)
        if k in lex.mat_short:
            return lex.mat_short[k]
    tail = [i for i in (lex.library or L.MATERIALS) if "_" in i and i.split("_", 1)[1] == squash(n)]
    if len(tail) == 1:
        return tail[0]
    best = lex.fuzzy_material(n)
    if best and best[0][1] >= 0.85 and (len(best) < 2 or best[1][1] < best[0][1]):
        return best[0][0]
    return None


def _slot(mid, text, role):
    return {"id": mid, "choices": [], "spans": [], "text": text, "how": "llm", "score": 1.0, "kind": "material",
            "alts": [], "role": role, "content": None, "size_um": None, "shape": None, "size_src": None,
            "shape_src": None, "aspect": None, "length_um": None, "thickness_um": None, "std_um": None, "cv": None,
            "props": None}


def _fmt(v):
    return f"{v:g}"


def build_intent(js, text, lex, rule_it, all_text=None):
    """The intent (parser.py's form) from the model's JSON, every part of it
    checked against the sentence. Returns (intent, report): report lists
    what was dropped and where the rules read otherwise."""
    it = copy.deepcopy(rule_it)
    it["how"] = "llm"
    rep = {"dropped": [], "differs": [], "derived": [], "restored": []}
    if not isinstance(js, dict):
        return rule_it, None
    src = all_text or text
    nums = numbers_in(src)
    lang = rule_it.get("lang", "en")

    def num(v, kind, what):
        if v is None:
            return None
        how = derivable(v, nums, kind)
        if how is None:
            rep["dropped"].append(f"{what} = {v}")
            return None
        return float(v)

    # ---- matrix
    mx = js.get("matrix") if isinstance(js.get("matrix"), dict) else None
    rule_mx = (rule_it.get("matrix") or {}).get("id")
    strong_rule = [f.get("id") for f in rule_it.get("fillers") or [] if f.get("id")]
    if mx and isinstance(mx.get("material"), str) and mx["material"].strip():
        mid = _said_form(resolve_material(mx["material"], src, lex), src, lex, rule_it)
        ev = material_evidence(mid, src, lex, rule_it)
        if mid and ev == "fuzzy" and rule_mx and rule_mx != mid:
            ev = None                  # a name found only by sound loses to the one the rules read
        if mid and rule_mx and rule_mx != mid and any(mid in ids and rule_mx in ids for ids in L.AMBIGUOUS.values()):
            mid = rule_mx              # 실리콘 as a matrix is silicone: the rules read the role
        rmx = rule_it.get("matrix") or {}
        if mid and rule_mx and rule_mx != mid \
                and (rmx.get("how") == "exact" or (rmx.get("how") == "fuzzy" and (rmx.get("score") or 0) >= 0.8)) \
                and rule_mx not in negated_ids(src, lex, {rule_mx}):
            norm = rule_it.get("norm") or src
            seg = squash(" ".join(norm[a:b] for a, b in (rule_it.get("matrix") or {}).get("spans") or []))
            mine = [squash(al) for al, m, k in lex.mat_alias if m == mid and len(squash(al)) >= 2]
            mine += [squash(w) for w, ids in L.AMBIGUOUS.items() if mid in ids and len(squash(w)) >= 2]
            if any(n in seg and n != seg for n in mine) or mid in strong_rule:
                mid = rule_mx          # a name inside the matrix's longer name, or a filler the rules read as one
        if mid and ev:
            s = _slot(mid, mx["material"], "matrix")
            if rule_mx == mid:
                s["how"] = (rule_it.get("matrix") or {}).get("how") or "exact"
            elif rule_mx:
                rep["differs"].append(("matrix", rule_mx, mid))
            s["props"] = _props(mx.get("props"), nums, rep, mid)
            s["amount"] = num(mx.get("amount"), "said", "matrix amount")
            it["matrix"] = s
        else:
            if mid:
                rep["dropped"].append(f"matrix {mx['material']}")
            it["matrix"] = copy.deepcopy(rule_it["matrix"]) if rule_mx else (
                _unknown_slot(mx["material"], "matrix") if not mid else None)
    elif js.get("matrix") is None and not rule_mx:
        it["matrix"] = None
    if mx is not None:                 # "수지 100g": the amount even without the resin's name
        it["matrix_amount"] = num(mx.get("amount"), "said", "matrix amount")

    # ---- fillers
    rule_fl = [f for f in rule_it.get("fillers") or []]
    partial = _partial_texts(rule_it)
    fillers = []
    raw_fl = js.get("fillers") if isinstance(js.get("fillers"), list) else []
    model_ids = [resolve_material(h.get("material"), src, lex) for h in raw_fl if isinstance(h, dict)]
    for h in raw_fl:
        if not isinstance(h, dict) or not isinstance(h.get("material"), str):
            continue
        mid = _said_form(resolve_material(h["material"], src, lex), src, lex, rule_it)
        if mid and (it.get("matrix") or {}).get("id") == mid and len(raw_fl) == 1 and not rule_fl:
            continue
        ev = material_evidence(mid, src, lex, rule_it)
        if mid and mid not in strong_rule:
            norm = rule_it.get("norm") or src
            mine = [squash(al) for al, m, k in lex.mat_alias if m == mid and len(squash(al)) >= 2]
            for r in rule_fl:
                if r.get("id") and r["id"] != mid and r.get("how") == "exact":
                    seg = squash(" ".join(norm[a:b] for a, b in r.get("spans") or []))
                    if any(n in seg and n != seg for n in mine):
                        mid, ev = r["id"], "rules"      # 결정실리카: quartz, not the silica inside it
                        break
        # found only by sound while the rules found by name a filler the model left out,
        # or while a word holds a known name inside an unknown one: not used
        if ev == "fuzzy" and not strong_by_sound(mid, src, lex) and [r for r in strong_rule if r not in model_ids]:
            ev = None
        if not mid or not ev:
            if mid:
                rep["dropped"].append(f"filler {h['material']}")
                continue
            fillers.append(_unknown_slot(h["material"], "filler"))
            continue
        for r in rule_fl:
            if r.get("id") and r["id"] != mid and any(mid in ids and r["id"] in ids for ids in L.AMBIGUOUS.values()):
                mid = r["id"]            # the rules read the word by its role
                ev = "rules"
            elif not r.get("id") and mid in (r.get("choices") or []) and mid not in strong_rule \
                    and squash(lex.strip(r.get("text") or "")) in L.AMBIGUOUS:
                ev = "fuzzy"             # 유리: which glass is asked, the model's first
        s = _slot(mid, h["material"], "filler")
        if ev == "fuzzy" and (not strong_by_sound(mid, src, lex) or any(squash(h["material"]) in p for p in partial)
                              or any(not r.get("id") and mid in (r.get("choices") or [])
                                     and squash(lex.strip(r.get("text") or "")) in L.AMBIGUOUS for r in rule_fl)):
            cands = [mid] + [c for r in rule_fl if not r.get("id") for c in
                             list(r.get("choices") or []) + [a[0] if isinstance(a, (list, tuple)) else a for a in r.get("alts") or []]
                             if isinstance(c, str) and c != mid]
            s["confirm"] = list(dict.fromkeys(cands))[:4]
        same = [f for f in rule_fl if f.get("id") == mid]
        if model_ids.count(mid) > 1:
            same = []                   # one material in two sizes or contents: the rules read only one of them
        if same:
            s["how"] = same[0].get("how") or "exact"
        # content
        pct = h.get("percent")
        basis = h.get("basis") if h.get("basis") in ("vol", "wt", "phr") else None
        if basis and not re.search(_BASIS_WORDS[basis], src, re.IGNORECASE):
            basis = None                 # a basis the sentence does not say is asked
        if isinstance(pct, (int, float)) and not isinstance(pct, bool):
            pct = float(pct)
            if pct <= 1.0 and not re.search(re.escape(_fmt(pct)) + r"\s*(?:%|퍼|프로|percent|vol|wt|v/v|w/w)", src):
                pct = 100.0 * pct
            how = derivable(pct, nums, "pct")
            if how == "said" and basis != "phr" and _said_as_amount(src, pct):
                s["amount"], pct, how = pct, None, None
            rb = _ratio_share(src, pct) if pct is not None else None
            rq = (same[0].get("content") or {}) if len(same) == 1 else {}
            mp = (rule_it.get("matrix_pct") or {}).get("value")
            if mp is not None:
                # the matrix's share only when its number stands right after its name ("에폭시 40%에"),
                # not "에폭시에 30%" (the filler's)
                mx_names = [al for al, m, k in lex.mat_alias if m == (it.get("matrix") or {}).get("id")]
                norm = rule_it.get("norm") or src
                if not any(re.search(re.escape(n) + r"\s*" + re.escape(_fmt(mp)) + r"\s*(?:%|퍼|프로|vol|wt)", norm,
                                     re.IGNORECASE) for n in mx_names if n):
                    mp = None
            if pct is not None and rq.get("value") is not None and (
                    (rq.get("how") == "phr" and _close(pct, [float(x) for x in re.findall(r"\d+(?:\.\d+)?", str(rq.get("raw") or ""))]))
                    or (rq.get("how") == "derived" and mp is not None and _close(pct, [mp]))):
                # "30 phr" or "에폭시 40%에 실리카": the rules' conversion (23.08 wt%, 100 - 40 = 60 %) stands
                pct, how, basis, rb = float(rq["value"]), "rules", rq.get("basis") or basis, None
            if rb is not None:
                pct, how = rb, "ratio"
            rc0 = (same[0].get("content") or {}) if len(same) == 1 else {}
            if how not in (None, "said") and rc0.get("value") is not None and "range" not in rc0 \
                    and rc0.get("how") not in ("bare", "fraction", "derived") and abs(rc0["value"] - pct) > 0.05 \
                    and re.search(r"(?<![0-9.])" + re.escape(_fmt(rc0["value"])) + r"\s*(?:%|퍼|프로|percent|vol\s*%|wt\s*%)", src):
                rep["differs"].append((f"content_rules:{mid}", pct, rc0["value"]))
                pct, how = float(rc0["value"]), "rules"
                basis = basis or rc0.get("basis")
            if pct is None:
                pass
            elif how is not None and how != "rules" and _vague_amount(src, pct):
                rep["dropped"].append(f"{h['material']} {pct:g}% (vague)")
                how = None
            elif how is None:
                rep["dropped"].append(f"{h['material']} {pct:g}%")
            if how is None or pct is None:
                pass
            elif pct >= 100.0 and basis != "phr":
                s["amount"] = pct            # 150 of alumina: an amount, not a percent
            else:
                s["content"] = {"value": pct, "basis": basis, "how": "llm" if how in ("said", "rules") else "llm_derived",
                                "raw": _fmt(pct)}
                if how in ("ratio", "rest"):
                    rep["derived"].append((mid, pct, how))
                rc = (same[0].get("content") or {}) if len(same) == 1 else {}
                if rc.get("value") is not None and abs(rc["value"] - pct) > 0.05 and "range" not in rc:
                    rep["differs"].append((f"content:{mid}", rc["value"], pct))
                if basis is None and rc.get("basis"):
                    s["content"]["basis"] = rc["basis"]
        elif same and (same[0].get("content") or {}).get("range"):
            s["content"] = same[0]["content"]
        if s.get("amount") is None:
            s["amount"] = num(h.get("amount"), "said", f"{h['material']} amount")
        # shape and size: a size the rules read with its unit stands
        if len(same) == 1 and same[0].get("shape"):
            s["shape"], s["shape_src"] = same[0]["shape"], same[0].get("shape_src")
        elif h.get("shape") in ("sphere", "platelet", "fiber", "irregular", "cube"):
            s["shape"], s["shape_src"] = h["shape"], "llm"
        for key, field in (("size_um", "size_um"), ("size_std_um", "std_um"), ("length_um", "length_um"),
                           ("thickness_um", "thickness_um")):
            v = num(h.get(key), "len", f"{h['material']} {key}")
            if v is not None and not _size_said(src, v, key):
                rep["dropped"].append(f"{h['material']} {key} = {v:g} (no unit or size word)")
                v = None
            rv = same[0].get(field) if len(same) == 1 else None
            if rv and (v is None or abs(v - rv) > 1e-6 * max(1.0, rv)):
                if v is not None:
                    rep["differs"].append((f"{field}:{mid}", v, rv))
                v = rv
            if v is not None:
                s[field] = v
        if s["size_um"]:
            s["size_src"] = "llm"
        a = num(h.get("aspect"), "said", f"{h['material']} aspect")
        if len(same) == 1 and same[0].get("aspect"):
            a = same[0]["aspect"]
        if a is not None:
            s["aspect"] = a
        for k in ("size_range", "size_levels"):
            if len(same) == 1 and same[0].get(k):
                s[k] = same[0][k]
        s["props"] = _props(h.get("props"), nums, rep, mid)
        if s.get("confirm"):            # asked, the model's choice first
            s["choices"], s["id"], s["kind"] = s.pop("confirm"), None, "material?"
        fillers.append(s)
    if raw_fl or not rule_fl:
        it["fillers"] = fillers
        gone = {f.get("id") for f in rule_fl} - {f.get("id") for f in fillers}
        for g in gone:
            if g:
                rep["differs"].append(("filler_removed", g, None))
    _amounts(it, rep, src)

    # ---- analyses: each needs a word of the sentence that points to it
    an = [a for a in (js.get("analyses") or []) if a in ANALYSIS_KEYS] if isinstance(js.get("analyses"), list) else []
    low = src.lower()
    kept = [a for a in an if a in (rule_it.get("analyses") or []) or re.search(ANALYSIS_CUES.get(a, a), low)]
    for a in an:
        if a not in kept:
            rep["dropped"].append(f"analysis {a}")
    if kept:
        if set(kept) != set(rule_it.get("analyses") or []) and rule_it.get("analyses"):
            rep["differs"].append(("analyses", sorted(rule_it.get("analyses") or []), sorted(kept)))
        it["analyses"] = list(dict.fromkeys(kept))
        it["analysis_choices"] = []
    elif an:
        it["analyses"] = list(rule_it.get("analyses") or [])

    # ---- task, DOE, calibration, optimisation
    task = js.get("task") if js.get("task") in ("run", "doe", "calibration", "optimization", "structure") else None
    if task:
        it["task"] = None if task == "run" else task
    factors = []
    rule_doe = rule_it.get("doe") or {}
    if rule_doe.get("factors") and (js.get("task") in ("doe", "optimization") or js.get("doe")):
        js = dict(js, doe=[])                        # both see a sweep: the rules read its range and steps
        it["doe"] = copy.deepcopy(rule_doe)
        if it.get("task") not in ("doe", "optimization") and rule_it.get("task") in ("doe", "optimization"):
            it["task"] = rule_it["task"]
    for d in js.get("doe") or [] if isinstance(js.get("doe"), list) else []:
        if not isinstance(d, dict) or d.get("what") not in ("content", "size"):
            continue
        i = d.get("filler") if isinstance(d.get("filler"), int) and 0 <= d["filler"] < max(1, len(it["fillers"])) else 0
        kind = "pct" if d["what"] == "content" else "len"
        lo = num(d.get("from"), kind, "DOE from")
        hi = num(d.get("to"), kind, "DOE to")
        lv = [x for x in (num(v, kind, "DOE level") for v in (d.get("levels") or [])
                          if isinstance(d.get("levels"), list)) if x is not None]
        f = {"filler": i, "what": d["what"], "range": (min(lo, hi), max(lo, hi)) if lo is not None and hi is not None
             else None, "levels": lv or None}
        # a sweep of sizes the model called one of contents: the rules read its unit
        for k, sl in enumerate(it["fillers"]):
            sr = next((r.get("size_range") for r in rule_it.get("fillers") or [] if r.get("id") == sl.get("id")), None)
            if f["what"] == "content" and f["range"] and sr and _close(f["range"][0], [sr[0]]) and _close(f["range"][1], [sr[1]]):
                f["what"], f["filler"] = "size", k
        if f["range"] and abs(f["range"][1] - f["range"][0]) < 1e-9 and not f["levels"]:
            f["range"] = None            # from 50 to 50: not a sweep
        if f["range"] or f["levels"]:
            factors.append(f)
        st = d.get("steps")
        if isinstance(st, int) and not isinstance(st, bool) and 2 <= st <= 50 and _close(float(st), nums):
            it["doe"]["steps"] = st
        sp = num(d.get("step"), kind, "DOE step")
        if sp:
            it["doe"]["step"] = sp
    if factors:
        # the levels of a swept content written as copies of its filler (silica 30, 40, 50, 60): one filler
        for f in factors:
            if f["what"] != "content" or f["filler"] >= len(it["fillers"]):
                continue
            keep = it["fillers"][f["filler"]]
            lv = f["levels"] or []
            lo, hi = f["range"] or ((min(lv), max(lv)) if lv else (None, None))
            dup = [x for x in it["fillers"] if x is not keep and x.get("id") == keep.get("id")
                   and lo is not None and lo - 1e-6 <= ((x.get("content") or {}).get("value") or -1) <= hi + 1e-6]
            if dup:
                it["fillers"] = [x for x in it["fillers"] if not any(x is d for d in dup)]
                f["filler"] = next(i for i, x in enumerate(it["fillers"]) if x is keep)
        it["doe"]["factors"] = factors
        if it.get("task") not in ("doe", "optimization"):
            it["task"] = "doe"
        for f in factors:          # a swept content is not a fixed one
            if f["what"] == "content" and f["filler"] < len(it["fillers"]):
                sl = it["fillers"][f["filler"]]
                if sl.get("content") is None or "range" not in (sl["content"] or {}):
                    lo_hi = f["range"] or (min(f["levels"]), max(f["levels"]))
                    sl["content"] = {"value": 0.5 * (lo_hi[0] + lo_hi[1]), "basis": (sl.get("content") or {}).get("basis"),
                                     "range": lo_hi, "how": "llm", "raw": f"{lo_hi[0]:g}-{lo_hi[1]:g}"}
    elif it.get("task") in ("doe", "optimization") and not rule_it["doe"]["factors"]:
        it["doe"]["factors"] = []
    if not factors and "calibration" not in (js.get("task"), it.get("task"), rule_it.get("task")):
        ids = [f.get("id") for f in it["fillers"]]
        for mid in {i for i in ids if i and ids.count(i) > 1}:
            rf = [x for x in rule_it["doe"]["factors"] if x.get("what") == "content"
                  and x.get("filler", 0) < len(rule_it["fillers"]) and rule_it["fillers"][x.get("filler", 0)].get("id") == mid]
            if not rf:
                continue
            keep = next(f for f in it["fillers"] if f.get("id") == mid)
            it["fillers"] = [f for f in it["fillers"] if f.get("id") != mid or f is keep]
            rs = rule_it["fillers"][rf[0].get("filler", 0)]
            keep["content"] = copy.deepcopy(rs.get("content"))
            k = next(i for i, f in enumerate(it["fillers"]) if f is keep)
            it["doe"]["factors"] = [dict(x, filler=k) for x in rf]
            if it.get("task") not in ("doe", "optimization"):
                it["task"] = "doe"
    # a best value wanted over a range, or measurements to fit: the rules' words stand
    if rule_it.get("task") == "optimization" and it.get("task") in (None, "doe"):
        it["task"] = "optimization"
    elif rule_it.get("task") == "calibration" and it.get("task") is None:
        it["task"] = "calibration"
    meas = []
    for m in js.get("measurements") or [] if isinstance(js.get("measurements"), list) else []:
        if not isinstance(m, dict) or m.get("property") not in MEAS_PROPS:
            continue
        v = num(m.get("value"), "prop", f"measured {m.get('property')}")
        if v is None:
            continue
        c = m.get("percent")
        c = num(c, "pct", "measured at %") if c is not None else None
        meas.append({"property": m["property"], "value": v, "content": c, "raw": _fmt(v),
                     "analysis": MEAS_ANALYSIS.get(m["property"])})
    if rule_it["calibration"]["measurements"]:
        # the rules read the values with their units (S/cm -> S/m) and conditions; a value they
        # left out (said without its unit, "20%에서 1.0, 40%에서 2.2 W/mK") comes from the model
        ruled = copy.deepcopy(rule_it["calibration"]["measurements"])
        said = []
        for r in ruled:
            said += [float(x) for x in re.findall(r"\d+(?:\.\d+)?", str(r.get("raw") or ""))[:1]] + [r["value"]]
        meas = ruled + [m for m in meas if not _close(m["value"], said)]

        def at(m):
            raw = re.findall(r"\d+(?:\.\d+)?", str(m.get("raw") or ""))[:1] or [_fmt(m["value"])]
            i = src.find(raw[0])
            return i if i >= 0 else 10 ** 6
        meas.sort(key=at)
    if meas:
        it["calibration"]["measurements"] = meas
        for m in meas:
            if m["analysis"] and m["analysis"] not in it["analyses"]:
                it["analyses"].append(m["analysis"])
    unk = [u for u in (js.get("unknowns") or []) if u in ("r_int", "r_contact", "filler_k")] \
        if isinstance(js.get("unknowns"), list) else []
    if unk and not rule_it["calibration"]["unknowns"]:
        it["calibration"]["unknowns"] = list(dict.fromkeys(unk))
    if js.get("goal") in ("max", "min"):
        it["optimization"]["goal"] = js["goal"]
    if it.get("task") == "calibration" and it["calibration"]["measurements"]:
        at = [m.get("content") for m in it["calibration"]["measurements"] if m.get("content") is not None]
        ids = [f.get("id") for f in it["fillers"]]
        for mid in {i for i in ids if i and ids.count(i) > 1}:
            copies = [f for f in it["fillers"] if f.get("id") == mid]
            if all(_close((f.get("content") or {}).get("value") or -1, at) for f in copies[1:]):
                keep = copies[0]
                it["fillers"] = [f for f in it["fillers"] if f.get("id") != mid or f is keep]
    # a calibration needs measurements, a study its range: without them the rules' task stands
    if it.get("task") == "calibration" and not it["calibration"]["measurements"]:
        it["task"] = rule_it.get("task")
    if it.get("task") in ("doe", "optimization") and not it["doe"]["factors"] and rule_it.get("task") not in ("doe", "optimization"):
        it["task"] = rule_it.get("task")

    # ---- settings: what the rules read from explicit words stands; the model fills the rest
    st = js.get("settings") if isinstance(js.get("settings"), dict) else {}
    if st.get("quality") in ("fast", "standard", "accurate") and not rule_it.get("quality"):
        it["quality"] = st["quality"]
    if st.get("decide_for_me") is True:
        it["auto"] = True
    if st.get("directions") in ("z", "xyz") and not rule_it.get("directions"):
        it["directions"] = st["directions"]
    if not rule_it.get("orientation"):
        said = [k for k, rx in ORIENT_CUES.items() if re.search(rx, src, re.IGNORECASE)]
        if st.get("orientation") in said:
            it["orientation"] = st["orientation"]
        elif len(said) == 1:
            it["orientation"] = said[0]
    for key, path in (("cores", ("parallel", "threads")), ("parallel_runs", ("parallel", "concurrency"))):
        v = st.get(key)
        if isinstance(v, int) and not isinstance(v, bool) and _close(float(v), nums) \
                and (rule_it.get(path[0]) or {}).get(path[1]) is None:
            it[path[0]][path[1]] = v
    v = st.get("seeds")
    if isinstance(v, int) and not isinstance(v, bool) and _close(float(v), nums) and not rule_it.get("seeds"):
        it["seeds"] = v
    for key, path in (("rve_um", ("rve", "L_um")), ("voxel_um", ("rve", "voxel_um"))):
        v = num(st.get(key), "len", key)
        if v:
            it[path[0]][path[1]] = v
    v = num(st.get("film_um"), "len", "film")
    if v:
        it["film"] = v

    # the rules' questions about names stay only for what the model left open
    named = {f.get("id") for f in it["fillers"]} | {(it.get("matrix") or {}).get("id")}
    it["unresolved"] = [u for u in rule_it.get("unresolved") or []
                        if u.get("kind") not in ("material", "material?", "content")
                        or not any((c[0] if isinstance(c, (list, tuple)) else c) in named
                                   for c in u.get("candidates") or [])]
    it["unresolved"] = [u for u in it["unresolved"] if u.get("kind") != "content"]
    fill_gaps(it, rule_it, js, text, rep, lex)
    _order_by_text(it, rule_it, src, lex)
    # a sweep points at a filler that is there
    n = len(it.get("fillers") or [])
    it["doe"]["factors"] = [f for f in it["doe"].get("factors") or []
                            if f.get("what") == "seed" or 0 <= int(f.get("filler", 0) or 0) < n]
    if it.get("task") in ("doe", "optimization") and not it["doe"]["factors"] and rule_it.get("task") not in ("doe", "optimization"):
        it["task"] = rule_it.get("task")
    # the matrix's share only when its number stands right after its name ("에폭시 40%에"), not "에폭시에 30%"
    mp = (it.get("matrix_pct") or {}).get("value")
    if mp is not None:
        mx_names = [al for al, m, k in lex.mat_alias if m == (it.get("matrix") or {}).get("id")]
        norm = rule_it.get("norm") or src
        if not any(re.search(re.escape(n) + r"\s*" + re.escape(_fmt(mp)) + r"\s*(?:%|퍼|프로|vol|wt)", norm, re.IGNORECASE)
                   for n in mx_names if n):
            it["matrix_pct"] = None
    it["llm_report"] = rep
    it["lang"] = lang
    return it, rep


# words that take something back or correct it: then what the model left out stays out
TAKE_BACK = re.compile(r"말고|아니고|아니라|려다가?|으려다|하기로|아니\s|아니,|빼고|빼줘|빼서|빼면|제외|대신|필요\s*없|안\s*넣|없이|그만|정정|바꿔|바꾸|"
                       r"\binstead\b|\bnot\b|n't|\bskip|\bwithout\b|\bexcept\b|rather than|\bno\b|\bactually\b|"
                       r"make that|\bwait\b|\bremove\b|\bdrop\b|\bonly\b|만\s|만으로|만\b", re.IGNORECASE)
# words that make an amount vague: then a number the rules found is not the amount
VAGUE = re.compile(r"살짝|조금\s*(?:더|넘|많|적)|약간\s*(?:더|넘|많|적)|넘게|이상|이하|미만|초과|보다|"
                   r"more than|less than|a bit|at least|at most|over\b|under\b|above|below", re.IGNORECASE)


NEGATED_AFTER = re.compile(r"^\s*(?:은|는|을|를|이|가|도)?\s*(?:빼고|빼줘|빼서|빼면|말고|제외|없이|아니고|아니라|대신|\S{0,6}려다)")
NEGATED_BEFORE = re.compile(r"(?:\bnot|\bno|\bwithout|\bexcept|\binstead\s+of|\bminus|\bskip|\bdrop)\s+(?:the\s+|any\s+)?$",
                            re.IGNORECASE)


NEAR_TAKE_BACK = re.compile(r"말고|아니고|아니라|려다|빼고|빼줘|제외|대신|없이|\binstead\b|\bnot\b|\bwithout\b|\bexcept\b|"
                            r"rather than|\bskip\b|\bdrop\b|\bremove\b", re.IGNORECASE)


# "X는 (너무 비싸니까) 빼고": the topic of a clause that ends in taking it back
NEGATED_CLAUSE = re.compile(r"^\s*(?:은|는)\s*([^,.;!?]{0,18}?)(?:빼고|빼줘|빼서|빼자|제외|말고|안\s*넣)")


def negated_ids(text, lex, ids):
    """The materials the sentence takes back ("BN은 빼고", "알루미나 말고", "not alumina", "instead of BN")."""
    out = set()
    every = {al for al, m, k in lex.mat_alias if len(al) >= 2} | {k for k in lex.mat_short if len(k) >= 2}

    def clause(after, mid):
        m = NEGATED_CLAUSE.match(after)
        if not m:
            return False
        gap = m.group(1)                 # no other material in between ("알루미나는 넣고 BN은 빼고")
        return not any(al in gap for al in every)
    for mid in ids:
        names = {al for al, m, k in lex.mat_alias if m == mid} | {k for k, m in lex.mat_short.items() if m == mid}
        for al in sorted(names, key=len, reverse=True):
            if len(al) < 2:
                continue
            flags = 0 if has_hangul(al) or al in lex.mat_short else re.IGNORECASE
            for m in re.finditer(re.escape(al), text, flags):
                if NEGATED_AFTER.match(text[m.end():m.end() + 12]) or NEGATED_BEFORE.search(text[max(0, m.start() - 20):m.start()]) \
                        or clause(text[m.end():m.end() + 30], mid):
                    out.add(mid)
        # a Korean name said short ("다이아는 빼고" for 다이아몬드): its first syllables as a word of their own
        for al in names:
            if has_hangul(al) and len(al) >= 4:
                for n in range(2, len(al)):
                    for m in re.finditer(r"(?:^|(?<=[\s,(]))" + re.escape(al[:n]) + r"(?=은|는|을|를|도|\s)", text):
                        if NEGATED_AFTER.match(text[m.end():m.end() + 12]) or clause(text[m.end():m.end() + 30], mid):
                            out.add(mid)
    return out


def fill_gaps(it, rule_it, js, text, rep, lex):
    """What the rules read exactly and the model left out comes back, unless
    the sentence takes something back (then the model's reading stands):
    a filler and its content, an analysis, the content of a filler."""
    took_back = bool(TAKE_BACK.search(text))
    neg = negated_ids(text, lex, {f.get("id") for f in list(it["fillers"]) + list(rule_it.get("fillers") or [])
                                  if f.get("id")})
    if neg and len([f for f in it["fillers"] if f.get("id") not in neg]) >= 1:
        for g in neg:
            rep["differs"].append(("filler_removed", g, None))
        it["fillers"] = [f for f in it["fillers"] if f.get("id") not in neg]
    model_ids = {f.get("id") for f in it["fillers"]}
    # a filler comes back unless the sentence takes it back, or a word that takes back is next to it
    mspans = list((rule_it.get("matrix") or {}).get("spans") or [])
    material_taken_back = bool(NEAR_TAKE_BACK.search(text))
    for f in rule_it.get("fillers") or []:
        if f.get("id") in neg or material_taken_back:
            continue
        overlaps = any(a < d and c < b for a, b in f.get("spans") or [] for c, d in mspans)
        # a word that also names the model's matrix ("실리콘": silicone or silicon) is the matrix's
        word = squash(lex.strip(f.get("text") or "") if hasattr(lex, "strip") else f.get("text") or "")
        mxid = (it.get("matrix") or {}).get("id")
        if mxid in (lex.mat.get(word) or {}) or mxid in (L.AMBIGUOUS.get(word) or []):
            overlaps = True
        if word in L.SHORT_KO and not re.search(r"(?:^|[\s,(/+])" + word + r"(?:\s|가루|분말|필러|입자|파우더|플레이크|나노|와이어|$)", text):
            overlaps = True
        if f.get("id") and f["id"] not in model_ids and f.get("how") in ("exact", "fuzzy") and not overlaps \
                and f["id"] != (it.get("matrix") or {}).get("id"):
            it["fillers"].append(dict(copy.deepcopy(f), restored=True))
            rep["restored"].append(f"filler {f['id']}")
        elif not f.get("id") and not overlaps and not model_ids - {None} \
                and not any(set(x.get("choices") or []) & set(f.get("choices") or []) for x in it["fillers"]):
            cands = set(c for c in f.get("choices") or [] if isinstance(c, str))
            cands |= {a[0] if isinstance(a, (list, tuple)) else a for a in f.get("alts") or []}
            if (it.get("matrix") or {}).get("id") in cands:
                continue
            texts = {squash(x.get("text") or "") for x in it["fillers"]}
            if not (cands & model_ids) and squash(f.get("text") or "") not in texts:
                it["fillers"].append(copy.deepcopy(f))
    back = [f for f in it["fillers"] if f.get("restored")]
    if back:
        ids = [f.get("id") for f in it["fillers"]]
        for r in back:
            rv = (r.get("content") or {}).get("value")
            for f in list(it["fillers"]):
                if f is not r and ids.count(f.get("id")) > 1 and f.get("how") == "llm" \
                        and rv is not None and _close((f.get("content") or {}).get("value") or -1, [rv]):
                    it["fillers"] = [x for x in it["fillers"] if x is not f]
                    ids = [x.get("id") for x in it["fillers"]]
                    break
        it["fillers"] = [f for f in it["fillers"] if not (f.get("kind") == "unknown" and f.get("how") == "llm")]
    if not took_back:
        fuzzy = {n.get("key") for n in rule_it.get("notes") or [] if n.get("type") == "fuzzy_analysis"}
        named = [a for a in rule_it.get("analyses") or [] if a not in fuzzy]
        if named and js.get("analyses") and not set(named) & set(it.get("analyses") or []):
            rep["differs"].append(("analyses_rules", sorted(it.get("analyses") or []), sorted(named)))
            it["analyses"] = list(named)
        ra = [a for a in rule_it.get("analyses") or [] if a not in (it.get("analyses") or []) and a not in fuzzy]
        if ra and js.get("analyses"):
            it["analyses"] = list(it["analyses"]) + ra
            rep["restored"].append("analyses " + ", ".join(ra))
        if it.get("matrix") is None and (rule_it.get("matrix") or {}).get("id"):
            it["matrix"] = copy.deepcopy(rule_it["matrix"])
            rep["restored"].append(f"matrix {rule_it['matrix']['id']}")
    if not VAGUE.search(text):
        for f in it["fillers"]:
            if f.get("content") is not None or not f.get("id"):
                continue
            same = [r for r in rule_it.get("fillers") or [] if r.get("id") == f["id"]]
            rc = (same[0].get("content") or {}) if len(same) == 1 else {}
            if rc.get("value") is not None and rc.get("how") not in ("bare", "fraction", "derived"):
                f["content"] = copy.deepcopy(rc)
                rep["restored"].append(f"content {f['id']} {rc['value']:g}")


_LEN_UNIT = r"(?:um|µm|μm|micron|마이크로|미크론|nm|나노|mm|밀리)"
_SIZE_WORD = r"(?:입경|지름|직경|크기|사이즈|두께|길이|d50|d\s*50|size|diameter|thick|long|length|wide|across)"
_SPREAD_WORD = r"(?:표준\s*편차|편차|std|stdev|sigma|±|\+-|\+/-|분포|spread|cv)"


def _size_said(text, v, key):
    """A size the model gave is in the sentence with a length unit or a size
    word next to it (not an aspect ratio of 10); a spread with a spread word."""
    from .textnorm import normalize
    t = normalize(text or "").lower()
    cands = {v, v * 1000.0, v / 1000.0}
    for m in re.finditer(r"(?<![0-9.])(\d+(?:\.\d+)?)", t):
        x = float(m.group(1))
        if not _close(x, list(cands)):
            continue
        before, after = t[max(0, m.start() - 14):m.start()], t[m.end():m.end() + 12]
        if key == "size_std_um":
            if re.search(_SPREAD_WORD, before + after):
                return True
            continue
        if re.match(r"\s*" + _LEN_UNIT, after) or re.search(_SIZE_WORD + r"[^0-9]{0,6}$", before):
            return True
    return False


def _said_as_amount(text, v):
    """The sentence says this number with a mass or parts (실리콘 200g, 질화붕소 50g) and never with %."""
    from .textnorm import normalize
    t = normalize(text or "")
    mass = [float(m.group(1)) for m in re.finditer(r"(?<![A-Za-z0-9.])(\d+(?:\.\d+)?)\s*(?:g|kg|mg|그램|parts?|부)(?![A-Za-z피])", t)]
    pct = [float(m.group(1)) for m in re.finditer(r"(?<![0-9.])(\d+(?:\.\d+)?)\s*(?:%|퍼|프로|percent)", t)]
    return _close(v, mass) and not _close(v, pct)


RATIO = re.compile(r"비율|비로|ratio|\d\s*(?::|대)\s*\d", re.IGNORECASE)


def _ratio_share(text, pct):
    """"에폭시 2, 질화규소 3 비율로": the filler's share of the two bare numbers
    of a ratio (60 %), when the model gave the filler's own number."""
    from .textnorm import normalize
    t = normalize(text or "")
    if not RATIO.search(t):
        return None
    bare = [float(m.group(1)) for m in re.finditer(
        r"(?<![A-Za-z0-9.])(\d+(?:\.\d+)?)(?!\s*(?:%|퍼|프로|percent|vol|wt|phr|g\b|kg|um|µm|마이크로|미크론|nm|mm|단계|번|개|코어))", t)]
    if len(bare) != 2 or not any(_close(pct, [b]) for b in bare) or sum(bare) <= 0:
        return None
    return round(100.0 * pct / sum(bare), 4)


def _vague_amount(text, pct):
    """True when the number behind this content is said vaguely ("a bit more
    than half", "절반보다 살짝 많이", "40% 이상"): it is not the content."""
    from .textnorm import normalize
    t = normalize(text or "")
    spans = [(m.start(), m.end()) for m in VAGUE.finditer(t)]
    if not spans:
        return False
    src = []
    for m in re.finditer(r"(?<![A-Za-z0-9.])\d+(?:\.\d+)?", t):
        x = float(m.group(0))
        if _close(pct, [x, 100.0 * x]) or (x <= 1.0 and _close(pct, [100.0 * x])):
            src.append((m.start(), m.end()))
    for m in re.finditer(r"\bhalf\b|절반|(?:^|\s)반(?=\s|정도|쯤|가량|$)", t, re.IGNORECASE):
        if _close(pct, [50.0]):
            src.append((m.start(), m.end()))
    return any(a - 15 <= e and b + 15 >= s for a, b in src for s, e in spans)


def _amounts(it, rep, text=""):
    """Amounts instead of percents (100 g of resin and 150 g of alumina, 100
    parts and 150 parts): the weight percent from them, the calculation shown."""
    fl = [f for f in it.get("fillers") or [] if f.get("amount") and f.get("content") is None]
    m = (it.get("matrix") or {}).get("amount") or it.get("matrix_amount")
    if fl and not m:
        # the one mass or number of parts of the sentence that is not a filler's: the resin's
        said = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*(?:g|kg|mg|그램|parts?|부)(?![A-Za-z피])", text or "")]
        rest = [x for x in said if not any(abs(x - (f.get("amount") or -1)) < 1e-9 for f in it["fillers"])]
        if len(rest) == 1:
            m = rest[0]
    if not fl or not m:
        return
    tot = m + sum(f.get("amount") or 0 for f in it["fillers"])
    for f in fl:
        v = round(100.0 * f["amount"] / tot, 4)
        f["content"] = {"value": v, "basis": "wt", "how": "llm_derived", "raw": f"{f['amount']:g}/{tot:g}"}
        rep["derived"].append((f["id"], v, f"amount {f['amount']:g} of {tot:g}"))


def _order_by_text(it, rule_it, text, lex):
    """The fillers in the order the sentence names them (a filler brought
    back by the rules goes where it was said, not at the end)."""
    first = {}
    for r in rule_it.get("fillers") or []:
        if r.get("id") and r.get("spans"):
            first.setdefault(r["id"], min(a for a, b in r["spans"]))
    low = text.lower()

    def pos(f):
        if f.get("id") in first:
            return first[f["id"]]
        names = [al for al, m, k in lex.mat_alias if m == f.get("id")] + [f.get("text") or ""]
        hits = [low.find(n.lower()) for n in names if n and low.find(n.lower()) >= 0]
        return min(hits) if hits else 10 ** 6
    fl = it.get("fillers") or []
    if len({f.get("id") for f in fl}) == len(fl) and len(fl) > 1:
        order = sorted(range(len(fl)), key=lambda i: (pos(fl[i]), i))
        if order != list(range(len(fl))):
            moved = [fl[i] for i in order]
            remap = {old: new for new, old in enumerate(order)}
            for fct in it.get("doe", {}).get("factors") or []:
                if "filler" in fct:
                    fct["filler"] = remap.get(fct["filler"], fct["filler"])
            it["fillers"] = moved


def _unknown_slot(name, role):
    s = _slot(None, name, role)
    s["kind"] = "unknown"
    return s


def _props(p, nums, rep, mid):
    if not isinstance(p, dict):
        return None
    out = {}
    for k in PROP_KEYS:
        v = p.get(k)
        if v is None:
            continue
        if derivable(v, nums, "prop") is None:
            rep["dropped"].append(f"{mid}.{k} = {v}")
            continue
        out[k] = float(v)
    return out or None


def state_of(it, ans=None):
    """The request so far in the model's JSON form, for a follow-up."""
    ans = ans or {}
    mx = it.get("matrix") or {}
    out = {"matrix": {"material": ans.get("matrix") or mx.get("id") or mx.get("text")} if (mx or ans.get("matrix")) else None,
           "fillers": [], "analyses": list(dict.fromkeys(list(it.get("analyses") or []) + list(ans.get("analyses") or []))),
           "task": it.get("task") or "run"}
    for i, f in enumerate(it.get("fillers") or []):
        c = f.get("content") or {}
        pct = ans.get(f"content:{i}") or c.get("value")
        out["fillers"].append({"material": ans.get(f"filler:{i}") or f.get("id") or f.get("text"), "percent": pct,
                               "basis": c.get("basis"), "shape": ans.get(f"shape:{i}") or f.get("shape"),
                               "size_um": ans.get(f"size:{i}") or f.get("size_um"), "props": f.get("props")})
    if it.get("doe", {}).get("factors"):
        out["doe"] = [{"filler": f.get("filler", 0), "what": f["what"],
                       "from": (f.get("range") or [None, None])[0], "to": (f.get("range") or [None, None])[1],
                       "levels": f.get("levels"), "steps": it["doe"].get("steps")} for f in it["doe"]["factors"]
                      if f["what"] in ("content", "size")]
    st = {"quality": ans.get("quality") or it.get("quality"), "directions": it.get("directions"),
          "film_um": it.get("film"), "decide_for_me": bool(it.get("auto") or ans.get("_auto")) or None}
    out["settings"] = st
    return out
