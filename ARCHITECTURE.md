# Architecture — mdbug

## Overview

mdbug has a hard two-layer boundary: a backend-agnostic Python analyzer that operates on a normalized sample list, and thin per-backend PowerShell adapters that acquire those samples and screenshots from a specific emulator. The two layers communicate only through files written to disk (`<outDir>/samples.txt`, `<outDir>/shots/*.png`) and command-line arguments. Neither layer imports the other; they are decoupled by design.

For the full design rationale and decisions, see the design spec:
`jazzmd/docs/superpowers/specs/2026-06-17-mdbug-harness-design.md`

---

## Layer 1 — Backend-agnostic Python analyzer (`analyzer/`)

The analyzer is a pure Python package with no runtime dependencies beyond the standard library. It receives a normalized sample list (a list of integer rows, one row per sample interval) and knows nothing about which emulator produced it or what the metrics mean physically.

### Modules

**`analyzer/parse.py`**
- `parse_gdb_dump(text, count, width)` — parses verbatim GDB batch stdout (lines of the form `0xADDR:\t0xV 0xV 0xV…`) into a list of int rows, where each row is exactly `count` elements. Incomplete trailing chunks are dropped.
- `parse_export(text, count)` — parses the emusplatter batch export format (one line of space-separated decimal values per frame) into the same list-of-rows shape.

Both parsers produce the same normalized shape so downstream code is format-agnostic.

**`analyzer/gate.py`**
- `aggregate(samples, fields)` — reduces the sample list to `{field_name: scalar}` by applying each field's declared aggregate function (`max`, `last`, `sum`, `median`, `p90`, `range`, `stdev`, `mean_abs_delta`, or `periodicity`) across all samples.
- `gate(observed, baseline_fields, ceilings, tolerances, fields, done_ok)` — checks each gated field against (a) its configured ceiling (absolute hard cap) and (b) `baseline + tolerance` (regression check). Also fails when `done_ok` is False (scenario did not complete). Returns a verdict dict with `passed`, `rows` (one per field with observed/baseline/delta/ceiling/result), and `reasons` (failure descriptions).

**`analyzer/report.py`**
- `render_report(meta, verdict, shots, raw)` — renders a markdown report from the verdict: header, gate table, embedded checkpoint screenshots, failure list, and a collapsed raw-dump appendix.

**`analyzer/config.py`**
- `load_config(path)` — loads and validates a JSON config, raising on missing required keys.
- `resolve_symbol_address(symbol_table_text, name)` — extracts a symbol's work-RAM address from an SGDK-style text symbol table for the export sampler.

**`analyzer/cli.py`**
- Entry point invoked by the orchestrator. Wires `--config`, `--backend`, `--samples-file`, `--samples-format`, `--shots-dir`, `--out`, `--update-baseline`, and metadata flags into the full parse → aggregate → gate → report pipeline. Exits 0 on PASS, 1 on FAIL.

**`analyzer/profile.py`** (PC-sampling profiler — a parallel pipeline, independent of the gate)
- `parse_pc_samples(text)`, `parse_symbol_table(text)`, `profile_samples(symbol_text, pcs)`,
  `render_profile_report(...)` — a **clock-agnostic** symbolizer: it maps a flat list of sampled
  68k program-counter values to their enclosing code symbol (nm-style address ranges from
  `symbol.txt`) and ranks them into a function-level flame table. It knows nothing about *how*
  the PCs were sampled, so any clock can feed it. CLI: `python -m analyzer.profile`. The PCs come
  from the drop-in HInt sampler in `instrumentation/` (see `PROFILING.md` for the end-to-end
  dump procedure). This shares the gate's host-independence: the emulated sampling is
  deterministic, so the profile is reproducible regardless of host speed.

The analyzer never interprets what a metric means — it samples named fields from a flat array and gates them against configured ceilings and a committed baseline. Adding a new direct or derived metric is purely a config change.

---

## Layer 2 — Per-backend PowerShell adapters (`backends/`, `lib/`)

Each adapter is a single PowerShell script that accepts two actions: `sample` and `screenshot`. It launches its emulator, acquires data, writes files to `<outDir>`, and returns. It never calls the analyzer.

### `backends/blastem.ps1`

