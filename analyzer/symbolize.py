"""ELF/DWARF-backed PC symbolizer (the rich path beside profile.py's nm floor).

The pure-stdlib nm pipeline in :mod:`analyzer.profile` (``parse_symbol_table`` +
``profile_samples`` over ``symbol.txt``) is the floor that always works. This
module is the *optional* upgrade: when ``pyelftools`` is installed and the
config resolves a ``build.elf``, it reads the ELF ``.symtab`` for **true**
``st_value``/``st_size`` ranges (rather than nm's next-address inference) and
the DWARF line program + ``DW_TAG_inlined_subroutine`` tree for ``pc -> file:line``
and inline call frames (the ``addr2line -i`` equivalent that recovers SGDK
``-O3``/``-flto`` synthetic names: ``.isra`` / ``.constprop`` / ``.lto_priv`` /
``.part``).

The two-layer boundary is preserved: this module never imports a backend and
never shells out; it only reads files. ``pyelftools`` is an OPTIONAL dependency
-- it is import-guarded here and callers must fall back to the nm path when
:func:`have_elftools` is False, when ``build.elf`` is absent, or when
:func:`load_symbols` raises :class:`SymbolizeError`.

:func:`symbolize_pcs` honors :func:`analyzer.profile.profile_samples`'s exact
contract -- a flat PC list in, ranked ``[{name, count, pct}]`` out with
byte-identical ordering (count desc, then symbol address asc, ``(unknown)``
last) -- so the ELF path is a drop-in replacement that additionally exposes an
inline-frame ``stacks`` dict for folded/flamegraph output.
"""
import bisect
from collections import Counter, namedtuple

try:
    from elftools.elf.elffile import ELFFile
    from elftools.common.exceptions import ELFError
    _HAVE_ELFTOOLS = True
except ImportError:  # pragma: no cover - exercised only where the dep is absent
    ELFFile = None

    class ELFError(Exception):
        """Stand-in so callers can ``except (SymbolizeError, ELFError)`` safely."""

    _HAVE_ELFTOOLS = False


def have_elftools():
    """True when pyelftools imported -- the gate for choosing the ELF path."""
    return _HAVE_ELFTOOLS


class SymbolizeError(Exception):
    """Raised for any ELF we cannot symbolize (bad/non-68K/missing .symtab).

    Callers catch this (alongside ``ELFError``) and fall back to the nm path so
    a malformed or wrong-arch ELF degrades cleanly instead of mis-symbolizing.
    """


# A code symbol with its TRUE half-open range [addr, addr + size). ``size`` may
# be 0 for symbols the assembler emitted without a ``.size`` directive; those
# fall back to nm-style next-address inference in SymbolIndex so they still
# resolve. ``size`` is what disasm.py needs for an exact slice.
Symbol = namedtuple("Symbol", "name addr size")

# SHF_EXECINSTR (0x4): a section that holds executable instructions. We relax
# STT_NOTYPE symbols to "code" only inside such sections (raw-asm / stripped
# entry points often lack STT_FUNC typing).
_SHF_EXECINSTR = 0x4


