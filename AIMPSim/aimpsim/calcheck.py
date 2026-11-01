"""A calibration looked at before it runs and after a run that did not reach
the measurements.

Before (precheck): the measurements against what the model can give at all.
The parallel and series arrangements of filler and matrix (Wiener bounds)
hold for any microstructure: a measured conductivity above the parallel
bound with the library values cannot be reached by an interfacial
resistance, which only lowers it. Then each set of unknowns that could
explain the data - what the request asked for first, then the filler's
conductivity, the matrix's, both, the filler's with R_int - is tried on
MPSim's own effective-medium preview (differential Bruggeman with
Hasselman-Johnson particles, calibrate.preview, well under a second each);
the first set whose estimate reproduces every measurement is run, and the
summary says why.

After (next_round): a run whose result says "not reached" is read like the
calibration tab reads it. The effective-medium model is corrected by what
the RVE gave at the estimate (the contacts it has and the mean field has
not), and the same candidates are tried again: the unknowns as they were
with the range widened at the end the estimate sat on, then the other sets.
The first that reaches the data is run next; when none does, the run stops
with the reason. There is no fixed number of rounds (see next_round); loop.MAX_ROUNDS is only a
safety stop.

Only thermal conductivity is checked on the effective-medium model (the
preview's scope); for another property a range the estimate sat at the end
of is widened once.
"""
from __future__ import annotations

import copy
import json
import math
import re

TOL = 0.15          # relative: the effective-medium model (10 %) and the measurement (5 %)
_CACHE = {}


def _mp():
    try:
        from mpsim import calibrate as CA
        from mpsim import doe as DOE
        from mpsim import spec as S
        return CA, DOE, S
    except Exception:                                                # noqa: BLE001
        return None


def unknown_entry(key, form, i=0, wide=False):
    """An unknown of the calibration tab: {key, path, label, unit, lo, hi, scale, links}."""
    ph = (form.get("phases") or [{}])[i] if form.get("phases") else {}
    mp = (form.get("matrix") or {}).get("props") or {}
    pp = ph.get("props") or {}
    name = ph.get("name") or f"Phase {i + 1}"
    mname = (form.get("matrix") or {}).get("name") or "Matrix"
    if key == "r_int":
        return {"key": key, "path": f"phases.{i}.r_int", "label": f"{name}: interfacial resistance R_int",
                "unit": "m²K/W", "lo": 1e-9, "hi": 1e-5, "scale": "log",
                # touching particles: their contact faces carry two filler-resin interfaces
                "links": [{"path": f"phases.{i}.r_contact", "expr": "2*x"}]}
    if key == "r_contact":
        return {"key": key, "path": f"phases.{i}.r_contact", "label": f"{name}: contact resistance R_c",
                "unit": "m²K/W", "lo": 1e-9, "hi": 1e-4, "scale": "log", "links": []}
    if key == "filler_k":
        k = float(pp.get("k") or 1.0)
        return {"key": key, "path": f"phases.{i}.props.k", "label": f"{name}: thermal conductivity", "unit": "W/m·K",
                "lo": _r3(k * (0.5 if wide else 0.1)), "hi": _r3(k * (30.0 if wide else 2.0)), "scale": "log", "links": []}
    if key == "matrix_k":
        k = float(mp.get("k") or 0.2)
        return {"key": key, "path": "matrix.props.k", "label": f"{mname}: thermal conductivity", "unit": "W/m·K",
                "lo": _r3(k * 0.5), "hi": _r3(k * (3.0 if wide else 2.0)), "scale": "log", "links": []}
    # another material value ("실리카 CTE 보정", "filler_k@1" for the second filler): its library value times a span
    m = re.match(r"(filler|matrix)_(k|alpha|eps_r|E|sigma|nu)(?:@(\d+))?$", key or "")
    if not m:
        return None
    who, prop = m.group(1), m.group(2)
    if who == "filler" and m.group(3):
        i = int(m.group(3))
        ph = (form.get("phases") or [{}])[i] if i < len(form.get("phases") or []) else {}
        pp, name = ph.get("props") or {}, ph.get("name") or f"Phase {i + 1}"
    v = float((pp if who == "filler" else mp).get(prop) or {"k": 1.0, "alpha": 20.0, "eps_r": 3.0, "E": 3.0,
                                                             "sigma": 1.0, "nu": 0.3}[prop])
    lo, hi = SPAN[prop][1 if wide else 0]
    if prop == "nu":
        lo_v, hi_v, scale = max(0.0, v - 0.15), min(0.499, v + 0.15), "lin"
    else:
        lo_v, hi_v, scale = _r3(v * lo), _r3(v * hi), "log"
    return {"key": key, "path": (f"phases.{i}.props.{prop}" if who == "filler" else f"matrix.props.{prop}"),
            "label": f"{name if who == 'filler' else mname}: {PROP_LABEL[prop]}", "unit": PROP_UNIT[prop],
            "lo": lo_v, "hi": hi_v, "scale": scale, "links": []}


