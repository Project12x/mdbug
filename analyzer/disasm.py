"""Instruction-level PC-sample annotation: disassemble a 68k symbol's TRUE
byte range from ROM and attribute sampled PCs to individual instructions.

The function-level :mod:`analyzer.profile` flame table tells you *which* function
is hot; this drills one level deeper -- *which instruction inside it*. Given a
symbol's exact ``[addr, addr+size)`` range (from :mod:`analyzer.symbolize`, which
reads the real ``st_size`` out of the ELF ``.symtab``), the raw ROM bytes, and a
flat PC-sample list, it disassembles the slice with capstone's m68k backend and
weights each decoded instruction by how many samples landed inside it.

A sampled PC lands on whichever instruction's half-open ``[address, address+size)``
range contains it -- so mid-instruction PCs (the HInt frame can interrupt at any
byte) and variable-length 68k encodings both attribute correctly.

capstone is an OPTIONAL dependency, import-guarded exactly like
:mod:`analyzer.symbolize` guards pyelftools. When it is absent :func:`have_capstone`
returns ``False`` and callers (the ``--disasm`` CLI pass) skip with a one-line
diagnostic; the pure-stdlib ``profile.py`` nm pipeline -- the floor that always
works -- is never affected because this module is imported lazily.
"""
from collections import Counter, namedtuple

try:
    import capstone
    from capstone import Cs, CS_ARCH_M68K, CS_MODE_M68K_000
    _HAVE_CAPSTONE = True
except ImportError:  # pragma: no cover - exercised by the importorskip guard
    _HAVE_CAPSTONE = False


def have_capstone():
    """Whether capstone (the m68k disassembler backend) is importable."""
    return _HAVE_CAPSTONE


class DisasmError(Exception):
    """Raised when a symbol's range cannot be disassembled (bad slice/bounds)."""


# One decoded instruction annotated with its PC-sample weight.
#   pc    -- instruction start address (load/link address, == ROM offset + base)
#   bytes -- hex string of the encoding (e.g. "4e71")
#   text  -- "mnemonic op_str" (e.g. "moveq #$1, d0"), op-less insns just "rts"
#   count -- samples whose PC fell in [pc, pc+size) of this instruction
#   pct   -- 100 * count / (in-range samples for this symbol); 0.0 when none
InsnRow = namedtuple("InsnRow", "pc bytes text count pct")


def disasm_symbol(rom_bytes, symbol, pcs, *, base=0):
    """Disassemble ``symbol``'s range from ``rom_bytes`` and weight by ``pcs``.

    ``symbol`` is a :class:`analyzer.symbolize.Symbol` (``name``/``addr``/``size``)
    -- any object exposing ``.addr`` and ``.size`` works; pyelftools supplies the
    TRUE half-open range, so no nm next-addr inference is needed here.

    ``rom_bytes`` is the raw ROM image (``config.build.rom``). ``base`` is the
    ROM->load offset: for a flat MD 68k link the link address equals the ROM file
    offset, so ``base`` is ``0`` (the default); it is exposed so a non-zero-based
    link still maps. The disassembled slice is
    ``rom_bytes[symbol.addr - base : symbol.addr - base + symbol.size]``.

    ``pcs`` is the same flat PC-sample list :func:`analyzer.profile.parse_pc_samples`
    yields. Each decoded instruction's ``count`` is the number of sampled PCs in
    its half-open ``[address, address+size)`` span; ``pct`` is over the symbol's
    in-range samples only (so it reads as "where inside this function").

    Returns a list of :class:`InsnRow` in address order (a source-less annotated
    listing). Raises :class:`DisasmError` if capstone is unavailable or the slice
    is out of the ROM's bounds.
    """
    if not _HAVE_CAPSTONE:
        raise DisasmError("capstone not installed")
    if symbol.size <= 0:
        raise DisasmError(
            "symbol %r has no size (st_size==0); cannot bound the slice"
            % getattr(symbol, "name", "?"))

    start = symbol.addr - base
    end = start + symbol.size
    if start < 0 or end > len(rom_bytes):
        raise DisasmError(
            "symbol range [0x%x, 0x%x) out of ROM bounds (base=0x%x, len=%d)"
            % (symbol.addr, symbol.addr + symbol.size, base, len(rom_bytes)))
    code = bytes(rom_bytes[start:end])

    # Histogram the samples once, then a sampled PC attributes to whichever
    # instruction's half-open byte span contains it (handles mid-instruction PCs
    # and variable-length 68k encodings).
    hist = Counter(pcs)

    md = Cs(CS_ARCH_M68K, CS_MODE_M68K_000)

    decoded = []  # (pc, hexbytes, text, count)
    in_range_total = 0
    for insn in md.disasm(code, symbol.addr):
        count = 0
        for p in range(insn.address, insn.address + insn.size):
            count += hist.get(p, 0)
        in_range_total += count
        text = insn.mnemonic
        if insn.op_str:
            text = "%s %s" % (insn.mnemonic, insn.op_str)
        decoded.append((insn.address, insn.bytes.hex(), text.strip(), count))

    rows = []
    for pc, hexbytes, text, count in decoded:
        pct = round(100.0 * count / in_range_total, 1) if in_range_total else 0.0
        rows.append(InsnRow(pc=pc, bytes=hexbytes, text=text, count=count, pct=pct))
    return rows
