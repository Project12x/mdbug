"""Aggregate samples by field, then gate against ceilings + baseline."""
import math


def _percentile(vals, pct):
    """Nearest-rank percentile (returns an actual observed value, integer-clean).

    Robust to the handful of low load/idle windows, so median/p90 track the
    typical and near-worst frame where a mean would be skewed. Both builds share
    the same route, so the median/p90 *delta* between them is apples-to-apples --
    the basis for judging a change by more than its single worst frame.
    """
    if not vals:
        return 0
    xs = sorted(vals)
    k = max(1, math.ceil(pct / 100.0 * len(xs))) - 1
    return xs[min(k, len(xs) - 1)]


def _stdev(vals):
    """Population standard deviation, rounded to the nearest integer."""
    if not vals:
        return 0
    mean = sum(vals) / float(len(vals))
    variance = sum((v - mean) * (v - mean) for v in vals) / float(len(vals))
    return int(math.sqrt(variance) + 0.5)


def _span(vals):
    return (max(vals) - min(vals)) if vals else 0


def _mean_abs_delta(vals):
    """Mean absolute difference between adjacent samples, integer-rounded."""
    if len(vals) < 2:
        return 0
    total = sum(abs(vals[i] - vals[i - 1]) for i in range(1, len(vals)))
    return int((total / float(len(vals) - 1)) + 0.5)


def _periodicity(vals):
    """Peak positive autocorrelation across lags 2..N/2, scaled 0..1000.

    This is a compact detector for repeating frame-cost structure (for example a
    sawtooth every few frames). A flat line has no signal and returns 0.
    """
    if len(vals) < 4:
        return 0
    mean = sum(vals) / float(len(vals))
    centered = [v - mean for v in vals]
    max_lag = min(len(vals) // 2, 60)
    best = 0.0
    for lag in range(2, max_lag + 1):
        a = centered[:-lag]
        b = centered[lag:]
        energy_a = sum(v * v for v in a)
        energy_b = sum(v * v for v in b)
        if energy_a == 0 or energy_b == 0:
            continue
        corr = sum(x * y for x, y in zip(a, b)) / math.sqrt(energy_a * energy_b)
        if corr > best:
            best = corr
    return int(best * 1000.0 + 0.5)


_AGG = {
    "max": lambda vals: max(vals) if vals else 0,
    "last": lambda vals: vals[-1] if vals else 0,
    "sum": lambda vals: sum(vals),
    "median": lambda vals: _percentile(vals, 50),
    "p90": lambda vals: _percentile(vals, 90),
    "range": _span,
    "stdev": _stdev,
    "mean_abs_delta": _mean_abs_delta,
    "periodicity": _periodicity,
}


def aggregate(samples, fields):
    """Reduce samples to {field_name: value} using each field's aggregate mode."""
    out = {}
    for f in fields:
        idx = f["index"]
        for s in samples:
            if idx >= len(s):
                raise ValueError("field '%s' index %d out of range for sample width %d"
                                 % (f["name"], idx, len(s)))
        vals = [s[idx] for s in samples]
        agg = _AGG.get(f["aggregate"])
        if agg is None:
            raise ValueError("unknown aggregate: %s" % f["aggregate"])
        out[f["name"]] = agg(vals)
    return out


def gate(observed, baseline_fields, ceilings, tolerances, fields, done_ok=True,
         validity=None):
    """Return a verdict dict. FAIL if any gated field breaches its ceiling or
    regresses past baseline+tolerance, or if the scenario did not complete.

    `validity` is an optional dict; `validity["requireNonzero"]` lists field
    names that must have a nonzero observed value for the run to be considered
    valid. A zero/missing required field marks the verdict INVALID (a separate
    state from FAIL: the run produced no usable activity, so its numbers cannot
    be trusted) -- `invalid=True`, `passed=False`, with reasons prepended."""
    rows = []
    reasons = []
    passed = True
    invalid = False
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
    if validity:
        invalid_reasons = []
        for name in validity.get("requireNonzero", []):
            if not observed.get(name):  # 0, None, or missing
                invalid_reasons.append("%s == 0 (no activity) -- gate INVALID" % name)
        if invalid_reasons:
            invalid = True
            passed = False
            reasons = invalid_reasons + reasons
    return {"passed": passed, "invalid": invalid, "rows": rows, "reasons": reasons}