PROP_LABEL = {"k": "thermal conductivity", "alpha": "CTE", "eps_r": "relative permittivity", "E": "Young's modulus",
              "sigma": "electrical conductivity", "nu": "Poisson's ratio"}
PROP_UNIT = {"k": "W/m·K", "alpha": "ppm/K", "eps_r": "", "E": "GPa", "sigma": "S/m", "nu": ""}
# the range of a fitted material value as factors of its library value: (as asked, widened)
SPAN = {"k": ((0.1, 2.0), (0.5, 30.0)), "alpha": ((0.5, 2.0), (0.2, 5.0)), "eps_r": ((0.7, 1.5), (0.5, 3.0)),
        "E": ((0.5, 2.0), (0.2, 5.0)), "sigma": ((1e-3, 10.0), (1e-6, 100.0)), "nu": ((1, 1), (1, 1))}
# what a calibration of each property fits when the request names nothing: the interfacial resistance for
# conduction of heat; the resin's own value for expansion, permittivity and stiffness (a formulation's resin
# varies, a filler grade much less); the particles' conductivity with their contacts for electrical conduction
DEFAULT_UNKNOWN = {"k": "r_int", "alpha": "matrix_alpha", "eps_r": "matrix_eps_r", "E": "matrix_E", "sigma": "filler_sigma"}


def _r3(v):
    return float(f"{v:.3g}")


def job_of(form, cal, unknowns):
    """The MPSim calibration job (the tab's calJob) for these unknowns."""
    meas = []
    for m in cal.get("measurements") or []:
        st = m.get("set") or []
        meas.append({"label": m.get("label"), "property": m["property"], "direction": m.get("direction") or "z",
                     "value": float(m["value"]), "rel_unc": float(m.get("unc") or 5) / 100.0,
                     "set": {s["path"]: float(s["value"]) for s in st} if isinstance(st, list) else dict(st)})
    unk = [{k: u[k] for k in ("path", "label", "unit", "lo", "hi", "scale", "links")} for u in unknowns]
    return {"name": cal.get("name") or "calibration", "base": form, "measurements": meas, "unknowns": unk}


def _bounds(form, cal):
    """Per measurement: the content and the Wiener bounds with the library values."""
    mp = _mp()
    if mp is None:
        return None
    CA, DOE, S = mp
    base = CA.fill_props(form)
    rows = []
    for m in cal.get("measurements") or []:
        if m.get("property") != "k":
            continue
        f = copy.deepcopy(base)
        for s in m.get("set") or []:
            DOE.set_path(f, s["path"], float(s["value"]))
        try:
            sp = S.normalize(f)
        except ValueError:
            return None
        km = float(sp["matrix"]["props"]["k"]) if sp.get("matrix", {}).get("props") else float(base["matrix"]["props"]["k"])
        solid = [(float(p["vf"]), float(p["props"]["k"])) for p in sp["phases"] if not p.get("void")]
        phi = sum(v for v, _ in solid)
        par = sum(v * k for v, k in solid) + (1.0 - phi) * km
        ser = 1.0 / (sum(v / k for v, k in solid) + (1.0 - phi) / km)
        rows.append({"label": m.get("label"), "value": float(m["value"]), "phi": phi, "parallel": par, "series": ser,
                     "km": km, "kf": [k for _, k in solid]})
    return rows