class SymbolIndex(object):
    """Sorted code-symbol table with a bisect address index.

    ``resolve(pc)`` maps a sampled PC to the enclosing function name; ``symbol``
    returns the full :class:`Symbol` (true range) for the disassembler.
    """

    def __init__(self, symbols):
        # symbols: iterable of Symbol. Sort by address; on a tie prefer the
        # entry that carries a real size (more specific) then by name.
        syms = sorted(symbols, key=lambda s: (s.addr, -s.size, s.name))
        # Drop exact-duplicate (addr, name) rows that some linkers emit twice.
        deduped = []
        seen = set()
        for s in syms:
            key = (s.addr, s.name)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(s)
        self._syms = deduped
        self._addrs = [s.addr for s in deduped]
        self._by_name = {}
        for s in deduped:
            # First definition of a name wins (matches nm/linker first-wins).
            self._by_name.setdefault(s.name, s)

    def __len__(self):
        return len(self._syms)

    def resolve(self, pc):
        """Return the name of the symbol containing ``pc`` (half-open), else None.

        Sized symbols use ``addr <= pc < addr + size``. A zero-size symbol owns
        the gap up to the next symbol's address (nm next-addr inference), so
        size-less entries still resolve PCs that land in them.
        """
        i = bisect.bisect_right(self._addrs, pc) - 1
        if i < 0:
            return None
        s = self._syms[i]
        if s.size:
            if pc < s.addr + s.size:
                return s.name
            # PC sits in a hole past this sized symbol's end. nm would still
            # attribute it to this symbol (no size info); we don't, to avoid a
            # false positive -- but if the *next* symbol is size-less it already
            # owns this range and bisect would have selected it. So a gap here
            # is genuinely unattributed only when the next symbol starts later.
            # Fall through: treat as unknown (return None) for sized precision.
            return None
        # Size-less symbol: owns everything up to the next symbol's address.
        return s.name

    def symbol(self, name):
        """Return the :class:`Symbol` for ``name`` (feeds disasm), or None."""
        return self._by_name.get(name)

    def symbols(self):
        """All :class:`Symbol` rows in address order (test/inspection aid)."""
        return list(self._syms)


class LineIndex(object):
    """DWARF line-program index: rightmost ``addr <= pc`` -> ``(file, line)``."""

    def __init__(self, rows):
        # rows: iterable of (addr, file, line). Sort + split for bisect.
        rows = sorted(rows, key=lambda r: r[0])
        self._addrs = [r[0] for r in rows]
        self._info = [(r[1], r[2]) for r in rows]

    def __len__(self):
        return len(self._addrs)

    def lookup(self, pc):
        """Return ``(file, line)`` for the line-table row covering ``pc``, else None."""
        if not self._addrs:
            return None
        i = bisect.bisect_right(self._addrs, pc) - 1
        if i < 0:
            return None
        return self._info[i]


class InlineIndex(object):
    """Inline call-frame index (the ``addr2line -i`` equivalent).

    Each covered range maps to the stack of frame names from outermost
    (concrete subprogram) to innermost (deepest inlined callee). ``frames(pc)``
    returns ``[innermost, ..., outermost]`` -- empty when ``pc`` is uncovered.
    """

    def __init__(self, ranges):
        # ranges: iterable of (low, high, [outermost..innermost] names).
        # Sort by low addr; keep half-open [low, high). Overlapping inline
        # ranges are expected (an inlined callee nests inside its caller); we
        # resolve by scanning all ranges that cover pc and taking the deepest
        # stack, so storage stays a flat sorted list.
        self._ranges = sorted(ranges, key=lambda r: (r[0], -(r[1] - r[0])))
        self._lows = [r[0] for r in self._ranges]

    def __len__(self):
        return len(self._ranges)

    def frames(self, pc):
        """Return ``[innermost..outermost]`` frame names covering ``pc`` (or [])."""
        best = []
        # All ranges with low <= pc are candidates; pick the one whose stack is
        # deepest among those that actually cover pc (high > pc). The deepest
        # stack is the most specific (it nests the others).
        i = bisect.bisect_right(self._lows, pc)
        for low, high, names in self._ranges[:i]:
            if pc < high and len(names) > len(best):
                best = names
        # Stored outermost..innermost; callers want innermost first.
        return list(reversed(best))


def _open_elf(elf_path):
    """Open and validate an ELF as an EM_68K image. Returns (file, ELFFile).

    Raises SymbolizeError for the wrong machine, ELFError for a bad image.
    Caller is responsible for closing the returned file object.
    """
    if not _HAVE_ELFTOOLS:  # pragma: no cover - guarded by have_elftools()
        raise SymbolizeError("pyelftools not installed")
    f = open(elf_path, "rb")
    try:
        elf = ELFFile(f)
    except ELFError:
        f.close()
        raise
    except Exception as exc:  # malformed file masquerading as ELF
        f.close()
        raise SymbolizeError("not a valid ELF: %s" % (exc,))
    if elf["e_machine"] != "EM_68K":
        f.close()
        raise SymbolizeError(
            "not a 68000 ELF (e_machine=%s); refusing to mis-symbolize"
            % elf["e_machine"]
        )
    return f, elf


