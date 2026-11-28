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
    if key == "rc_elec":
        # the electrical contact resistance of touching particles (a paste): the range of the Calibration tab
        return {"key": key, "path": f"phases.{i}.rc_elec", "label": f"{name}: electrical contact resistance R_c,e",
                "unit": "Ω·m²", "lo": 1e-17 if not wide else 1e-19, "hi": 1e-11 if not wide else 1e-9, "scale": "log",
                "links": []}
    if key == "filler_k":
        # as asked: the span a filler's own value may take (PLAUSIBLE, 0.1-10 x the library value: grades, purity,
        # porosity) - 2 x left a silica grade of 3 W/m·K (2.2 x) for a second round
        k = float(pp.get("k") or 1.0)
        return {"key": key, "path": f"phases.{i}.props.k", "label": f"{name}: thermal conductivity", "unit": "W/m·K",
                "lo": _r3(k * (0.5 if wide else 0.1)), "hi": _r3(k * (30.0 if wide else 10.0)), "scale": "log", "links": []}
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


# The sets of unknowns tried for a conductivity. matrix_k + r_int is the pair a series of contents may need: the
# RVE of touching particles depends on the content otherwise than a mean field does (on the voxels it rises more
# steeply - shared voxel faces conduct; on the tetrahedral FEM less steeply - resin films separate the particles:
# silicone + AlN 30/40/50 vol%, RVE / model 0.89 / 0.80 / 0.70), so a set fitted on the model can leave one end of
# a content series short and the other over at once - no single unknown moves both ways; the resin's k weighs most
# at low contents, R_int (with R_c following it) at high ones. Found on the voxel examples 2026-11-26: R_int alone,
# the filler's k, the resin's k and filler + resin k all missed by 13-20 % on the RVE; matrix k + R_int reached
# within 5 %. On the FEM (2026-11-28) every example reached with the single unknown it planned.
PLANS = [("r_int",), ("filler_k",), ("matrix_k",), ("matrix_k", "r_int"), ("filler_k", "matrix_k"),
         ("filler_k", "r_int")]
# the sets of unknowns tried for another property, judged on its closed form (QUICK_MODEL)
PLANS_OF = {"alpha": [("matrix_alpha",), ("filler_alpha",), ("matrix_alpha", "filler_alpha")],
            "eps_r": [("matrix_eps_r",), ("filler_eps_r",), ("matrix_eps_r", "filler_eps_r")],
            "E": [("matrix_E",), ("filler_E",), ("matrix_E", "filler_E")],
            "sigma": [("filler_sigma",), ("matrix_sigma",)]}
EXTRA_UNKNOWN = 0.03     # an extra unknown is taken only when it fits better by more than this (relative miss)
TRY_ANYWAY = 0.30        # nothing within TOL on the model: the best set still within this is run on the RVE once
# a fitted material value counts as that material's own within these factors of its library value; beyond them the
# fit stands for something the model lacks (the shape, the grade, the basis) and the set is not chosen by itself
PLAUSIBLE = {("matrix", "k"): (0.5, 2.0), ("filler", "k"): (0.1, 10.0)}
PLAUSIBLE_DEFAULT = (1.0 / 3.0, 3.0)


def _plausible(form, unk, est):
    """Whether every fitted material value of a set lies within PLAUSIBLE of the value it started from."""
    for u, v in zip(unk, est):
        parts = (u.get("path") or "").split(".")
        if len(parts) < 3 or parts[-2] != "props" or v is None:
            continue                         # a resistance: any value in its range is a resistance
        prop = parts[-1]
        who = "matrix" if parts[0] == "matrix" else "filler"
        ent = form.get("matrix") if who == "matrix" else (form.get("phases") or [{}])[int(parts[1])]
        try:
            r = float(v) / float(((ent or {}).get("props") or {})[prop])
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            continue
        lo, hi = PLAUSIBLE.get((who, prop), PLAUSIBLE_DEFAULT)
        if not lo <= r <= hi:
            return False
    return True


def _score(t):
    k = t["keys"]
    n = t.get("n") or (len(k) if isinstance(k, (list, tuple)) else len(str(k).split(":")[0].split("+")))
    return t["miss"] + EXTRA_UNKNOWN * (n - 1)


def _choose(tried, bounds_ok=True, rve_below=False):
    """(choice, ok, asked_close) before any RVE run. The request's own set runs when the model reaches the data
    with it (miss <= TOL), and also when it comes within TRY_ANYWAY with plausible, determined values: the model has
    not been corrected by an RVE yet, and a mean field and an RVE of touching particles differ by 15-30 % - the
    first round on the RVE corrects it, and the request is not overruled by the model's own error. Not, though,
    when the error can only take the RVE further away: on the tetrahedral FEM (rve_below) the resin films between
    touching particles put the RVE 2-30 % below the mean field (every example of 2026-11-28 at its true values:
    spheres 0.70-0.98 of the model, BN platelets 0.83-1.01), so a set whose fit stays short of the data
    (`short`) does not reach them on the RVE either. Otherwise the set that fits best with plausible values."""
    ok = [i for i, t in enumerate(tried) if t["miss"] is not None and t["miss"] <= TOL and not t.get("underdetermined")
          and t.get("plausible", True)]
    a = tried[0] if tried else {}
    close = (bounds_ok and a.get("miss") is not None and a["miss"] <= TRY_ANYWAY and not a.get("underdetermined")
             and a.get("plausible", True) and not (rve_below and a.get("short")))
    if 0 in ok or close:
        return 0, ok, bool(close and 0 not in ok)
    return (min(ok, key=lambda i: _score(tried[i])) if ok else 0), ok, False