def _try(form, cal, unknowns, scale=None):
    """The effective-medium preview of one set of unknowns: (worst relative miss, fit, preview) or None.
    scale: per measurement, what the RVE gave over what the mean field gives (applied to the data)."""
    mp = _mp()
    if mp is None:
        return None
    CA = mp[0]
    job = job_of(form, cal, unknowns)
    if scale:
        for m, c in zip(job["measurements"], scale):
            m["value"] = m["value"] / c
    try:
        pv = CA.preview(job)
    except Exception:                                                # noqa: BLE001
        return None
    if not pv.get("available"):
        return None
    fit = pv.get("fit") or []
    miss = max((abs(f / m["value"] - 1.0) for f, m in zip(fit, job["measurements"])), default=1.0)
    return miss, fit, pv


def _key(*a):
    return json.dumps(a, sort_keys=True, default=str)


PLANS = [("r_int",), ("filler_k",), ("matrix_k",), ("filler_k", "matrix_k"), ("filler_k", "r_int")]
# the sets of unknowns tried in turn for another property (no effective-medium check: each is run)
PLANS_OF = {"alpha": [("matrix_alpha",), ("filler_alpha",), ("matrix_alpha", "filler_alpha")],
            "eps_r": [("matrix_eps_r",), ("filler_eps_r",), ("matrix_eps_r", "filler_eps_r")],
            "E": [("matrix_E",), ("filler_E",), ("matrix_E", "filler_E")],
            "sigma": [("filler_sigma",), ("matrix_sigma",)]}


def precheck(form, cal, asked, lang="en"):
    """{rows, plans, choice, asked_ok, text} for a calibration about to run.
    asked: the unknown keys of the request (r_int, r_contact, filler_k)."""
    k = _key(form, cal, asked)
    if k in _CACHE:
        return copy.deepcopy(_CACHE[k])
    rows = _bounds(form, cal)
    if rows is None or not rows or len(rows) != len(cal.get("measurements") or []):
        return None
    plans = [tuple(asked)] + [p for p in PLANS if p != tuple(asked) and len(p) <= len(cal["measurements"])]
    tried = []
    for p in plans:
        unk = [unknown_entry(x, form, wide=p != tuple(asked)) for x in p]
        r = _try(form, cal, unk)
        if r is None:
            tried.append({"keys": list(p), "miss": None, "unknowns": unk})
            continue
        miss, fit, pv = r
        und = bool((pv.get("identifiability") or {}).get("underdetermined"))
        tried.append({"keys": list(p), "miss": miss, "fit": fit, "unknowns": unk, "underdetermined": und,
                      "estimate": {u["label"]: s["map"] for u, s in zip(unk, pv.get("unknowns") or [])}})
        if miss <= TOL and not und:
            break                      # the first set that reaches the data (the request's own first)
    ok = [i for i, t in enumerate(tried) if t["miss"] is not None and t["miss"] <= TOL and not t.get("underdetermined")]
    choice = 0 if 0 in ok else (ok[0] if ok else 0)
    above = [r for r in rows if r["value"] > r["parallel"] * 1.05]
    out = {"rows": rows, "plans": tried, "choice": choice, "asked_ok": 0 in ok, "reachable": bool(ok),
           "above": [r["label"] for r in above]}
    _CACHE[k] = copy.deepcopy(out)
    return out


