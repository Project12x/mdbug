"""PC-sampling symbolizer: attribute sampled 68k PCs to functions.

Clock-agnostic by design. The input is a flat list of sampled program-counter
values; where they come from (a BlastEm-patch histogram or a native-debugger
per-scanline HInt log) is the *clock's* concern, not the symbolizer's. This
module only needs the PCs plus the SGDK `symbol.txt`.

symbol.txt lines are `<hex-addr> <type> <name>`; code symbols are type `t`
(local) or `T` (global). A PC is attributed to the rightmost code symbol whose
address is <= the PC (standard nm-style range inference; symbol.txt carries no
explicit sizes).
"""
import argparse
import re

_SYM = re.compile(r"^([0-9a-fA-F]+)\s+(\S)\s+(\S+)")


def parse_symbol_table(symbol_text):
    """Return sorted ``[(addr, name)]`` for code (type t/T) symbols only."""
    syms = []
    for line in symbol_text.splitlines():
        m = _SYM.match(line)
        if m and m.group(2) in ("t", "T"):
            syms.append((int(m.group(1), 16), m.group(3)))
    syms.sort()
    return syms


def symbolize_pc(table, pc):
    """Map ``pc`` to the enclosing code symbol (rightmost addr <= pc), or None."""
    lo, hi = 0, len(table)
    while lo < hi:
        mid = (lo + hi) // 2
        if table[mid][0] <= pc:
            lo = mid + 1
        else:
            hi = mid
    return table[lo - 1][1] if lo else None


def _to_int(tok):
    return int(tok, 16) if tok.lower().startswith("0x") else int(tok)


def parse_pc_samples(text):
    """Parse the clock-agnostic sample file into a flat list of PC ints.

    Two line shapes are accepted so either sampling clock can feed the same
    symbolizer:

    - ``<pc>``          one sampled PC (native-debugger HInt log, Path C)
    - ``<count> <pc>``  a pre-aggregated histogram bucket (BlastEm patch, Path B)

    PCs are hex (``0x``-prefixed) or decimal; counts are decimal. Blank lines
    and ``#`` comment lines are ignored.
    """
    pcs = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        toks = line.split()
        if len(toks) == 1:
            pcs.append(_to_int(toks[0]))
        else:
            count, pc = int(toks[0]), _to_int(toks[1])
            pcs.extend([pc] * count)
    return pcs


def render_profile_report(ranked, meta):
    """Render a ranked PC profile as a markdown flame table."""
    lines = ["# mdbug PC profile - %s" % meta.get("route", "?"), ""]
    lines.append("Samples: %s  -  commit `%s`" %
                 (meta.get("total", "?"), meta.get("gitSha", "?")))
    lines.append("")
    lines.append("| Function | Samples | % |")
    lines.append("|---|---:|---:|")
    for r in ranked:
        lines.append("| %s | %d | %.1f |" % (r["name"], r["count"], r["pct"]))
    return "\n".join(lines) + "\n"


def profile_samples(symbol_text, pcs):
    """Aggregate ``pcs`` into ranked ``[{name, count, pct}]``.

    Sorted by count descending, then symbol address ascending for stable
    output. PCs that fall below the first code symbol bucket under
    ``(unknown)``, which always sorts last.
    """
    table = parse_symbol_table(symbol_text)
    addr_of = {name: addr for addr, name in table}
    counts = {}
    for pc in pcs:
        name = symbolize_pc(table, pc) or "(unknown)"
        counts[name] = counts.get(name, 0) + 1
    total = len(pcs)
    ranked = []
    for name, count in sorted(
        counts.items(), key=lambda kv: (-kv[1], addr_of.get(kv[0], 1 << 30))
    ):
        pct = round(100.0 * count / total, 1) if total else 0.0
        ranked.append({"name": name, "count": count, "pct": pct})
    return ranked


def main(argv=None):
    """CLI: symbolize a PC sample file against symbol.txt into a ranked report."""
    ap = argparse.ArgumentParser(prog="mdbug-profile")
    ap.add_argument("--symbols", required=True, help="SGDK symbol.txt path")
    ap.add_argument("--samples", required=True, help="PC sample file (see parse_pc_samples)")
    ap.add_argument("--out", default=None, help="write markdown report here")
    ap.add_argument("--route", default="?", help="route/build label for the report")
    ap.add_argument("--git-sha", default="?")
    ap.add_argument("--top", type=int, default=0, help="limit to top N functions (0 = all)")
    args = ap.parse_args(argv)

    with open(args.symbols, "r", encoding="utf-8") as f:
        symbol_text = f.read()
    with open(args.samples, "r", encoding="utf-8") as f:
        pcs = parse_pc_samples(f.read())

    ranked = profile_samples(symbol_text, pcs)
    if args.top:
        ranked = ranked[:args.top]
    md = render_profile_report(
        ranked, {"total": len(pcs), "route": args.route, "gitSha": args.git_sha})
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(md)
    print(md)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
