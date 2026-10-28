"""From an intent to a run: the questions still open, the settings chosen
for the problem when the user leaves them open ("알아서"), the MPSim inputs
and the summary shown before anything runs.

What is never guessed (asked even with "알아서"): the matrix, every filler
and its content, the property to compute, the measurements of a
calibration and the range of a DOE. What has a sound default (asked unless
the user leaves it to the program): the content basis (vol%), the particle
shape (sphere) and size (10 µm), the accuracy level and the parallel runs -
for these the program picks what suits the problem and says why.

Material values are never written by the planner: a material is the MPSim
library's entry with its own values; a value the user states ("열전도도
30 W/mK인 알루미나") is the only exception and is marked as theirs.
"""
from __future__ import annotations

import copy
import math
import re

from .lang import AN_NAME, QUALITY_NAME, SHAPE_NAME, SRC, TASK_NAME, name, t
from .numbers import as_content, quantities, to_um
from .textnorm import normalize

DEFAULT_SIZE_UM = 10.0            # MPSim's own default particle size
MATRIX_CHOICES = ["epoxy", "silicone", "polyimide", "bt", "ppe", "lcp", "ptfe", "cyanate_ester"]
FILLER_CHOICES = ["sio2", "al2o3", "aln", "hbn", "mgo", "zno", "cu", "ag", "graphite", "air"]
ANALYSIS_CHOICES = ["thermal", "electrical", "dielectric", "cte", "viscosity", "moisture", "emi", "magnetic"]
FILM_ANALYSES = {"thermomech", "joule"}
PORE_ANALYSES = {"permeability", "filtration", "tortuosity", "acoustics", "radiation", "porosimetry", "pore_network"}
PROP_OF = {"thermal": "k", "electrical": "sigma", "dielectric": "eps_r", "magnetic": "mu_r", "cte": "E",
           "mechtest": "E", "emi": "sigma", "joule": "sigma", "moisture": "D_w", "thermomech": "E"}
DOE_MAX = 64


def _lab(lang, ko, en):
    return ko if lang == "ko" else en


