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

from . import calcheck as CC
from . import design as DZ
from . import matprops as MP
from .lang import AN_NAME, QUALITY_NAME, SHAPE_NAME, SRC, TASK_NAME, name, t
from .numbers import as_content, quantities, to_um
from .reader import COMPARE, MIXED
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
PROP_UNIT = {"k": "W/m·K", "sigma": "S/m", "E": "GPa", "alpha": "ppm/K", "rho": "g/cm³", "cp": "J/kg·K"}


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
        # a design finds the content and the sizes: they are not asked
        dz = it.get("design") if it.get("task") == "design" else None
        if dz and ans.get("design_target"):
            more = DZ.read(str(ans["design_target"]))
            if more.get("targets"):
                dz = dict(dz, targets=more["targets"])
        find = set((dz or {}).get("find") or [])

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

        mprops = (mx or {}).get("props") if matrix_id and (mx or {}).get("id") == matrix_id else None
        if matrix_id:
            mprops, how = self._said_values(matrix_id, mprops, it)
            it["_matrix_props"] = mprops
            if mprops:
                notes.append(self._values_note(self.mname(matrix_id), matrix_id, mprops, how, lang))
        rep_ = it.get("llm_report") or {}
        for what, a, b in rep_.get("differs") or []:
            if what == "matrix":
                notes.append(_lab(lang, f"AI 판단: 매트릭스 {self.mname(b)} (규칙으로는 {self.mname(a)})",
                                  f"AI reading: matrix {self.mname(b)} (the rules read {self.mname(a)})"))
            elif what.startswith("content:"):
                m = what.split(":", 1)[1]
                notes.append(_lab(lang, f"AI 판단: {self.mname(m)} {b:g}% (규칙으로는 {a:g}%)",
                                  f"AI reading: {self.mname(m)} {b:g}% (the rules read {a:g}%)"))
            elif what.startswith("content_rules:"):
                m = what.split(":", 1)[1]
                notes.append(_lab(lang, f"{self.mname(m)} {b:g}%: 문장에 % 단위로 쓴 값 (AI 계산 {a:g}%는 쓰지 않음)",
                                  f"{self.mname(m)} {b:g}%: the value written with % (the AI's calculation {a:g}% not used)"))
            elif what == "analyses_rules":
                notes.append(_lab(lang, "문장에 쓴 해석 이름을 따름: " + ", ".join(name(AN_NAME, k, "ko") for k in b)
                                  + " (AI는 " + ", ".join(name(AN_NAME, k, "ko") for k in a) + ")",
                                  "the analyses named in the sentence: " + ", ".join(name(AN_NAME, k, "en") for k in b)
                                  + " (the AI read " + ", ".join(name(AN_NAME, k, "en") for k in a) + ")"))
            elif what == "filler_swapped":
                notes.append(_lab(lang, f"AI가 '{a}'(으)로 읽었으나 문장의 재료는 {self.mname(b)}: {self.mname(b)}로 씀",
                                  f"the AI read '{a}'; the sentence names {self.mname(b)}, which is used"))
            elif what == "filler_removed":
                notes.append(_lab(lang, f"AI 판단: {self.mname(a)}은(는) 넣지 않음 (빼거나 바꾼다고 읽음)",
                                  f"AI reading: no {self.mname(a)} (read as taken back or replaced)"))
            elif what == "analyses":
                notes.append(_lab(lang, "AI 판단: 해석 " + ", ".join(name(AN_NAME, k, "ko") for k in b)
                                  + " (규칙으로는 " + (", ".join(name(AN_NAME, k, "ko") for k in a) or "-") + ")",
                                  "AI reading: analyses " + ", ".join(name(AN_NAME, k, "en") for k in b)
                                  + " (the rules read " + (", ".join(name(AN_NAME, k, "en") for k in a) or "-") + ")"))
        for d in rep_.get("dropped") or []:
            notes.append(_lab(lang, f"문장에 없는 값이라 쓰지 않음: {d}", f"not in the sentence, not used: {d}"))

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
                    "derived" if c.get("how") == "derived" else "llm" if c.get("how") == "llm_derived" else "text")
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
            if c is None and not (dz and "content" in find):
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
            if size is None and dz and ("size" in find or ("ratio" in find and len({x.get("id") for x in slots}) == 1)):
                zsrc = "design"
            elif size is None:
                if auto or (fid and self.lex.is_void(fid)):
                    size, zsrc = DEFAULT_SIZE_UM, "auto"
                else:
                    ask(f"size:{i}", t("q_size", lang, name=fname),
                        [opt("5", "5 µm", "5 µm"), opt("10", "10 µm", "10 µm", True), opt("20", "20 µm", "20 µm")],
                        essential=False, default="10")
                    size, zsrc = DEFAULT_SIZE_UM, "default"
            f["size_um"], f["size_src"] = size, zsrc
            for k in ("aspect", "length_um", "thickness_um", "std_um", "cv", "size_range", "size_levels", "props"):
                f[k] = s.get(k)
            if fid:
                f["props"], how = self._said_values(fid, f.get("props"), it)
                if f["props"]:
                    notes.append(self._values_note(fname, fid, f["props"], how, lang))
            fl.append(f)

        # ---- a comparison of alternatives: each on its own, never one mixture ----
        compare = None
        named = [f for f in fl if f.get("id")]
        text_ = it.get("text") or ""
        if len({f["id"] for f in named}) >= 2 and (it.get("task") or "run") == "run" \
                and (it.get("compare") or (COMPARE.search(text_) and not MIXED.search(text_))):
            pick = ans.get("compare") or ("each" if auto else None)
            if pick == "each":
                compare = "each"
            elif pick and any(f["id"] == pick for f in named):
                fl = [f for f in fl if f.get("id") == pick]
            else:
                names = ", ".join(f["name"] for f in named)
                ask("compare", t("q_compare", lang, names=names),
                    [opt("each", f"각각 따로 ({len(named)}건)", f"each on its own ({len(named)} runs)", True)]
                    + [opt(f["id"], f"{f['name']}만", f"only {f['name']}") for f in named], free=False)
                compare = "each"

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
        for bs in (() if compare else ("vol", "wt")):
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
            mprop = next((m.get("property") for m in meas if m.get("property")), "k")
            # a value of another property than the one measured cannot be fitted to it ("실리카 CTE"
            # with conductivities measured): kept only when its property is measured
            unk = [u for u in unk if not re.match(r"(?:filler|matrix)_", u)
                   or re.match(r"(?:filler|matrix)_(.+?)(?:@\d+)?$", u).group(1) in {m.get("property") for m in meas} | {None}]
            if mprop != "k" and any(u in ("r_int", "r_contact") for u in unk):
                # MPSim's interface and contact resistances act on the heat flow only (the thermal solve)
                unk = [u for u in unk if u not in ("r_int", "r_contact")]
                notes.append(_lab(lang, f"계면·접촉 열저항은 열전도 해석에만 쓰여 {mprop} 측정으로는 보정할 수 없어, 그 물성을 정하는 재료값을 "
                                        f"보정합니다", f"interface and contact resistances act on the heat flow only, so {mprop} data "
                                                       f"cannot fit them: the material value that property depends on is fitted"))
            if not unk:
                dflt = CC.DEFAULT_UNKNOWN.get(mprop, "r_int")
                if auto or mprop != "k":
                    unk = [dflt]
                else:
                    ask("cal_unknowns", t("q_cal_unknowns", lang),
                        [opt("r_int", "필러-수지 계면저항 (R_int)", "filler-matrix interface resistance (R_int)", True),
                         opt("filler_k", "필러 열전도도", "the filler's conductivity"),
                         opt("r_contact", "입자 접촉저항 (R_c)", "particle contact resistance (R_c)")],
                        essential=False, default="r_int", multi=True, free=False)
                    unk = ["r_int"]
            cal = {"measurements": meas, "unknowns": unk}
        dplan = None
        if task == "design":
            dplan = self._design_plan(it, dz, fl, an, ans, auto, lang, ask, opt, notes, problems)
            if dplan:
                doe = dplan["doe"]

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
        n_cases = (dplan["n_cases"] if dplan else self._n_cases(doe)) if doe else 1
        quality, qsrc, qwhy = ans.get("quality"), "answer", ""
        if not quality and it.get("quality"):
            quality, qsrc = it["quality"], "text"
        # a comparison runs each filler on its own: the accuracy level of the densest one
        rec_q, rec_why = (max((self.auto_quality([f], an, matrix_id, n_cases, lang) for f in fl),
                              key=lambda q: ("fast", "standard", "accurate").index(q[0]))
                          if compare and fl else self.auto_quality(fl, an, matrix_id, n_cases, lang))
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
        if compare:
            notes.insert(0, _lab(lang, f"비교: {', '.join(f['name'] for f in fl)} 각각 따로 {len(fl)}건 (섞지 않음)",
                                 f"comparison: {', '.join(f['name'] for f in fl)}, each on its own - {len(fl)} runs (not mixed)"))
        for mid, v, how in (it.get("llm_report") or {}).get("derived") or []:
            notes.append(_lab(lang, f"AI 계산: {self.mname(mid)} {v:g}% ({how})", f"AI calculation: {self.mname(mid)} {v:g}% ({how})"))
        for r_ in (it.get("llm_report") or {}).get("restored") or []:
            notes.append(_lab(lang, f"모델이 빠뜨려 규칙으로 보충: {r_}", f"left out by the model, kept from the rules: {r_}"))
        summary = self._summary(it, lang, task, matrix_id, matrix_src, fl, an, quality, qsrc, qwhy, par, psrc,
                                rec_par_txt, None if dplan else doe, cal, optz, film_um, notes, n_cases)
        if dplan:
            at = next((k for k, r in enumerate(summary) if r.get("k") in ("해석", "Analyses")), len(summary))
            summary[at:at] = self._design_rows(dplan, film_um, lang)
        complete = all(f["id"] and f["content"] for f in fl) or (dplan is not None and all(f["id"] for f in fl))
        if not open_essential and matrix_id and fl and complete:
            try:
                if dplan:
                    payload = self._payload_design(it, lang, matrix_id, fl, an, quality, par, dplan, film_um)
                elif compare:
                    # one run per alternative, queued one after the other
                    runs = [self._payload(it, lang, task, matrix_id, [f], an, quality, par, doe, cal, optz, film_um)
                            for f in fl]
                    payload = runs[0]
                    payload["more_forms"] = [r["form"] for r in runs[1:]]
                else:
                    payload = self._payload(it, lang, task, matrix_id, fl, an, quality, par, doe, cal, optz, film_um)
                payload["settings_src"] = psrc
            except ValueError as e:
                problems.append(str(e))
            if payload is not None and self.host.get("validate") and not problems:
                for fm in [payload["form"]] + list(payload.get("more_forms") or []):
                    err = self.host["validate"](fm)
                    if err:
                        problems.append(err)
                        break
            if payload is not None and payload.get("cal"):
                # the unknowns by name and range, not by key
                for r in summary:
                    if r.get("k") in ("보정 대상", "Calibrated"):
                        r["v"] = "; ".join(f"{u.get('label') or u['path']} {u['lo']:.3g}~{u['hi']:.3g} {u.get('unit', '')}".strip()
                                           for u in payload["cal"]["unknowns"])
            if payload is not None and payload.get("cal") and not problems:
                # what the measurements allow, before any RVE is solved (calcheck.py)
                self._cal_precheck(payload, ans, lang, ask, opt, summary)
            if payload is not None and self.host.get("plan") and not problems:
                try:
                    pl = self.host["plan"](payload["form"])
                    at = next((k for k, r in enumerate(summary) if r.get("key") == "quality"), len(summary) - 1)
                    summary.insert(at + 1, self._plan_row(pl, lang))
                    payload["plan"] = {k: pl.get(k) for k in ("N", "h_um", "L_um", "memory_gb", "film", "Nz")}
                    if dplan:
                        # the largest case of the study: the finest particles beside the coarsest, at the most filler
                        big = self.host["plan"](self._corner_form(payload, dplan))
                        row = self._plan_row(big, lang)
                        row["k"] = _lab(lang, "가장 무거운 조합(범위 끝)", "Heaviest corner")
                        summary.insert(at + 2, row)
                        payload["plan_largest"] = {k: big.get(k) for k in ("N", "h_um", "L_um", "memory_gb", "film", "Nz")}
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
        if n_cases >= 30:
            return "fast", _lab(lang, f"케이스 {n_cases}개 - 빠른 스크리닝", f"{n_cases} cases - a fast screen")
        if n_cases >= 10:
            return "standard", _lab(lang, f"케이스 {n_cases}개 - 표준", f"{n_cases} cases - standard")
        if not fl or not matrix_id or not all(f.get("id") and f.get("content") for f in fl):
            return "standard", ""
        phi = self.phi(fl, matrix_id)
        a = self.contrast(fl, matrix_id, an)
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
        if f.get("props"):
            # this request's values in this case only: the library entry is not changed
            ph["props"] = dict(self.props(f["id"]), **f["props"])
            ph["name"] += " · " + ", ".join(f"{k} {v:g}" for k, v in f["props"].items())
        return ph

    def _payload(self, it, lang, task, matrix_id, fl, an, quality, par, doe, cal, optz, film_um, phases=None):
        dw = (it.get("dist") or {}).get("type")
        phases = phases or [self._phase(f, lang, dw) for f in fl]
        # interface resistances said for the fillers ("필러-레진, 필러-필러 1E-8") hold for every one of them
        for p in phases:
            for k, v in (it.get("interface") or {}).items():
                if v is not None and k in ("r_int", "r_contact"):
                    p[k] = float(v)
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
        mx = {"material_id": matrix_id}
        mp_ = it.get("_matrix_props")
        if mp_:
            # this request's values in this case only: the library entry is not changed
            mx["props"] = dict(self.props(matrix_id), **mp_)
            mx["name"] = self.mname(matrix_id) + " · " + ", ".join(f"{k} {v:g}" for k, v in mp_.items())
        form = {"name": "AI · " + name_, "matrix": mx, "phases": phases, "rve": rve,
                "analyses": {k: True for k in an}, "options": {"directions": "zxy" if dirs == "xyz" else dirs}}
        out = {"kind": task, "form": form}
        if par:
            out["settings"] = {"concurrency": int(par.get("concurrency") or 1), "threads": int(par.get("threads") or 0)}
        if doe:
            params = []
            for f in doe["factors"]:
                if f["what"] in ("content", "size") and not (0 <= int(f.get("filler", 0) or 0) < len(phases)):
                    continue
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
                          "parameters": params, "edge": self._edge(it, params),
                          "n_cases": n if design == "full" else min(DOE_MAX, 32)}
        if cal:
            i = 0
            ms = []
            for m in cal["measurements"]:
                st = []
                if m.get("content") is not None:
                    st.append({"path": f"phases.{i}.fraction.value", "value": m["content"]})
                # the direction it was measured in: in-plane ("면내 열전도도") along x, otherwise through the thickness
                ms.append({"label": (f"{m['content']:g}%" if m.get("content") is not None else "sample"),
                           "property": m["property"], "direction": "x" if it.get("directions") == "x" else "z",
                           "value": m["value"], "unc": 5, "set": st})
            # each unknown with its range (the calibration tab's defaults), R_c following R_int on touching particles
            filled = self._filled(form)
            paths = [CC.unknown_entry(u, filled, i) or {"path": u, "lo": 1e-9, "hi": 1e-5, "scale": "log", "links": []}
                     for u in cal["unknowns"]]
            if any(u.get("key") == "r_contact" for u in paths):
                for u in paths:
                    if u.get("key") == "r_int":
                        u["links"] = []
            out["cal"] = {"name": form["name"] + " · calibration", "measurements": ms, "unknowns": paths,
                          "asked": list(cal["unknowns"])}
            for m in cal["measurements"]:
                if m.get("analysis") and m["analysis"] not in form["analyses"]:
                    form["analyses"][m["analysis"]] = True
        if optz:
            out["opt"] = optz
        return out

    # ------------------------------------------------------------------ calibration precheck
    def _filled(self, form):
        """The form with the library values written in (a phase given by id only)."""
        f = copy.deepcopy(form)
        mx = f.get("matrix") or {}
        if mx.get("material_id") and not mx.get("props"):
            mx["props"] = dict(self.props(mx["material_id"]))
        mx.setdefault("name", self.mname(mx.get("material_id")))
        for ph in f.get("phases") or []:
            if ph.get("material_id") and not ph.get("props"):
                ph["props"] = dict(self.props(ph["material_id"]))
        return f

    def _cal_precheck(self, payload, ans, lang, ask, opt, summary):
        """The measurements against the model before the run: when what was asked
        cannot reach them, the set of unknowns that can is recommended (and
        pre-selected) with the reason; the user may keep the request's own."""
        L = lambda ko, en: _lab(lang, ko, en)                                     # noqa: E731
        cal = payload["cal"]
        asked = [u.get("key") or u["path"] for u in cal["unknowns"]]
        try:
            chk = CC.precheck(self._filled(payload["form"]), cal, asked, lang)
        except Exception:                                                  # noqa: BLE001
            chk = None
        if not chk:
            return
        foot = [r for r in summary if r.get("k") == "*"]
        summary[:] = [r for r in summary if r.get("k") != "*"]
        names = {"r_int": L("계면저항 R_int", "R_int"), "r_contact": L("접촉저항 R_c", "R_c"),
                 "filler_k": L("필러 열전도도", "filler k"), "matrix_k": L("매트릭스 열전도도", "matrix k")}
        lab = lambda keys: " + ".join(names.get(k, k) for k in keys)                    # noqa: E731
        plans = chk["plans"]
        rec = plans[chk["choice"]]
        pick = ans.get("cal_plan")
        chosen = next((p for p in plans if "+".join(p["keys"]) == pick), None) if pick else rec
        unit = "W/m·K"
        rows = []
        for r in chk["rows"]:
            rows.append(f"{r['label']}: {L('측정', 'measured')} {r['value']:g} · "
                        + L(f"병렬 상한 {r['parallel']:.3g}, 직렬 하한 {r['series']:.3g} {unit}",
                            f"parallel bound {r['parallel']:.3g}, series bound {r['series']:.3g} {unit}"))
        txt = "; ".join(rows)
        if chk["above"]:
            txt += L(f" - {', '.join(chk['above'])}의 측정값은 라이브러리 값(매트릭스 {chk['rows'][0]['km']:g}, 필러 "
                     f"{chk['rows'][0]['kf'][0]:g} {unit})으로는 어떤 미세구조로도 낼 수 없는 값(병렬 상한 초과)",
                     f" - {', '.join(chk['above'])} lies above what any microstructure gives with the library values "
                     f"(matrix {chk['rows'][0]['km']:g}, filler {chk['rows'][0]['kf'][0]:g} {unit})")
        summary.append({"k": L("사전 점검", "Precheck"), "v": txt})
        a = plans[0]
        if a.get("miss") is not None:
            summary.append({"k": L("요청대로", "As asked"),
                            "v": L(f"{lab(a['keys'])}: 유효매질 추정이 측정을 최대 {100 * a['miss']:.0f}% 벗어남",
                                   f"{lab(a['keys'])}: the effective-medium estimate misses the data by up to {100 * a['miss']:.0f} %")
                            + (L(" - 도달 가능", " - reachable") if chk["asked_ok"] else L(" - 이것만으로는 도달 불가", " - cannot reach them alone"))})
        if not chk["asked_ok"] and chk["reachable"]:
            est = ", ".join(f"{names.get(u.get('key'), u['label'])} ≈ {v:.3g}"
                            for u, v in zip(rec["unknowns"], (rec.get("estimate") or {}).values()))
            summary.append({"k": L("AI 추천", "AI recommends"),
                            "v": L(f"{lab(rec['keys'])} 보정 (유효매질 추정 {est}, 측정과 {100 * rec['miss']:.1f}% 이내). "
                                   f"측정값이 이 조합을 가리키거나, 재료 등급(예: 결정질 실리카)·함량 기준이 입력과 다를 수 있음",
                                   f"calibrate {lab(rec['keys'])} (effective-medium estimate {est}, within "
                                   f"{100 * rec['miss']:.1f} % of the data); or the material grade (crystalline silica, "
                                   f"say) or the content basis differs from the input")})
            ask("cal_plan", L("측정값에 맞출 보정 대상을 고르세요.", "Which unknowns should the calibration fit?"),
                [opt("+".join(rec["keys"]), lab(rec["keys"]) + " ← 추천", lab(rec["keys"]) + " ← recommended", True)]
                + [opt("+".join(p["keys"]), lab(p["keys"]) + (" (요청)" if i == 0 else ""), lab(p["keys"]) + (" (asked)" if i == 0 else ""))
                   for i, p in enumerate(plans) if p is not rec and p.get("miss") is not None],
                essential=False, default="+".join(rec["keys"]), free=False)
        elif not chk["reachable"]:
            summary.append({"k": L("AI 판단", "AI reading"),
                            "v": L("어떤 보정 대상 조합도 유효매질 추정으로 측정을 재현하지 못함: 측정값, 함량 기준(vol/wt), 재료를 확인하세요. "
                                   "요청대로 실행하고, 끝난 뒤 결과를 보고 범위를 다시 잡습니다.",
                                   "no set of unknowns reproduces the data on the effective-medium model: check the values, the "
                                   "content basis (vol/wt) and the materials. It runs as asked, and the ranges are revisited "
                                   "from the result.")})
        if chosen is not None and chosen is not a:
            cal["unknowns"] = copy.deepcopy(chosen["unknowns"])
        summary[:] = [r for r in summary if r.get("k") not in ("보정 대상", "Calibrated")]
        cal["plan_keys"] = "+".join((chosen or a)["keys"])
        summary.append({"k": L("보정 대상", "Calibrated"),
                        "v": "; ".join(f"{u['label']} {u['lo']:.3g}~{u['hi']:.3g} {u.get('unit', '')}" for u in cal["unknowns"])
                        + L(" · 결과가 측정에 닿지 않으면 AI가 범위나 대상을 바꿔 닿을 때까지 다시 보정하고, 더 바꿀 것이 없으면 묻습니다",
                            " · if the result does not reach the data, the AI changes a range or the unknowns and runs again until "
                            "it does, and asks when nothing is left to change")})
        summary.extend(foot)

    # ------------------------------------------------------------------ material values said
    def _said_values(self, mid, model_props, it):
        """The values this request gives a material: the model's, and the
        rules' over them (a relative change from the library value, "10 낮게",
        only from the rules). -> (values or None, how)"""
        said = [x for x in it.get("matprops") or [] if x.get("id") == mid]
        vals, how = MP.resolve(said, self.props(mid))
        out = dict(model_props or {})
        out.update(vals)
        for k in out:
            how.setdefault(k, ("said", None))
        return (out or None), how

    def _values_note(self, label, mid, vals, how, lang):
        lib = self.props(mid)
        parts_ko, parts_en = [], []
        for k, v in vals.items():
            u = PROP_UNIT.get(k, "")
            b = lib.get(k)
            kind, x = how.get(k, ("said", None))
            if kind == "delta":
                ko, en = f"라이브러리 {b:g}에서 {x:+g}", f"library {b:g} {x:+g}"
            elif kind == "percent":
                ko, en = f"라이브러리 {b:g}의 {x:+g}%", f"library {b:g} {x:+g} %"
            elif kind == "factor":
                ko, en = f"라이브러리 {b:g} × {x:g}", f"library {b:g} × {x:g}"
            else:
                ko, en = f"입력값, 라이브러리 {b if b is not None else '-'}", f"your value; library {b if b is not None else '-'}"
            parts_ko.append(f"{k} = {v:.4g} {u} ({ko})")
            parts_en.append(f"{k} = {v:.4g} {u} ({en})")
        return _lab(lang, f"{label}: " + ", ".join(parts_ko) + " - 이번 해석에만 쓰고 재료 라이브러리는 바꾸지 않음",
                    f"{label}: " + ", ".join(parts_en) + " - for this request only; the material library is not changed")

    # ------------------------------------------------------------------ design
    def _design_plan(self, it, dz, fl, an, ans, auto, lang, ask, opt, notes, problems):
        """The study of a design request (design.py): its classes of
        particles, its DOE parameters and how the recipe is chosen."""
        L = lambda ko, en: _lab(lang, ko, en)                                     # noqa: E731
        if not dz.get("targets"):
            ask("design_target", L("어떤 목표를 맞출까요? (예: z방향 열전도도 3 W/mK 이상)",
                                   "Which target should the design reach? (e.g. a k_z of at least 3 W/mK)"))
            return None
        d = copy.deepcopy(dz)
        tg = dict(d["targets"][0])
        # every target is met ("유전율 3.0 이하이면서 CTE 30 이하"): each property's analysis runs in every case
        tgs = []
        for t_ in d["targets"]:
            if all(x["property"] != t_["property"] for x in tgs):
                tgs.append(dict(t_, response=DZ.PROP_RESPONSE[t_["property"]]))
        for t_ in reversed(tgs):
            a_t = DZ.PROP_ANALYSIS[t_["property"]]
            if a_t not in an:
                an.insert(0, a_t)
        check = ["viscosity"] if (set(d.get("prefer") or []) or d.get("objective") == "viscosity" or "viscosity" in an) else []
        an[:] = [a for a in an if a != "viscosity"]
        if tg.get("direction") == "z":
            it["directions"] = "z"
        elif tg.get("direction") == "xy":
            it["directions"] = "x"
        uniq = list(dict.fromkeys(f["id"] for f in fl if f.get("id")))
        if not uniq:
            return None
        if len(uniq) > 2:
            problems.append(L("설계는 필러 재료 두 가지까지 다룹니다. 두 가지로 줄여 주세요.",
                              "A design handles up to two filler materials; name two."))
            return None
        find = set(d.get("find") or [])
        f0 = next(f for f in fl if f.get("id") == uniq[0])
        dup = [f for f in fl if f.get("id") == uniq[0]] if len(uniq) == 1 else []
        same = len(uniq) == 1 and ("ratio" in find or (d.get("classes") or 1) >= 2 or len(dup) >= 2)
        ss = d.get("sizes_said") or []
        if (d.get("classes") or 0) >= 3 and not (len(uniq) == 1 and len(ss) >= 3 and "size" not in find):
            notes.append(L("세 가지 크기는 크기를 모두 말한 경우(예: 70, 5, 0.5 µm)만 다루고, 여기서는 두 가지 크기(굵은 입자·미세 입자)로 설계합니다",
                           "three sizes are designed when all three are said (70, 5 and 0.5 µm, say); here two sizes (coarse and fine) are"))
        if len(uniq) == 1 and len(ss) >= 2 and "size" not in find:
            # the sizes of the blend said one by one ("70um, 5um, 0.5um 세 가지"): one class each, sizes kept
            tags = [L("굵은", "coarse"), L("중간", "medium"), L("미세", "fine")] if len(ss) >= 3 else [L("굵은", "coarse"), L("미세", "fine")]
            classes = [{"name": f"{f0['name']}, {v:g} µm", "f": dict(f0, size_um=v), "same": i > 0, "tag": tags[i]}
                       for i, v in enumerate(ss[:3])]
            same = True
        elif same and len(dup) >= 2 and all(x.get("size_um") for x in dup[:2]) and "size" not in find:
            # two sizes of one material said ("1 um and 0.3 um alumina"): the blend of these two
            big, small = sorted(dup[:2], key=lambda x: -x["size_um"])
            classes = [{"name": f"{f0['name']}, {big['size_um']:g} µm", "f": big, "same": False},
                       {"name": f"{f0['name']}, {small['size_um']:g} µm", "f": small, "same": True}]
        elif same:
            f0 = dict(f0, size_um=None) if "size" in find or not f0.get("size_um") else f0
            classes = [{"name": f"{f0['name']}, coarse", "f": f0, "same": False},
                       {"name": f"{f0['name']}, fine", "f": dict(f0, size_um=None), "same": True}]
        elif len(uniq) == 2:
            f1 = next(f for f in fl if f.get("id") == uniq[1])
            classes = [{"name": f0["name"], "f": f0, "same": False}, {"name": f1["name"], "f": f1, "same": False}]
        else:
            classes = [{"name": f0["name"], "f": f0, "same": False}]
        sizes_fixed = [c["f"].get("size_um") if "size" not in find else None for c in classes]
        need_sizes = any(v is None for v in sizes_fixed) and ("size" in find or same)
        if ans.get("design_sizes"):
            qs = [q for q in quantities(normalize(str(ans["design_sizes"])))]
            if qs:
                u = qs[0].get("unit") if qs[0].get("unit") in ("um", "nm", "mm") else "um"
                lo_ = to_um(qs[0]["value"], u)
                hi_ = to_um(qs[0]["hi"], u) if "hi" in qs[0] else (to_um(qs[1]["value"], qs[1].get("unit") or u) if len(qs) > 1 else None)
                if lo_ and hi_:
                    d["size_min_um"], d["size_max_um"] = min(lo_, hi_), max(lo_, hi_)
        if need_sizes and (d.get("size_min_um") is None or d.get("size_max_um") is None):
            lo_ = d.get("size_min_um") or (d["size_max_um"] / 10.0 if d.get("size_max_um") else 1.0)
            hi_ = d.get("size_max_um") or (d["size_min_um"] * 10.0 if d.get("size_min_um") else 20.0)
            if not auto:
                ask("design_sizes", L("입자 크기 범위는? (예: 1~20 µm)", "Which size range? (e.g. 1-20 µm)"),
                    [opt(f"{lo_:g}~{hi_:g} um", f"{lo_:g}~{hi_:g} µm", f"{lo_:g}-{hi_:g} µm", True)],
                    essential=False, default=f"{lo_:g}~{hi_:g} um")
            notes.append(L(f"크기 범위 {lo_:g}~{hi_:g} µm (말하지 않은 쪽은 가정)", f"size range {lo_:g}-{hi_:g} µm (the bound not said is assumed)"))
            d["size_min_um"], d["size_max_um"] = lo_, hi_
        if d.get("content_max") is None and "content" in find:
            d["content_max"] = 60.0
            notes.append(L("최대 함량 60 vol% (가정 - 말하지 않음)", "highest content 60 vol% (assumed - not said)"))
        content_fixed = None
        if "content" not in find:
            cs = [f["content"]["value"] for f in fl if f.get("content")]
            if not cs:
                return None
            content_fixed = sum(cs)
        params, centre, miss = DZ.plan_factors(d, classes, sizes_fixed, content_fixed)
        if params is None:
            return None
        if not params:
            problems.append(L("설계로 바꿀 변수가 없습니다 (함량·크기·비율 중 무엇을 찾을지 알려 주세요).",
                              "Nothing for the design to vary: say what to find (content, size or blend)."))
            return None
        design, n = DZ.doe_design(params)
        roles = {p["path"]: p.pop("role") for p in params}
        basis = d.get("basis") or "vol"
        tg["response"] = DZ.PROP_RESPONSE[tg["property"]]
        spec = {"target": tg, "targets": tgs, "content_floor": d.get("content_min"),
                "objective": d.get("objective") or "content", "prefer": list(d.get("prefer") or []),
                "tol": d.get("tol") or DZ.TOL_DEFAULT, "roles": roles, "basis": basis, "lang": lang,
                "phases": [{"name": c["name"], "d": sizes_fixed[i] if not need_sizes else None} for i, c in enumerate(classes)],
                "spheres": all((c["f"].get("shape") or "sphere") == "sphere" for c in classes),
                "same_material": same, "content_fixed": content_fixed,
                "share_fixed": centre.get("share", 0.0), "check_analyses": check, "mono": bool(d.get("mono"))}
        doe = {"design": design, "samples": n if design == "lhs" else 12, "parameters": params, "n_cases": n,
               "factors": []}
        return {"doe": doe, "n_cases": n, "classes": classes, "centre": centre, "spec": spec, "d": d, "basis": basis,
                "check": check, "interface": dict(it.get("interface") or {})}

    def _design_rows(self, dp, film_um, lang):
        L = lambda ko, en: _lab(lang, ko, en)                                     # noqa: E731
        sp = dp["spec"]
        tg = sp["target"]
        pn = {"k": L("열전도도", "thermal conductivity"), "sigma": L("전기전도도", "electrical conductivity"),
              "eps_r": L("유전율", "permittivity"), "alpha": "CTE", "E": L("탄성률", "Young's modulus")}[tg["property"]]
        dr = {"z": "z ", "xy": L("면내 ", "in-plane ")}.get(tg.get("direction") or "", "")
        op = {">=": "≥", "<=": "≤", "=": "="}[tg["op"]]
        unit = DZ.PROP_UNIT.get(tg["property"], "")
        goal = {"content": L("총 필러 함량 최소", "the least total filler"),
                "viscosity": L("점도 최소", "the lowest viscosity")}.get(sp["objective"], sp["objective"])
        each = f"{dr}{pn} {op} {tg['value']:g} {unit}".strip()
        PN = {"k": L("열전도도", "thermal conductivity"), "sigma": L("전기전도도", "electrical conductivity"),
              "eps_r": L("유전율", "permittivity"), "alpha": "CTE", "E": L("탄성률", "Young's modulus")}
        for t_ in (sp.get("targets") or [])[1:]:
            each += L(" 이면서 ", " and ") + f"{PN[t_['property']]} {({'>=': '≥', '<=': '≤', '=': '='})[t_['op']]} " \
                f"{t_['value']:g} {DZ.PROP_UNIT.get(t_['property'], '')}".rstrip()
        rows = [{"k": L("목표", "Goal"), "v": f"{goal} · {each}"}]
        lab = {"content": L("총 함량", "total content"), "share": L("미세 입자 비율", "fine share") if sp["same_material"]
               else L("두 번째 필러 비율", "second filler's share"), "size0": L("굵은 입자", "coarse size") if sp["same_material"]
               else L("크기", "size"), "size1": L("미세 입자", "fine size") if sp["same_material"] else L("크기 2", "size 2")}
        if len(sp.get("phases") or []) == 3:
            lab.update(share=L("중간 입자 비율", "medium share"), share2=L("미세 입자 비율", "fine share"))
        ps = []
        for p in dp["doe"]["parameters"]:
            role = sp["roles"].get(p["path"])
            unit = ("µm" if role and role.startswith("size") else L("%(필러 중)", "% of filler") if role in ("share", "share2")
                    else f"{sp['basis']}%" if role == "content" else p["unit"])
            ps.append(f"{lab.get(role, p['label'])} {p['min']:g}~{p['max']:g} {unit}")
        n = dp["n_cases"]
        how = L(f"라틴 하이퍼큐브 {n}케이스", f"Latin hypercube, {n} cases") if dp["doe"]["design"] == "lhs" \
            else L(f"전체 조합 {n}케이스", f"full factorial, {n} cases")
        rows.append({"k": L("변수 (DOE)", "Variables (DOE)"), "v": " · ".join(ps) + f" ({how})"})
        fixed = []
        if film_um:
            fixed.append(L(f"필름 {film_um:g} µm", f"film {film_um:g} µm"))
        itf = dp.get("interface") or {}
        if itf.get("r_int") is not None:
            fixed.append(f"R_int {itf['r_int']:.3g} m²K/W")
        if itf.get("r_contact") is not None:
            fixed.append(f"R_c {itf['r_contact']:.3g} m²K/W")
        if sp.get("mono"):
            fixed.append(L("입자마다 단일 크기 (분포 없음)", "one size per class (no distribution)"))
        if fixed:
            rows.append({"k": L("고정 조건", "Fixed"), "v": " · ".join(fixed)})
        tol = sp["tol"]
        if sp["objective"] == "content":
            pick = L(f"목표를 만족하는 최저 함량, 그보다 {tol:g} vol% 이내의 조합 중 ", f"the lowest content that meets the target; of the recipes within {tol:g} vol% of it, ")
            pick += (L("점도가 가장 낮은 것 (같은 함량에서 점도가 낮을수록 패킹 φm이 높음)", "the one of lowest viscosity (at one content, a lower viscosity is a higher packing φm)")
                     if sp["prefer"] else L("함량이 가장 낮은 것", "the lowest"))
        else:
            pick = L("목표를 만족하는 조합 중 점도가 가장 낮은 것", "of the recipes that meet the target, the lowest viscosity")
        rows.append({"k": L("추천 기준", "Choice"), "v": pick})
        if sp["prefer"] or sp["objective"] == "viscosity":
            rows.append({"k": L("점도·패킹", "Viscosity, packing"),
                         "v": L("DOE 각 케이스에서 풀지 않고, MPSim 점도 해석과 같은 식으로 모든 후보에서 계산: φm = 크기 분포의 랜덤 최밀충전(Farr-Groot), "
                                "상대점도 = Krieger-Dougherty. 추천 조합만 점도 해석 전체(입자동역학 포함)로 확인",
                                "not solved in each DOE case but computed for every candidate with the closed forms of MPSim's viscosity "
                                "analysis: φm = random close packing of the size distribution (Farr-Groot), relative viscosity = "
                                "Krieger-Dougherty; only the recommended recipe gets the full viscosity analysis (with particle dynamics)")
                         + ("" if sp["spheres"] else L(" - 구형이 아니어서 φm 식은 쓰지 않음", " - not spheres: the φm closed form is not used"))})
        rows.append({"k": L("진행", "Then"),
                     "v": L("DOE가 끝나면 대리모델(가우스 과정, 교차검증)이 추천 함량을 허용 오차 안으로 정할 만큼 정확한지 라운드마다 보고, 모자라면 "
                            "결정을 가르는 점을 더 해석합니다. 정해지면 추천 조합을 구조 3개로 확인 해석하고, 목표를 만족할 때까지 계속합니다",
                            "when the DOE is done, each round checks whether the surrogate (Gaussian process, cross-validated) fixes "
                            "the recipe's content within the tolerance, and runs the points that settle it when it does not; the "
                            "recipe is then checked with three realisations, until the check meets the target")
                     + (L(" (" + ", ".join(name(AN_NAME, a, "ko") for a in [DZ.PROP_ANALYSIS[tg["property"]]] + dp["check"]) + ")",
                          " (" + ", ".join(name(AN_NAME, a, "en") for a in [DZ.PROP_ANALYSIS[tg["property"]]] + dp["check"]) + ")"))})
        return rows

    def _design_phases(self, it, lang, fl, dp):
        """The base case's phases: one per class, at the centre of the study."""
        sp, centre = dp["spec"], dp["centre"]
        tot = float(centre.get("content") or 50.0)
        share = float(centre.get("share", 0.0)) / 100.0 if len(dp["classes"]) >= 2 else 0.0
        vf = DZ.class_fractions(len(dp["classes"]), share, float(centre.get("share2", 0.0)) / 100.0)
        out = []
        for i, c in enumerate(dp["classes"]):
            f = dict(c["f"])
            f["size_um"] = centre.get(f"size{i}") or f.get("size_um") or DEFAULT_SIZE_UM
            v = tot * vf[i]
            f["content"] = {"value": round(v, 4), "basis": dp["basis"]}
            if sp.get("mono"):
                f["std_um"], f["cv"] = None, None
            ph = self._phase(f, lang, None if not sp.get("mono") else "mono")
            if sp.get("mono"):
                ph["dist"] = {"type": "mono"}
            ph["name"] = c["name"]
            if it.get("orientation") and ph["shape"] in ("spheroid", "cylinder"):
                ph["orientation"]["mode"] = it["orientation"]
            out.append(ph)
        return out

    def _payload_design(self, it, lang, matrix_id, fl, an, quality, par, dp, film_um):
        out = self._payload(it, lang, "design", matrix_id, [], an, quality, par, None, None, None, film_um,
                            phases=self._design_phases(it, lang, fl, dp))
        form = out["form"]
        form["name"] = "AI · design · " + self.mname(matrix_id).split(" (")[0] + " + " + \
            " + ".join(dict.fromkeys(self.mname(c["f"]["id"]).split(" (")[0] for c in dp["classes"]))
        doe = copy.deepcopy(dp["doe"])
        doe.pop("factors", None)
        doe["name"] = form["name"] + " · DOE"
        doe["edge"] = self._edge(it, doe["parameters"])
        out["doe"] = doe
        out["design"] = copy.deepcopy(dp["spec"])
        out["design"]["interface"] = dp["interface"]
        return out

    @staticmethod
    def _edge(it, params):
        """The grid of a study's cases. A particle size that varies: each case its own grid, edge and voxel
        planned by MPSim for its particles at the accuracy level ('own'). One grid for all would put a
        30 µm particle in the 21 µm box planned for 5 µm (the cases then differ by the box, not the size),
        or leave the small ones under-resolved. A grid the person set stays theirs: their voxel with each
        case's edge ('adaptive'), their edge for every case ('fixed')."""
        rv = it.get("rve") or {}
        if not any(str(p.get("path", "")).endswith(".size.d") for p in params) or rv.get("L_um") or rv.get("N"):
            return "fixed"
        return "adaptive" if rv.get("voxel_um") else "own"      # a voxel set: kept, the edge still per case

    def _corner_form(self, payload, dp):
        """The base case at the heaviest corner of the study, for its plan."""
        form = copy.deepcopy(payload["form"])
        roles = dp["spec"]["roles"]
        vals = {}
        for p in dp["doe"]["parameters"]:
            role = roles.get(p["path"])
            vals[role] = p["max"] if role in ("content", "size0", "share", "share2") else p["min"] if role == "size1" else p["max"]
        ph = form["phases"]
        tot = vals.get("content", sum(x["fraction"]["value"] for x in ph))
        if len(ph) >= 2:
            s = vals.get("share", dp["centre"].get("share", 0.0)) / 100.0
            s = s if s > 0 else 0.25
            vf = DZ.class_fractions(len(ph), s, vals.get("share2", dp["centre"].get("share2", 0.0)) / 100.0)
            for x, v in zip(ph, vf):
                x["fraction"]["value"] = tot * v
        else:
            ph[0]["fraction"]["value"] = tot
        for i in range(len(ph)):
            if f"size{i}" in vals:
                ph[i]["size"]["d"] = vals[f"size{i}"]
        return form

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
            if f.get("shape") != "network" and f.get("size_um") is None:
                parts.append(L("크기는 설계에서 찾음", "size found by the design"))
            elif f.get("shape") != "network":
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
            elif task == "design":
                parts.append(L("함량은 설계에서 찾음", "content found by the design"))
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
            elif n.get("type") == "composite_loading":
                rows.append({"k": L("해석", "Reading"),
                             "v": L(f"'{n['text']}' → 복합재의 필러 함량 {n['value']:g}%로 읽음 (매트릭스가 {n['value']:g}%라면 "
                                    f"'필러 {100 - n['value']:g}%'로 알려 주세요)",
                                    f"'{n['text']}' read as the composite's filler content, {n['value']:g} % (if the matrix "
                                    f"is {n['value']:g} %, say 'filler {100 - n['value']:g}%')")})
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
    # a design: what the follow-up says of it replaces that part ("최대 함량은 60%로")
    nd = new.get("design") or {}
    if nd and (DZ.active(nd) or DZ.wanted(nd) or (it.get("design") and any(
            nd.get(k) is not None for k in ("content_max", "content_min", "size_max_um", "size_min_um", "tol")))):
        md = copy.deepcopy(it.get("design") or DZ.empty())
        if nd.get("targets"):
            md["targets"] = nd["targets"]
        for k in ("objective", "content_max", "content_min", "size_max_um", "size_min_um", "classes", "tol", "basis"):
            if nd.get(k) is not None:
                md[k] = nd[k]
        for k in ("find", "prefer"):
            md[k] = list(dict.fromkeys(list(md.get(k) or []) + list(nd.get(k) or [])))
        md["mono"] = bool(md.get("mono") or nd.get("mono"))
        md.setdefault("said", {}).update(nd.get("said") or {})
        it["design"] = md
        if DZ.active(md) or DZ.wanted(md):
            it["task"] = "design"
    for k, v in (new.get("interface") or {}).items():
        it.setdefault("interface", {})[k] = v
    # a material value said again replaces the earlier one
    if new.get("matprops"):
        keys = {(x["id"], x["prop"]) for x in new["matprops"]}
        it["matprops"] = [x for x in it.get("matprops") or [] if (x["id"], x["prop"]) not in keys] + list(new["matprops"])
    return it


_ = (math, re)


_POLY = {"epoxy", "bt", "polyimide", "pbo", "bcb", "su8", "silicone", "ppe", "lcp", "ptfe", "peek", "parylene_c",
         "cyanate_ester", "pps", "fr4"}


def _is_polymer(mid):
    return mid in _POLY
