"""Finding the lexicon's words in a sentence.

A sentence is cut into tokens (Hangul runs, Latin words that may carry
digits and hyphens - Al2O3, h-BN, SU-8 - numbers and signs). Words are
found in three passes, the first that claims a span keeps it:

1. exact: one to four tokens joined and squashed equal an alias; inside a
   Hangul token, a Korean alias of two or more syllables found as a part of
   it ("구형알루미나필러를" holds 구형, 알루미나, 필러), longest first;
2. one-syllable Korean words (구, 은, 휨) only as a whole token, after the
   particles are stripped, and 은/금/철/동 only next to a filler word, a
   number or the element symbol;
3. fuzzy, for what is left: the token with its particles and its role and
   shape words stripped, against every material and analysis alias
   (phonetic.similarity). At 0.8 or above it is taken (and reported); from
   0.65 it is offered as a question with the best candidates.
"""
from __future__ import annotations

import re

from . import lexicon_data as L
from .phonetic import has_hangul, sim, similarity, squash

TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9+]*(?:[\-][A-Za-z0-9+]+)*|[가-힣]+|\d+(?:\.\d+)?|\S")
ACCEPT, OFFER = 0.8, 0.65


def _name_parts(name):
    """Aliases from an MPSim library name: 'Al₂O₃ (alumina)' -> Al2O3, alumina."""
    import unicodedata
    n = unicodedata.normalize("NFKC", name)
    out = [n]
    m = re.match(r"\s*([^()]+?)\s*\(([^)]*)\)", n)
    if m:
        out += [m.group(1), m.group(2)]
        out += [p.strip() for p in re.split(r"[,/;]", m.group(2)) if p.strip()]
    return [o for o in out if len(squash(o)) >= 2]