def load_symbols(elf_path):
    """Read ``.symtab`` into a :class:`SymbolIndex` of true code-symbol ranges.

    Keeps ``STT_FUNC`` entries; relaxes ``STT_NOTYPE`` symbols that live in an
    executable (``SHF_EXECINSTR``) section so raw-asm / minimally-typed entry
    points still appear. Uses ``st_value``/``st_size`` verbatim (size 0 is kept
    and resolved by next-address inference in :class:`SymbolIndex`).

    Raises :class:`SymbolizeError` for a non-68K ELF or a missing ``.symtab``,
    or ``ELFError`` for a corrupt image.
    """
    f, elf = _open_elf(elf_path)
    try:
        symtab = elf.get_section_by_name(".symtab")
        if symtab is None:
            raise SymbolizeError(
                "no .symtab (stripped?); use the nm symbol.txt path instead"
            )
        # Precompute which section indices are executable so we can relax
        # STT_NOTYPE -> code only inside SHF_EXECINSTR sections.
        exec_sections = set()
        for i in range(elf.num_sections()):
            sec = elf.get_section(i)
            if sec["sh_flags"] & _SHF_EXECINSTR:
                exec_sections.add(i)

        symbols = []
        for sym in symtab.iter_symbols():
            name = sym.name
            if not name:
                continue
            stype = sym["st_info"]["type"]
            shndx = sym["st_shndx"]
            is_func = stype == "STT_FUNC"
            is_exec_notype = (
                stype == "STT_NOTYPE"
                and isinstance(shndx, int)
                and shndx in exec_sections
            )
            if not (is_func or is_exec_notype):
                continue
            addr = sym["st_value"]
            size = sym["st_size"]
            symbols.append(Symbol(name, addr, size))

        if not symbols:
            raise SymbolizeError(
                "no code symbols in .symtab; use the nm symbol.txt path instead"
            )
        return SymbolIndex(symbols)
    finally:
        f.close()


def load_line_program(elf_path):
    """Flatten the DWARF line program into a :class:`LineIndex`, or None.

    Returns None when the ELF has no ``.debug_info`` (stripped / built ``-g0``),
    so ``file:line`` silently degrades to symbol-only. Drops ``end_sequence``
    marker rows (they carry no real file/line).
    """
    f, elf = _open_elf(elf_path)
    try:
        if not elf.has_dwarf_info():
            return None
        dwarf = elf.get_dwarf_info()
        if not dwarf.has_debug_info:
            return None
        rows = []
        for cu in dwarf.iter_CUs():
            lp = dwarf.line_program_for_CU(cu)
            if lp is None:
                continue
            file_entries = lp["file_entry"]
            for entry in lp.get_entries():
                state = entry.state
                if state is None or state.end_sequence:
                    continue
                fname = _line_file_name(file_entries, state.file)
                rows.append((state.address, fname, state.line))
        if not rows:
            return None
        return LineIndex(rows)
    finally:
        f.close()


def _line_file_name(file_entries, file_index):
    """Resolve a line-program file index to a name (best-effort, bytes->str)."""
    # DWARF<5 file indices are 1-based; DWARF5 are 0-based. pyelftools exposes
    # the entries list as-is, so probe both interpretations defensively.
    entry = None
    if 0 <= file_index < len(file_entries):
        entry = file_entries[file_index]
    elif 0 < file_index <= len(file_entries):
        entry = file_entries[file_index - 1]
    if entry is None:
        return "?"
    name = entry.name
    if isinstance(name, bytes):
        name = name.decode("utf-8", "replace")
    return name


