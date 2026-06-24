"""Tests for the ELF/DWARF symbolizer (analyzer.symbolize).

pyelftools is an OPTIONAL dependency, so the whole module import-skips when it
is absent. The ELF-backed end-to-end tests additionally need a real EM_68K ELF;
we build a tiny synthetic one once per session with the SGDK m68k assembler +
linker and skip cleanly when that toolchain is unavailable. The pure index
classes (SymbolIndex / LineIndex / InlineIndex) take plain data, so those tests
run whenever pyelftools imports -- no ELF, no toolchain required.

Run from tools/mdbug:  python -m pytest tests/test_symbolize.py -q
"""
import os
import shutil
import subprocess

import pytest

pytest.importorskip("elftools")

from analyzer import symbolize as S
from analyzer.symbolize import (
    Symbol,
    SymbolIndex,
    LineIndex,
    InlineIndex,
    SymbolizeError,
    have_elftools,
    load_symbols,
    load_line_program,
    load_inline_index,
    symbolize_pcs,
    symbolize_pcs_from_symbol_text,
)


# --- Pure index unit tests (no ELF, no toolchain) ---------------------------

def test_have_elftools_true_when_imported():
    # We got past importorskip, so the probe must agree.
    assert have_elftools() is True


def test_symbol_index_resolve_uses_true_sizes_half_open():
    idx = SymbolIndex([
        Symbol("a", 0x1000, 0x40),   # [0x1000, 0x1040)
        Symbol("b", 0x1040, 0x10),   # [0x1040, 0x1050)
    ])
    assert idx.resolve(0x1000) == "a"          # start inclusive
    assert idx.resolve(0x103F) == "a"          # last byte of a
    assert idx.resolve(0x1040) == "b"          # end exclusive -> next symbol
    assert idx.resolve(0x104F) == "b"
    assert idx.resolve(0x0FFF) is None         # below first symbol
    assert idx.resolve(0x2000) is None         # past the last sized symbol


def test_symbol_index_zero_size_falls_back_to_next_addr_inference():
    # nm-style: a size-less symbol owns everything up to the next symbol.
    idx = SymbolIndex([
        Symbol("a", 0x1000, 0),       # size unknown
        Symbol("b", 0x1500, 0x10),
    ])
    assert idx.resolve(0x1000) == "a"
    assert idx.resolve(0x14FF) == "a"          # still inside a (no size cap)
    assert idx.resolve(0x1500) == "b"


def test_symbol_index_symbol_lookup_returns_full_symbol():
    idx = SymbolIndex([Symbol("draw", 0x2000, 0x80)])
    s = idx.symbol("draw")
    assert s == Symbol("draw", 0x2000, 0x80)
    assert s.addr == 0x2000 and s.size == 0x80   # feeds disasm slice
    assert idx.symbol("missing") is None


def test_line_index_lookup_rightmost_addr():
    li = LineIndex([
        (0x1000, "a.c", 10),
        (0x1010, "a.c", 11),
        (0x1020, "b.c", 4),
    ])
    assert li.lookup(0x1000) == ("a.c", 10)
    assert li.lookup(0x100F) == ("a.c", 10)     # within first row's span
    assert li.lookup(0x1010) == ("a.c", 11)
    assert li.lookup(0x1024) == ("b.c", 4)
    assert li.lookup(0x0FFF) is None            # below first row
    assert LineIndex([]).lookup(0x1000) is None


def test_inline_index_frames_innermost_first_deepest_wins():
    # Outer subprogram [0x1000,0x1100) contains an inlined callee [0x1040,0x1080).
    ii = InlineIndex([
        (0x1000, 0x1100, ["outer"]),
        (0x1040, 0x1080, ["outer", "inner_isra_0"]),
    ])
    # Inside the inlined region: innermost..outermost.
    assert ii.frames(0x1050) == ["inner_isra_0", "outer"]
    # Outside the inline but inside the subprogram: just the outer frame.
    assert ii.frames(0x1010) == ["outer"]
    # Uncovered PC -> empty list.
    assert ii.frames(0x2000) == []