class Lexicon:
    def __init__(self, library=None):
        """library: the MPSim materials ([{id, name, group, void}]), whose
        names become aliases too; without it the built-in names only."""
        self.library = {m["id"]: m for m in (library or [])}
        self.mat = {}          # squashed alias -> {id: kind}
        self.mat_short = {}    # short element symbols, case as written (In, W, Ag, BN) -> id
        self.mat_alias = []    # (alias, id, kind) for fuzzy matching
        for mid, a in L.MATERIALS.items():
            if self.library and mid not in self.library:
                continue
            for kind in ("ko", "en", "formula"):
                for al in a.get(kind, []):
                    self._add_mat(al, mid, kind)
            self._add_mat(mid, mid, "formula")
        for mid, m in self.library.items():
            for al in _name_parts(m.get("name", "")):
                self._add_mat(al, mid, "lib")
            self._add_mat(mid, mid, "formula")
        self.terms = {}
        for table, data in (("analysis", L.ANALYSES), ("shape", L.SHAPES), ("task", L.TASKS),
                            ("quality", L.QUALITY), ("direction", L.DIRECTIONS), ("orientation", L.ORIENTATION),
                            ("dist", L.DISTRIBUTION)):
            for key, a in data.items():
                for al in a.get("ko", []) + a.get("en", []):
                    self.terms.setdefault(squash(al), []).append((table, key, al))
        for al in L.ROLE_FILLER["ko"] + L.ROLE_FILLER["en"]:
            self.terms.setdefault(squash(al), []).append(("role", "filler", al))
        for al in L.ROLE_MATRIX["ko"] + L.ROLE_MATRIX["en"]:
            self.terms.setdefault(squash(al), []).append(("role", "matrix", al))
        for al in L.AUTO["ko"] + L.AUTO["en"]:
            self.terms.setdefault(squash(al), []).append(("auto", "auto", al))
        for al, keys in L.AMBIGUOUS_ANALYSES.items():
            self.terms.setdefault(squash(al), []).append(("analysis?", tuple(keys), al))
        for al, keys in L.ANALYSIS_GROUPS.items():
            self.terms.setdefault(squash(al), []).append(("analysis_group", tuple(keys), al))
        for al in L.ALL_PROPS:
            self.terms.setdefault(squash(al), []).append(("analysis_all", "all", al))
        for key, a in L.CAL_UNKNOWNS.items():
            for al in a:
                self.terms.setdefault(squash(al), []).append(("unknown_param", key, al))
        self.stop = {squash(w) for w in L.STOP["ko"] + L.STOP["en"] + L.STOP_KO_EXTRA}
        self.particles = sorted(L.PARTICLES, key=len, reverse=True)
        self.affix = sorted({squash(w) for w in L.ROLE_FILLER["ko"] + L.ROLE_MATRIX["ko"] + L.MATRIX_FORM["ko"]
                             + [w for a in L.SHAPES.values() for w in a["ko"]]}, key=len, reverse=True)
        # Korean aliases (2+ syllables) found inside longer Hangul tokens
        self.ko_sub = sorted({(squash(al), "mat") for al in self.mat if has_hangul(al) and len(al) >= 2}
                             | {(k, "term") for k in self.terms if has_hangul(k) and len(k) >= 2},
                             key=lambda x: -len(x[0]))

    def _add_mat(self, alias, mid, kind):
        s = squash(alias)
        if not s or (kind == "formula" and alias == mid and len(s) <= 3):
            return                     # ids such as "in", "w" are not words to look for
        if len(s) <= 3 and not has_hangul(s):
            # In, W, Ag, BN: as written only - "in", "w/mK" are not metals
            k = re.sub(r"[\s\-]", "", alias)
            if kind == "lib" and k in self.mat_short:
                return                 # a library name never overrides the lexicon's own alias
            self.mat_short[k] = mid
            return
        if kind == "lib" and any(v != "lib" for v in self.mat.get(s, {}).values()):
            return
        self.mat.setdefault(s, {})[mid] = kind
        self.mat_alias.append((alias, mid, kind))

    def group(self, mid):
        m = self.library.get(mid) or {}
        return m.get("group") or _GROUP_GUESS.get(mid, "inorganic")

    def is_void(self, mid):
        m = self.library.get(mid) or {}
        return bool(m.get("void")) or mid in ("air", "vacuum")

    # ------------------------------------------------------------------
    def strip_particles(self, word):
        w = word
        for p in self.particles:
            if len(w) > len(p) + 1 and w.endswith(p):
                return w[:-len(p)]
        return w

    def strip(self, word):
        """A Hangul word without its particles and role/shape affixes."""
        w = word
        changed = True
        while changed and has_hangul(w):
            changed = False
            for p in self.particles:
                if len(w) > len(p) + 1 and w.endswith(p):
                    w, changed = w[:-len(p)], True
                    break
            for a in self.affix:
                if len(w) > len(a) + 1 and w.endswith(a):
                    w, changed = w[:-len(a)], True
                    break
                if len(w) > len(a) + 1 and w.startswith(a):
                    w, changed = w[len(a):], True
                    break
        return w

    def scan(self, text):
        """Mentions in the text: [{kind, key, start, end, text, score, how,
        alts}] - kind 'material' (key = material id, or a tuple when
        ambiguous), 'analysis', 'shape', 'task', ... , 'unknown' for words
        that look like a material but match none."""
        toks = [(m.group(), m.start(), m.end()) for m in TOKEN.finditer(text)]
        used = [False] * len(toks)
        out = []

        def emit(kind, key, a, b, how, score=1.0, alts=None, alias=None):
            out.append({"kind": kind, "key": key, "start": a, "end": b, "text": text[a:b], "how": how,
                        "score": score, "alts": alts or [], "alias": alias})

        def lookup(s, orig=None):
            hits = []
            o = re.sub(r"[\s\-]", "", orig or "")
            if o in self.mat_short and s not in self.mat:
                hits.append(("material", self.mat_short[o]))
            if s in self.mat:
                ids = self.mat[s]
                hits.append(("material", tuple(sorted(ids)) if len(ids) > 1 else next(iter(ids))))
            for table, key, _al in self.terms.get(s, []):
                hits.append((table, key))
            if s in {squash(k) for k in L.AMBIGUOUS} and not any(h[0] == "material" for h in hits):
                amb = next(v for k, v in L.AMBIGUOUS.items() if squash(k) == s)
                hits.append(("material", tuple(amb) if len(amb) > 1 else amb[0]))
            return list(dict.fromkeys(hits))

        # pass 1a: n-grams of whole tokens (longest first), with the particles of the last stripped
        for n in (4, 3, 2, 1):
            if n == 1:
                # pass 0: two or three Latin words as one name with a typo ("aluminium nitrde",
                # "boron nitrid"): taken when they match a name of several words better than 0.85
                multi = [(al, mid) for al, mid, kind in self.mat_alias if " " in al.strip() and not has_hangul(al)]
                for w in (3, 2):
                    for i in range(len(toks) - w + 1):
                        parts = [x[0] for x in toks[i:i + w]]
                        if any(used[i:i + w]) or not all(re.fullmatch(r"[A-Za-z][A-Za-z\-]*", p) for p in parts):
                            continue
                        joined = " ".join(parts)
                        if squash(joined) in self.mat:
                            continue
                        best = max(((similarity(joined, al), mid, al) for al, mid in multi), default=(0, None, None))
                        if best[0] >= 0.85:
                            emit("material", best[1], toks[i][1], toks[i + w - 1][2], "fuzzy", best[0], alts=[(best[1], best[0], best[2])])
                            for k in range(i, i + w):
                                used[k] = True
            for i in range(len(toks) - n + 1):
                if any(used[i:i + n]):
                    continue
                parts = [t[0] for t in toks[i:i + n]]
                if not all(re.match(r"[A-Za-z가-힣]", p) or (0 < k < n - 1 and p in ("-", "'", "\u2019"))
                           or (n > 1 and re.fullmatch(r"\d+", p)) or (n == 1 and re.fullmatch(r"\d{4,}", p))
                           for k, p in enumerate(parts)):
                    continue
                cands = [squash("".join(parts))]
                if has_hangul(parts[-1]):
                    last = parts[-1]
                    for p in self.particles:
                        if len(last) > len(p) and last.endswith(p):
                            cands.append(squash("".join(parts[:-1]) + last[:-len(p)]))
                for c in cands:
                    if n == 1 and has_hangul(c) and len(c) == 1:
                        if c in L.SHORT_KO:
                            if not self._short_ok(toks, i):
                                continue
                        elif not self.terms.get(c):
                            continue
                    hits = lookup(c, "".join(parts) if c == cands[0] else None)
                    # one Latin letter is a metal only next to a number or a filler word ("W 30%", not "W/mK")
                    if n == 1 and len(parts[0]) == 1 and hits and not self._short_ok(toks, i):
                        hits = [h for h in hits if h[0] != "material"]
                    # "In a 10 um film", "In the ...", "At 50 %": a preposition, not indium or astatine
                    if n == 1 and parts[0] in ("In", "At", "As", "Be", "No", "So", "He", "Is", "On") and hits \
                            and i + 1 < len(toks) and toks[i + 1][0].lower() in ("a", "an", "the", "this", "that", "my",
                                                                                   "our", "each", "every", "it", "we", "i"):
                        hits = [h for h in hits if h[0] != "material"]
                    # a Latin word with a filler or resin word attached names a material ("XYZ필러")
                    if hits and n == 1 and not has_hangul(parts[0]) and i + 1 < len(toks)                             and toks[i + 1][1] == toks[i][2] and self._role_word(toks[i + 1][0])                             and not any(h[0] == "material" for h in hits):
                        hits = []
                    if hits:
                        a, b = toks[i][1], toks[i + n - 1][2]
                        if cands.index(c) > 0:
                            b -= len(parts[-1]) - len(parts[-1].rstrip()) if False else 0
                        for kind, key in hits:
                            emit(kind, key, a, b, "exact")
                        for k in range(i, i + n):
                            used[k] = True
                        break
        # pass 1b: Korean aliases inside longer Hangul tokens. When a known
        # material name is only part of an unknown word ("그래핀옥사이드" holds
        # 그래핀), the word is offered as a question, not taken as that material.
        for i, (t, a0, b0) in enumerate(toks):
            if used[i] or not has_hangul(t) or len(t) < 3:
                continue
            taken = [False] * len(t)
            local = []
            for al, typ in self.ko_sub:
                pos = t.find(al)
                while pos >= 0:
                    if not any(taken[pos:pos + len(al)]):
                        for kind, key in lookup(al):
                            local.append((kind, key, a0 + pos, a0 + pos + len(al)))
                        for k in range(pos, pos + len(al)):
                            taken[k] = True
                    pos = t.find(al, pos + 1)
            if not local:
                continue
            pieces = "".join(ch if not tk else " " for ch, tk in zip(t, taken)).split()

            def known(r):
                c = self.strip(r)
                return (not c or r in self.particles or c in self.particles or squash(c) in self.stop
                        or squash(c) in self.terms or squash(r) in self.terms or squash(c) in self.affix)
            rest = [r for r in pieces if not known(r)]
            dropped = False
            for kind, key, a, b in local:
                if kind == "material" and rest:
                    if b - a <= 2:
                        dropped = True     # a short name inside an unknown word: left to the spelling pass
                        continue
                    ids = key if isinstance(key, tuple) else (key,)
                    emit("material?", ids, a0, b0, "partial", 0.7, alts=[(x, 0.7, t) for x in ids])
                else:
                    emit(kind, key, a, b, "exact")
            if dropped:
                continue
            # a word that held no material (애폭시레진: only 레진) is left to the fuzzy pass
            used[i] = any(k == "material" for k, *_ in local) or not rest
        # pass 2: fuzzy on what is left
        for i, (t, a, b) in enumerate(toks):
            if used[i] or not re.match(r"[A-Za-z가-힣]", t):
                continue
            core = self.strip(t) if has_hangul(t) else t
            sc = squash(core)
            attached = i + 1 < len(toks) and toks[i + 1][1] == b and self._role_word(toks[i + 1][0])
            if not sc or sc in self.stop or (sc in self.terms and not attached) or core in self.particles:
                continue
            if (has_hangul(sc) and len(sc) < 2) or (not has_hangul(sc) and len(sc) < 4):
                if not has_hangul(sc) and (_looks_formula(t) or attached):
                    emit("unknown", None, a, b, "formula", 0.0)
                continue
            best = self.fuzzy_material(core)
            if has_hangul(t) and core != t:
                full = self.fuzzy_material(self.strip_particles(t))
                if full and (not best or full[0][1] >= best[0][1]):
                    best = full
            ana = self.fuzzy_term(core, "analysis")
            short = (has_hangul(sc) and len(sc) <= 2) or (not has_hangul(sc) and len(sc) <= 5)
            if short and best and best[0][1] < 0.9:
                best = [b for b in best if b[1] >= 0.9]
            if short and ana and ana[0][1] < 0.9:
                ana = []
            if ana and ana[0][1] >= ACCEPT and (not best or ana[0][1] > best[0][1]):
                emit("analysis", ana[0][0], a, b, "fuzzy", ana[0][1], alts=ana[:3])
                continue
            # a tie of sounds is broken by the spelling ("sillicone": silicone, not silicon)
            if best and len(best) > 1 and best[0][1] - best[1][1] < 0.04:
                raw = sorted(best[:2], key=lambda x: -sim(squash(core), squash(x[2])))
                r0, r1 = (sim(squash(core), squash(x[2])) for x in raw)
                if r0 - r1 >= 0.08:
                    best = [raw[0]] + [x for x in best if x is not raw[0]]
                    best[0] = (best[0][0], max(best[0][1], best[1][1] + 0.04), best[0][2])
            if best and best[0][1] >= ACCEPT and (len(best) < 2 or best[0][1] - best[1][1] >= 0.04
                                                  or best[0][0] == best[1][0]):
                emit("material", best[0][0], a, b, "fuzzy", best[0][1], alts=best[:3])
            elif best and best[0][1] >= OFFER:
                emit("material?", tuple(dict.fromkeys(x[0] for x in best[:3])), a, b, "fuzzy", best[0][1],
                     alts=best[:3])
            elif self._material_like(toks, i):
                emit("unknown", None, a, b, "context", 0.0, alts=best[:3] if best else [])
        out.sort(key=lambda m: m["start"])
        return out

    def _role_word(self, t):
        t = squash(t)
        return any(t.startswith(squash(w)) for w in L.ROLE_FILLER["ko"] + L.ROLE_MATRIX["ko"])

    def _short_ok(self, toks, i):
        """은/금/철/동 as a material: next to a filler word, a number, a shape
        word or the element symbol in brackets."""
        # written onto a Latin word or a number ("topcut은", "3um은"): a particle, not silver
        if i > 0 and toks[i - 1][2] == toks[i][1] and re.match(r"[A-Za-z0-9%]", toks[i - 1][0][-1:]):
            return False
        near = [toks[k][0] for k in range(max(0, i - 3), min(len(toks), i + 3)) if k != i]
        words = {squash(w) for w in L.ROLE_FILLER["ko"] + L.ROLE_FILLER["en"]
                 + [x for a in L.SHAPES.values() for x in a["ko"] + a["en"]]}
        return any(squash(w) in words or re.match(r"\d", w) or w in ("Ag", "Au", "Fe", "Cu")
                   or squash(w) in {squash(x) for x in L.ROLE_FILLER["en"]} for w in near)             and not (i + 1 < len(toks) and toks[i + 1][0] == "/")

    def _material_like(self, toks, i):
        """A word next to a filler or resin word ('XX 필러', 'XX resin') that
        names nothing known."""
        near = [squash(toks[k][0]) for k in (i - 1, i + 1) if 0 <= k < len(toks)]
        t = toks[i][0]
        if has_hangul(t) and self.strip(t).endswith(L.NOT_MATERIAL_KO):
            return False                 # 예전해석에서, 실험조건: words of the work, not a material
        if has_hangul(t) and (self.strip_particles(t) in L.SIZE_CLASS_KO or self.strip(t) in L.SIZE_CLASS_KO
                              or self.strip(t) + "입자" in L.SIZE_CLASS_KO):
            return False                 # 대입자, 소입자, 미세입자: a class of sizes, not a material
        if t.lower() in L.NOT_MATERIAL_EN:
            return False
        own = has_hangul(t) and any(t.endswith(w) and len(t) > len(w) for w in L.ROLE_FILLER["ko"] + L.ROLE_MATRIX["ko"])
        roles = {squash(w) for w in L.ROLE_FILLER["ko"] + L.ROLE_FILLER["en"] + L.ROLE_MATRIX["ko"] + L.ROLE_MATRIX["en"]}
        return own or any(n in roles for n in near) or _looks_formula(t)

    def fuzzy_material(self, word):
        """[(id, score, alias)] best first, one entry per material."""
        cache = self.__dict__.setdefault("_fm", {})
        if word in cache:
            return cache[word]
        best = {}
        for alias, mid, kind in self.mat_alias:
            if kind == "formula":
                continue
            s = similarity(word, alias)
            if s > best.get(mid, (0, ""))[0]:
                best[mid] = (s, alias)
        out = sorted(((mid, s, al) for mid, (s, al) in best.items()), key=lambda x: -x[1])[:5]
        cache[word] = out
        return out

    def fuzzy_term(self, word, table):
        cache = self.__dict__.setdefault("_ft", {})
        if (word, table) in cache:
            return cache[(word, table)]
        best = {}
        for s_alias, lst in self.terms.items():
            for tb, key, al in lst:
                if tb != table or isinstance(key, tuple):
                    continue
                s = similarity(word, al)
                if s > best.get(key, (0, ""))[0]:
                    best[key] = (s, al)
        out = sorted(((k, s, al) for k, (s, al) in best.items()), key=lambda x: -x[1])[:5]
        cache[(word, table)] = out
        return out


def _looks_formula(t):
    return bool(re.fullmatch(r"(?:[A-Z][a-z]?\d*){2,}", t))


_GROUP_GUESS = {"epoxy": "polymer", "bt": "polymer", "polyimide": "polymer", "pbo": "polymer", "bcb": "polymer",
                "su8": "polymer", "silicone": "polymer", "ppe": "polymer", "lcp": "polymer", "ptfe": "polymer",
                "peek": "polymer", "parylene_c": "polymer", "cyanate_ester": "polymer", "pps": "polymer",
                "fr4": "polymer", "air": "gas", "vacuum": "gas"}