def precheck(form, cal, asked, lang="en"):
    """{rows, plans, choice, asked_ok, text} for a calibration about to run.
    asked: the unknown keys of the request (r_int, r_contact, filler_k).
    Every set is tried on the model; the request's own is run when it reaches the data with values the materials
    can have, otherwise the set that fits best (an extra unknown only for a clearly better fit)."""
    k = _key(form, cal, asked)
    if k in _CACHE:
        return copy.deepcopy(_CACHE[k])
    props = {m.get("property") for m in cal.get("measurements") or []}
    if props and "k" not in props:
        out = _precheck_quick(form, cal, asked)
        if out is not None:
            _CACHE[k] = copy.deepcopy(out)
        return out
    rows = _bounds(form, cal)
    if rows is None or not rows or len(rows) != len(cal.get("measurements") or []):
        return None
    n = _n_meas(cal)
    plans = [tuple(asked)] + [p for p in PLANS if p != tuple(asked) and len(p) <= n]
    tried = []
    for p in plans:
        unk = [unknown_entry(x, form, wide=p != tuple(asked)) for x in p]
        r = _try(form, cal, unk)
        if r is None:
            tried.append({"keys": list(p), "miss": None, "unknowns": unk})
            continue
        miss, fit, pv = r
        und = bool((pv.get("identifiability") or {}).get("underdetermined")) or len(p) > n
        est = [s["map"] for s in pv.get("unknowns") or []]
        # the model's best still below a measurement by more than TOL
        short = any(f < float(m["value"]) * (1.0 - TOL) for f, m in zip(fit, cal.get("measurements") or []))
        tried.append({"keys": list(p), "miss": miss, "fit": fit, "unknowns": unk, "underdetermined": und,
                      "plausible": _plausible(form, unk, est), "short": short,
                      "estimate": {u["label"]: v for u, v in zip(unk, est)}})
    above = [r for r in rows if r["value"] > r["parallel"] * 1.05]
    fem = _fem_thermal(form)
    choice, ok, close = _choose(tried, bounds_ok=not above, rve_below=fem)
    out = {"rows": rows, "plans": tried, "choice": choice, "asked_ok": 0 in ok, "asked_close": close,
           "reachable": bool(ok) or close, "above": [r["label"] for r in above], "model": "emt", "fem": fem}
    _CACHE[k] = copy.deepcopy(out)
    return out


def _fem_thermal(form):
    """Whether MPSim solves this case's thermal conductivity on the body-fitted tetrahedral FEM (its default since
    5.12.0; voxels for what the mesh cannot carry, or when the case asks for them)."""
    mp = _mp()
    if mp is None:
        return False
    CA, _DOE, S = mp
    try:
        from mpsim import pipeline as PL
        return PL.thermal_backend(S.normalize(CA.fill_props(form)), "puma").partition("+")[0] == "tet"
    except Exception:                                                # noqa: BLE001
        return False


def _n_meas(cal):
    """The measurements that tell unknowns apart: one per sample (content and property) measured."""
    seen = set()
    for m in cal.get("measurements") or []:
        st = m.get("set") or []
        st = tuple(sorted((s["path"], float(s["value"])) for s in st)) if isinstance(st, list) else tuple(sorted(st.items()))
        seen.add((m.get("property"), m.get("direction"), st))
    return len(seen)


# ---------------------------------------------------------------------- closed forms for the other properties
# What the conductivity's effective-medium preview does for k, these do for the other properties a calibration
# fits: a closed form for spheres, corrected by what the RVE gave (scale), tells which set of unknowns reaches the
# data and about where - so the next calibration starts on the right range, instead of widening ten times per
# round (one 14-minute round each for the silica CTE example).
QUICK_MODEL = {"alpha": "Kerner", "eps_r": "Maxwell Garnett", "E": "Mori-Tanaka"}


def _kg(p):
    E = float(p.get("E") or 1.0)
    nu = min(0.499, max(0.0, float(p.get("nu") if p.get("nu") is not None else 0.3)))
    return E / (3.0 * (1.0 - 2.0 * nu)), E / (2.0 * (1.0 + nu))


def quick_value(row, prop):
    """The closed form of prop for one sample: row = {matrix: props, phases: [(vf, props)]}; None if none."""
    m = row["matrix"]
    ph = [(v, p) for v, p in row["phases"] if v > 0]
    phi = sum(v for v, _ in ph)
    try:
        if prop == "eps_r":
            e = float(m["eps_r"])
            b = sum(v * (float(p["eps_r"]) - e) / (float(p["eps_r"]) + 2.0 * e) for v, p in ph)
            return e * (1.0 + 2.0 * b) / (1.0 - b)
        if prop in ("alpha", "E"):
            Km, Gm = _kg(m)
            if phi <= 0:
                return float(m["alpha"] if prop == "alpha" else m["E"])
            kgs = [(v, *_kg(p), float(p.get("alpha") or 0.0)) for v, p in ph]
            Kf = sum(v * k for v, k, _, _ in kgs) / phi
            Gf = sum(v * g for v, _, g, _ in kgs) / phi
            if prop == "E":
                fm = Gm * (9 * Km + 8 * Gm) / (6 * (Km + 2 * Gm))
                K = Km + phi * (Kf - Km) / (1 + (1 - phi) * (Kf - Km) / (Km + 4 * Gm / 3))
                G = Gm + phi * (Gf - Gm) / (1 + (1 - phi) * (Gf - Gm) / (Gm + fm))
                return 9 * K * G / (3 * K + G)
            # Kerner (1956): the expansion of spheres in a matrix
            af = sum(v * k * a for v, k, _, a in kgs) / sum(v * k for v, k, _, _ in kgs)
            am = float(m["alpha"])
            mean = (1 - phi) * am + phi * af
            return mean - (am - af) * (1 - phi) * phi * (1 / Km - 1 / Kf) / ((1 - phi) / Kf + phi / Km + 3 / (4 * Gm))
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None
    return None


