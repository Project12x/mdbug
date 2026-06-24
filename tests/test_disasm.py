"""Tests for the instruction-level PC-sample annotator (analyzer.disasm).

``disasm.py`` disassembles a 68k symbol's TRUE byte range (from the ELF, via
:mod:`analyzer.symbolize`) out of the raw ROM and weights each decoded
instruction by how many sampled PCs landed inside its half-open span. capstone
is an OPTIONAL dep, so the whole module skips cleanly when it is absent.

Fixtures are tiny hand-assembled big-endian m68k encodings (no ELF, no ROM file
required) so the suite runs anywhere capstone is installed. Run from tools/mdbug:
  python -m pytest tests/test_disasm.py -q
"""
import os
import sys
from collections import namedtuple

import pytest

# capstone is optional: skip the entire module when the lib is unavailable so the
# pure-stdlib floor (profile.py nm path) is never gated on it.
pytest.importorskip("capstone")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analyzer.disasm import disasm_symbol, have_capstone, DisasmError, InsnRow
from analyzer.reporters import render_disasm


# Mimics analyzer.symbolize.Symbol (name, addr, size) -- disasm_symbol only needs
# .addr/.size/.name, so any duck-typed object works.
Symbol = namedtuple("Symbol", "name addr size")


# A tiny hand-assembled big-endian m68k routine, linked at 0x1000:
#   0x1000: 7001        moveq  #1, d0      (2 bytes)
#   0x1002: 5240        addq.w #1, d0      (2 bytes)
#   0x1004: 4e71        nop                (2 bytes)  -- op-less mnemonic
#   0x1006: 4e75        rts                (2 bytes)  -- op-less mnemonic
# Placed at offset 0x1000 inside a ROM image so addr == ROM file offset (base=0).
FUNC_ADDR = 0x1000
FUNC_BYTES = bytes([0x70, 0x01, 0x52, 0x40, 0x4e, 0x71, 0x4e, 0x75])
SYM = Symbol("hot_routine", FUNC_ADDR, len(FUNC_BYTES))


def _rom():
    """Build a ROM image with FUNC_BYTES placed at FUNC_ADDR (rest zero-filled)."""
    rom = bytearray(FUNC_ADDR + len(FUNC_BYTES) + 0x10)
    rom[FUNC_ADDR:FUNC_ADDR + len(FUNC_BYTES)] = FUNC_BYTES
    return bytes(rom)


def test_have_capstone_true_when_lib_present():
    # We only reach here past the importorskip, so capstone is installed.
    assert have_capstone() is True


def test_decodes_each_instruction_in_address_order():
    rows = disasm_symbol(_rom(), SYM, [], base=0)
    assert [r.pc for r in rows] == [0x1000, 0x1002, 0x1004, 0x1006]
    # One InsnRow per decoded instruction; text is mnemonic[+op_str], stripped.
    assert isinstance(rows[0], InsnRow)
    assert rows[0].text == "moveq #$1, d0"
    assert rows[1].text == "addq.w #$1, d0"
    # op-less mnemonics carry no trailing space.
    assert rows[2].text == "nop"
    assert rows[3].text == "rts"
    assert rows[0].bytes == "7001"


def test_sample_lands_on_containing_instruction():
    # One sample on each instruction's start address.
    pcs = [0x1000, 0x1002, 0x1004, 0x1006]
    rows = disasm_symbol(_rom(), SYM, pcs)
    assert [r.count for r in rows] == [1, 1, 1, 1]
    # Four equally weighted samples -> 25% each.
    assert all(r.pct == 25.0 for r in rows)


def test_mid_instruction_pc_attributes_to_its_instruction():
    # A PC at 0x1003 falls inside addq.w's [0x1002, 0x1004) span, not at a start.
    rows = disasm_symbol(_rom(), SYM, [0x1003])
    by_pc = {r.pc: r for r in rows}
    assert by_pc[0x1002].count == 1
    assert by_pc[0x1002].pct == 100.0
    # Every other instruction is cold.
    assert by_pc[0x1000].count == 0
    assert by_pc[0x1004].count == 0


def test_weights_concentrate_on_hot_instruction():
    # moveq sampled 3x, addq sampled 1x, others cold.
    pcs = [0x1000, 0x1001, 0x1000, 0x1002]
    rows = disasm_symbol(_rom(), SYM, pcs)
    by_pc = {r.pc: r for r in rows}
    assert by_pc[0x1000].count == 3   # 0x1000 x2 + 0x1001 (mid-insn) -> moveq
    assert by_pc[0x1002].count == 1
    # pct is over in-range samples (4), not the symbol's whole sample count.
    assert by_pc[0x1000].pct == 75.0
    assert by_pc[0x1002].pct == 25.0


def test_out_of_range_pcs_do_not_count():
    # PCs outside [0x1000, 0x1008) belong to other functions; ignored here.
    rows = disasm_symbol(_rom(), SYM, [0x9999, 0x0008, 0x1000])
    by_pc = {r.pc: r for r in rows}
    assert by_pc[0x1000].count == 1
    assert sum(r.count for r in rows) == 1  # only the in-range PC counted


def test_no_samples_yields_zero_pct():
    rows = disasm_symbol(_rom(), SYM, [])
    assert all(r.count == 0 and r.pct == 0.0 for r in rows)


def test_nonzero_base_offset_maps_into_rom():
    # Same code, but the ROM is laid out so the symbol's link addr is offset from
    # its file position by `base`: file offset = addr - base.
    base = 0x1000
    rom = bytearray(len(FUNC_BYTES) + 4)
    rom[0:len(FUNC_BYTES)] = FUNC_BYTES   # code now at file offset 0
    sym = Symbol("hot_routine", FUNC_ADDR, len(FUNC_BYTES))  # still linked at 0x1000
    rows = disasm_symbol(bytes(rom), sym, [0x1000], base=base)
    # Decoded addresses still use the link address (symbol.addr), not file offset.
    assert rows[0].pc == 0x1000
    assert rows[0].count == 1


def test_out_of_bounds_slice_raises():
    sym = Symbol("oversize", FUNC_ADDR, 0x1000)  # extends past the ROM image
    with pytest.raises(DisasmError):
        disasm_symbol(_rom(), sym, [])


def test_zero_size_symbol_raises():
    sym = Symbol("sizeless", FUNC_ADDR, 0)
    with pytest.raises(DisasmError):
        disasm_symbol(_rom(), sym, [])


def test_render_disasm_table_marks_hottest_instruction():
    pcs = [0x1000, 0x1000, 0x1002]  # moveq hot (2), addq (1)
    rows = disasm_symbol(_rom(), SYM, pcs)
    md = render_disasm(rows, "hot_routine", {"route": "autoplay", "gitSha": "abc123"})
    assert "# mdbug disasm - hot_routine" in md
    assert "autoplay" in md
    assert "| PC | Samples | % | Insn |" in md
    # The fenced PC column is rendered.
    assert "0x001000" in md
    # The hottest row (moveq, count 2) carries the marker; cold rows do not.
    moveq_line = [ln for ln in md.splitlines() if "0x001000" in ln][0]
    nop_line = [ln for ln in md.splitlines() if "0x001004" in ln][0]
    assert "<-" in moveq_line
    assert "<-" not in nop_line
    # Total in-range samples surfaced in the header.
    assert "Samples in range: 3" in md


def test_render_disasm_empty_rows_is_valid_header():
    md = render_disasm([], "empty_sym", {"route": "r"})
    assert "# mdbug disasm - empty_sym" in md
    assert "Samples in range: 0" in md
    assert md.endswith("\n")
