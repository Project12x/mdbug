"""Render a shareable markdown report from a gate verdict."""


def _cell(v):
    return "-" if v is None else str(v)


def render_report(meta, verdict, shots, raw):
    status = "PASS" if verdict["passed"] else "FAIL"
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
    if not verdict["passed"] and verdict["reasons"]:
        lines.append("## Failures")
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