def _quick_rows(form, cal):
    """Per measurement: the sample's matrix and fillers (volume fractions, properties) - the content basis and the
    densities resolved once by MPSim (they do not change with the unknowns)."""
    mp = _mp()
    if mp is None:
        return None
    CA, DOE, S = mp
    base = CA.fill_props(form)
    rows = []
    for m in cal.get("measurements") or []:
        f = copy.deepcopy(base)
        st = m.get("set") or []
        for path, v in (st.items() if isinstance(st, dict) else ((s["path"], s["value"]) for s in st)):
            DOE.set_path(f, path, float(v))
        try:
            sp = S.normalize(f)
        except ValueError:
            return None
        rows.append({"prop": m["property"], "value": float(m["value"]), "label": m.get("label"),
                     "matrix": dict(sp["matrix"]["props"]),
                     "phases": [(0.0 if p.get("void") else float(p["vf"]), dict(p.get("props") or {})) for p in sp["phases"]]})
    return rows


def _quick_at(rows, unk, theta):
    out = []
    for r in rows:
        rr = {"matrix": dict(r["matrix"]), "phases": [(v, dict(p)) for v, p in r["phases"]]}
        for u, t in zip(unk, theta):
            parts = u["path"].split(".")
            prop = parts[-1]
            if parts[0] == "matrix":
                rr["matrix"][prop] = t
            else:
                rr["phases"][int(parts[1])][1][prop] = t
        out.append(quick_value(rr, r["prop"]))
    return out


def _quick_fit(rows, unk, scale=None):
    """The unknowns' values that bring the closed form (times scale) closest to every measurement, on a grid over
    their widest ranges: (worst relative miss, values, computed) or None."""
    import itertools
    import numpy as np
    axes = []
    for u in unk:
        lim_lo, lim_hi = _limits(u)
        if u["scale"] == "log":
            lo, hi = max(lim_lo, u["lo"] / 100.0), min(lim_hi, u["hi"] * 100.0)
        else:
            lo, hi = u["lo"], u["hi"]
        n = 161 if len(unk) == 1 else 41
        axes.append(np.exp(np.linspace(math.log(max(lo, 1e-30)), math.log(hi), n)) if u["scale"] == "log" and lo > 0
                    else np.linspace(lo, hi, n))
    best = None
    for theta in itertools.product(*axes):
        y = _quick_at(rows, unk, theta)
        if any(v is None or not v > 0 for v in y):
            continue
        if scale:
            y = [v * c for v, c in zip(y, scale)]
        miss = max(abs(v / r["value"] - 1.0) for v, r in zip(y, rows))
        if best is None or miss < best[0]:
            best = (miss, [float(t) for t in theta], y)
    return best


def _around(u, v, f=3.0):
    """An unknown's range about a value (a factor f each way, within the physical limits)."""
    u = dict(u)
    lim_lo, lim_hi = _limits(u)
    if u["scale"] == "log" and v > 0:
        u["lo"], u["hi"] = max(lim_lo, _r3(v / f)), min(lim_hi, _r3(v * f))
    else:
        span = max(abs(u["hi"] - u["lo"]), 1e-9)
        u["lo"], u["hi"] = max(lim_lo, v - 0.5 * span), min(lim_hi, v + 0.5 * span)
    return u


def _quick_plans(form, cal, plans, asked, scale=None):
    rows = _quick_rows(form, cal)
    if not rows or any(quick_value(r, r["prop"]) is None for r in rows):
        return None, rows
    n = _n_meas(cal)
    tried = []
    for p in plans:
        unk = [unknown_entry(x, form, wide=tuple(p) != tuple(asked)) for x in p]
        if not all(unk):
            continue
        r = _quick_fit(rows, unk, scale)
        if r is None:
            tried.append({"keys": list(p), "miss": None, "unknowns": unk})
            continue
        miss, th, y = r
        # the run's range: the request's own range, stretched to hold the estimate with room on either side
        run = []
        for u, v in zip(unk, th):
            a = _around(u, v)
            if tuple(p) == tuple(asked) and scale is None:
                a["lo"], a["hi"] = min(u["lo"], a["lo"]), max(u["hi"], a["hi"])
            run.append(a)
        tried.append({"keys": list(p), "miss": miss, "fit": y, "unknowns": run, "underdetermined": len(p) > n,
                      "plausible": _plausible(form, unk, th), "estimate": {u["label"]: v for u, v in zip(unk, th)}})
    return tried, rows


def _precheck_quick(form, cal, asked):
    """The precheck of a CTE, permittivity or modulus calibration on the closed form (QUICK_MODEL)."""
    props = {m.get("property") for m in cal.get("measurements") or []}
    if len(props) != 1 or next(iter(props)) not in QUICK_MODEL:
        return None
    prop = next(iter(props))
    n = _n_meas(cal)
    plans = [tuple(asked)] + [p for p in PLANS_OF[prop] if p != tuple(asked) and len(p) <= n]
    tried, rows = _quick_plans(form, cal, plans, asked)
    if not tried:
        return None
    choice, ok, close = _choose(tried)
    lib_rows = [{"label": r["label"], "value": r["value"], "model": quick_value(r, prop)} for r in rows]
    return {"rows": lib_rows, "plans": tried, "choice": choice, "asked_ok": 0 in ok, "asked_close": close,
            "reachable": bool(ok) or close, "above": [], "model": QUICK_MODEL[prop], "property": prop}


def _name(kk):
    return str(kk).split(":")[0]


SAME_SET_RUNS = 3        # one set of unknowns is run at most this often (its ranges moved in between)