def next_round(form, cal, unknowns, result, tried_keys, lang="en", library=None):
    """What to run after a calibration result: {action: done | rerun | ask | stop, unknowns, why}.
    There is no fixed number of rounds: a range is widened while the estimate sits at its end (up to the
    physical limits) and the other sets of unknowns are tried once each, so the candidates run out; then the
    person is asked (options) - another grade of the filler, the other content basis, or to stop."""
    summ = result.get("unknowns") or []
    rows = result.get("measurements") or []
    unreached = any(u.get("unreached") for u in summ)
    off = [r for r in rows if abs(float(r.get("residual_sigma") or 0.0)) > 2.5]
    if not unreached and not off:
        return {"action": "done", "why": "reached"}
    mp = _mp()
    props = {m.get("property") for m in cal.get("measurements") or []}
    if mp is None or props != {"k"}:
        # another property (no effective-medium check): the range the estimate sat at the end of is widened
        # while it can be (up to the physical limits), then each other set of unknowns of that property is
        # run once; then the person is asked
        keys = "+".join(u.get("key") or u["path"] for u in unknowns)
        wid, moved = [], False
        for u, s in zip(unknowns, summ):
            u = dict(u)
            span = math.log(u["hi"] / u["lo"]) if u["scale"] == "log" and u["lo"] > 0 else (u["hi"] - u["lo"])
            lim_lo, lim_hi = _limits(u)
            if (s.get("edge") in ("low", "both") or _near(float(s["map"]), u["lo"], span, u["scale"])) and u["lo"] > lim_lo * 1.0001:
                u["lo"] = max(lim_lo, _r3(u["lo"] / 10.0) if u["scale"] == "log" else u["lo"] - 0.5 * span)
                moved = True
            if (s.get("edge") in ("high", "both") or _near(float(s["map"]), u["hi"], span, u["scale"])) and u["hi"] < lim_hi * 0.9999:
                u["hi"] = min(lim_hi, _r3(u["hi"] * 10.0) if u["scale"] == "log" else u["hi"] + 0.5 * span)
                moved = True
            wid.append(u)
        wkey = keys + ":" + ",".join(f"{u['lo']:.3g}-{u['hi']:.3g}" for u in wid)
        if moved and wkey not in tried_keys:
            return {"action": "rerun", "unknowns": wid, "keys": wkey, "why": "widened", "miss": None}
        prop = next(iter(props)) if len(props) == 1 else None
        for p in PLANS_OF.get(prop, []):
            kk = "+".join(p)
            if kk == keys or kk in tried_keys or len(p) > len(cal["measurements"]):
                continue
            unk = [unknown_entry(x, form, wide=True) for x in p]
            if all(unk):
                return {"action": "rerun", "unknowns": unk, "keys": kk, "why": "switched", "miss": None}
        return {"action": "ask", "why": "no_plan", "options": options(form, cal, library)}
    CA = mp[0]
    # what the RVE gave over the mean field at the estimate: the contacts the RVE has
    th = [float(s["map"]) for s in summ]
    scale = []
    job = job_of(form, cal, unknowns)
    try:
        from mpsim import doe as DOE
        from mpsim import spec as S
        base = CA.fill_props(form)
        U = [CA._Unknown(u) for u in job["unknowns"]]
        import numpy as np
        for m, r in zip(job["measurements"], rows):
            f = copy.deepcopy(base)
            for path, v in (m.get("set") or {}).items():
                DOE.set_path(f, path, v)
            sp = S.normalize(CA._set_theta(f, U, th))
            emt = float(CA._theory_model(sp, U, np.array([th]))[0])
            direct = float(r.get("direct") or 0.0)
            scale.append(direct / emt if emt > 0 and direct > 0 else 1.0)
    except Exception:                                                # noqa: BLE001
        scale = None
    cands = []
    # the same unknowns, the range widened where the estimate sat at its end
    wid = []
    moved = False
    for u, s in zip(unknowns, summ):
        u = dict(u)
        span = math.log(u["hi"] / u["lo"]) if u["scale"] == "log" and u["lo"] > 0 else (u["hi"] - u["lo"])
        at_lo = s.get("edge") in ("low", "both") or _near(float(s["map"]), u["lo"], span, u["scale"])
        at_hi = s.get("edge") in ("high", "both") or _near(float(s["map"]), u["hi"], span, u["scale"])
        lim_lo, lim_hi = _limits(u)
        if at_lo and u["lo"] > lim_lo * 1.0001:
            u["lo"] = max(lim_lo, _r3(u["lo"] / 100.0) if u["scale"] == "log" else u["lo"] - span)
            moved = True
        if at_hi and u["hi"] < lim_hi * 0.9999:
            u["hi"] = min(lim_hi, _r3(u["hi"] * 100.0) if u["scale"] == "log" else u["hi"] + span)
            moved = True
        wid.append(u)
    keys = "+".join(u.get("key") or u["path"] for u in unknowns)
    # widened again and again while the estimate sits at an end - up to the physical limits, so the loop ends
    wkey = keys + ":" + ",".join(f"{u['lo']:.3g}-{u['hi']:.3g}" for u in wid)
    if moved and wkey not in tried_keys:
        cands.append((wkey, wid, "widened"))
    for p in PLANS:
        kk = "+".join(p)
        if kk == keys or kk in tried_keys or len(p) > len(cal["measurements"]):
            continue
        cands.append((kk, [unknown_entry(x, form, wide=True) for x in p], "switched"))
    for kk, unk, how in cands:
        r = _try(form, cal, unk, scale)
        if r is None:
            continue
        miss, fit, pv = r
        if miss <= TOL and not (pv.get("identifiability") or {}).get("underdetermined"):
            return {"action": "rerun", "unknowns": unk, "keys": kk, "why": how, "miss": miss,
                    "estimate": {u["label"]: s["map"] for u, s in zip(unk, pv.get("unknowns") or [])},
                    "scale": scale}
    return {"action": "ask", "why": "no_plan", "scale": scale, "options": options(form, cal, library)}


