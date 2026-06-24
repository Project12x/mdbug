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
import os
import re
import sys

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


def _choose_symbolize(args, pcs, symbol_text, with_inline):
    """Pick the ELF (pyelftools) or nm (symbol.txt) symbolizer.

    Returns ``(ranked, stacks, index)`` where ``ranked`` is the byte-identical
    ``[{name,count,pct}]`` contract of :func:`profile_samples`, ``stacks`` is the
    optional inline-frame dict (or ``None``), and ``index`` is a loaded
    ``SymbolIndex`` for ``--disasm`` (or ``None``).

    ``--symbolizer=auto`` (default) prefers the rich ELF path when ``--elf`` is given
    and pyelftools is importable, else falls back to the nm floor; ``=elf`` forces the
    rich path (a clear error if it is unavailable); ``=nm`` always uses the legacy
    floor. Every optional-dep import stays inside this function so the module remains
    importable without pyelftools.
    """
    want_elf = args.symbolizer == "elf" or (args.symbolizer == "auto" and args.elf)
    if want_elf:
        from analyzer import symbolize
        if symbolize.have_elftools() and args.elf:
            try:
                ranked, stacks = symbolize.symbolize_pcs(
                    args.elf, pcs, with_inline=with_inline)
                index = symbolize.load_symbols(args.elf) if args.disasm else None
                return ranked, stacks, index
            except (symbolize.SymbolizeError, symbolize.ELFError, OSError) as e:
                # OSError covers a build.elf that points at a not-yet-built / unreadable
                # file: in auto mode degrade to the nm floor; in elf mode surface it.
                if args.symbolizer == "elf":
                    raise SystemExit("mdbug-profile: ELF symbolize failed: %s" % e)
        elif args.symbolizer == "elf":
            raise SystemExit(
                "mdbug-profile: --symbolizer=elf needs pyelftools (pip install -r "
                "requirements.txt) and --elf")
    # nm floor: the always-available stdlib path over symbol.txt.
    return profile_samples(symbol_text, pcs), None, None


def _run_disasm(args, pcs, index, meta):
    """Instruction-level drill-down of one symbol -- a non-fatal sub-pass.

    Prints a one-line reason and returns when a piece is missing (capstone, the ELF
    symbolizer/index, the ROM bytes, or the symbol), so the profile output is never
    blocked by an unavailable drill-down.
    """
    from analyzer import disasm, reporters
    if not disasm.have_capstone():
        print("disasm unavailable (capstone not installed -- pip install -r requirements.txt)")
        return
    if index is None or not args.elf:
        print("disasm unavailable (needs --elf with the ELF symbolizer)")
        return
    if not args.rom or not os.path.exists(args.rom):
        print("disasm unavailable (needs --rom bytes)")
        return
    sym = index.symbol(args.disasm)
    if sym is None:
        print("disasm: symbol %r not found in ELF" % args.disasm)
        return
    with open(args.rom, "rb") as f:
        rom_bytes = f.read()
    try:
        rows = disasm.disasm_symbol(rom_bytes, sym, pcs)
    except disasm.DisasmError as e:
        print("disasm: %s" % e)
        return
    print(reporters.render_disasm(rows, args.disasm, meta))


def main(argv=None):
    """CLI: symbolize a PC sample file into a ranked report or interchange artifact.

    The legacy nm path (``--symbols`` over symbol.txt) is the always-available floor.
    Optional richer paths layer on top and degrade cleanly when their deps are absent:
    ``--elf`` (pyelftools true-range + inline symbolization), ``--format
    folded|speedscope|perfetto`` (interchange artifacts carrying inline call frames
    when DWARF is present), and ``--disasm SYMBOL`` (capstone per-instruction weights).
    """
    ap = argparse.ArgumentParser(prog="mdbug-profile")
    ap.add_argument("--symbols", default=None, help="SGDK symbol.txt path (nm floor)")
    ap.add_argument("--samples", required=True, help="PC sample file (see parse_pc_samples)")
    ap.add_argument("--out", default=None, help="write the report here")
    ap.add_argument("--route", default="?", help="route/build label for the report")
    ap.add_argument("--git-sha", default="?")
    ap.add_argument("--top", type=int, default=0, help="limit md table to top N (0 = all)")
    ap.add_argument("--elf", default=None,
                    help="ROM ELF (out/rom.out) for true-range + inline symbolization")
    ap.add_argument("--rom", default=None, help="raw ROM (out/rom.bin) for --disasm bytes")
    ap.add_argument("--symbolizer", choices=["auto", "elf", "nm"], default="auto")
    ap.add_argument("--format", choices=["md", "folded", "speedscope", "perfetto"],
                    default="md")
    ap.add_argument("--disasm", default=None, metavar="SYMBOL",
                    help="instruction-level drill-down of one symbol (needs --elf/--rom)")
    args = ap.parse_args(argv)

    with open(args.samples, "r", encoding="utf-8") as f:
        pcs = parse_pc_samples(f.read())
    symbol_text = ""
    if args.symbols and os.path.exists(args.symbols):
        with open(args.symbols, "r", encoding="utf-8") as f:
            symbol_text = f.read()
    elif args.symbolizer != "elf" and not args.elf:
        ap.error("--symbols is required unless --elf is given (with --symbolizer auto/elf)")
    if args.symbolizer == "nm" and not symbol_text:
        print("mdbug-profile: --symbolizer=nm but symbol.txt is missing/empty (%s); "
              "output will be all-(unknown)" % args.symbols, file=sys.stderr)

    with_inline = args.format in ("folded", "speedscope", "perfetto")
    ranked, stacks, index = _choose_symbolize(args, pcs, symbol_text, with_inline)

    meta = {"total": len(pcs), "route": args.route, "gitSha": args.git_sha}
    if args.format == "md":
        if args.top:
            ranked = ranked[:args.top]   # --top trims the flame table; artifacts stay whole
        out = render_profile_report(ranked, meta)
    else:
        if args.top:
            print("mdbug-profile: --top is ignored for %s (interchange artifacts carry "
                  "all frames)" % args.format, file=sys.stderr)
        from analyzer import reporters
        renderer = {"folded": reporters.render_folded,
                    "speedscope": reporters.render_speedscope,
                    "perfetto": reporters.render_perfetto}[args.format]
        out = renderer(ranked, stacks, meta)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out)
    print(out)

    if args.disasm:
        _run_disasm(args, pcs, index, meta)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