def _emt_scale(form, cal, unknowns, rows, th):
    """Per measurement: what the RVE gave over the mean field at the estimate (the contacts the RVE has)."""
    mp = _mp()
    if mp is None:
        return None
    CA = mp[0]
    job = job_of(form, cal, unknowns)
    try:
        from mpsim import doe as DOE
        from mpsim import spec as S
        import numpy as np
        base = CA.fill_props(form)
        U = [CA._Unknown(u) for u in job["unknowns"]]
        scale = []
        for m, r in zip(job["measurements"], rows):
            f = copy.deepcopy(base)
            for path, v in (m.get("set") or {}).items():
                DOE.set_path(f, path, v)
            sp = S.normalize(CA._set_theta(f, U, th))
            emt = float(CA._theory_model(sp, U, np.array([th]), m.get("direction") or "z")[0])
            direct = float(r.get("direct") or 0.0)
            scale.append(direct / emt if emt > 0 and direct > 0 else 1.0)
        return scale
    except Exception:                                                # noqa: BLE001
        return None


def _widened(unknowns, summ, factor):
    """The same unknowns with the range widened (times factor) at the end the estimate sat on: (unknowns, moved)."""
    wid, moved = [], False
    for u, s in zip(unknowns, summ):
        u = dict(u)
        span = math.log(u["hi"] / u["lo"]) if u["scale"] == "log" and u["lo"] > 0 else (u["hi"] - u["lo"])
        at_lo = s.get("edge") in ("low", "both") or _near(float(s["map"]), u["lo"], span, u["scale"])
        at_hi = s.get("edge") in ("high", "both") or _near(float(s["map"]), u["hi"], span, u["scale"])
        lim_lo, lim_hi = _limits(u)
        if at_lo and u["lo"] > lim_lo * 1.0001:
            u["lo"] = max(lim_lo, _r3(u["lo"] / factor) if u["scale"] == "log" else u["lo"] - 0.5 * span)
            moved = True
        if at_hi and u["hi"] < lim_hi * 0.9999:
            u["hi"] = min(lim_hi, _r3(u["hi"] * factor) if u["scale"] == "log" else u["hi"] + 0.5 * span)
            moved = True
        wid.append(u)
    return wid, moved


def _ranges(unk):
    return ",".join(f"{u['lo']:.3g}-{u['hi']:.3g}" for u in unk)


def _pick(scored, tried_keys, names_tried):
    """The set to run next: the best that reaches the data on the corrected model with values the materials can
    have (an extra unknown only for a clearly better fit); failing that, the most promising set not run yet, once -
    the corrected model is only a guide, the RVE decides."""
    runs = {}
    for k in tried_keys:
        runs[_name(k)] = runs.get(_name(k), 0) + 1
    live = [t for t in scored if t["keys"] not in tried_keys and runs.get(_name(t["keys"]), 0) < SAME_SET_RUNS
            and not t["und"] and t["miss"] is not None]
    ok = [t for t in live if t["miss"] <= TOL and t["plausible"]]
    if ok:
        return min(ok, key=_score)
    new = [t for t in live if t["miss"] <= TRY_ANYWAY and t["plausible"] and _name(t["keys"]) not in names_tried]
    if new:
        t = min(new, key=_score)
        return dict(t, why="promising")
    return None


def next_round(form, cal, unknowns, result, tried_keys, lang="en", library=None):
    """What to run after a calibration result: {action: done | rerun | ask | stop, unknowns, why}.
    The result is read like the calibration tab reads it; the model of the property (the effective-medium preview
    for k, a closed form for the CTE, the permittivity and the modulus) is corrected by what the RVE gave at the
    estimate, and every candidate - the same unknowns over a moved range, and every other set the measurements can
    tell apart - is fitted on it. The best that reaches the data with values the materials can have is run; when
    none does, the most promising set not run yet is run once. When nothing is left, the person is asked (options):
    the particle shape, another grade, the content basis when it was not said, the closest result, or to stop.
    There is no fixed number of rounds: each set is run a few times at most, so the candidates run out."""
    summ = result.get("unknowns") or []
    rows = result.get("measurements") or []
    unreached = any(u.get("unreached") for u in summ)
    off = [r for r in rows if abs(float(r.get("residual_sigma") or 0.0)) > 2.5]
    if not unreached and not off:
        return {"action": "done", "why": "reached"}
    mp = _mp()
    props = {m.get("property") for m in cal.get("measurements") or []}
    prop = next(iter(props)) if len(props) == 1 else None
    keys = "+".join(u.get("key") or u["path"] for u in unknowns)
    names_tried = {_name(k) for k in tried_keys} | {keys}
    th = [float(s["map"]) for s in summ]
    n = _n_meas(cal)
    scored, scale, model = [], None, None
    if mp is not None and props == {"k"}:
        model = "emt"
        scale = _emt_scale(form, cal, unknowns, rows, th)
        cands = []
        wid, moved = _widened(unknowns, summ, 100.0)
        if moved:
            cands.append((keys + ":" + _ranges(wid), wid, "widened"))
        for p in PLANS:
            kk = "+".join(p)
            if kk in names_tried or len(p) > n:
                continue
            cands.append((kk, [unknown_entry(x, form, wide=True) for x in p], "switched"))
        for kk, unk, how in cands:
            r = _try(form, cal, unk, scale)
            if r is None:
                continue
            miss, fit, pv = r
            est = [s["map"] for s in pv.get("unknowns") or []]
            scored.append({"keys": kk, "unknowns": unk, "why": how, "miss": miss, "est": est,
                           "plausible": _plausible(form, unk, est), "n": len(unk), "fit": fit,
                           "und": bool((pv.get("identifiability") or {}).get("underdetermined")) or len(unk) > n})
    elif mp is not None and prop in QUICK_MODEL:
        rq = _quick_rows(form, cal)
        y0 = _quick_at(rq, unknowns, th) if rq else None
        if y0 and all(v is not None and v > 0 for v in y0) and all(float(r.get("direct") or 0) > 0 for r in rows):
            model = QUICK_MODEL[prop]
            scale = [float(r["direct"]) / v for r, v in zip(rows, y0)]
            own = tuple(u.get("key") or u["path"] for u in unknowns)
            for p in [own] + [q for q in PLANS_OF[prop] if q != own and len(q) <= n]:
                unk = [unknown_entry(x, form, wide=True) for x in p]
                if not all(unk):
                    continue
                r = _quick_fit(rq, unk, scale)
                if r is None:
                    continue
                miss, est, y = r
                run = [_around(u, v) for u, v in zip(unk, est)]
                scored.append({"keys": "+".join(p) + ":" + _ranges(run), "unknowns": run, "miss": miss, "est": est,
                               "why": "widened" if p == own else "switched", "plausible": _plausible(form, unk, est),
                               "n": len(unk), "fit": y, "und": len(p) > n})
    if model is None:
        # no model of the property (the electrical conductivity): the range the estimate sat at the end of is
        # widened while it can be, then each other set of unknowns of that property is run once
        wid, moved = _widened(unknowns, summ, 10.0)
        wkey = keys + ":" + _ranges(wid)
        if moved and wkey not in tried_keys:
            return {"action": "rerun", "unknowns": wid, "keys": wkey, "why": "widened", "miss": None}
        for p in PLANS_OF.get(prop, []):
            kk = "+".join(p)
            if kk in names_tried or len(p) > n:
                continue
            unk = [unknown_entry(x, form, wide=True) for x in p]
            if all(unk):
                return {"action": "rerun", "unknowns": unk, "keys": kk, "why": "switched", "miss": None}
        return {"action": "ask", "why": "no_plan", "options": options(form, cal, library, lang)}
    pick = _pick(scored, tried_keys, names_tried)
    if pick is not None:
        return {"action": "rerun", "unknowns": pick["unknowns"], "keys": pick["keys"], "why": pick["why"],
                "miss": pick["miss"], "model": model, "scale": scale,
                "estimate": {u["label"]: v for u, v in zip(pick["unknowns"], pick["est"])}}
    # nothing left to run: the closest set on the corrected model, and why it is not run
    close = sorted([t for t in scored if t["miss"] is not None], key=lambda t: t["miss"])
    closest = None
    if close:
        t = close[0]
        closest = {"keys": _name(t["keys"]), "miss": t["miss"], "plausible": t["plausible"],
                   "estimate": {u["label"]: v for u, v in zip(t["unknowns"], t["est"])}}
    return {"action": "ask", "why": "no_plan", "scale": scale, "model": model, "closest": closest,
            "options": options(form, cal, library, lang)}