# the widest range an unknown is widened to: beyond them a value is not a material's
_LIMITS = {"r_int": (1e-12, 1e-3), "r_contact": (1e-12, 1e-3), "k": (1e-3, 3000.0), "sigma": (1e-16, 1e9),
           "eps_r": (1.0, 1e5), "E": (1e-4, 2000.0), "alpha": (0.0, 500.0), "nu": (0.0, 0.5)}


def _limits(u):
    key = (u.get("path") or "").split(".")[-1]
    return _LIMITS.get(key, (u["lo"] / 1e3 if u["lo"] > 0 else u["lo"] - 1e3, u["hi"] * 1e3))


def options(form, cal, library=None):
    """What only the person can decide when no set of unknowns reaches the data:
    another grade of the filler (a library entry of the same family with a
    different value), the other content basis, or to stop."""
    out = []
    library = library or {}
    ph = (form.get("phases") or [{}])[0]
    mid = ph.get("material_id")
    me = library.get(mid) or {}
    props = {m.get("property") for m in cal.get("measurements") or []}
    prop = {"k": "k", "sigma": "sigma", "eps_r": "eps_r", "E": "E", "alpha": "alpha"}.get(next(iter(props), "k"), "k")
    words = {w for w in re.findall(r"[a-z]{4,}", (me.get("name") or "").lower()) if w not in _GENERIC}
    v0 = (ph.get("props") or me.get("props") or {}).get(prop)
    for oid, o in library.items():
        if oid == mid or not words:
            continue
        ow = {w for w in re.findall(r"[a-z]{4,}", (o.get("name") or "").lower()) if w not in _GENERIC}
        ov = (o.get("props") or {}).get(prop)
        if words & ow and ov is not None and (v0 is None or abs(float(ov) / float(v0) - 1.0) > 0.2):
            out.append({"id": f"material:{oid}", "label": f"{o.get('name') or oid} ({prop} {float(ov):g})"})
    basis = (ph.get("fraction") or {}).get("basis") or "vol"
    out.append({"id": "basis:" + ("wt" if basis == "vol" else "vol"),
                "label": "wt%" if basis == "vol" else "vol%"})
    out.append({"id": "stop", "label": "stop"})
    return out[:6]


def apply_answer(form, cal, answer, library=None):
    """The form and calibration after the person's answer to options()."""
    form = copy.deepcopy(form)
    cal = copy.deepcopy(cal)
    library = library or {}
    if answer.startswith("material:"):
        oid = answer.split(":", 1)[1]
        o = library.get(oid)
        if o:
            for ph in form.get("phases") or []:
                ph["material_id"] = oid
                ph["props"] = dict(o.get("props") or {})
                ph["name"] = o.get("name") or oid
    elif answer.startswith("basis:"):
        b = answer.split(":", 1)[1]
        for ph in form.get("phases") or []:
            ph.setdefault("fraction", {})["basis"] = b
    return form, cal


_GENERIC = {"filler", "matrix", "resin", "powder", "grade", "particles", "spheres", "isotropic", "approximation"}


