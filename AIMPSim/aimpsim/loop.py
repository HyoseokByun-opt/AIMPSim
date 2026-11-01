"""Studies run until they answer.

A DOE gives a surrogate; whether it is good enough is judged where the
decision is made, not by a fixed number of cases.

Design ("the least filler that reaches k_z = 3"), each round:
- the recipe from the surrogate (design.recommend);
- how sure its content is: the surrogate's standard deviation at the recipe
  over the slope of the property with the content (dk/dφ), in vol%;
- converged when that is within the content tolerance (1 vol%) and the
  surrogate cross-validates (R² ≥ 0.8). The recipe is then run once with
  three realisations; a check that meets the target ends the study, one that
  does not joins the data and the study goes on;
- otherwise the points that settle the decision are run next: where the
  surrogate is least sure whether the target is met (the straddle score
  1.96 σ - |μ - target|, Bryan et al., NIPS 2005), near the lowest content,
  the recipe itself first, spread apart;
- when the error no longer falls from one round to the next it is the
  scatter of a single run, not the lack of points: the recipe is checked and
  the study ends there, which the answer says.

Optimisation (a property maximised, minimised or brought to a value):
expected improvement (Jones, Schonlau and Welch, J. Global Optim. 13 (1998)
455) on the surrogate; the points of highest expected improvement are run
until it falls below 1 % of the range the runs span. While the surrogate
cross-validates below R² 0.8, half of each round goes where it is least sure
instead. The predicted optimum is then run as a case of the study: it stands
when the run gives what was predicted (within 2 σ) and the fit that now holds
it keeps the optimum there; otherwise the search goes on. Two checks that do
not settle it are the runs' own scatter, and the best run is the answer.

Points are kept apart (MIN_DIST in the unit cube of the factors); once the
runs fill the space at that distance it halves, so the search closes in.

Every loop ends on these criteria; MAX_ROUNDS is only a safety stop
(aimpsim_config.json "max_rounds", 0 = none).
"""
from __future__ import annotations

import math

MAX_ROUNDS = 12
R2_OK = 0.8
NOISE_GAIN = 0.10        # an RMSE that fell by less than this over a round: the runs' own scatter
MIN_DIST = 0.12          # new points this far apart in the unit cube of the factors
LOG_SPAN = 4.0           # decades of an electrical conductivity kept about what is sought (see _opt_round)


def max_rounds():
    try:
        import json
        from .llm import config_path
        with open(config_path(), encoding="utf-8") as fh:
            v = json.load(fh).get("max_rounds")
        return MAX_ROUNDS if v is None else int(v)
    except Exception:                                                # noqa: BLE001
        return MAX_ROUNDS


def _lhs(bounds, params, n, rng):
    import numpy as np
    U = np.zeros((n, len(bounds)))
    V = np.zeros((n, len(bounds)))
    for j, (lo, hi) in enumerate(bounds):
        u = (rng.permutation(n) + rng.random(n)) / n
        U[:, j] = u
        if params[j].get("scale") == "log" and lo > 0:
            V[:, j] = np.exp(np.log(lo) + u * (np.log(hi) - np.log(lo)))
        else:
            V[:, j] = lo + u * (hi - lo)
    return U, V


def _unit(V, bounds, params):
    import numpy as np
    V = np.atleast_2d(np.asarray(V, float))
    U = np.zeros_like(V)
    for j, (lo, hi) in enumerate(bounds):
        if params[j].get("scale") == "log" and lo > 0:
            U[:, j] = (np.log(np.maximum(V[:, j], 1e-300)) - math.log(lo)) / max(math.log(hi) - math.log(lo), 1e-12)
        else:
            U[:, j] = (V[:, j] - lo) / max(hi - lo, 1e-12)
    return U


def _meets(tg, v):
    if tg["op"] == ">=":
        return v >= tg["value"]
    if tg["op"] == "<=":
        return v <= tg["value"]
    return abs(v - tg["value"]) <= 0.02 * abs(tg["value"])