# the widest range an unknown is widened to: beyond them a value is not a material's
_LIMITS = {"r_int": (1e-12, 1e-3), "r_contact": (1e-12, 1e-3), "rc_elec": (1e-21, 1e-7), "k": (1e-3, 3000.0), "sigma": (1e-16, 1e9),
           "eps_r": (1.0, 1e5), "E": (1e-4, 2000.0), "alpha": (0.0, 500.0), "nu": (0.0, 0.5)}


def _limits(u):
    key = (u.get("path") or "").split(".")[-1]
    return _LIMITS.get(key, (u["lo"] / 1e3 if u["lo"] > 0 else u["lo"] - 1e3, u["hi"] * 1e3))


# the aspect ratios offered for platelets and fibres whose shape the request did not give in numbers
ASPECTS = {"platelet": (10, 20, 50), "fiber": (5, 20, 50)}


def axis_mode(said, ph):
    """MPSim's orientation mode for how the particles are said to lie. The words name the particle: "lying in the
    plane" (xy) or "standing up / aligned through the thickness" (z). MPSim orients a particle's symmetry axis, which
    for a fibre or a needle is its length but for a platelet (spheroid c/a < 1) is the normal of the plate: a platelet
    lying in the xy plane has its axis along z, and one standing up has its axis in the xy plane."""
    if said not in ("xy", "z"):
        return said
    sz = ph.get("size") or {}
    if ph.get("shape") == "spheroid" and float(sz.get("aspect") or 1.0) < 1.0:
        return "z" if said == "xy" else "xy"
    return said


# Randomly oriented platelets or fibres exist only below a content set by their aspect ratio: thin platelets order
# above rho*D^3 ≈ 4, a volume fraction of about pi/aspect (Eppenga & Frenkel 1984), rods above about 3.3/aspect
# (Onsager 1949). Above it a random packing is crowded - the placement jams and the clump relaxation crawls without
# reaching the content (a 40 wt% BN of aspect 20, 28 vol% against a limit of 16 %, stood at a size scale of 0.85
# after 90,000 steps; laid in the plane, the same sample packed in 6 s by one random placement round) - and real
# films and pads hold such particles lying in the plane.
ISO_LIMIT = {"platelet": math.pi, "fiber": 3.3}


def _vf_max(form, sets=()):
    """The highest volume fraction each phase takes: the form's own content and every set of values (a measurement's
    sample, the top of a DOE range), the basis and densities resolved by MPSim. None without MPSim."""
    mp = _mp()
    if mp is None:
        return None
    CA, DOE, S = mp
    try:
        base = CA.fill_props(form)
    except Exception:                                                # noqa: BLE001
        return None
    best = None
    for st in [[]] + [list(s) for s in sets or []]:
        f = copy.deepcopy(base)
        try:
            for path, v in st:
                DOE.set_path(f, path, float(v))
            vf = [0.0 if p.get("void") else float(p["vf"]) for p in S.normalize(f)["phases"]]
        except Exception:                                            # noqa: BLE001
            continue
        best = vf if best is None else [max(a, b) for a, b in zip(best, vf)]
    return best


def _sets_of(cal=None, doe=None):
    """The sets of values a case takes: each measurement's sample, and the top of each content range of a DOE."""
    out = []
    for m in (cal or {}).get("measurements") or []:
        st = m.get("set") or []
        out.append(list(st.items()) if isinstance(st, dict) else [(s["path"], s["value"]) for s in st])
    for p in (doe or {}).get("parameters") or []:
        if str(p.get("path", "")).endswith("fraction.value") and p.get("max") is not None:
            out.append([(p["path"], p["max"])])
    return out