def look_alike(form, summ, library, lang="en"):
    """A calibrated material value close to another grade in the library ("silica k 6.39: crystalline silica
    (quartz) holds 6.5"): the grade the measurements may have come from."""
    out = []
    for s in summ:
        path = s.get("path") or ""
        parts = path.split(".")
        if len(parts) < 3 or parts[-2] != "props":
            continue
        prop = parts[-1]
        if parts[0] == "matrix":
            continue                     # a resin near another library resin (epoxy 0.25 ~ SU-8 0.2) is no grade of it
        ent = (form.get("phases") or [{}])[int(parts[1])]
        mid = (ent or {}).get("material_id")
        me = library.get(mid) or {}
        words = {w for w in re.findall(r"[a-z]{4,}", (me.get("name") or "").lower()) if w not in _GENERIC}
        v = float(s["map"])
        for oid, o in library.items():
            ov = (o.get("props") or {}).get(prop)
            if oid == mid or ov is None or not words:
                continue
            ow = {w for w in re.findall(r"[a-z]{4,}", (o.get("name") or "").lower()) if w not in _GENERIC}
            if words & ow and abs(float(ov) / v - 1.0) <= 0.2:
                out.append((s["label"], v, o.get("name") or oid, float(ov)))
    if not out:
        return ""
    ko = lang == "ko"
    return " " + "; ".join((f"{a}의 {v:.3g}는 라이브러리의 {n}({ov:g})에 가깝습니다 - 측정한 재료가 그 등급일 수 있습니다." if ko else
                            f"{a} {v:.3g} is close to {n} in the library ({ov:g}): the measured material may be that grade.")
                           for a, v, n, ov in out)


def far_from_library(form, summ, library, lang="en"):
    """A calibrated material value more than three times off its library value (silica CTE 16.7 against 0.5):
    reached, but more likely something else differs - the other component's value, the content basis, the grade."""
    out = []
    for s in summ:
        parts = (s.get("path") or "").split(".")
        if len(parts) < 3 or parts[-2] != "props":
            continue
        ent = form.get("matrix") if parts[0] == "matrix" else (form.get("phases") or [{}])[int(parts[1])]
        lib = ((library.get((ent or {}).get("material_id")) or {}).get("props") or {}).get(parts[-1])
        try:
            r = float(s["map"]) / float(lib)
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        if r > 3.0 or r < 1.0 / 3.0:
            out.append((s["label"], float(s["map"]), float(lib), r))
    if not out:
        return ""
    ko = lang == "ko"
    return " " + "; ".join((f"다만 {a} {v:.3g}는 라이브러리 값({lv:g})의 {rr:.2g}배로 그 재료의 값이라 보기 어렵습니다. 다른 성분의 값, "
                            f"함량 기준(vol/wt), 재료 등급이 다를 가능성을 먼저 확인하세요(예: 다른 보정 대상으로 다시 보정)." if ko else
                            f"Note that {a} {v:.3g} is {rr:.2g} times its library value ({lv:g}), hardly that material's own: the "
                            f"other component's value, the content basis (vol/wt) or the grade may differ - worth a calibration "
                            f"of other unknowns.") for a, v, lv, rr in out)