def _pick(V, score, existing_U, bounds, params, k, first=None, positive=False):
    """k points of highest score, MIN_DIST apart from each other and from the runs. Once the
    runs fill the space at that distance (one factor: 9 runs), the distance halves down to
    MIN_DIST / 8 so the search can close in on the answer; only then is nothing left."""
    import numpy as np
    U = _unit(V, bounds, params)
    taken0 = [u for u in np.atleast_2d(existing_U)] if len(existing_U) else []
    order = [i for i in np.argsort(-score) if np.isfinite(score[i]) and (not positive or score[i] > 0)]
    dist = MIN_DIST
    while True:
        out, taken = [], list(taken0)
        if first is not None:
            uf = _unit([first], bounds, params)[0]
            if not taken or min(float(np.linalg.norm(uf - t)) for t in taken) > min(0.05, dist):
                out.append(list(map(float, first)))
                taken.append(uf)
        for i in order:
            if len(out) >= k:
                break
            if taken and min(float(np.linalg.norm(U[i] - t)) for t in taken) < dist:
                continue
            out.append(list(map(float, V[i])))
            taken.append(U[i])
        if out or dist <= MIN_DIST / 8:
            return out
        dist /= 2


def _points(vals, paths):
    return [{p: float(v[j]) for j, p in enumerate(paths)} for v in vals]