def crowded(form, cal=None, doe=None, aspect=None):
    """Phases of platelets or fibres, randomly oriented, at more than the content random orientation allows:
    [{"i", "shape", "aspect", "vf", "limit"}]. `aspect` tries another aspect ratio for every such phase."""
    out = []
    vf = None
    for i, ph in enumerate(form.get("phases") or []):
        shape, ar = _shape_of(ph)
        if not shape or ((ph.get("orientation") or {}).get("mode") or "iso") != "iso":
            continue
        ar = float(aspect or ar or 0.0)
        if ar <= 1.0:
            continue
        if vf is None:
            vf = _vf_max(form, _sets_of(cal, doe)) or []
        if i < len(vf) and vf[i] > ISO_LIMIT[shape] / ar:
            out.append({"i": i, "shape": shape, "aspect": ar, "vf": vf[i], "limit": ISO_LIMIT[shape] / ar})
    return out


def lay_in_plane(form, cr):
    """The crowded phases lying in the xy plane (in place)."""
    for c in cr:
        ph = form["phases"][c["i"]]
        ph.setdefault("orientation", {})["mode"] = axis_mode("xy", ph)
    return form


def crowded_note(cr, lang="en", laid=True):
    """What crowded() found: laid in the plane, or (the request said random) a caution."""
    ko = lang == "ko"
    out = []
    for c in cr:
        what = (f"{'판상' if c['shape'] == 'platelet' else '섬유'} 입자(종횡비 {c['aspect']:g})는 {100 * c['vf']:.0f} vol%에서 "
                f"무작위로 놓일 수 없습니다(한계 약 {100 * c['limit']:.0f} vol%)" if ko else
                f"{'platelets' if c['shape'] == 'platelet' else 'fibres'} of aspect ratio {c['aspect']:g} cannot lie at "
                f"random at {100 * c['vf']:.0f} vol% (limit about {100 * c['limit']:.0f} vol%)")
        if laid:
            what += ": 면 방향으로 눕혀 배치합니다" if ko else ": they are placed lying in the plane"
        else:
            what += (": 말씀하신 무작위 배향으로는 배치가 아주 오래 걸리거나 함량에 닿지 않을 수 있습니다" if ko else
                     ": with the random orientation asked for, the placement may take very long or miss the content")
        out.append(what)
    return "; ".join(out)


def _shape_of(ph):
    sz = ph.get("size") or {}
    if ph.get("shape") == "spheroid" and float(sz.get("aspect") or 1.0) < 1.0:
        return "platelet", 1.0 / float(sz["aspect"])
    if ph.get("shape") == "cylinder" and sz.get("length") and sz.get("d"):
        return "fiber", float(sz["length"]) / float(sz["d"])
    return None, None