# --- nm-path delegation (pure stdlib, always available) ---------------------

SYMBOLS = """\
00000200 t _Entry_Point
00001000 T draw_stream_delta_tiles
00001500 t level_bg_b_attr_at
00002000 T build_bg_a_column_strip_cache
"""


def test_symbolize_pcs_from_symbol_text_matches_profile_samples():
    from analyzer.profile import profile_samples
    pcs = [0x1100, 0x1200, 0x1550, 0x2000, 0x0100]
    assert symbolize_pcs_from_symbol_text(SYMBOLS, pcs) == profile_samples(SYMBOLS, pcs)


# --- Synthetic-ELF fixture + ELF-backed end-to-end -------------------------

def _find_tool(*names):
    """Resolve an m68k binutil from the SGDK bin first, then PATH."""
    sgdk_bin = os.path.join(os.environ.get("GDK", r"C:\sgdk"), "bin")
    for n in names:
        cand = os.path.join(sgdk_bin, n)
        if os.path.isfile(cand):
            return cand
        found = shutil.which(n)
        if found:
            return found
    return None


# Two functions with explicit .size directives so .symtab carries TRUE sizes
# (func_a: nop+nop+rts = 6 bytes; func_b: moveq+rts = 4 bytes), linked at 0x1000
# with a flat text layout matching MD's link-addr == ROM-offset convention.
_SYNTH_ASM = """\
\t.text
\t.globl\tfunc_a
\t.type\tfunc_a, @function
func_a:
\tnop
\tnop
\trts
\t.size\tfunc_a, .-func_a

\t.globl\tfunc_b
\t.type\tfunc_b, @function
func_b:
\tmoveq\t#0, %d0
\trts
\t.size\tfunc_b, .-func_b
"""