def load_inline_index(elf_path):
    """Build an :class:`InlineIndex` from the DWARF DIE tree, or None.

    Walks ``DW_TAG_subprogram`` and nested ``DW_TAG_inlined_subroutine`` DIEs,
    collecting each one's PC coverage (``DW_AT_low_pc``/``DW_AT_high_pc`` or
    ``DW_AT_ranges``) and resolving ``DW_AT_name`` through
    ``DW_AT_abstract_origin`` / ``DW_AT_specification`` -- which is how the
    real SGDK ``-O3``/``-flto`` callee names (``.isra`` / ``.constprop`` /
    ``.lto_priv`` / ``.part``) are recovered. Returns None when the ELF carries
    no DWARF.
    """
    f, elf = _open_elf(elf_path)
    try:
        if not elf.has_dwarf_info():
            return None
        dwarf = elf.get_dwarf_info()
        if not dwarf.has_debug_info:
            return None
        ranges_out = []
        for cu in dwarf.iter_CUs():
            top = cu.get_top_DIE()
            range_lists = dwarf.range_lists()
            for die in top.iter_children():
                if die.tag == "DW_TAG_subprogram":
                    _walk_subprogram(dwarf, cu, range_lists, die, [], ranges_out)
        if not ranges_out:
            return None
        return InlineIndex(ranges_out)
    finally:
        f.close()


def _die_name(dwarf, cu, die):
    """Best-effort name for a DIE, following abstract_origin/specification."""
    if "DW_AT_name" in die.attributes:
        return _attr_str(die.attributes["DW_AT_name"].value)
    for ref in ("DW_AT_abstract_origin", "DW_AT_specification"):
        if ref in die.attributes:
            try:
                target = die.get_DIE_from_attribute(ref)
            except Exception:
                continue
            name = _die_name(dwarf, cu, target)
            if name:
                return name
    return None