def options(form, cal, library=None, lang="en"):
    """What only the person can decide when no set of unknowns reaches the data: the aspect ratio of platelets or
    fibres whose shape was not given in numbers (it sets how they conduct and no calibration fits it), another grade
    of the filler (a library entry of the same family with a different value), the content basis when the request
    did not say it (a basis it said is not offered back), the closest result as it stands, or to stop."""
    ko = lang == "ko"
    out = []
    library = library or {}
    said = cal.get("said") or {}
    ph = (form.get("phases") or [{}])[0]
    shape, ar = _shape_of(ph)
    # platelets or fibres measured in-plane, their orientation not said: lying in the plane, as a pad or a film
    # made by casting or pressing usually holds them (random orientation conducts the same in every direction)
    inplane = any((m.get("direction") or "z") in ("x", "y") for m in cal.get("measurements") or [])
    if shape and inplane and not said.get("orientation") and ((ph.get("orientation") or {}).get("mode") or "iso") == "iso":
        out.append({"id": "orient:xy", "label": ("입자가 면 방향으로 누워 정렬 (패드·필름에서 흔함)" if ko else
                                               "particles lying in the plane (usual in pads and films)")})
    if shape and not (said.get("aspect") or [False])[0]:
        for a in ASPECTS[shape]:
            if ar and abs(a / ar - 1.0) < 0.2:
                continue
            # an aspect ratio random orientation cannot hold at this content: the particles are laid in the plane
            flat = not said.get("orientation") and bool(crowded(form, cal, aspect=a))
            out.append({"id": f"aspect:{a:g}", "label": ((f"판상 종횡비 {a:g} (두께 = 지름/{a:g})" if shape == "platelet"
                                                          else f"섬유 종횡비 {a:g} (길이 = 지름×{a:g})")
                                                         + (", 이 함량에서는 면 방향으로 누움" if flat else "")) if ko else
                        ((f"platelets of aspect ratio {a:g} (thickness = diameter/{a:g})" if shape == "platelet"
                          else f"fibres of aspect ratio {a:g} (length = {a:g} diameters)")
                         + (", lying in the plane at this content" if flat else ""))})
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
    if not said.get("basis"):
        basis = (ph.get("fraction") or {}).get("basis") or "vol"
        out.append({"id": "basis:" + ("wt" if basis == "vol" else "vol"),
                    "label": ("함량을 wt%로 보기" if basis == "vol" else "함량을 vol%로 보기") if ko else
                    ("the contents as wt%" if basis == "vol" else "the contents as vol%")})
    out = out[:5]
    out.append({"id": "accept", "label": "가장 가까운 결과로 마치기" if ko else "finish with the closest result"})
    out.append({"id": "stop", "label": "stop"})
    return out


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
        cal.setdefault("said", {})["basis"] = True
    elif answer.startswith("aspect:"):
        a = float(answer.split(":", 1)[1])
        for ph in form.get("phases") or []:
            shape, _ = _shape_of(ph)
            sz = ph.setdefault("size", {})
            if shape == "platelet":
                sz["aspect"] = round(1.0 / a, 6)
            elif shape == "fiber":
                sz["length"] = round(float(sz["d"]) * a, 6)
        cal.setdefault("said", {})["aspect"] = [True] * len(form.get("phases") or [])
        if not cal["said"].get("orientation"):
            lay_in_plane(form, crowded(form, cal))
    elif answer.startswith("orient:"):
        mode = answer.split(":", 1)[1]
        for ph in form.get("phases") or []:
            if _shape_of(ph)[0]:
                ph.setdefault("orientation", {})["mode"] = axis_mode(mode, ph)
        cal.setdefault("said", {})["orientation"] = True
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

    def val(s):
        """An estimate as the data give it: a value, or a bound where the result stops depending on it (the
        posterior does not fall to zero at that end of the range - R_int far below what matters)."""
        u = s.get("unit") or ""
        u = "" if u.strip() in ("-", "—", "–") else " " + u
        v, ci, edge = f"{float(s['map']):.3g}", s.get("ci95") or [None, None], s.get("edge")
        if edge in ("low", "high") and ci[1 if edge == "low" else 0] is not None:
            b = float(ci[1 if edge == "low" else 0])
            if edge == "low":
                return L(f"{s['label']} ≤ {b:.3g}{u} (95 %; 가장 가능성 높은 값 {v} - 그보다 작으면 결과가 거의 변하지 않아 "
                         f"측정으로는 상한만 정해짐)",
                         f"{s['label']} ≤ {b:.3g}{u} (95 %; most probable {v} - below it the result hardly changes, so "
                         f"the data give an upper bound)")
            return L(f"{s['label']} ≥ {b:.3g}{u} (95 %; 가장 가능성 높은 값 {v} - 그보다 크면 결과가 거의 변하지 않아 "
                     f"측정으로는 하한만 정해짐)",
                     f"{s['label']} ≥ {b:.3g}{u} (95 %; most probable {v} - above it the result hardly changes, so "
                     f"the data give a lower bound)")
        return f"{s['label']} = {v}{u}"
    vals = "; ".join(val(s) for s in summ)
    near = ", ".join(f"{r.get('label')}: {L('측정', 'measured')} {float(r['measured']):.3g}, RVE {float(r['direct']):.3g}"
                     for r in rows if r.get("direct") is not None)
    if out["action"] == "done" and out.get("why") != "accepted":
        alike = look_alike(form or {}, summ, library or {}, lang) if form and library else ""
        # a value far from its library entry is noted, unless another grade in the library explains it already
        far = far_from_library(form or {}, [s for s in summ if s["label"] not in alike], library or {}, lang)
        # a material value moved by the fit, said with its library value (silicone k 0.303: 1.5 times 0.2)
        moved = []
        for s in summ:
            parts = (s.get("path") or "").split(".")
            if form and len(parts) >= 3 and parts[-2] == "props" and s["label"] not in alike + far:
                ent = form.get("matrix") if parts[0] == "matrix" else (form.get("phases") or [{}])[int(parts[1])]
                try:
                    lv = float(((ent or {}).get("props") or {})[parts[-1]])
                    r = float(s["map"]) / lv
                except (KeyError, TypeError, ValueError, ZeroDivisionError):
                    continue
                if abs(r - 1.0) >= 0.2 and 1 / 3 <= r <= 3:
                    moved.append(L(f"{s['label']}은 입력값 {lv:g}의 {r:.2g}배", f"{s['label']} is {r:.2g} times the input {lv:g}"))
        mv = (L(" 보정으로 바뀐 재료값: ", " Material values the fit moved: ") + "; ".join(moved) + ".") if moved else ""
        return L(f"보정이 측정에 닿았습니다. {vals}. ({near})", f"The calibration reaches the data: {vals} ({near}).") + mv + alike + far
    model = out.get("model")
    mname = {"emt": L("유효매질 모델", "effective-medium model")}.get(model) or (
        L(f"{model} 식", f"{model} closed form") if model else L("모델", "model"))
    if out["action"] == "ask":
        c = out.get("closest") or {}
        why = ""
        if c:
            ce = ", ".join(f"{k} ≈ {v:.3g}" for k, v in (c.get("estimate") or {}).items())
            miss = 100 * c["miss"]
            if not c.get("plausible"):
                why = L(f" 가장 가까운 조합({ce})은 모델에서 측정과 {miss:.0f}% 차이로 맞지만, 재료값이 라이브러리 값과 너무 멀어 "
                        f"그 재료의 값이라 보기 어려우므로 돌리지 않았습니다.",
                        f" The closest set ({ce}) comes within {miss:.0f} % on the model, but only with material values "
                        f"far from the library's - hardly those materials' own - so it was not run.")
            else:
                why = L(f" 가장 가까운 조합({ce})은 모델에서 측정과 {miss:.0f}% 차이이고, 이미 돌려 보았습니다.",
                        f" The closest set ({ce}) is {miss:.0f} % from the data on the model and was run already.")
        opts = out.get("options") or []
        hint = []
        if any(o["id"].startswith("orient:") for o in opts):
            hint.append(L("면내로 측정한 판상·섬유 입자는 면 방향으로 누워 있으면 무작위 배향보다 면내 열전도가 크게 높습니다",
                          "platelets or fibres measured in-plane conduct far better in the plane when they lie in it than "
                          "when they are randomly oriented"))
        if any(o["id"].startswith("aspect:") for o in opts):
            hint.append(L("판상·섬유 입자의 종횡비는 보정으로 정할 수 없고 열전도에 크게 작용하므로, 실제 종횡비를 고르거나 알려 주세요",
                          "the aspect ratio of platelets or fibres cannot be calibrated and governs how they conduct: choose "
                          "or say the real one"))
        if any(o["id"].startswith("material:") for o in opts):
            hint.append(L("필러 등급이 다를 수 있습니다", "the filler grade may differ"))
        if any(o["id"].startswith("basis:") for o in opts):
            hint.append(L("함량 기준(vol/wt)이 다를 수 있습니다", "the content basis (vol/wt) may differ"))
        return L(f"측정에 닿지 않았습니다 ({near}). 범위를 옮긴 경우와 측정으로 정할 수 있는 다른 보정 대상을, 이번 RVE 결과로 보정한 "
                 f"{mname}로 모두 시험했지만 닿는 조합이 남아 있지 않습니다.{why} "
                 + (" · ".join(hint) + ". " if hint else "")
                 + "아래에서 고르거나 직접 알려 주세요. '가장 가까운 결과로 마치기'는 지금의 보정값을 측정에 닿지 않은 값으로 표시하고 마칩니다.",
                 f"The data were not reached ({near}). A moved range and every other set of unknowns the measurements can "
                 f"tell apart were tried on the {mname} corrected by this RVE result, and none is left that reaches "
                 f"them.{why} " + ("; ".join(hint) + ". " if hint else "")
                 + "Choose below or say what to change; 'finish with the closest result' keeps the present values, marked "
                   "as not reaching the data.")
    if out["action"] == "done" and out.get("why") == "accepted":
        return L(f"측정에 닿지 않은 채 가장 가까운 결과로 마칩니다: {vals} ({near}). 이 값은 측정을 재현하지 않으므로, 쓰기 전에 "
                 f"측정값과 재료·형상을 다시 확인하세요.",
                 f"Finished with the closest result, which does not reach the data: {vals} ({near}). It does not "
                 f"reproduce the measurements: check the values, the materials and the shape before using it.")
    if out["action"] == "stop" and out.get("why") == "rounds":
        return L(f"측정에 닿지 않았습니다 ({near}). AI가 범위와 대상을 바꿔 안전 한도({_rounds()}라운드)까지 다시 보정했지만 닿지 않아 멈춥니다. "
                 f"Calibration 탭의 'Every parameter set solved'와 측정값·함량 기준·재료 등급을 확인하세요.",
                 f"The data were not reached ({near}). The AI changed ranges and unknowns up to the safety limit ({_rounds()} rounds) "
                 f"without reaching them, so it stops: see 'Every parameter set solved' in the "
                 f"Calibration tab, and check the values, the content basis and the material grade.")
    if out["action"] == "stop":
        return L(f"측정에 닿지 않았습니다 ({near}). 범위를 넓히거나 보정 대상을 바꿔도 {mname} 점검에서 측정에 닿는 조합이 없어 "
                 f"멈춥니다. 측정값, 함량 기준(vol/wt), 재료 등급, 입자 크기를 확인하세요.",
                 f"The data were not reached ({near}). Neither a wider range nor other unknowns reach them on the "
                 f"{mname} check, so it stops here: check the values, the content basis (vol/wt), the "
                 f"material grade and the particle size.")
    new = "; ".join(f"{u['label']} {u['lo']:.3g}~{u['hi']:.3g}" for u in out["unknowns"])
    est = ", ".join(f"{k} ≈ {v:.3g}" for k, v in (out.get("estimate") or {}).items())
    if out.get("miss") is None:
        # no model of the property (the electrical conductivity): the next calibration is simply run
        if out.get("why") == "widened":
            return L(f"측정에 닿지 않았습니다 ({near}). 추정이 범위 끝에 걸려 있어 범위를 넓혀 다시 보정합니다: {new}.",
                     f"The data were not reached ({near}). The estimate sat at the end of its range, which is widened "
                     f"and run again: {new}.")
        olds = ", ".join(u["label"] for u in old)
        return L(f"측정에 닿지 않았습니다 ({near}). {olds}의 범위를 끝까지 넓혀도 닿지 않아 보정 대상을 바꿔 다시 보정합니다: {new}.",
                 f"The data were not reached ({near}). {olds} cannot reach them within physical limits, so other unknowns "
                 f"are calibrated: {new}.")
    chk = L(f"RVE 결과로 보정한 {mname}에서 측정과 {100 * out['miss']:.1f}% 이내 ({est})",
            f"on the {mname} corrected by the RVE it comes within {100 * out['miss']:.1f} % ({est})")
    if out.get("why") == "widened":
        return L(f"측정에 닿지 않았습니다 ({near}). 같은 보정 대상의 범위를 추정이 있는 곳으로 옮겨 다시 보정합니다: {new}. {chk}.",
                 f"The data were not reached ({near}). The same unknowns are run again over the range where the estimate "
                 f"lies: {new}; {chk}.")
    olds = ", ".join(u["label"] for u in old)
    if out.get("why") == "promising":
        return L(f"측정에 닿지 않았습니다 ({near}). {olds}만으로는 닿지 않습니다. 보정한 {mname}로는 어느 조합도 확실히 닿지 않지만, "
                 f"가장 가까운 조합을 RVE로 한 번 보정해 봅니다: {new} (모델에서 측정과 {100 * out['miss']:.0f}% 차이, {est}).",
                 f"The data were not reached ({near}). {olds} alone does not reach them. No set is sure to on the corrected "
                 f"{mname}, so the closest is calibrated on the RVE once: {new} ({100 * out['miss']:.0f} % from the data "
                 f"on the model, {est}).")
    return L(f"측정에 닿지 않았습니다 ({near}). {olds}만으로는 닿지 않아 보정 대상을 바꿔 다시 보정합니다: {new}. {chk}.",
             f"The data were not reached ({near}). {olds} alone cannot reach them, so other unknowns are calibrated: "
             f"{new}; {chk}.")


def _rounds():
    from .loop import max_rounds
    return max_rounds()


def _near(v, end, span, scale):
    if scale == "log" and v > 0 and end > 0:
        return abs(math.log(v / end)) <= 0.03 * abs(span)
    return abs(v - end) <= 0.03 * abs(span)