@pytest.fixture(scope="session")
def synth_elf(tmp_path_factory):
    """Build a tiny EM_68K ELF with two sized functions, or skip.

    Skips (rather than fails) when the m68k assembler/linker is not present, so
    the suite stays green on a machine without the SGDK toolchain.
    """
    as_tool = _find_tool("m68k-elf-as", "as.exe", "as")
    ld_tool = _find_tool("m68k-elf-ld", "ld.exe", "ld")
    if not as_tool or not ld_tool:
        pytest.skip("m68k assembler/linker unavailable (SGDK bin not found)")

    d = tmp_path_factory.mktemp("synth_elf")
    asm = os.path.join(str(d), "synth.s")
    obj = os.path.join(str(d), "synth.o")
    out = os.path.join(str(d), "synth.out")
    with open(asm, "w", encoding="utf-8") as f:
        f.write(_SYNTH_ASM)
    try:
        subprocess.run([as_tool, "-m68000", "-o", obj, asm], check=True,
                       capture_output=True)
        subprocess.run([ld_tool, "-Ttext=0x1000", "-e", "func_a",
                        "-o", out, obj], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        pytest.skip("synthetic ELF build failed: %s" % (exc,))
    if not os.path.isfile(out):
        pytest.skip("synthetic ELF was not produced")
    return out


def test_load_symbols_reads_true_ranges(synth_elf):
    idx = load_symbols(synth_elf)
    a = idx.symbol("func_a")
    b = idx.symbol("func_b")
    assert a is not None and b is not None
    # TRUE sizes from .symtab (.size directives), not next-addr inference.
    assert a.addr == 0x1000 and a.size == 6     # nop, nop, rts
    assert b.addr == 0x1006 and b.size == 4     # moveq, rts


def test_load_symbols_resolves_pcs_in_each_function(synth_elf):
    idx = load_symbols(synth_elf)
    assert idx.resolve(0x1000) == "func_a"
    assert idx.resolve(0x1002) == "func_a"      # mid-instruction PC
    assert idx.resolve(0x1006) == "func_b"
    assert idx.resolve(0x1009) == "func_b"      # last byte of func_b [0x1006,0x100A)
    assert idx.resolve(0x100A) is None          # past the end (true-size gap)


def test_symbolize_pcs_ranked_contract(synth_elf):
    # func_a x3, func_b x1, one PC below both -> (unknown). Mirrors
    # profile.profile_samples ordering: count desc, addr asc, unknown last.
    pcs = [0x1000, 0x1002, 0x1004, 0x1006, 0x0010]
    ranked, stacks = symbolize_pcs(synth_elf, pcs)
    assert stacks is None                       # with_inline defaults False
    assert ranked == [
        {"name": "func_a", "count": 3, "pct": 60.0},
        {"name": "func_b", "count": 1, "pct": 20.0},
        {"name": "(unknown)", "count": 1, "pct": 20.0},
    ]


def test_symbolize_pcs_matches_nm_shape(synth_elf):
    # The ELF ranked output must be byte-identical in SHAPE to the nm path
    # (same keys, same ordering rule) -- the profile.py drop-in contract.
    pcs = [0x1000, 0x1002, 0x1006]
    ranked, _ = symbolize_pcs(synth_elf, pcs)
    assert all(set(r.keys()) == {"name", "count", "pct"} for r in ranked)
    # Sorted by count desc then addr asc: func_a (addr 0x1000) before func_b.
    assert [r["name"] for r in ranked] == ["func_a", "func_b"]


def test_symbolize_pcs_with_inline_falls_back_to_symbol_when_no_dwarf(synth_elf):
    # The synthetic ELF has no DWARF, so inline stacks degrade to bare symbols.
    pcs = [0x1000, 0x1002, 0x1006]
    ranked, stacks = symbolize_pcs(synth_elf, pcs, with_inline=True)
    assert ranked  # symbols still resolve
    assert stacks == {"func_a": 2, "func_b": 1}   # flat single-frame keys


def test_load_line_program_none_without_dwarf(synth_elf):
    # -g0 / no DWARF -> file:line silently unavailable, never an error.
    assert load_line_program(synth_elf) is None


def test_load_inline_index_none_without_dwarf(synth_elf):
    assert load_inline_index(synth_elf) is None


# --- Error / degrade paths --------------------------------------------------

def test_load_symbols_rejects_non_68k_elf(tmp_path):
    # A minimal non-68K ELF must raise SymbolizeError so the caller falls back
    # to the nm path instead of mis-symbolizing.
    bad = tmp_path / "x86.out"
    bad.write_bytes(_minimal_elf(machine=0x3E))   # EM_X86_64
    with pytest.raises(SymbolizeError):
        load_symbols(str(bad))


def test_load_symbols_raises_on_garbage_file(tmp_path):
    bad = tmp_path / "garbage.out"
    bad.write_bytes(b"not an elf at all\x00\x01\x02")
    from analyzer.symbolize import ELFError
    with pytest.raises((SymbolizeError, ELFError)):
        load_symbols(str(bad))


def _minimal_elf(machine):
    """Hand-build a 64-byte ELF32 BE header with a chosen e_machine, no sections.

    Enough for pyelftools to parse the header and report e_machine; load_symbols
    only needs e_machine (rejects non-68K) before touching sections.
    """
    import struct
    e_ident = (
        b"\x7fELF"          # magic
        b"\x01"             # EI_CLASS = ELFCLASS32
        b"\x02"             # EI_DATA  = ELFDATA2MSB (big-endian, like m68k)
        b"\x01"             # EI_VERSION = 1
        + b"\x00" * 9       # pad
    )
    # ELF32 big-endian header (e_ident + 13 fields).
    header = e_ident + struct.pack(
        ">HHIIIIIHHHHHH",
        2,        # e_type    = ET_EXEC
        machine,  # e_machine
        1,        # e_version
        0,        # e_entry
        0,        # e_phoff
        0,        # e_shoff (no section table)
        0,        # e_flags
        52,       # e_ehsize
        0, 0,     # e_phentsize, e_phnum
        0,        # e_shentsize
        0,        # e_shnum
        0,        # e_shstrndx
    )
    return header
