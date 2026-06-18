"""Aggregate samples by field, then gate against ceilings + baseline."""

_AGG = {
    "max": lambda vals: max(vals) if vals else 0,
    "last": lambda vals: vals[-1] if vals else 0,
    "sum": lambda vals: sum(vals),
}


def aggregate(samples, fields):
    """Reduce samples to {field_name: value} using each field's aggregate mode."""
    out = {}
    for f in fields:
        vals = [s[f["index"]] for s in samples]
        agg = _AGG.get(f["aggregate"])
        if agg is None:
            raise ValueError("unknown aggregate: %s" % f["aggregate"])
        out[f["name"]] = agg(vals)
    return out


def gate(observed, baseline_fields, ceilings, tolerances, fields, done_ok=True):
    """Return a verdict dict. FAIL if any gated field breaches its ceiling or
    regresses past baseline+tolerance, or if the scenario did not complete."""
    rows = []
    reasons = []
    passed = True
    default_tol = tolerances.get("default", 0)
    for f in fields:
        name = f["name"]
        obs = observed.get(name)
        unit = f.get("unit", "")
        if not f.get("gate", False):
            rows.append({"name": name, "observed": obs, "baseline": None,
                         "delta": None, "ceiling": None, "result": "info", "unit": unit})
            continue
        base = baseline_fields.get(name)
        ceil = ceilings.get(name)
        tol = tolerances.get(name, default_tol)
        result = "pass"
        if ceil is not None and obs > ceil:
            result = "fail"
            passed = False
            reasons.append("%s %s exceeds ceiling %s" % (name, obs, ceil))
        if base is not None and obs > base + tol:
            result = "fail"
            passed = False
            reasons.append("%s %s regressed past baseline %s (+%s)" % (name, obs, base, tol))
        delta = (obs - base) if base is not None else None
        rows.append({"name": name, "observed": obs, "baseline": base, "delta": delta,
                     "ceiling": ceil, "result": result, "unit": unit})
    if not done_ok:
        passed = False
        reasons.append("scenario did not complete (done-flag not observed)")
    return {"passed": passed, "rows": rows, "reasons": reasons}