def explain(out, old, result, lang="en", form=None, library=None):
    """The AI tab's words for a next_round answer."""
    ko = lang == "ko"
    L = lambda a, b: a if ko else b                                               # noqa: E731
    summ = result.get("unknowns") or []
    rows = result.get("measurements") or []
    vals = "; ".join(f"{s['label']} = {float(s['map']):.3g} {s.get('unit', '')}".strip() for s in summ)
    near = ", ".join(f"{r.get('label')}: {L('측정', 'measured')} {float(r['measured']):.3g}, RVE {float(r['direct']):.3g}"
                     for r in rows if r.get("direct") is not None)
    if out["action"] == "done":
        alike = look_alike(form or {}, summ, library or {}, lang) if form and library else ""
        # a value far from its library entry is noted, unless another grade in the library explains it already
        far = far_from_library(form or {}, [s for s in summ if s["label"] not in alike], library or {}, lang)
        return L(f"보정이 측정에 닿았습니다. {vals}. ({near})", f"The calibration reaches the data: {vals} ({near}).") + alike + far
    if out["action"] == "ask":
        return L(f"측정에 닿지 않았습니다 ({near}). 범위를 더 넓힌 경우와 아직 해 보지 않은 보정 대상을, 이번 RVE 결과로 보정한 "
                 f"유효매질 모델로 시험했지만 측정에 닿는 조합이 없습니다. 재료 등급이나 함량 기준이 입력과 다를 수 있습니다. "
                 f"아래에서 고르거나, 직접 알려 주세요(예: '결정질 실리카로', 'wt%로').",
                 f"The data were not reached ({near}). A wider range and the unknowns not yet tried were tested on the "
                 f"effective-medium model corrected by this RVE result, and nothing reaches the data: the material grade or "
                 f"the content basis may differ from the input. Choose below, or say what to change (e.g. 'crystalline "
                 f"silica', 'wt%').")
    if out["action"] == "stop" and out.get("why") == "rounds":
        return L(f"측정에 닿지 않았습니다 ({near}). AI가 범위와 대상을 바꿔 안전 한도({_rounds()}라운드)까지 다시 보정했지만 닿지 않아 멈춥니다. "
                 f"Calibration 탭의 'Every parameter set solved'와 측정값·함량 기준·재료 등급을 확인하세요.",
                 f"The data were not reached ({near}). The AI changed ranges and unknowns up to the safety limit ({_rounds()} rounds) "
                 f"without reaching them, so it stops: see 'Every parameter set solved' in the "
                 f"Calibration tab, and check the values, the content basis and the material grade.")
    if out["action"] == "stop":
        return L(f"측정에 닿지 않았습니다 ({near}). 범위를 넓히거나 보정 대상을 바꿔도 유효매질 점검에서 측정에 닿는 조합이 없어 "
                 f"멈춥니다. 측정값, 함량 기준(vol/wt), 재료 등급, 입자 크기를 확인하세요.",
                 f"The data were not reached ({near}). Neither a wider range nor other unknowns reach them on the "
                 f"effective-medium check, so it stops here: check the values, the content basis (vol/wt), the "
                 f"material grade and the particle size.")
    new = "; ".join(f"{u['label']} {u['lo']:.3g}~{u['hi']:.3g}" for u in out["unknowns"])
    est = ", ".join(f"{k} ≈ {v:.3g}" for k, v in (out.get("estimate") or {}).items())
    if out.get("miss") is None:
        # another property than k: no effective-medium check, the next calibration is simply run
        if out.get("why") == "widened":
            return L(f"측정에 닿지 않았습니다 ({near}). 추정이 범위 끝에 걸려 있어 범위를 넓혀 다시 보정합니다: {new}.",
                     f"The data were not reached ({near}). The estimate sat at the end of its range, which is widened "
                     f"and run again: {new}.")
        olds = ", ".join(u["label"] for u in old)
        return L(f"측정에 닿지 않았습니다 ({near}). {olds}의 범위를 끝까지 넓혀도 닿지 않아 보정 대상을 바꿔 다시 보정합니다: {new}.",
                 f"The data were not reached ({near}). {olds} cannot reach them within physical limits, so other unknowns "
                 f"are calibrated: {new}.")
    if out.get("why") == "widened":
        return L(f"측정에 닿지 않았습니다 ({near}). 추정이 범위 끝에 걸려 있어 범위를 넓혀 다시 보정합니다: {new}. "
                 f"RVE와 유효매질 모델의 차이를 반영한 점검에서 측정과 {100 * out.get('miss', 0):.1f}% 이내 ({est}).",
                 f"The data were not reached ({near}). The estimate sat at the end of its range, which is widened "
                 f"and run again: {new}; on the effective-medium check corrected by the RVE it comes within "
                 f"{100 * out.get('miss', 0):.1f} % ({est}).")
    olds = ", ".join(u["label"] for u in old)
    return L(f"측정에 닿지 않았습니다 ({near}). {olds}만으로는 RVE와 유효매질 모델의 차이를 반영해도 닿지 않아 보정 대상을 바꿔 "
             f"다시 보정합니다: {new}. 점검에서 측정과 {100 * out.get('miss', 0):.1f}% 이내 ({est}).",
             f"The data were not reached ({near}). {olds} alone cannot reach them, also with the RVE's correction "
             f"of the effective-medium model, so other unknowns are calibrated: {new}; the check comes within "
             f"{100 * out.get('miss', 0):.1f} % ({est}).")


def _rounds():
    from .loop import max_rounds
    return max_rounds()


def _near(v, end, span, scale):
    if scale == "log" and v > 0 and end > 0:
        return abs(math.log(v / end)) <= 0.03 * abs(span)
    return abs(v - end) <= 0.03 * abs(span)
