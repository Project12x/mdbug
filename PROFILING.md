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
`python -m analyzer.profile --symbols out/symbol.txt --samples out/pc_samples.txt --out out/profile.md [--route LABEL] [--top N]`.

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
The dump step is a documented gdb procedure today (the TL;DR script). Integrating it as a
first-class `mdbug.ps1 -Profile` pass (config-driven dump + `profile.py` + a report section)
is the next step, tracked with the broader MD debug-suite work.
