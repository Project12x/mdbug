# mdbug — Mega Drive Perf-Gate Harness

`mdbug` is a standalone, config-driven Mega Drive **performance-gate, PC-sampling profiler, and screenshot** harness with selectable `blastem` and `emusplatter` backends. It boots a ROM, drives a deterministic in-ROM workload, samples an in-ROM perf block via GDB or a batch work-RAM export, captures screenshots at fixed checkpoints, and emits PASS/FAIL against a committed baseline and hard ceilings — producing a single shareable markdown report. Any Mega Drive project that implements the four-item instrumentation contract below can adopt it without forking.

## The instrumentation contract

A consuming ROM implements these four things; everything else is config:

1. **Perf block** — a global symbol holding a fixed-width array of per-interval worst-case values (e.g. `volatile u16 g_perf[N]`). The config declares the symbol name, element count, element width, and a field map (`index -> { name, aggregate: max|last|sum|median|p90|range|stdev|mean_abs_delta|periodicity, unit, gate }`). GDB mode references the symbol by name; export mode resolves its work-RAM address from the ELF symbol table.

2. **Sample trigger** — a no-op breakpoint symbol (e.g. `dbg_perf_tick`) the ROM calls once per interval after writing the block and resetting its accumulators. The GDB sampler breaks here each cycle; the harness takes the field-wise max across all samples. The export sampler reads the block every frame and aggregates across all dumps, so no trigger call is needed in that path.

3. **Deterministic workload** — a compile-time tape or attract mode that runs identically on every invocation. The harness never injects live gameplay input as the canonical gate path. A generic GDB `preroll` hook is available for runtime-enabled workloads.

4. **Done flag** (optional) — a global the ROM sets at scenario end (e.g. `g_autoplay_done = 1`). The harness reads it at the end of the GDB session; a missing or zero flag causes a FAIL with a "scenario did not complete" reason, catching hangs and crashes.

Non-SGDK / raw-68K projects satisfy the contract by exposing any two of the above symbols.

## Quick start

```powershell
# Run the gate (exit 0 = PASS, 1 = FAIL; report at config.report.outDir/report.md):
pwsh -File mdbug.ps1 -Config <your.config.json>

# Choose a backend explicitly:
pwsh -File mdbug.ps1 -Config <your.config.json> -Backend blastem
pwsh -File mdbug.ps1 -Config <your.config.json> -Backend emusplatter

# Capture a first baseline (do deliberately; commits observed values as the new ground truth):
pwsh -File mdbug.ps1 -Config <your.config.json> -UpdateBaseline

# Skip the build step (ROM already built):
pwsh -File mdbug.ps1 -Config <your.config.json> -NoBuild

# Dry run — print commands without launching anything:
pwsh -File mdbug.ps1 -Config <your.config.json> -DryRun
```

See `examples/example.config.json` for an annotated full config. The JSON schema is in `config.schema.json`.

## Optional features

- **Validity guard** — `gate.validity.requireNonzero: [<field>, ...]` marks a run **INVALID** (a third verdict beside PASS/FAIL, with a nonzero exit) when a listed field is zero/missing, catching no-activity runs (e.g. the camera never moved).
- **A/B compare** — `python -m analyzer.cli --config <c> --samples-file <s> --samples-format <f> --save-snapshot NAME` writes `perf/snap.NAME.json`; `python -m analyzer.cli --config <c> --compare A B --out compare.md` renders a `| Metric | A | B | Delta |` table (no live samples needed).
- **Watch trace** — top-level `watch: [{ name, symbol, format? }]` traces globals across intervals; the report gains a **Trajectory** table (GDB-mode backends only).
- **Jitter / periodicity metrics** — `range`, `stdev`, `mean_abs_delta`, and `periodicity` aggregate modes summarize pacing steadiness from any configured field. For true per-frame Jazz MD samples, set the build command to `build.bat autoplay frame-samples` and raise `perf.samples` to cover the full route; the default build still snapshots every 16 frames.

See `HOWTO.md` for full details on each.

## PC-sampling profiler

Beyond the gate's lumped perf counters, mdbug includes a **statistical PC-sampling profiler**
that splits a frame section into a function-level flame table — *where* the emulated 68000
actually spends time. A drop-in per-scanline HInt (`instrumentation/pc_sample.*`) rings the
interrupted PC in RAM; gdb dumps it; `analyzer/profile.py` symbolizes it against the ELF. It
is host-independent and reproducible (same determinism the gate relies on — a slow laptop and
a fast workstation produce the identical profile). See **`PROFILING.md`** for the end-to-end
workflow + caveats, and **`instrumentation/README.md`** for the drop-in target code.

## Backends

**`blastem`** (portable default) — launches BlastEm with `-D` to expose a GDB stub, then uses the shared `lib/gdb_sample.ps1` to sample via GDB remote. Screenshots use BlastEm's screenshot-key capture at wall-clock checkpoints (a headless run with no window handle warns and skips screenshots instead of failing). BlastEm is auto-installed via `install_blastem.ps1` when `backends.blastem.path` is null; GDB resolves via a fallback chain when `backends.blastem.gdb` is null: `$env:GDK\bin\gdb.exe` → config `build.gdk` → `C:\SDKs\SGDK\bin\gdb.exe` → `C:\SDKS\SGDK\bin\gdb.exe` → PATH (`m68k-elf-gdb`/`gdb`), throwing one clear error if none is found.

**`emusplatter`** — a headless/deterministic Ares fork backend. Set `backends.emusplatter.path` in the config to the built binary. Requires the fork's `--headless`, `--frames`, `--dump-workram`, `--screenshot`, and (for gdb mode) `--gdb-server` flags. The default `sampleMode` is `export` (runs `--dump-workram <addr>,<size>,<file>` once per frame for `backends.emusplatter.frames` frames, then aggregates — fast, fully headless, no GDB required). Set `sampleMode` to `gdb` to use the shared GDB sampler via the fork's `--gdb-server` flag instead.

Baselines are per-backend (`baseline.<backend>.json`) since absolute cycle counts differ between emulators. Each backend compares against its own committed baseline.

## License

MIT. See `LICENSE`.