class Planner:
    def __init__(self, lex, host=None):
        self.lex = lex
        self.host = host or {}

    # ------------------------------------------------------------------ helpers
    def mname(self, mid, lang="en"):
        m = self.lex.library.get(mid) or {}
        return m.get("name") or mid

    def props(self, mid):
        return (self.lex.library.get(mid) or {}).get("props") or {}

    def cores(self):
        try:
            return int(self.host.get("cores") or 0) or 8
        except (TypeError, ValueError):
            return 8

    # ------------------------------------------------------------------ main
    def resolve(self, it, ans=None):
        """(questions, decisions, summary, payload or None, problems)."""
        ans = ans or {}
        lang = it["lang"]
        auto = bool(it.get("auto") or ans.get("_auto"))
        Q, notes, problems = [], [], []

        def ask(qid, text, options=None, essential=True, default=None, free=True, multi=False):
            if qid in ans and ans[qid] not in (None, ""):
                return
            Q.append({"id": qid, "text": text, "options": options or [], "essential": essential,
                      "default": default, "free": free, "multi": multi})

        def opt(value, ko, en, rec=False):
            return {"value": value, "label": _lab(lang, ko, en), "recommended": rec}

        # ---- matrix ----
        mx = it.get("matrix")
        matrix_id, matrix_src = ans.get("matrix"), "answer"
        if not matrix_id and mx is not None:
            matrix_id = mx.get("id")
            matrix_src = "fuzzy" if mx.get("how") == "fuzzy" else ("llm" if mx.get("how") == "llm" else "text")
            if not matrix_id and mx.get("choices"):
                ask("matrix", t("q_ambiguous", lang, text=mx["text"]),
                    [opt(c, self.mname(c), self.mname(c)) for c in mx["choices"]])
        if not matrix_id and not any(q["id"] == "matrix" for q in Q):
            ask("matrix", t("q_matrix", lang), [opt(c, self.mname(c), self.mname(c), c == "epoxy") for c in MATRIX_CHOICES])

        # ---- fillers ----
        fl = []
        slots = list(it.get("fillers") or [])
        if ans.get("filler_new"):
            slots.append({"id": ans["filler_new"], "kind": "material", "how": "answer", "content": None, "shape": None,
                          "size_um": None, "choices": [], "text": ans["filler_new"]})
        if not slots:
            ask("filler_new", t("q_filler", lang), [opt(c, self.mname(c), self.mname(c)) for c in FILLER_CHOICES])
        for i, s in enumerate(slots):
            fid = ans.get(f"filler:{i}") or s.get("id")
            label = s.get("text") or "?"
            if not fid:
                if s.get("kind") == "unknown" or not s.get("choices"):
                    cands = [a[0] if isinstance(a, (list, tuple)) else a for a in (s.get("alts") or [])][:3]
                    ask(f"filler:{i}", t("q_unknown", lang, text=label),
                        [opt(c, self.mname(c), self.mname(c)) for c in cands])
                else:
                    ask(f"filler:{i}", t("q_ambiguous", lang, text=label),
                        [opt(c, self.mname(c), self.mname(c)) for c in s["choices"]])
            fname = self.mname(fid) if fid else label
            f = {"id": fid, "name": fname, "src": "answer" if ans.get(f"filler:{i}") else
                 ("fuzzy" if s.get("how") == "fuzzy" else ("llm" if s.get("how") == "llm" else "text")), "slot": s}
            # content
            c = None
            if ans.get(f"content:{i}") not in (None, ""):
                c = self._content_answer(ans[f"content:{i}"])
                if c:
                    c["src"] = "answer"
            elif s.get("content"):
                c = dict(s["content"])
                c["src"] = "rule" if c.get("how") in ("fraction", "bare", "phr") else (
                    "derived" if c.get("how") == "derived" else "text")
                if c.get("how") == "derived":
                    notes.append(_lab(lang, f"{fname} 함량 = {c['raw']}% = {c['value']:g}%",
                                      f"{fname} content = {c['raw']}% = {c['value']:g}%"))
            elif it.get("matrix_pct") and len(slots) == 1:
                mp = it["matrix_pct"]
                c = {"value": 100.0 - mp["value"], "basis": mp.get("basis"), "src": "derived"}
                notes.append(_lab(lang, f"{fname} 함량 = 100 − 매트릭스 {mp['value']:g}% = {100 - mp['value']:g}%",
                                  f"{fname} content = 100 − matrix {mp['value']:g}% = {100 - mp['value']:g}%"))
            if c is not None and not (0.0 < float(c["value"]) < 100.0):
                notes.append(_lab(lang, f"{fname} 함량 {c['value']:g}%는 0과 100 사이가 아니어서 다시 묻습니다",
                                  f"{fname}: a content of {c['value']:g}% is not between 0 and 100 - asked again"))
                c = None
            if c is None:
                ask(f"content:{i}", t("q_content", lang, name=fname))
            f["content"] = c
            # shape
            shape, ssrc = ans.get(f"shape:{i}"), "answer"
            if not shape:
                shape, ssrc = s.get("shape"), "text"
            if fid and self.lex.is_void(fid) and not shape:
                shape, ssrc = "sphere", "default"
            if not shape:
                if auto:
                    shape, ssrc = "sphere", "auto"
                else:
                    ask(f"shape:{i}", t("q_shape", lang, name=fname),
                        [opt(k, name(SHAPE_NAME, k, "ko"), name(SHAPE_NAME, k, "en"), k == "sphere")
                         for k in ("sphere", "platelet", "fiber", "irregular", "cube")], essential=False, default="sphere")
                    shape, ssrc = "sphere", "default"
            f["shape"], f["shape_src"] = shape, ssrc
            # size
            size, zsrc = None, "answer"
            if ans.get(f"size:{i}") not in (None, ""):
                size = self._size_answer(ans[f"size:{i}"])
            if size is None and s.get("size_um"):
                size, zsrc = s["size_um"], "text"
            if size is None:
                if auto or (fid and self.lex.is_void(fid)):
                    size, zsrc = DEFAULT_SIZE_UM, "auto"
                else:
                    ask(f"size:{i}", t("q_size", lang, name=fname),
                        [opt("5", "5 µm", "5 µm"), opt("10", "10 µm", "10 µm", True), opt("20", "20 µm", "20 µm")],
                        essential=False, default="10")
                    size, zsrc = DEFAULT_SIZE_UM, "default"
            f["size_um"], f["size_src"] = size, zsrc
            for k in ("aspect", "length_um", "thickness_um", "std_um", "cv", "size_range", "size_levels"):
                f[k] = s.get(k)
            fl.append(f)

        # ---- basis ----
        basis_q = ans.get("basis")
        need_basis = [f for f in fl if f["content"] and f["content"].get("basis") in (None, "") ]
        if basis_q:
            for f in need_basis:
                f["content"]["basis"] = basis_q
        elif need_basis:
            g = it.get("basis") if it.get("basis") in ("vol", "wt") else None
            if g:
                for f in need_basis:
                    f["content"]["basis"] = g
            elif auto:
                for f in need_basis:
                    f["content"]["basis"] = "vol"
                    f["content"]["basis_src"] = "auto"
            else:
                ask("basis", t("q_basis", lang), [opt("vol", "부피% (vol%)", "by volume (vol%)", True),
                                                  opt("wt", "중량% (wt%)", "by weight (wt%)")], essential=False,
                    default="vol", free=False)
                for f in need_basis:
                    f["content"]["basis"] = "vol"
                    f["content"]["basis_src"] = "default"
        # phr -> wt%
        phr = [f for f in fl if f["content"] and f["content"].get("basis") == "phr"]
        if phr:
            tot = sum(f["content"]["value"] for f in phr)
            for f in phr:
                v = f["content"]["value"]
                f["content"] = dict(f["content"], value=100.0 * v / (100.0 + tot), basis="wt", src="rule")
                notes.append(_lab(lang, f"{f['name']} {v:g} phr → {100 * v / (100 + tot):.2f} wt%",
                                  f"{f['name']} {v:g} phr → {100 * v / (100 + tot):.2f} wt%"))

        # ---- totals ----
        for bs in ("vol", "wt"):
            tot = sum(f["content"]["value"] for f in fl if f.get("content") and (f["content"].get("basis") or "vol") == bs)
            if tot >= 100.0:
                problems.append(_lab(lang, f"필러 함량의 합이 {tot:g} {bs}%로 100% 이상입니다. 함량을 다시 알려 주세요.",
                                     f"The fillers add up to {tot:g} {bs}%, 100 % or more - give the contents again."))
        mp = it.get("matrix_pct")
        if mp and fl and all(f.get("content") for f in fl) and not any(
                (f["content"].get("how") == "derived") for f in fl):
            tot = mp["value"] + sum(f["content"]["value"] for f in fl)
            if abs(tot - 100.0) > 0.5:
                notes.append(_lab(lang, f"매트릭스 {mp['value']:g}% + 필러 = {tot:g}% (100%가 아님): 필러 함량을 말한 대로 쓰고, 나머지는 매트릭스입니다",
                                  f"matrix {mp['value']:g}% + fillers = {tot:g}% (not 100 %): the fillers as said, the rest matrix"))

        # ---- analyses ----
        an = list(it.get("analyses") or [])
        for k in (ans.get("analyses") or []):
            if k not in an:
                an.append(k)
        for j, ch in enumerate(it.get("analysis_choices") or []):
            pick = ans.get(f"analysis_pick:{j}")
            if pick:
                if pick not in an:
                    an.append(pick)
            elif not ch["keys"] == ["thermal", "electrical", "dielectric", "cte"]:
                ask(f"analysis_pick:{j}", t("q_which_cond", lang, text=ch["text"]),
                    [opt(k, name(AN_NAME, k, "ko"), name(AN_NAME, k, "en")) for k in ch["keys"]], free=False)
        if not an and not any(q["id"].startswith("analysis_pick") for q in Q):
            if it.get("task") != "structure":
                ask("analyses", t("q_analysis", lang),
                    [opt(k, name(AN_NAME, k, "ko"), name(AN_NAME, k, "en"), k == "thermal") for k in ANALYSIS_CHOICES],
                    multi=True, free=False)

        # ---- task ----
        task = it.get("task") or "run"
        doe, cal, optz = None, None, None
        if task in ("doe", "optimization"):
            factors = list(it.get("doe", {}).get("factors") or [])
            if ans.get("doe_range"):
                factors = self._factors_from_text(ans["doe_range"], fl, lang) or factors
            if not factors:
                ask("doe_range", t("q_doe_range", lang))
            steps = it["doe"].get("steps") or (int(ans["doe_steps"]) if ans.get("doe_steps") else None)
            step = it["doe"].get("step")
            doe = {"factors": factors, "steps": steps, "step": step}
            if factors and not steps and not step and not any(f.get("levels") for f in factors):
                if auto:
                    doe["steps"], doe["steps_src"] = 5, "auto"
                else:
                    ask("doe_steps", t("q_doe_steps", lang), [opt(str(n), f"{n}", f"{n}", n == 5) for n in (3, 4, 5, 6, 8)],
                        essential=False, default="5")
                    doe["steps"], doe["steps_src"] = 5, "default"
        if task == "optimization":
            goal = ans.get("opt_goal") or it.get("optimization", {}).get("goal")
            if not goal:
                p = name(AN_NAME, an[0], lang) if an else "?"
                ask("opt_goal", t("q_opt_goal", lang, prop=p), [opt("max", "최대", "maximise", True), opt("min", "최소", "minimise")],
                    free=False)
            optz = {"goal": goal, "target": it.get("optimization", {}).get("target"), "analysis": an[0] if an else None}
        if task == "calibration":
            meas = list(it.get("calibration", {}).get("measurements") or [])
            if ans.get("cal_meas"):
                meas = self._measurements_from_text(ans["cal_meas"]) or meas
            if not meas:
                ask("cal_meas", t("q_cal_meas", lang))
            unk = list(it.get("calibration", {}).get("unknowns") or [])
            if ans.get("cal_unknowns"):
                unk = ans["cal_unknowns"] if isinstance(ans["cal_unknowns"], list) else [ans["cal_unknowns"]]
            if not unk:
                if auto:
                    unk = ["r_int"]
                else:
                    ask("cal_unknowns", t("q_cal_unknowns", lang),
                        [opt("r_int", "필러-수지 계면저항 (R_int)", "filler-matrix interface resistance (R_int)", True),
                         opt("filler_k", "필러 열전도도", "the filler's conductivity"),
                         opt("r_contact", "입자 접촉저항 (R_c)", "particle contact resistance (R_c)")],
                        essential=False, default="r_int", multi=True, free=False)
                    unk = ["r_int"]
            cal = {"measurements": meas, "unknowns": unk}

        # ---- film and pores ----
        film_um = it.get("film") or (self._size_answer(ans["film"]) if ans.get("film") else None)
        if set(an) & FILM_ANALYSES and not film_um:
            if auto:
                film_um = 50.0
                notes.append(_lab(lang, "필름 두께 50 µm (가정)", "film thickness 50 µm (assumed)"))
            else:
                ask("film", t("q_film", lang))
        if set(an) & PORE_ANALYSES and not any(f["id"] and self.lex.is_void(f["id"]) for f in fl):
            ask("pores", t("q_pores", lang))
            if ans.get("pores"):
                c = self._content_answer(ans["pores"])
                if c:
                    fl.append({"id": "air", "name": self.mname("air"), "src": "answer", "slot": {},
                               "content": dict(c, basis="vol", src="answer"), "shape": "network", "shape_src": "default",
                               "size_um": 5.0, "size_src": "default"})
                    Q[:] = [q for q in Q if q["id"] != "pores"]

        # ---- accuracy level and parallel ----
        n_cases = self._n_cases(doe) if doe else 1
        quality, qsrc, qwhy = ans.get("quality"), "answer", ""
        if not quality and it.get("quality"):
            quality, qsrc = it["quality"], "text"
        rec_q, rec_why = self.auto_quality(fl, an, matrix_id, n_cases, lang)
        if not quality:
            if auto:
                quality, qsrc, qwhy = rec_q, "auto", rec_why
            else:
                ask("quality", t("q_quality", lang),
                    [opt(k, name(QUALITY_NAME, k, "ko") + (" ← 추천" if k == rec_q else ""),
                         name(QUALITY_NAME, k, "en") + (" ← recommended" if k == rec_q else ""), k == rec_q)
                     for k in ("fast", "standard", "accurate")], essential=False, default=rec_q, free=False)
                quality, qsrc, qwhy = rec_q, "default", rec_why
        par = dict(it.get("parallel") or {})
        if ans.get("parallel"):
            par = self._parallel_answer(ans["parallel"], n_cases)
        rec_par, rec_par_txt = self.auto_parallel(n_cases, lang)
        psrc = "text" if it.get("parallel") else "answer"
        if not par:
            if auto:
                par, psrc = rec_par, "auto"
            else:
                ask("parallel", t("q_parallel", lang),
                    [opt("auto", "자동: " + rec_par_txt, "Automatic: " + rec_par_txt, True),
                     opt("one", "한 번에 1개, 모든 코어", "One at a time on every core")]
                    + ([opt("half", f"동시에 2개, 각 {self.cores() // 2}코어", f"2 at a time, {self.cores() // 2} cores each")]
                       if n_cases > 1 else []), essential=False, default="auto", free=True)
                par, psrc = rec_par, "default"

        # ---- the payload ----
        open_essential = [q for q in Q if q["essential"]]
        payload = None
        summary = self._summary(it, lang, task, matrix_id, matrix_src, fl, an, quality, qsrc, qwhy, par, psrc,
                                rec_par_txt, doe, cal, optz, film_um, notes, n_cases)
        if not open_essential and matrix_id and fl and all(f["id"] and f["content"] for f in fl):
            try:
                payload = self._payload(it, lang, task, matrix_id, fl, an, quality, par, doe, cal, optz, film_um)
                payload["settings_src"] = psrc
            except ValueError as e:
                problems.append(str(e))
            if payload is not None and self.host.get("validate") and not problems:
                err = self.host["validate"](payload["form"])
                if err:
                    problems.append(err)
            if payload is not None and self.host.get("plan") and not problems:
                try:
                    pl = self.host["plan"](payload["form"])
                    at = next((k for k, r in enumerate(summary) if r.get("key") == "quality"), len(summary) - 1)
                    summary.insert(at + 1, self._plan_row(pl, lang))
                    payload["plan"] = {k: pl.get(k) for k in ("N", "h_um", "L_um", "memory_gb", "film", "Nz")}
                except Exception as e:                                     # noqa: BLE001
                    problems.append(str(e))
        return {"questions": Q, "summary": summary, "payload": payload, "problems": problems, "notes": notes,
                "task": task, "auto": auto}

    # ------------------------------------------------------------------ automatic choices
    def phi(self, fl, matrix_id):
        """The volume fraction of all particles (wt% converted with the
        library densities)."""
        vol = 0.0
        wt = [(f, f["content"]["value"]) for f in fl if f.get("content") and f["content"].get("basis") == "wt"]
        for f in fl:
            c = f.get("content")
            if c and c.get("basis") != "wt":
                vol += c["value"] / 100.0
        if wt:
            rho_m = self.props(matrix_id).get("rho") or 1.2
            w_m = 1.0 - sum(v for _, v in wt) / 100.0
            vs = [(v / 100.0) / (self.props(f["id"]).get("rho") or 2.5) for f, v in wt]
            tot = sum(vs) + max(w_m, 0.0) / rho_m
            vol += sum(vs) / tot * (1.0 - vol) if tot > 0 else 0.0
        return vol

    def contrast(self, fl, matrix_id, an):
        pm = self.props(matrix_id)
        best = 1.0
        for k in an:
            key = PROP_OF.get(k)
            if not key or not pm.get(key):
                continue
            for f in fl:
                pp = self.props(f["id"]).get(key) if f.get("id") else None
                if pp:
                    r = float(pp) / float(pm[key])
                    best = max(best, r if r >= 1 else 1.0 / r)
        return best

    def auto_quality(self, fl, an, matrix_id, n_cases, lang):
        """The accuracy level for the problem. MPSim's own study (rve.QUALITY):
        Standard (7 diameters, one realisation) is within 1 % for moderate
        loadings; Accurate (10 diameters) is the level for dense,
        high-contrast fillers. A study of many cases is kept at Standard (or
        Fast beyond 30 cases) so that it finishes."""
        if not fl or not matrix_id or not all(f.get("id") and f.get("content") for f in fl):
            return "standard", ""
        phi = self.phi(fl, matrix_id)
        a = self.contrast(fl, matrix_id, an)
        if n_cases >= 30:
            return "fast", _lab(lang, f"케이스 {n_cases}개 - 빠른 스크리닝", f"{n_cases} cases - a fast screen")
        if n_cases >= 10:
            return "standard", _lab(lang, f"케이스 {n_cases}개 - 표준", f"{n_cases} cases - standard")
        if phi >= 0.45 and a >= 30:
            return "accurate", _lab(lang, f"고충진({100 * phi:.0f} vol%)·고대비(물성비 {a:.0f}) - 결과가 배치에 민감",
                                    f"dense ({100 * phi:.0f} vol%) and high contrast (ratio {a:.0f}) - sensitive to the arrangement")
        return "standard", _lab(lang, f"{100 * phi:.0f} vol%, 물성비 {a:.0f} - 표준으로 1% 이내",
                                f"{100 * phi:.0f} vol%, ratio {a:.0f} - Standard is within 1 %")

    def auto_parallel(self, n_cases, lang):
        c = self.cores()
        if n_cases <= 1:
            return {"threads": 0, "concurrency": 1}, _lab(lang, f"해석 1건이 {c}코어 모두 사용", f"one run on all {c} cores")
        n = max(1, min(n_cases, c // 6 if c >= 12 else 2))
        return ({"threads": 0, "concurrency": n},
                _lab(lang, f"동시에 {n}개, 각 약 {c // n}코어 (메모리는 MPSim이 확인)",
                     f"{n} at a time, about {c // n} cores each (MPSim checks the memory)"))

    # ------------------------------------------------------------------ answers in words
    def _content_answer(self, v):
        if isinstance(v, (int, float)):
            q = {"value": float(v), "unit": None}
        else:
            qs = quantities(normalize(str(v)))
            if not qs:
                return None
            q = qs[0]
        c = as_content(q)
        if not c:
            return None
        return {"value": c[0], "basis": c[1], "how": c[2]}

    def _size_answer(self, v):
        if isinstance(v, (int, float)):
            return float(v)
        qs = quantities(normalize(str(v)))
        if not qs:
            return None
        return to_um(qs[0]["value"], qs[0].get("unit") if qs[0].get("unit") in ("um", "nm", "mm") else "um")

    def _parallel_answer(self, v, n_cases):
        c = self.cores()
        if v == "auto":
            return self.auto_parallel(n_cases, "en")[0]
        if v == "one":
            return {"threads": 0, "concurrency": 1}
        if v == "half":
            return {"threads": max(1, c // 2), "concurrency": 2}
        from .parser import parse
        it = parse(str(v), self.lex)
        return it.get("parallel") or {"threads": 0, "concurrency": 1}

    def _factors_from_text(self, text, fl, lang):
        from .parser import parse
        it = parse(str(text), self.lex)
        out = list(it.get("doe", {}).get("factors") or [])
        if out:
            # the factor's filler as in this conversation
            for f in out:
                if "filler" in f and it["fillers"]:
                    fid = it["fillers"][f["filler"]]["id"]
                    f["filler"] = next((i for i, x in enumerate(fl) if x["id"] == fid), 0)
            return out
        for q in quantities(normalize(str(text))):
            if "hi" in q or q.get("levels"):
                c = as_content(q)
                if c and len(fl) >= 1:
                    hi = as_content(dict(q, value=q["hi"]))[0] if "hi" in q else None
                    return [{"filler": 0, "what": "content", "range": (c[0], hi) if hi is not None else None,
                             "levels": [as_content(dict(q, value=x))[0] for x in q["levels"]] if q.get("levels") else None}]
        return []

    def _measurements_from_text(self, text):
        from .parser import parse
        it = parse(str(text), self.lex)
        return it.get("calibration", {}).get("measurements") or []

    # ------------------------------------------------------------------ DOE size
    def _levels(self, f, steps, step):
        if f.get("levels"):
            return list(f["levels"])
        lo, hi = f["range"]
        if step:
            n = int(round(abs(hi - lo) / step)) + 1
        else:
            n = steps or 5
        n = max(2, n)
        return [lo + (hi - lo) * k / (n - 1) for k in range(n)]

    def _n_cases(self, doe):
        if not doe or not doe.get("factors"):
            return 1
        n = 1
        for f in doe["factors"]:
            if f.get("range") is None and not f.get("levels"):
                continue
            n *= len(self._levels(f, doe.get("steps"), doe.get("step")))
        return n

    # ------------------------------------------------------------------ MPSim inputs
    def _phase(self, f, lang, dist_word=None):
        shape = f["shape"]
        d = float(f["size_um"])
        size = {"d": d, "unit": "um"}
        ms = "sphere"
        if shape == "platelet":
            ms = "spheroid"
            if f.get("thickness_um"):
                size["aspect"] = max(0.01, min(1.0, f["thickness_um"] / d))
            elif f.get("aspect"):
                a = float(f["aspect"])
                size["aspect"] = 1.0 / a if a > 1 else a
            else:
                size["aspect"] = 0.2
        elif shape == "fiber":
            ms = "cylinder"
            if f.get("length_um"):
                size["length"] = float(f["length_um"])
            else:
                size["length"] = d * (float(f["aspect"]) if f.get("aspect") and f["aspect"] > 1 else 10.0)
        elif shape == "irregular":
            ms = "polyhedron"
            size.update(poly="irregular", variants=8)
        elif shape == "cube":
            ms = "cube"
        elif shape == "spheroid":
            ms = "spheroid"
            size["aspect"] = float(f.get("aspect") or 0.5)
        elif shape == "network":
            ms = "network"
        dist = {"type": "mono"}
        if dist_word == "lognormal" or f.get("std_um") or f.get("cv"):
            std = f.get("std_um") or (f.get("cv") or 0.4) * d
            dist = {"type": "lognormal", "std": float(std)}
        ph = {"material_id": f["id"], "name": self.mname(f["id"]), "shape": ms, "size": size, "dist": dist,
              "fraction": {"value": round(float(f["content"]["value"]), 4), "basis": f["content"].get("basis") or "vol"},
              "orientation": {"mode": f.get("orientation") or "iso", "spread_deg": 0}}
        return ph

    def _payload(self, it, lang, task, matrix_id, fl, an, quality, par, doe, cal, optz, film_um):
        dw = (it.get("dist") or {}).get("type")
        phases = [self._phase(f, lang, dw) for f in fl]
        orient = it.get("orientation")
        for p, f in zip(phases, fl):
            if orient and f["shape"] in ("platelet", "fiber", "spheroid"):
                p["orientation"]["mode"] = orient
        dirs = it.get("directions")
        if not dirs:
            dirs = "xyz" if any(p["orientation"]["mode"] != "iso" for p in phases) else "z"
        name_ = " + ".join([self.mname(matrix_id).split(" (")[0]] + [
            f"{self.mname(f['id']).split(' (')[0]} {f['content']['value']:g} {f['content'].get('basis') or 'vol'}%"
            for f in fl])
        rve = {"auto": True, "quality": quality, "seed": int(it.get("seed") or 1)}
        if it.get("seeds"):
            rve["n_seeds"] = int(min(10, max(0, it["seeds"])))
        r = it.get("rve") or {}
        if r.get("L_um") or r.get("voxel_um") or r.get("N"):
            rve["auto"] = False
            if r.get("L_um"):
                rve["L_um"] = float(r["L_um"])
            if r.get("voxel_um"):
                rve["voxel_um"] = float(r["voxel_um"])
            if r.get("N"):
                rve["N"] = int(r["N"])
        if film_um:
            rve.update(film=True, T_um=float(film_um))
        form = {"name": "AI · " + name_, "matrix": {"material_id": matrix_id}, "phases": phases, "rve": rve,
                "analyses": {k: True for k in an}, "options": {"directions": "zxy" if dirs == "xyz" else dirs}}
        out = {"kind": task, "form": form}
        if par:
            out["settings"] = {"concurrency": int(par.get("concurrency") or 1), "threads": int(par.get("threads") or 0)}
        if doe:
            params = []
            for f in doe["factors"]:
                lv = None
                if f["what"] in ("content", "size") and (f.get("range") or f.get("levels")):
                    lv = self._levels(f, doe.get("steps"), doe.get("step"))
                i = f.get("filler", 0)
                if f["what"] == "content":
                    params.append({"path": f"phases.{i}.fraction.value", "label": f"{phases[i]['name']}: content",
                                   "unit": "%", "min": min(lv), "max": max(lv), "steps": len(lv), "scale": "lin"})
                    phases[i]["fraction"]["value"] = round(0.5 * (min(lv) + max(lv)), 4)
                elif f["what"] == "size":
                    params.append({"path": f"phases.{i}.size.d", "label": f"{phases[i]['name']}: diameter",
                                   "unit": "µm", "min": min(lv), "max": max(lv), "steps": len(lv), "scale": "lin"})
                elif f["what"] == "seed":
                    lo, hi = f["range"]
                    params.append({"path": "rve.seed", "label": "Random seed", "unit": "-", "min": lo, "max": hi,
                                   "steps": hi - lo + 1, "scale": "lin"})
            n = 1
            for p in params:
                n *= p["steps"]
            design = "full"
            if n > DOE_MAX:
                design = "lhs"
            out["doe"] = {"name": form["name"] + " · DOE", "design": design, "samples": min(DOE_MAX, 32),
                          "parameters": params, "edge": "fixed", "n_cases": n if design == "full" else min(DOE_MAX, 32)}
        if cal:
            i = 0
            ms = []
            for m in cal["measurements"]:
                st = []
                if m.get("content") is not None:
                    st.append({"path": f"phases.{i}.fraction.value", "value": m["content"]})
                ms.append({"label": (f"{m['content']:g}%" if m.get("content") is not None else "sample"),
                           "property": m["property"], "direction": "z", "value": m["value"], "unc": 5, "set": st})
            paths = []
            for u in cal["unknowns"]:
                paths.append({"r_int": f"phases.{i}.r_int", "r_contact": f"phases.{i}.r_contact",
                              "filler_k": f"phases.{i}.props.k"}.get(u, u))
            out["cal"] = {"name": form["name"] + " · calibration", "measurements": ms, "unknowns": paths}
            for m in cal["measurements"]:
                if m.get("analysis") and m["analysis"] not in form["analyses"]:
                    form["analyses"][m["analysis"]] = True
        if optz:
            out["opt"] = optz
        return out

    # ------------------------------------------------------------------ summary
    def _tag(self, src, lang):
        return name(SRC, src, lang) if src else ""

    def _summary(self, it, lang, task, matrix_id, matrix_src, fl, an, quality, qsrc, qwhy, par, psrc, partxt,
                 doe, cal, optz, film_um, notes, n_cases):
        L = lambda ko, en: _lab(lang, ko, en)                                     # noqa: E731
        rows = [{"k": L("작업", "Task"), "v": name(TASK_NAME, task, lang) + (f" · {n_cases} {L('케이스', 'cases')}" if doe else "")}]
        rows.append({"k": L("매트릭스", "Matrix"), "v": self.mname(matrix_id) if matrix_id else "?",
                     "src": self._tag(matrix_src, lang) if matrix_id else ""})
        for i, f in enumerate(fl):
            c = f.get("content") or {}
            parts = [self.mname(f["id"]) if f.get("id") else (f.get("name") or "?")]
            tags = []
            if f.get("src") in ("fuzzy", "llm"):
                tags.append(self._tag(f["src"], lang) + f" ('{f['slot'].get('text', '')}')")
            parts.append(name(SHAPE_NAME, f.get("shape"), lang) + ("*" if f.get("shape_src") in ("auto", "default") else ""))
            if f.get("shape") != "network":
                parts.append(f"{f.get('size_um'):g} µm" + ("*" if f.get("size_src") in ("auto", "default") else ""))
            if c:
                bs = c.get("basis") or "vol"
                star = "*" if c.get("basis_src") in ("auto", "default") else ""
                if c.get("range"):
                    parts.append(f"{c['range'][0]:g}~{c['range'][1]:g} {bs}% (DOE)" + star)
                elif c.get("levels"):
                    parts.append(", ".join(f"{x:g}" for x in c["levels"]) + f" {bs}% (DOE)" + star)
                else:
                    parts.append(f"{c['value']:g} {bs}%" + star)
                if c.get("how") == "fraction":
                    tags.append(L(f"'{c.get('raw', '')}' → 분율로 읽음", f"'{c.get('raw', '')}' read as a fraction"))
                elif c.get("how") == "bare":
                    tags.append(L(f"'{c.get('raw', '')}' 단위 없음 → %로 읽음", f"'{c.get('raw', '')}' has no unit - read as %"))
            else:
                parts.append("?")
            rows.append({"k": L(f"필러 {i + 1}", f"Filler {i + 1}"), "v": " · ".join(parts), "src": "; ".join(tags)})
        rows.append({"k": L("해석", "Analyses"), "v": ", ".join(name(AN_NAME, k, lang) for k in an) or "?"})
        if film_um:
            rows.append({"k": L("필름", "Film"), "v": f"{film_um:g} µm"})
        rows.append({"k": L("정확도", "Accuracy"), "v": name(QUALITY_NAME, quality, lang) + ("*" if qsrc in ("auto", "default") else ""),
                     "src": qwhy, "key": "quality"})
        if par:
            ptxt = (partxt if psrc in ("auto", "default") else
                    L(f"동시에 {par.get('concurrency', 1)}개 · 코어 {par.get('threads') or '자동'}",
                      f"{par.get('concurrency', 1)} at a time · cores {par.get('threads') or 'auto'}"))
            rows.append({"k": L("병렬", "Parallel"), "v": ptxt + ("*" if psrc in ("auto", "default") else "")})
        dirs = it.get("directions") or "z"
        rows.append({"k": L("방향", "Directions"), "v": {"z": "z", "x": "x", "xyz": "x, y, z"}.get(dirs, dirs)})
        if it.get("seeds"):
            rows.append({"k": L("반복", "Realisations"), "v": str(it["seeds"])})
        if doe:
            for f in doe.get("factors") or []:
                if f.get("range") or f.get("levels"):
                    lv = self._levels(f, doe.get("steps"), doe.get("step"))
                    what = {"content": L("함량", "content"), "size": L("크기", "size"), "seed": "seed"}.get(f["what"], f["what"])
                    nm = fl[f["filler"]]["name"] if "filler" in f and f["filler"] < len(fl) else ""
                    rows.append({"k": "DOE", "v": f"{nm} {what}: " + ", ".join(f"{x:g}" for x in lv)})
        if cal:
            for m in cal["measurements"]:
                rows.append({"k": L("측정값", "Measured"), "v": f"{m['property']} = {m['value']:g}"
                             + (f" @ {m['content']:g}%" if m.get("content") is not None else "")})
            rows.append({"k": L("보정 대상", "Calibrated"), "v": ", ".join(cal["unknowns"])})
        if optz and optz.get("goal"):
            rows.append({"k": L("목표", "Goal"), "v": {"max": L("최대화", "maximise"), "min": L("최소화", "minimise"),
                                                      "target": L(f"목표값 {optz.get('target')}", f"target {optz.get('target')}")}[optz["goal"]]
                         + (f" · {name(AN_NAME, optz['analysis'], lang)}" if optz.get("analysis") else "")})
        for n in notes:
            rows.append({"k": L("참고", "Note"), "v": n})
        for n in it.get("notes") or []:
            if n.get("type") == "fuzzy":
                rows.append({"k": L("오타 보정", "Spelling"), "v": f"'{n['text']}' → {self.mname(n['id'])} ({n['score']:.2f})"})
            elif n.get("type") == "fuzzy_analysis":
                rows.append({"k": L("오타 보정", "Spelling"), "v": f"'{n['text']}' → {name(AN_NAME, n['key'], lang)} ({n['score']:.2f})"})
            elif n.get("type") == "ambiguous_resolved":
                rows.append({"k": L("해석", "Reading"), "v": L(f"'{n['text']}' → {self.mname(n['id'])} (문맥: {'매트릭스' if n['as'] == 'matrix' else '필러'})",
                                                             f"'{n['text']}' → {self.mname(n['id'])} (context: {n['as']})")})
            elif n.get("type") == "unit" and n.get("rule") == "size_um":
                rows.append({"k": L("단위", "Unit"), "v": L(f"'{n['text']}' → µm로 읽음", f"'{n['text']}' read in µm")})
        if any("*" in str(r.get("v", "")) for r in rows):
            rows.append({"k": "*", "v": L("자동 또는 기본값 (말하지 않은 조건)", "automatic or default (not said)")})
        return rows

    def _plan_row(self, pl, lang):
        mem = pl.get("memory_gb") or {}
        m = max(mem.values()) if mem else 0.0
        grid = f"{pl.get('N')}³" if not pl.get("film") else f"{pl.get('N')}×{pl.get('N')}×{pl.get('Nz')}"
        return {"k": _lab(lang, "도메인 계획", "Domain plan"),
                "v": f"RVE {pl.get('L_um', 0):.4g} µm · voxel {pl.get('h_um', 0):.3g} µm · {grid} · "
                     + _lab(lang, f"메모리 약 {m:.2g} GB", f"about {m:.2g} GB")}


_INSTEAD_KO = re.compile(r"(?:말고|대신에?|아니고|아니라|빼고)")
_INSTEAD_EN = re.compile(r"\b(?:instead\s+of|rather\s+than|replace|not)\b", re.IGNORECASE)
_REMOVE = re.compile(r"(?:빼|제외|없이|지워|삭제|without|remove|drop|exclude|except|no\s+more|skip)", re.IGNORECASE)


def _swapped(new):
    """The material ids a follow-up replaces: "알루미나 말고 질화붕소" (the
    one before the word), "boron nitride instead of alumina", "replace
    alumina with BN" (the one after it)."""
    txt = new.get("norm") or ""
    slots = [s for s in (new.get("fillers") or []) + ([new["matrix"]] if new.get("matrix") else []) if s.get("id")]
    out = set()
    for m in _INSTEAD_KO.finditer(txt):
        before = [(max(b for a, b in s["spans"] if b <= m.start()), s) for s in slots
                  if any(b <= m.start() for a, b in s["spans"])]
        if before:
            out.add(max(before, key=lambda x: x[0])[1]["id"])
    for m in _INSTEAD_EN.finditer(txt):
        after = [(min(a for a, b in s["spans"] if a >= m.end()), s) for s in slots
                 if any(a >= m.end() for a, b in s["spans"])]
        if after:
            out.add(min(after, key=lambda x: x[0])[1]["id"])
    return out


def merge(old, new):
    """A follow-up sentence added to the conversation: what it says replaces
    or fills the earlier intent - a material it names instead of another
    takes that one's place and what was said of it; an analysis it says to
    leave out is taken away."""
    it = copy.deepcopy(old)
    gone = _swapped(new)
    if gone:
        new = copy.deepcopy(new)
        olds = {f.get("id"): f for f in it["fillers"]}
        keep_attrs = [olds[g] for g in gone if g in olds]
        it["fillers"] = [f for f in it["fillers"] if f.get("id") not in gone]
        new["fillers"] = [f for f in new["fillers"] if f.get("id") not in gone]
        if (it.get("matrix") or {}).get("id") in gone:
            pm = [f for f in new["fillers"] if f.get("id") and _is_polymer(f["id"])]
            if pm:
                new["matrix"] = pm[0]
                new["fillers"] = [f for f in new["fillers"] if f is not pm[0]]
        elif (new.get("matrix") or {}).get("id") in gone:
            new["matrix"] = None
        for f in new["fillers"]:
            if keep_attrs:
                src = keep_attrs.pop(0)
                for k in ("content", "shape", "size_um", "aspect", "length_um", "thickness_um", "std_um", "cv"):
                    if f.get(k) is None and src.get(k) is not None:
                        f[k] = src[k]
    removed = set()
    txt = new.get("norm") or ""
    for key, a, b in new.get("analysis_spans") or []:
        if _REMOVE.search(txt[max(0, a - 12):b + 12]):
            removed.add(key)
    if removed:
        new = copy.deepcopy(new)
        new["analyses"] = [k for k in new.get("analyses") or [] if k not in removed]
        it["analyses"] = [k for k in it.get("analyses") or [] if k not in removed]
    for k in ("quality", "directions", "orientation", "dist", "seeds", "seed", "film", "basis"):
        if new.get(k) is not None:
            it[k] = new[k]
    if new.get("auto"):
        it["auto"] = True
    if new.get("task"):
        it["task"] = new["task"]
    for k, v in (new.get("parallel") or {}).items():
        it.setdefault("parallel", {})[k] = v
    for k, v in (new.get("rve") or {}).items():
        it.setdefault("rve", {})[k] = v
    if new.get("matrix") is not None and new["matrix"].get("id"):
        it["matrix"] = new["matrix"]
    if new.get("matrix_pct"):
        it["matrix_pct"] = new["matrix_pct"]
    for f in new.get("fillers") or []:
        same = next((x for x in it["fillers"] if f.get("id") and x.get("id") == f["id"]), None)
        if same is None and not f.get("id") and len(it["fillers"]) == 1 and f.get("kind") != "unknown":
            same = it["fillers"][0]
        if same is None:
            it["fillers"].append(f)
        else:
            for k in ("content", "shape", "size_um", "aspect", "length_um", "thickness_um", "std_um", "cv",
                      "size_range", "size_levels"):
                if f.get(k) is not None:
                    same[k] = f[k]
    orphan = new.get("orphan") or {}
    if orphan and len(it["fillers"]) == 1:
        for k, v in orphan.items():
            if v is not None:
                it["fillers"][0][k] = v
    for k in new.get("analyses") or []:
        if k not in it["analyses"]:
            it["analyses"].append(k)
    if new.get("analysis_choices"):
        it["analysis_choices"] = new["analysis_choices"]
    d = new.get("doe") or {}
    if d.get("factors"):
        it["doe"]["factors"] = d["factors"]
    for k in ("steps", "step"):
        if d.get(k):
            it["doe"][k] = d[k]
    c = new.get("calibration") or {}
    if c.get("measurements"):
        it["calibration"]["measurements"] = c["measurements"]
    if c.get("unknowns"):
        it["calibration"]["unknowns"] = c["unknowns"]
    o = new.get("optimization") or {}
    it.setdefault("optimization", {}).update({k: v for k, v in o.items() if v is not None})
    it["notes"] = (it.get("notes") or []) + (new.get("notes") or [])
    return it


_ = (math, re)


_POLY = {"epoxy", "bt", "polyimide", "pbo", "bcb", "su8", "silicone", "ppe", "lcp", "ptfe", "peek", "parylene_c",
         "cyanate_ester", "pps", "fr4"}


def _is_polymer(mid):
    return mid in _POLY