def _attr_str(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value


def _die_pc_ranges(dwarf, cu, range_lists, die):
    """Return a list of half-open (low, high) PC ranges for a DIE (or [])."""
    attrs = die.attributes
    if "DW_AT_low_pc" in attrs:
        low = attrs["DW_AT_low_pc"].value
        if "DW_AT_high_pc" in attrs:
            high_attr = attrs["DW_AT_high_pc"]
            high = high_attr.value
            # DWARF4+: high_pc may be an offset (form class 'constant') from low.
            form = high_attr.form
            if form != "DW_FORM_addr":
                high = low + high
            return [(low, high)]
        return [(low, low + 1)]
    if "DW_AT_ranges" in attrs and range_lists is not None:
        try:
            rl = range_lists.get_range_list_at_offset(
                attrs["DW_AT_ranges"].value, cu=cu
            )
        except TypeError:
            rl = range_lists.get_range_list_at_offset(attrs["DW_AT_ranges"].value)
        except Exception:
            return []
        base = _cu_base_address(cu)
        out = []
        for ent in rl:
            kind = type(ent).__name__
            if kind == "BaseAddressEntry":
                base = ent.base_address
                continue
            begin = getattr(ent, "begin_offset", None)
            end = getattr(ent, "end_offset", None)
            if begin is None or end is None:
                continue
            # Pre-DWARF5 RangeEntry offsets are relative to the CU base; the
            # DWARF5 *_address fields are absolute. pyelftools normalizes most
            # of this, but add base when the entry exposes raw offsets.
            if getattr(ent, "is_absolute", False):
                out.append((begin, end))
            else:
                out.append((base + begin, base + end))
        return out
    return []


def _cu_base_address(cu):
    top = cu.get_top_DIE()
    if "DW_AT_low_pc" in top.attributes:
        return top.attributes["DW_AT_low_pc"].value
    return 0


def _walk_subprogram(dwarf, cu, range_lists, die, parent_stack, out):
    """Recurse a subprogram/inlined-subroutine subtree collecting frame stacks.

    ``parent_stack`` is the chain of names from the outermost concrete
    subprogram down to (not including) ``die``. For each DIE with PC coverage we
    emit (low, high, [outermost..innermost]) where the list is the parent stack
    plus this DIE's name.
    """
    name = _die_name(dwarf, cu, die)
    stack = parent_stack + [name] if name else parent_stack
    for (low, high) in _die_pc_ranges(dwarf, cu, range_lists, die):
        if high > low and stack:
            out.append((low, high, list(stack)))
    for child in die.iter_children():
        if child.tag in ("DW_TAG_inlined_subroutine", "DW_TAG_subprogram"):
            _walk_subprogram(dwarf, cu, range_lists, child, stack, out)
        elif child.tag in ("DW_TAG_lexical_block",):
            # Lexical blocks can nest inlined subroutines; descend but keep the
            # same frame stack (a block is not a frame).
            _walk_subprogram(dwarf, cu, range_lists, child, stack, out)


def _rank_counts(counts, addr_of, total):
    """Shared ranking: count desc, then symbol address asc, ``(unknown)`` last.

    Byte-identical ordering to :func:`analyzer.profile.profile_samples`.
    """
    ranked = []
    for name, count in sorted(
        counts.items(), key=lambda kv: (-kv[1], addr_of.get(kv[0], 1 << 30))
    ):
        pct = round(100.0 * count / total, 1) if total else 0.0
        ranked.append({"name": name, "count": count, "pct": pct})
    return ranked


def symbolize_pcs(elf_path, pcs, *, with_inline=False):
    """Symbolize a flat PC list against an ELF -> ``(ranked, stacks)``.

    ``ranked`` is ``[{name, count, pct}]`` sorted count desc, then symbol
    address asc, with ``(unknown)`` last -- byte-identical in shape and order to
    :func:`analyzer.profile.profile_samples`, but using TRUE ``.symtab`` ranges.

    When ``with_inline`` is True and DWARF inline info is present, ``stacks`` is
    a dict mapping a ``';'``-joined frame key (outermost..innermost) to its
    sample count, suitable for folded/flamegraph output; PCs without inline
    coverage fall back to a single-frame ``[symbol]`` key. When ``with_inline``
    is False, ``stacks`` is None.

    Internally degrades: if the inline index is absent (no DWARF / ``-g0``) the
    function still returns ``ranked`` (symbol-only), and ``stacks`` (if
    requested) is built from bare symbol names.

    Raises :class:`SymbolizeError` / ``ELFError`` only from :func:`load_symbols`
    (bad/non-68K/missing-symtab ELF); the caller catches and falls back to nm.
    """
    index = load_symbols(elf_path)
    addr_of = {s.name: s.addr for s in index.symbols()}

    counts = {}
    for pc in pcs:
        name = index.resolve(pc) or "(unknown)"
        counts[name] = counts.get(name, 0) + 1
    total = len(pcs)
    ranked = _rank_counts(counts, addr_of, total)

    if not with_inline:
        return ranked, None

    inline = None
    if with_inline:
        try:
            inline = load_inline_index(elf_path)
        except (SymbolizeError, ELFError):
            inline = None

    stacks = Counter()
    for pc in pcs:
        frames = inline.frames(pc) if inline is not None else []
        if frames:
            # frames is innermost..outermost; folded keys are outermost..inner.
            key = ";".join(reversed(frames))
        else:
            key = index.resolve(pc) or "(unknown)"
        stacks[key] += 1
    return ranked, dict(stacks)


def symbolize_pcs_from_symbol_text(symbol_text, pcs):
    """Delegate to the nm path so one call site can branch without re-importing.

    A thin convenience over :func:`analyzer.profile.profile_samples`: lets a
    caller that has already decided "use the legacy nm path" produce the same
    ranked shape without importing :mod:`analyzer.profile` twice. Returns just
    ``ranked`` (no inline stacks exist on the nm path).
    """
    from analyzer.profile import profile_samples

    return profile_samples(symbol_text, pcs)