def design_round(study, rows, spec, state=None, extra=None, seed=0):
    """One look at a design study. state: what earlier rounds left
    ({round, history: [{rmse, r2, content, dphi}], check: {values, value, ci}}).
    -> {action: refine | check | done | stop, points, result (design.recommend), assess, state, why}"""
    import numpy as np

    from . import design as DZ
    state = dict(state or {})
    rnd = int(state.get("round") or 0) + 1
    hist = list(state.get("history") or [])
    # the check runs that fell short are data too
    data = list(rows) + list(extra or []) + list(state.get("extra") or [])
    ctx = {}
    res = DZ.recommend(study, data, spec, ctx_out=ctx)
    out = {"result": res, "round": rnd, "points": [], "assess": {}}
    if not res.get("ok"):
        out.update(action="stop", why="few_runs")
        return out
    chk = state.get("check")
    if chk and chk.get("value") is not None:
        tgs = ctx.get("tgs") or [ctx["tg_raw"]]
        # what the check measured for every target (the first one's value is the check's own)
        got = {k: float(v) for k, v in (chk.get("measured") or {}).items() if isinstance(v, (int, float))}
        got[tgs[0]["response"]] = float(chk["value"])
        rec = res.get("recommended") or res.get("best") or {}
        same = False
        if rec.get("values"):
            a = _unit([[chk["values"].get(p, 0.0) for p in ctx["paths"]]], ctx["bounds"], ctx["params"])[0]
            b = _unit([[rec["values"].get(p, 0.0) for p in ctx["paths"]]], ctx["bounds"], ctx["params"])[0]
            same = float(np.linalg.norm(a - b)) < 0.05
        meets = all(_meets(t, got[t["response"]]) for t in tgs if t["response"] in got)
        if res.get("reached") and same and meets:
            state.update(round=rnd, check=chk)
            cv = ctx.get("cv") or {}
            out["assess"] = {"r2": cv.get("r2"), "rmse": cv.get("rmse"), "dphi": None,
                             "tol": float(spec.get("tol") or DZ.TOL_DEFAULT), "n_runs": res.get("n_runs"), "noise_limited": False}
            t0 = tgs[0]
            out["check"] = {"value": float(chk["value"]), "ci": chk.get("ci"), "target": t0["value"], "op": t0["op"],
                            "all": [{"property": t["property"], "value": got[t["response"]], "target": t["value"], "op": t["op"]}
                                    for t in tgs if t["response"] in got] if len(tgs) > 1 else None}
            out.update(action="done", why="checked", state=state)
            return out
        # the check fell short (or the recipe moved): it joins the data before the recipe is chosen again
        if chk.get("real") is not None:
            got["real_filler"] = float(chk["real"])
        state["extra"] = list(state.get("extra") or []) + [
            {"state": "done", "label": "check", "values": dict(chk["values"]), "metrics": got}]
        state["check"] = None
        out["why_check"] = "check_short"
        data = list(rows) + list(extra or []) + list(state["extra"])
        ctx = {}
        res = DZ.recommend(study, data, spec, ctx_out=ctx)
        out["result"] = res
        if not res.get("ok"):
            out.update(action="stop", why="few_runs", state=state)
            return out
    model, bounds, params, paths, ci = ctx["model"], ctx["bounds"], ctx["params"], ctx["paths"], ctx["ci"]
    tg, X = ctx["tg"], ctx["X"]
    r2 = (ctx.get("cv") or {}).get("r2")
    rmse = (ctx.get("cv") or {}).get("rmse")
    tol = float(spec.get("tol") or DZ.TOL_DEFAULT)
    rec = res.get("recommended") or res.get("best") or {}
    x_rec = np.array([rec.get("values", {}).get(p, np.nan) for p in paths], float)
    dphi = math.inf
    if res.get("reached") and ci is not None and np.all(np.isfinite(x_rec)) and not rec.get("from_run"):
        h = 0.5
        up, dn = x_rec.copy(), x_rec.copy()
        up[ci] += h
        dn[ci] -= h
        mu, sd = model["predict"](np.array([x_rec, up, dn]), std=True)
        slope = (float(mu[1]) - float(mu[2])) / (2 * h)
        if abs(slope) > 1e-12:
            dphi = float(sd[0]) / abs(slope)
    noise = (len(hist) >= 1 and rmse is not None and hist[-1].get("rmse")
             and rmse > (1.0 - NOISE_GAIN) * float(hist[-1]["rmse"]) and rnd >= 3)
    out["assess"] = {"r2": r2, "rmse": rmse, "dphi": None if not math.isfinite(dphi) else dphi, "tol": tol,
                     "n_runs": res.get("n_runs"), "noise_limited": bool(noise)}
    hist.append({"rmse": rmse, "r2": r2, "content": rec.get("content"), "dphi": out["assess"]["dphi"]})
    state.update(round=rnd, history=hist)
    out["state"] = state
    limit = max_rounds()
    if limit and rnd > limit:
        out.update(action="stop", why="rounds")
        return out
    # the least content may lie below the study's range: a recipe at its lower end, or a target nearer at the
    # lower end than at the upper one ("유전율 3.0 이하" with a filler that raises it). The range is extended
    # downwards a few vol% at a time (never below a lower bound the request said) until the answer is inside it
    if ci is not None and (spec.get("objective") or "content") == "content":
        lo_c, hi_c = bounds[ci]
        floor = spec.get("content_floor")
        room = lo_c - max(float(floor) if floor is not None else 0.5, 0.5)
        lower = False
        if room > 0.5 and res.get("reached") and "at_lower_bound" in (res.get("notes") or []):
            lower = True
        elif room > 0.5 and not res.get("reached") and np.all(np.isfinite(x_rec)):
            a, b = x_rec.copy(), x_rec.copy()
            a[ci], b[ci] = lo_c, hi_c
            m2 = np.asarray(model["predict"](np.array([a, b])), float)
            v = float(tg["value"])
            lower = (m2[0] > m2[1] + 1e-9 if tg["op"] == ">=" else m2[0] < m2[1] - 1e-9 if tg["op"] == "<="
                     else abs(m2[0] - v) < abs(m2[1] - v))
        if lower:
            step = min(room, max(5.0, 0.25 * (hi_c - lo_c)))
            vals = []
            for c in (lo_c - step, lo_c - 0.5 * step):
                v_ = x_rec.copy()
                v_[ci] = c
                vals.append(v_)
            if len(params) > 1:
                _, Vl = _lhs(bounds, params, 2, np.random.default_rng(seed + 100 + rnd))
                Vl[:, ci] = lo_c - step
                vals += list(Vl)
            out.update(action="refine", points=_points(vals, paths), why="below_range")
            return out
    converged = res.get("reached") and dphi <= tol and (r2 is not None and r2 >= R2_OK)
    if converged or (res.get("reached") and noise):
        state["check"] = {"values": dict(rec.get("values") or {}), "value": None, "ci": None}
        out.update(action="check", why="converged" if converged else "noise")
        return out
    if not res.get("reached") and r2 is not None and r2 >= R2_OK and rnd >= 2:
        out.update(action="stop", why="unreachable")
        return out
    # the points that settle the decision
    rng = np.random.default_rng(seed + rnd)
    U, V = _lhs(bounds, params, 4000, rng)
    if ci is not None:
        lo, hi = bounds[ci]
        cap = float(spec["content_cap"]) if spec.get("content_cap") is not None else hi
        c0 = float(rec.get("content") or hi)
        if res.get("reached"):
            a_, b_ = max(lo, c0 - 4.0), min(cap, c0 + 4.0)
        else:
            a_, b_ = max(lo, min(cap, hi) - 6.0), min(cap, hi)
        V[:, ci] = a_ + U[:, ci] * max(b_ - a_, 1e-6)
    mu, sd = model["predict"](V, std=True)
    mu, sd = np.asarray(mu, float), np.asarray(sd, float)
    score = 1.96 * sd - np.abs(mu - float(tg["value"]))
    k = 4 if len(params) <= 2 else 6
    first = x_rec if (res.get("reached") and np.all(np.isfinite(x_rec))) else None
    if first is not None and ci is not None:
        first = first.copy()
        first[ci] = float(rec.get("asked") or rec.get("content"))
    pts = _pick(V, score, _unit(X, bounds, params), bounds, params, k, first)
    if not pts:
        if res.get("reached"):
            state["check"] = {"values": dict(rec.get("values") or {}), "value": None, "ci": None}
        out.update(action="check" if res.get("reached") else "stop", why="no_points")
        return out
    out.update(action="refine", points=_points(pts, paths), why="uncertain" if r2 is None or r2 >= R2_OK else "weak")
    return out