- **sample**: launches `blastem <rom> -D` to expose a GDB remote stub, waits for the port to be listening, then delegates to `lib/gdb_sample.ps1`. Force-kills BlastEm in a `finally` block.
- **screenshot**: delegates to `lib/blastem_screenshot.ps1`, which uses the BlastEm screenshot key at wall-clock checkpoint times (`atSeconds`).
- When `EmuPath` is null, calls `install_blastem.ps1` to auto-install and reads the installed path from `blastem/path.txt`.

### `backends/emusplatter.ps1`

- **sample (export mode)**: runs `emusplatter --rom <rom> --headless --frames <N> --dump-workram <addr>,<size>,<file>`. Fully headless, no GDB required. The perf block is written to the dump file once per frame; `parse_export` reads all frames and `aggregate` recovers the worst-case values.
- **sample (gdb mode)**: runs `emusplatter --rom <rom> --headless --frames <N> --gdb-server <port>`, then delegates to `lib/gdb_sample.ps1` exactly like the blastem backend.
- **screenshot**: runs `emusplatter --headless --frames <atFrame> --screenshot <out>` once per checkpoint — frame-exact and deterministic.

### `lib/gdb_sample.ps1` — shared GDB sampler

Used by both blastem and emusplatter (gdb mode). Constructs a batch `.gdb` script:

```
set pagination off
set confirm off
target remote :<port>
<preroll commands>
break <TriggerSymbol>
continue
x/<count><width> &<Symbol>
... (repeated Samples times)
x/1<width> &<DoneSymbol>
disconnect
quit
```

Writes the script to a GUID-named temp file, runs `gdb -q -batch -x <script> <elf>`, captures stdout to a second temp file, reads it, removes all temp files, and returns the raw dump. In `-DryRun` mode, prints the script and removes the temp file without launching GDB. A 60-second timeout hard-kills the GDB process.

### `mdbug.ps1` — orchestrator

Reads the config, resolves all paths relative to the config file's directory, dispatches the sample pass and screenshot pass to the chosen backend adapter, then invokes `python -m analyzer.cli` with the output files and metadata. Sets the process exit code from the analyzer's exit code. Handles `-NoBuild`, `-NoScreenshots`, `-UpdateBaseline`, `-DryRun`.

---

## Data flow

```
mdbug.ps1
  |
  |-- (optional) build: config.build.command in config.build.cwd
  |
  |-- backends/<backend>.ps1  Action=sample
  |     |-- blastem: blastem -D  -->  lib/gdb_sample.ps1  -->  <outDir>/samples.txt
  |     |-- emusplatter export:  emusplatter --dump-workram  -->  <outDir>/samples.txt
  |     `-- emusplatter gdb:     emusplatter --gdb-server  -->  lib/gdb_sample.ps1  -->  <outDir>/samples.txt
  |
  |-- backends/<backend>.ps1  Action=screenshot
  |     |-- blastem:     lib/blastem_screenshot.ps1  -->  <outDir>/shots/*.png
  |     `-- emusplatter: emusplatter --screenshot     -->  <outDir>/shots/*.png
  |
  `-- python -m analyzer.cli
        |-- parse <outDir>/samples.txt  (gdb or export format)
        |-- aggregate per field (max / last / sum)
        |-- gate vs ceilings + baseline.<backend>.json + done-flag
        |-- render report.md (table + screenshots + verdict + raw dump)
        `-- exit 0 (PASS) / 1 (FAIL)
```

---

## Key design properties

- **No cross-layer imports.** The Python analyzer never calls PowerShell; the PowerShell adapters never import Python modules. Communication is through files and process exit codes only.
- **One normalized sample shape.** Both `parse_gdb_dump` and `parse_export` produce `list[list[int]]`. The rest of the analyzer is format-blind.
- **Config is the only project-specific artifact.** Field names, indices, aggregates, units, ceilings, trigger symbol, done-flag symbol, checkpoint times, and baseline paths are all in the JSON config. The harness has no hardcoded jazzmd knowledge.
- **Per-backend baselines.** `baseline.{backend}.json` is resolved at run time; absolute cycle counts differ between emulators, so each backend is gated against its own committed ground truth.
- **Host-testable without an emulator.** The entire analyzer layer is exercised by `python -m pytest` against synthetic dumps. No emulator, ROM, or ELF is required for CI on the harness itself.
