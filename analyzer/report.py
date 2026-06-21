"""Render a shareable markdown report from a gate verdict."""


def _cell(v):
    return "-" if v is None else str(v)


def render_report(meta, verdict, shots, raw, watch=None):
    if verdict.get("invalid"):
        status = "INVALID"
    elif verdict["passed"]:
        status = "PASS"
    else:
        status = "FAIL"
    lines = []
    lines.append("# mdbug perf gate - %s (%s)" % (meta.get("project", "?"), meta.get("backend", "?")))
    lines.append("")
    lines.append("**Result: %s**" % status)
    lines.append("")
    lines.append("Commit `%s` - %s - backend `%s`" %
                 (meta.get("gitSha", "?"), meta.get("date", "?"), meta.get("backend", "?")))
    lines.append("")
    lines.append("| Metric | Observed | Baseline | Delta | Ceiling | Result |")
    lines.append("|---|---|---|---|---|---|")
    for r in verdict["rows"]:
        obs = "%s %s" % (_cell(r["observed"]), r.get("unit", "")) if r["observed"] is not None else "-"
        lines.append("| %s | %s | %s | %s | %s | %s |" % (
            r["name"], obs.strip(), _cell(r["baseline"]),
            ("+%d" % r["delta"]) if isinstance(r["delta"], int) else _cell(r["delta"]),
            _cell(r["ceiling"]), r["result"]))
    lines.append("")
    if shots:
        lines.append("## Screenshots")
        lines.append("")
        for s in shots:
            lines.append("![%s](%s)" % (s["name"], s["path"]))
        lines.append("")
    if watch:
        lines.append("## Trajectory")
        lines.append("")
        names = list(watch.keys())
        n = max((len(watch[name]) for name in names), default=0)
        lines.append("| sample | %s |" % " | ".join(names))
        lines.append("|---|%s" % ("---|" * len(names)))
        for i in range(n):
            cells = [_cell(watch[name][i]) if i < len(watch[name]) else "-"
                     for name in names]
            lines.append("| %d | %s |" % (i, " | ".join(cells)))
        lines.append("")
    if not verdict["passed"] and verdict["reasons"]:
        lines.append("## %s" % ("Invalid" if verdict.get("invalid") else "Failures"))
        lines.append("")
        for reason in verdict["reasons"]:
            lines.append("- %s" % reason)
        lines.append("")
    if raw:
        lines.append("<details><summary>Raw samples</summary>")
        lines.append("")
        lines.append("```")
        lines.append(raw)
        lines.append("```")
        lines.append("")
        lines.append("</details>")
    return "\n".join(lines) + "\n"


def _delta_cell(a, b):
    if not isinstance(a, int) or not isinstance(b, int):
        return "-"
    d = b - a
    return ("+%d" % d) if d >= 0 else str(d)


def render_compare(a_meta, b_meta, a_fields, b_fields, fields):
    """Render a side-by-side A/B delta table for two perf snapshots.

    `fields` is the config field list; only its names (in order) are rendered, so
    the comparison matches the gated metric set. Each row shows snapshot A, B,
    and B-A. Missing values render as `-`.
    """
    a_name = a_meta.get("name", "A")
    b_name = b_meta.get("name", "B")
    lines = []
    lines.append("# mdbug A/B compare - %s vs %s" % (a_name, b_name))
    lines.append("")
    lines.append("`%s` (%s, %s)  vs  `%s` (%s, %s)" % (
        a_name, a_meta.get("gitSha", "?"), a_meta.get("backend", "?"),
        b_name, b_meta.get("gitSha", "?"), b_meta.get("backend", "?")))
    lines.append("")
    lines.append("| Metric | %s | %s | Delta |" % (a_name, b_name))
    lines.append("|---|---|---|---|")
    for f in fields:
        name = f["name"]
        a = a_fields.get(name)
        b = b_fields.get(name)
        lines.append("| %s | %s | %s | %s |" % (
            name, _cell(a), _cell(b), _delta_cell(a, b)))
    return "\n".join(lines) + "\n"
