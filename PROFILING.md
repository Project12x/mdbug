# PROFILING — mdbug PC-sampling profiler

The perf gate (`README.md`/`HOWTO.md`) tells you *that* a frame section is expensive (a
lumped scanline counter). The **PC-sampling profiler** tells you *where inside it* — a
statistical, function-level flame split of where the emulated 68000 actually spends time.

It reuses the deterministic-emulation property of the gate: the result is **host-independent
and fully reproducible** (a slow laptop and a fast workstation produce the identical
profile — host speed only changes how long the run takes, not the numbers).

---

## TL;DR (an agent can copy-paste this)

```powershell
# 1. Build a profiling ROM: your deterministic workload (autoplay) + DEBUG_PC_SAMPLE.
#    jazzmd:  build.bat autoplay pc-sample   -> out/rom.bin, out/rom.out (ELF), out/symbol.txt

# 2+3. Fill the RAM ring during the run, dump it via gdb, symbolize with profile.py:
$blastem = "tools\mdbug\blastem\<ver>\blastem.exe"; $gdb = "$env:GDK\bin\gdb.exe"
$elf = "out\rom.out"; $rom = "out\rom.bin"; $raw = "out\pc_raw.txt"; $samples = "out\pc_samples.txt"
$emu = Start-Process $blastem -ArgumentList "`"$rom`" -D" -PassThru
try {
  for ($i=0; $i -lt 100 -and -not (Get-NetTCPConnection -LocalPort 1234 -State Listen -EA SilentlyContinue); $i++) { Start-Sleep -Milliseconds 100 }
  $cmds = @("set pagination off","set confirm off","target remote :1234","break dbg_perf_tick")
  for ($i=0;$i -lt 82;$i++){ $cmds += "continue" }       # run past PC_SAMPLE_ARM_FRAME until the ring fills
  $cmds += "x/1024xw &g_pc_samples"; $cmds += @("disconnect","quit")   # 1024 = PC_SAMPLE_MAX
  Set-Content out\pc.gdb $cmds -Encoding ASCII
  $p = Start-Process $gdb -ArgumentList "-q -batch -x out\pc.gdb `"$elf`"" -NoNewWindow -PassThru -RedirectStandardOutput $raw -RedirectStandardError "$raw.err"
  $p.WaitForExit(190000) | Out-Null
} finally { if (-not $emu.HasExited) { Stop-Process -Id $emu.Id -Force } }
# extract PC values (ROM range only: < your ROM size, >= 0x200 entry) -> one per line
Select-String $raw -Pattern '0x[0-9a-fA-F]{4,8}' -AllMatches | % { $_.Matches } | % { $_.Value } |
  ? { [convert]::ToInt64($_,16) -lt 0x200000 -and [convert]::ToInt64($_,16) -ge 0x200 } | Set-Content $samples

# 4. Symbolize -> a ranked function flame table:
Push-Location tools\mdbug
python -m analyzer.profile --symbols ..\..\out\symbol.txt --samples ..\..\out\pc_samples.txt --out ..\..\out\profile.md --route my-scenario --top 20
Pop-Location
```

Output `out/profile.md`:

```
| Function | Samples | % |
|---|---:|---:|
| stream_plan_accumulate_missing_cells.isra.0 | 170 | 15.3 |
| draw_stream_delta_tiles.lto_priv.0          | 142 | 12.8 |
| ...
```

---

## How it works

```
ROM (DEBUG_PC_SAMPLE)                 gdb (BlastEm -D)            analyzer/profile.py
per-scanline HInt asm trampoline  ->  x/<MAX>xw &g_pc_samples ->  symbolize vs symbol.txt
  reads interrupted PC from the         (a flat list of PCs)        (nm address ranges)
  hardware frame -> RAM ring                                      -> ranked flame table
```

- **`instrumentation/pc_sample.{h,c}` + `pc_sample_hint.s`** (drop-in) — a per-scanline
  HInt whose asm trampoline reads the **interrupted 68000 PC from the hardware interrupt
  frame** (a C interrupt handler can't: its prologue makes the frame offset non-fixed) and
  rings it in RAM.
- **gdb** dumps `g_pc_samples` after a deterministic run.
- **`analyzer/profile.py`** (`python -m analyzer.profile`) maps each PC to the enclosing
  code symbol via `symbol.txt` (nm-style ranges) and ranks by sample count. Clock-agnostic:
  it just needs a flat PC list, so any sampler can feed it.

## Step 1 — add the instrumentation to your project

1. Copy `instrumentation/pc_sample.h` -> your `inc/`, `pc_sample.c` + `pc_sample_hint.s` ->
   your `src/` (SGDK assembles `src/*.s`).
2. Add a `DEBUG_PC_SAMPLE` build flag that lands in `build_config.h` (default 0). See your
   build system; jazzmd uses `build.bat <target> pc-sample`.
3. From your scene/level, gated on the flag:
   ```c
   #if DEBUG_PC_SAMPLE
     pc_sample_install();                                  // once, at scene start
   #endif
   // ...in your deterministic-workload loop, once you're in the hot section:
   #if DEBUG_PC_SAMPLE
     if (frame == PC_SAMPLE_ARM_FRAME) pc_sample_arm();    // begin capturing
   #endif
   ```

Knobs (override in `build_config.h` or before including the header): `PC_SAMPLE_MAX` (ring
size), `PC_SAMPLE_SKIP` (HInt fires every Nth scanline — hardware subsample; spreads samples + cuts overhead),
`PC_SAMPLE_ARM_FRAME` (when to start, after the settle).

## Step 2 — build with a deterministic workload + the flag
Same determinism requirement as the gate: a fixed attract/autoplay route, no live input.
The build must emit the **ELF** (`out/rom.out`) and the nm **symbol table**
(`out/symbol.txt`) the profiler needs.

## Step 3 — fill the ring + dump (gdb)
Two ways:
- **Per-frame fill (proven):** `break dbg_perf_tick`, `continue` ~N times until the ring
  fills (`N >= PC_SAMPLE_ARM_FRAME + PC_SAMPLE_MAX / (visible_lines / PC_SAMPLE_SKIP)`), then
  `x/<MAX>xw &g_pc_samples`. This is the TL;DR script.
- **Anchor fill (fewer round-trips):** the recorder calls `pc_sample_done()` when the ring
  fills — `break pc_sample_done`, one `continue`, then dump. Caveat: a set breakpoint slows
  BlastEm, so on a weak host budget enough timeout.

## Step 4 — symbolize
Floor (always works): `python -m analyzer.profile --symbols out/symbol.txt --samples out/pc_samples.txt --out out/profile.md [--route LABEL] [--top N]`.

Rich (optional libs): add `--elf out/rom.out` (pyelftools true ranges + inline names),
`--format folded|speedscope|perfetto` (interchange artifacts), and `--rom out/rom.bin
--disasm SYMBOL` (capstone per-instruction weights). `--symbolizer auto` (default) uses the
ELF when it and pyelftools are present, else the nm floor.

**Or skip Steps 3–4 entirely:** `mdbug.ps1 -Config <cfg> -Profile` does the gdb dump +
ROM-range filter + symbolize in one pass, driven by the config `profile.*` block
(`-DryRun` prints the gdb script + python command without launching anything). See the
`profile` block in `config.schema.json`.

---

## Symbolization & artifacts

The `--symbols out/symbol.txt` path above is the **floor — pure stdlib, always
available**: nm-style address ranges, function-level only. Two OPTIONAL libs upgrade
it; both are import-guarded, so the floor never depends on them.

```powershell
pip install -r requirements.txt          # pyelftools + capstone (optional)
```

- **ELF/DWARF symbolization (`pyelftools`).** Point the profiler at the ELF
  (`out/rom.out`) instead of `symbol.txt` and it reads **true** `st_size` ranges
  from `.symtab` plus the DWARF line program and inline-subroutine tree — the
  `addr2line -i` equivalent that resolves `pc -> file:line` and the **inline call
  frames** hidden behind SGDK `-O3`/`-flto` synthetic names
  (`.isra` / `.constprop` / `.lto_priv` / `.part`). When the lib is absent or no ELF is
  configured, it falls back to the `symbol.txt` nm path with identical ranking.
- **Interchange artifacts.** The same symbolized counts render to **folded stacks**
  (Brendan-Gregg, for `flamegraph.pl`/inferno), the **speedscope** `sampled` format,
  and **Perfetto / `chrome://tracing`** trace JSON — pure-stdlib reporters, so they
  work on both the ELF and nm paths (with inline frames the stacks carry the full call
  frame; without, each function is one flat frame).
- **`--disasm` drill-down (`capstone`).** One level below the flame table: disassemble a
  hot symbol's true byte range out of the ROM and weight **each 68k instruction** by the
  PCs that landed in it, flagging the hottest — *which instruction inside the function*.
  Needs `pyelftools` for the exact range; skips with a one-line note when `capstone` is
  absent.

---

## Caveats (read before trusting numbers)

- **Host speed does NOT corrupt the profile.** BlastEm is cycle-accurate + the workload is a
  fixed script, so the sampled PC distribution is deterministic and host-independent. A slow
  laptop yields the *same* profile, just slower. So you can profile anywhere, or on a fast
  machine, and trust it everywhere.
- **The HInt is an observer effect — read the RELATIVE split, not absolute time.** The
  instrumentation fires the HInt every `PC_SAMPLE_SKIP`-th scanline (hardware subsample via
  `VDP_setHIntCounter(PC_SAMPLE_SKIP-1)`), so the trampoline overhead is roughly *uniform* and
  small — about `15/PC_SAMPLE_SKIP` %/frame (~2% at the default `SKIP`=8). The **percentage
  split** between functions therefore holds; **absolute** timing is still slightly inflated, so
  never read perf *counters* (scroll/overrun/cpu_load) from a `pc-sample` build — those come
  from the clean gate build. The zero-skid fix (no in-ROM HInt at all) is a future
  emulator-side PC histogram.
- **Sampling spans the frames you choose.** With the default arm/skip the window mixes
  busy + idle frames (you'll see `VDP_waitVBlank` as idle). Gate `pc_sample_arm` to the
  heavy frames to sharpen the work split.
- **Second-order:** if the HInt overhead pushes frames into overrun, an adaptive
  governor/defer path can shift slightly. The large, qualitative gaps are robust; treat
  exact percentages as approximate. The zero-skid fix is a BlastEm-side PC histogram (no
  in-ROM HInt) — a future backend addition.

## Status / roadmap
**Landed:** the first-class `mdbug.ps1 -Profile` pass (config-driven dump + ROM-range
filter + symbolize + a `## PC profile` report section), the ELF/DWARF symbolizer
(`pyelftools`), the folded/speedscope/Perfetto reporters, and `--disasm` (`capstone`).
Call-graph **tracing** (the complementary md-profiler tool) is documented in `TRACE.md`.

**Next:** a **zero-skid** sampler — a BlastEm-side PC histogram with no in-ROM HInt, which
removes the observer effect entirely. That is an emulator-backend addition (a per-backend
`pcdump` capability); the analyzer is already clock-agnostic and consumes whatever flat PC
list a histogram clock emits, so no analyzer change is needed.