def opt_round(study, rows, response, goal, target=None, state=None, seed=0):
    """One look at an optimisation study: expected improvement over the best run.
    -> {action: refine | done | stop, points, best: {values, predicted, std}, assess, state, why}
    An electrical conductivity (decades across percolation) is fitted and searched as its logarithm; the
    values the answer shows are back in S/m (a standard deviation as its upper side)."""
    out = _opt_round(study, rows, response, goal, target, state, seed)
    if out.get("log"):
        def back(m, s=None):
            return 10.0 ** m if s is None else 10.0 ** (m + s) - 10.0 ** m
        for key in ("best", "check"):
            d = out.get(key)
            if d:
                d = dict(d)
                if d.get("std") is not None and d.get("predicted") is not None:
                    d["std"] = back(d["predicted"], d["std"])
                for k in ("predicted", "measured", "value"):
                    if d.get(k) is not None:
                        d[k] = back(d[k])
                out[key] = d
        if out.get("best_run"):
            out["best_run"] = dict(out["best_run"], value=back(out["best_run"]["value"]))
    return out


def _opt_round(study, rows, response, goal, target=None, state=None, seed=0):
    import numpy as np

    from mpsim import optimise as OPT
    state = dict(state or {})
    rnd = int(state.get("round") or 0) + 1
    X, y, names, paths, units, bounds, labels = OPT.dataset(study, rows, response)
    out = {"round": rnd, "points": [], "assess": {}}
    if len(y) < 5:
        out.update(action="stop", why="few_runs")
        return out
    if response == "sigma" and bool((y > 0).all()):
        y = np.log10(y)
        target = math.log10(float(target)) if target is not None and float(target) > 0 else target
        out["log"] = True
        # below percolation the conductivity falls by many decades at once: a step no smooth fit follows. What is
        # more than LOG_SPAN decades from what is sought is held there (still worse, no longer a cliff)
        if goal == "max":
            y = np.maximum(y, y.max() - LOG_SPAN)
        elif goal == "min":
            y = np.minimum(y, y.min() + LOG_SPAN)
        elif target is not None:
            y = np.clip(y, target - LOG_SPAN, target + LOG_SPAN)
    params = [p for p in study.get("parameters") or [] if p.get("path")]
    model = OPT.fit_surrogate(X, y, bounds, seed)
    cv = OPT.cross_validate(X, y, bounds, seed)
    r2 = (cv or {}).get("r2")

    def util(v):
        v = np.asarray(v, float)
        return v if goal == "max" else -v if goal == "min" else -np.abs(v - float(target))
    u_obs = util(y)
    best_u = float(u_obs.max())
    # the range of the better half of the runs: what an improvement is measured against (the whole range of an
    # electrical conductivity holds the decades below percolation, which say nothing about the top)
    top = y[u_obs >= np.median(u_obs)]
    span = float(np.ptp(top)) or float(np.ptp(y)) or max(abs(float(y.mean())), 1e-12)
    rng = np.random.default_rng(seed + rnd)
    U, V = _lhs(bounds, params, 4000, rng)
    V = np.vstack([V, X])
    mu, sd = model["predict"](V, std=True)
    mu, sd = np.asarray(mu, float), np.maximum(np.asarray(sd, float), 1e-12)
    # the runs' scatter about the fit (the last rows of V are the runs themselves)
    noise = float(np.sqrt(np.mean((y - mu[-len(y):]) ** 2)))
    mu_u = util(mu)
    z = (mu_u - best_u) / sd
    from math import erf, sqrt, pi, exp
    Phi = np.array([0.5 * (1.0 + erf(v / sqrt(2.0))) for v in z])
    phi = np.array([exp(-0.5 * v * v) / sqrt(2.0 * pi) for v in z])
    ei = (mu_u - best_u) * Phi + sd * phi
    j = int(np.argmax(mu_u))
    best = {"values": {p: float(V[j][k]) for k, p in enumerate(paths)}, "predicted": float(mu[j]), "std": float(sd[j])}
    jo = int(np.argmax(u_obs))
    out["best_run"] = {"label": labels[jo], "value": float(y[jo]), "values": {p: float(X[jo][k]) for k, p in enumerate(paths)}}
    out["best"] = best
    out["labels"] = {p.get("path"): p.get("label") or p.get("path") for p in params}
    # a factor whose whole range moves the prediction at the optimum by less than twice the runs' scatter
    # (the cross-validated RMSE, which holds the model's error too) does not set the answer: alumina of
    # 5-30 µm with no interfacial resistance conducts alike, and "30 µm" would only be the best scatter
    rmse_cv = (cv or {}).get("rmse")
    out["flat"] = []
    if rmse_cv and len(paths) > 1:
        for k, p in enumerate(paths):
            g = np.repeat(np.array([[best["values"][q] for q in paths]], float), 25, axis=0)
            lo_, hi_ = bounds[k]
            if params[k].get("scale") == "log" and lo_ > 0:
                g[:, k] = np.exp(np.linspace(math.log(lo_), math.log(hi_), 25))
            else:
                g[:, k] = np.linspace(lo_, hi_, 25)
            m_ = np.asarray(model["predict"](g), float)
            delta = float(m_.max() - m_.min())
            if delta < 2.0 * float(rmse_cv):
                out["flat"].append({"path": p, "label": out["labels"].get(p, p), "delta": delta, "rmse": float(rmse_cv)})
    out["assess"] = {"r2": r2, "rmse": (cv or {}).get("rmse"), "max_ei": float(ei.max()), "span": span}
    hist = list(state.get("history") or []) + [{"best_u": best_u, "max_ei": float(ei.max())}]
    state.update(round=rnd, history=hist)
    out["state"] = state
    XU = _unit(X, bounds, params)

    # the optimum's check run (a case of the study, so it is in the fit now): the measured
    # value against the prediction it was run for
    chk = state.get("check")
    if chk:
        state["check"] = None
        cu = _unit([[chk["values"].get(p, 0.0) for p in paths]], bounds, params)[0]
        near = [i for i in range(len(y)) if float(np.linalg.norm(XU[i] - cu)) < 1e-3]
        if not near:
            out["why_check"] = "check_missing"           # the run failed or was stopped
        else:
            yc = float(y[near[-1]])
            out["check"] = {"value": yc, "predicted": chk["predicted"], "std": chk["std"]}
            # it stands when it is what was predicted and the fit that now holds it keeps the optimum there
            # (a run elsewhere that measured higher by its own scatter does not move the fitted optimum)
            agrees = abs(yc - chk["predicted"]) <= max(2.0 * chk["std"], 0.02 * span)
            bu = _unit([[best["values"][p] for p in paths]], bounds, params)[0]
            stays = float(np.linalg.norm(bu - cu)) < 0.05
            if agrees and stays:
                br = out["best_run"]
                bru = _unit([[br["values"][p] for p in paths]], bounds, params)[0]
                if float(util(br["value"]) - util(yc)) > max(3.0 * noise, 0.02 * span) \
                        and float(np.linalg.norm(bru - cu)) > 0.05:
                    # a run already made measured better than the optimum's check by more than the scatter (the
                    # fit smooths a corner or a peak): that run is the answer
                    out["check"] = {"value": yc, "predicted": chk["predicted"], "std": chk["std"]}
                    out["best"] = {"values": br["values"], "predicted": br["value"], "std": 0.0, "measured": br["value"]}
                    out.update(action="done", why="run_better")
                    return out
                out["best"] = dict(chk, measured=yc)
                out.update(action="done", why="confirmed")
                return out
            state["checks_off"] = int(state.get("checks_off") or 0) + 1
            out["why_check"] = "check_off" if not agrees else "check_moved"

    def check(why):
        # a predicted optimum is only a prediction: it is run before it is called the optimum
        if int(state.get("checks_off") or 0) >= 2:
            # two checks away from their predictions: the runs' own scatter; the best run is the answer
            br = out["best_run"]
            out["best"] = {"values": br["values"], "predicted": br["value"], "std": 0.0, "measured": br["value"]}
            out.update(action="done", why="best_run")
            return out
        bu = _unit([[best["values"][p] for p in paths]], bounds, params)[0]
        d = [float(np.linalg.norm(XU[i] - bu)) for i in range(len(y))]
        i0 = int(np.argmin(d))
        if d[i0] < 0.02:                                  # the optimum is a run already: that is its check
            out["best"] = dict(best, values={p: float(X[i0][k]) for k, p in enumerate(paths)}, measured=float(y[i0]))
            out.update(action="done", why=why)
            return out
        state["check"] = dict(best)
        out.update(action="check", why=why, points=_points([[best["values"][p] for p in paths]], paths))
        return out

    limit = max_rounds()
    if float(ei.max()) <= 0.01 * span and (r2 is None or r2 >= R2_OK):
        return check("converged")
    if len(hist) >= 3 and abs(hist[-1]["best_u"] - hist[-3]["best_u"]) <= 0.005 * span:
        return check("no_gain")
    if limit and rnd > limit:
        out.update(action="stop", why="rounds")
        return out
    k = 4 if len(params) <= 2 else 6
    if r2 is not None and r2 < R2_OK:
        # the surrogate is not yet sound: half the points where it is least sure, to make it so
        pts = _pick(V, ei, XU, bounds, params, k // 2)
        pts += _pick(V, sd, np.vstack([XU] + ([_unit(pts, bounds, params)] if pts else [])), bounds, params, k - len(pts))
        why = "weak"
    else:
        pts = _pick(V, ei, XU, bounds, params, k)
        why = "ei"
    if not pts:
        return check("no_points")
    out.update(action="refine", points=_points(pts, paths), why=why)
    return out


def explain(out, kind, lang="en", unit=""):
    """The AI tab's words for one round."""
    ko = lang == "ko"
    L = lambda a, b: a if ko else b                                              # noqa: E731
    a = out.get("assess") or {}
    r2 = a.get("r2")
    r2t = f"R² {r2:.3f}" if r2 is not None else "R² -"
    n = len(out.get("points") or [])
    rnd = out.get("round")
    if kind == "design":
        res = out.get("result") or {}
        rec = res.get("recommended") or res.get("best") or {}
        dp = a.get("dphi")
        dpt = f"±{dp:.2f} vol%" if dp is not None else L("판단 불가", "not judged")
        c = out.get("check") or {}
        if out.get("action") == "done" and out.get("why") == "checked" and c:
            ci = f" ± {c['ci']:.2g}" if c.get("ci") is not None else ""
            op = {">=": "≥", "<=": "≤"}.get(c.get("op"), "≈")
            if c.get("all"):
                # several targets: each one's measured value against it
                PN = {"k": "k", "sigma": "σ", "eps_r": "ε_r", "alpha": "CTE", "E": "E"}
                each = ", ".join(f"{PN.get(x['property'], x['property'])} {x['value']:.4g} {({'>=': '≥', '<=': '≤'}).get(x['op'], '≈')} {x['target']:g}"
                                 for x in c["all"])
                return L(f"라운드 {rnd}: 추천 조합(총 함량 {rec.get('content')} vol%)의 확인 해석(구조 3개)이 모든 목표를 만족합니다 ({each}) → 설계를 마칩니다",
                         f"Round {rnd}: the recipe's check run (total {rec.get('content')} vol%, three realisations) meets every target ({each}): the design is complete")
            return L(f"라운드 {rnd}: 추천 조합(총 함량 {rec.get('content')} vol%)의 확인 해석(구조 3개) {c['value']:.4g}{ci} {unit} {op} 목표 {c['target']:g} → 설계를 마칩니다",
                     f"Round {rnd}: the recipe's check run (total {rec.get('content')} vol%, three realisations) gave {c['value']:.4g}{ci} {unit} {op} the target {c['target']:g}: the design is complete")
        head = L(f"라운드 {rnd}: 케이스 {a.get('n_runs')}개, 대리모델 교차검증 {r2t}, 추천 함량 {rec.get('content')} vol%의 불확도 {dpt} (허용 {a.get('tol')} vol%)",
                 f"Round {rnd}: {a.get('n_runs')} runs, surrogate cross-validated {r2t}; the recipe's content {rec.get('content')} vol% is sure to {dpt} (tolerance {a.get('tol')} vol%)")
        act = out.get("action")
        if out.get("why_check") == "check_short":
            head += L(" · 확인 해석이 목표에 못 미쳐 그 결과를 데이터에 넣었습니다", " · the check fell short of the target and joins the data")
        tail = {
            ("refine", "uncertain"): L(f" → 목표 경계에서 가장 불확실한 곳 {n}점을 추가로 해석합니다", f" → {n} points where it is least sure the target is met are run next"),
            ("refine", "weak"): L(f" → 대리모델이 약해 {n}점을 추가로 해석합니다", f" → the surrogate is weak; {n} more points are run"),
            ("refine", "below_range"): L(f" → 답이 함량 범위의 아래쪽에 있어, 범위보다 낮은 함량 {n}점을 해석해 범위를 넓힙니다",
                                         f" → the answer lies at or below the low end of the content range: {n} points below it are run"),
            ("check", "converged"): L(" → 수렴: 추천 조합을 구조 3개로 확인 해석합니다", " → converged: the recipe is checked with three realisations"),
            ("check", "noise"): L(" → 오차가 더 줄지 않아(해석 한 번의 산포 수준) 추천 조합을 확인 해석으로 판정합니다", " → the error no longer falls (the scatter of a single run): the recipe is decided by a check run"),
            ("check", "no_points"): L(" → 더 볼 곳이 없어 확인 해석합니다", " → nothing more to probe: the recipe is checked"),
            ("done", "checked"): L(" → 확인 해석이 목표를 만족해 설계를 마칩니다", " → the check run meets the target: the design is complete"),
            ("stop", "no_points"): L(" → 범위 안에 더 볼 곳이 없고 목표에 닿지 않아 멈춥니다", " → nothing more to probe in the ranges and the target is not reached: stopped"),
            ("stop", "unreachable"): L(" → 대리모델이 믿을 만한데 범위 안에서 목표에 닿지 않아 멈춥니다", " → the surrogate is sound and the target is out of reach in the ranges: stopped"),
            ("stop", "rounds"): L(" → 안전 한도(라운드 수)에 닿아 멈춥니다", " → the safety limit on rounds was reached: stopped"),
            ("stop", "few_runs"): L(" → 끝난 케이스가 너무 적어 멈춥니다", " → too few finished runs: stopped"),
        }.get((act, out.get("why")), "")
        return head + tail
    best = out.get("best") or {}
    labs = out.get("labels") or {}
    where = ", ".join(f"{labs.get(p, p)} {v:.4g}" for p, v in (best.get("values") or {}).items())
    head = L(f"라운드 {rnd}: 대리모델 교차검증 {r2t}, 최적 예측 {best.get('predicted', float('nan')):.4g} {unit}, 기대 개선 최대 {a.get('max_ei', 0):.3g}",
             f"Round {rnd}: surrogate cross-validated {r2t}, predicted optimum {best.get('predicted', float('nan')):.4g} {unit}, largest expected improvement {a.get('max_ei', 0):.3g}")
    c = out.get("check") or {}
    if out.get("why_check") == "check_off":
        head = L(f"라운드 {rnd}: 확인 해석 {c['value']:.4g} {unit}이 예측 {c['predicted']:.4g} ± {c['std']:.2g}와 달라 데이터에 넣고 다시 맞췄습니다 (교차검증 {r2t})",
                 f"Round {rnd}: the check run gave {c['value']:.4g} {unit} against the predicted {c['predicted']:.4g} ± {c['std']:.2g}; it joins the data and the surrogate is fitted again ({r2t})")
    elif out.get("why_check") == "check_moved":
        head = L(f"라운드 {rnd}: 확인 해석 {c['value']:.4g} {unit}은 예측 {c['predicted']:.4g} ± {c['std']:.2g} 안이지만, 데이터에 넣고 다시 맞추니 최적점이 옮겨갔습니다 (교차검증 {r2t})",
                 f"Round {rnd}: the check run gave {c['value']:.4g} {unit}, within the predicted {c['predicted']:.4g} ± {c['std']:.2g}, but with it in the data the fitted optimum moves ({r2t})")
    elif out.get("why_check") == "check_missing":
        head += L(" · 확인 해석 결과가 없어(실패 또는 멈춤) 다시 정합니다", " · the check run gave no result (failed or stopped) and is decided again")
    act, why = out.get("action"), out.get("why")
    flat = out.get("flat") or []
    note = ""
    if flat:
        names = ", ".join(f["label"] for f in flat)
        d0 = flat[0]
        fu = L("자릿수(log10)", "decades (log10)") if out.get("log") else unit
        note = L(f" · {names}: 범위 전체에서 예측 변화 {d0['delta']:.2g} {fu}로 해석 산포(교차검증 RMSE {d0['rmse']:.2g})의 2배보다 작아, 이 범위에서는 답을 정하지 않습니다(어느 값이어도 됩니다)",
                 f" · {names}: over its whole range the prediction moves by {d0['delta']:.2g} {fu}, less than twice the runs' scatter (cross-validated RMSE {d0['rmse']:.2g}), so it does not set the answer in this range (any value will do)")
    if act == "done" and why == "confirmed":
        return L(f"라운드 {rnd}: 확인 해석 {best['measured']:.4g} {unit}이 예측 {best['predicted']:.4g} ± {best['std']:.2g}와 맞아 최적 조건을 확정합니다: {where}",
                 f"Round {rnd}: the check run gave {best['measured']:.4g} {unit}, as predicted ({best['predicted']:.4g} ± {best['std']:.2g}); the optimum stands: {where}") + note
    if act == "done" and why == "run_better":
        return L(f"라운드 {rnd}: 예측 최적점의 확인 해석 {c['value']:.4g} {unit}은 예측({c['predicted']:.4g})대로였지만, 이미 해석한 케이스가 산포보다 크게 더 좋아 "
                 f"그 케이스를 답으로 합니다: {best['measured']:.4g} {unit}, {where}",
                 f"Round {rnd}: the predicted optimum's check gave {c['value']:.4g} {unit} as predicted ({c['predicted']:.4g}), "
                 f"but a run already made is better by more than the scatter, and it is the answer: {best['measured']:.4g} {unit} at {where}") + note
    if act == "done" and why == "best_run":
        return head + L(f" → 확인 해석 두 번으로도 최적점이 서지 않아(해석 한 번의 산포 수준) 가장 좋은 케이스를 답으로 합니다: {best['measured']:.4g} {unit}, {where}",
                        f" → two checks did not settle the optimum (the scatter of a single run); the best run is the answer: {best['measured']:.4g} {unit} at {where}") + note
    if act == "done":                     # the optimum is a run already
        return head + L(f" → 최적점이 이미 해석한 케이스와 같아 확정합니다: {where} (그 해석값 {best['measured']:.4g} {unit}, 대리모델 예측 {best['predicted']:.4g} ± {best['std']:.2g})",
                        f" → the optimum is a run already: {where} (that run {best['measured']:.4g} {unit}, surrogate {best['predicted']:.4g} ± {best['std']:.2g})") + note
    tail = {
        ("refine", "ei"): L(f" → 개선이 기대되는 {n}점을 추가로 해석합니다", f" → {n} points of highest expected improvement are run next"),
        ("refine", "weak"): L(f" → 대리모델 정확도가 부족해(R² < {R2_OK}) 가장 불확실한 곳과 개선이 기대되는 곳 {n}점을 추가로 해석합니다",
                              f" → the surrogate is not yet sound (R² < {R2_OK}); {n} points, where it is least sure and where improvement is expected, are run next"),
        ("check", "converged"): L(f" → 기대 개선이 응답 범위의 1% 아래: 예측 최적점({where})을 확인 해석합니다",
                                  f" → the expected improvement is below 1 % of the range: the predicted optimum ({where}) is run to check it"),
        ("check", "no_gain"): L(f" → 두 라운드 동안 최고값이 나아지지 않아 예측 최적점({where})을 확인 해석합니다",
                                f" → no gain over two rounds: the predicted optimum ({where}) is run to check it"),
        ("check", "no_points"): L(f" → 더 해석할 곳이 남지 않아 예측 최적점({where})을 확인 해석합니다",
                                  f" → nothing more to probe: the predicted optimum ({where}) is run to check it"),
        ("stop", "rounds"): L(" → 안전 한도(라운드 수)에 닿아 멈춥니다", " → the safety limit on rounds was reached: stopped"),
        ("stop", "few_runs"): L(" → 끝난 케이스가 너무 적어 멈춥니다", " → too few finished runs: stopped"),
    }.get((act, why), "")
    return head + tail
