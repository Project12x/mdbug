# HOWTO — mdbug

## Run the gate

```powershell
pwsh -File mdbug.ps1 -Config path\to\your.config.json
```

The orchestrator will (unless flags suppress a step):
1. Run `config.build.command` in `config.build.cwd` to build the ROM.
2. Resolve the perf-block work-RAM address from the ELF symbol table (export mode only).
3. Launch the backend to sample the perf block into `<outDir>/samples.txt`.
4. Run a screenshot pass into `<outDir>/shots/` at each configured checkpoint.
5. Run the Python analyzer (`python -m analyzer.cli`) to parse, aggregate, gate, and write `<outDir>/report.md`.
6. Exit 0 (PASS) or 1 (FAIL).

`<outDir>` is the value of `config.report.outDir`, resolved relative to the config file's directory.

Useful flags:
- `-NoBuild` — skip the build step; use the ROM already on disk.
- `-NoScreenshots` — skip the screenshot pass. Optional headlessly: when no
  window handle is available the screenshot pass now warns and continues instead
  of failing the run.
- `-DryRun` — print all commands without launching any process.

`mdbug.ps1` resolves gdb via a fallback chain so a headless run does not silently
yield zero samples: `backends.<backend>.gdb` → `$env:GDK\bin\gdb.exe` →
`build.gdk\bin\gdb.exe` → `C:\SDKs\SGDK\bin\gdb.exe` → `C:\SDKS\SGDK\bin\gdb.exe`
→ PATH (`m68k-elf-gdb`, then `gdb`). If none is found it throws one error naming
every candidate it tried. Export-mode backends (emusplatter) need no gdb and skip
this entirely.

## Read the report

`<outDir>/report.md` contains:

- A header with project name, git SHA, date, backend, and a bold **PASS** or **FAIL** verdict.
- A gate table with one row per configured field:

  | Metric | Observed | Baseline | Delta | Ceiling | Result |
  |---|---|---|---|---|---|
  | cpu_load_max | 142 % | 140 | +2 | 180 | pass |
  | overrun | 0 frames | 0 | +0 | - | pass |

  - **Metric** — field name from config.
  - **Observed** — the aggregate value (max/last/sum across samples) with its unit.
  - **Baseline** — the committed baseline value for this field (`-` when no baseline exists yet).
  - **Delta** — observed minus baseline (`-` when no baseline).
  - **Ceiling** — the hard absolute cap from `config.gate.ceilings` (`-` when none configured).
  - **Result** — `pass`, `fail`, or `info` (for `gate: false` fields that are recorded but not gated).

- A **Screenshots** section with embedded checkpoint PNGs from `<outDir>/shots/`.
- A **Trajectory** section (only when `config.watch` is set) — a table with a
  `sample` column plus one column per watched global, one row per interval (see
  "Watch globals over time" below).
- A **Failures** section listing each specific failure reason (only present on FAIL),
  titled **Invalid** instead when the verdict is INVALID.
- A collapsed `<details>` block with the raw GDB or export dump for forensics.

## Verdicts: PASS / FAIL / INVALID

The gate has three verdicts:

- **PASS** — every gated field is within its ceiling and baseline+tolerance, the
  scenario completed, and (if configured) all validity requirements hold. Exit 0.
- **FAIL** — a gated field breached its ceiling or regressed past tolerance, or the
  scenario did not complete. Exit 1.
- **INVALID** — the run produced no usable activity, so its numbers cannot be
  trusted (distinct from FAIL). Configure with `gate.validity.requireNonzero`, a
  list of field names that must be nonzero:

  ```json
  "gate": { "validity": { "requireNonzero": ["scroll_max"] } }
  ```

  If any listed field is zero or missing, the verdict is INVALID, the report shows
  **Result: INVALID** with an `<field> == 0 (no activity) -- gate INVALID` reason,
  and the exit code is nonzero. This catches runs where the camera never moved or
  the workload never started — numbers that would otherwise spuriously "pass".

## A/B compare two runs

Capture a snapshot during any normal run with `--save-snapshot NAME` (passed
through the analyzer; not yet a `mdbug.ps1` flag — call the analyzer directly or
add it to your wrapper):

```powershell
python -m analyzer.cli --config your.config.json --samples-file out/samples.txt --samples-format gdb --save-snapshot before
# ...make a change, rebuild, sample again...
python -m analyzer.cli --config your.config.json --samples-file out/samples.txt --samples-format gdb --save-snapshot after
```

Each snapshot is written to `<cfg_dir>/perf/snap.<NAME>.json`. Then render a
side-by-side delta table (compare mode needs no live samples):

```powershell
python -m analyzer.cli --config your.config.json --compare before after --out out/compare.md
```

This produces `| Metric | before | after | Delta |` rows for every configured
field and exits 0.

## Watch globals over time

Add an optional top-level `watch` array to trace globals across intervals:

```json
"watch": [
  { "name": "cam_x", "symbol": "g_dbg_cam_x" },
  { "name": "cam_y", "symbol": "g_dbg_cam_y", "type": "s16" }
]
```

Each entry maps a column name to a global **lvalue** `symbol`. The sampler reads
it as `*(ctype*)&symbol`, where `ctype` comes from the optional `"type"`
(`u8/s8/u16/s16/u32/s32`, default `u16`) — the cast is REQUIRED because under
`-O3/-flto` the watched globals are minimal symbols with no DWARF type, so a bare
`printf "%d", symbol` fails with "unknown type". Use `"type": "raw"` to skip the
cast and provide a fully-formed gdb expression in `symbol` instead. The GDB
sampler emits one `MDBUG_WATCH <name> <value>` line per interval after the perf
dump; these lines are ignored by perf parsing and collected by `parse_watch`
into per-name series.
The report appends a **Trajectory** table — one row per interval, one column per
watch (short series are padded with `-`). Watch is GDB-mode only; export-mode
backends do not emit watch lines.

## Re-baseline

Run with `-UpdateBaseline` to capture the current observed values as the new baseline:

```powershell
pwsh -File mdbug.ps1 -Config path\to\your.config.json -UpdateBaseline
```

This writes (or overwrites) `config.gate.baseline` (with `{backend}` resolved to the active backend). Do this deliberately — only when you have intentionally traded performance and accept the new numbers as the ground truth. Commit the updated baseline file alongside the code change.

Per-backend baselines are independent; re-baselining on one backend does not affect the other.

## Switch backends

Pass `-Backend` to override the config default:

```powershell
pwsh -File mdbug.ps1 -Config path\to\your.config.json -Backend blastem
pwsh -File mdbug.ps1 -Config path\to\your.config.json -Backend emusplatter
```

The config's `backends.default` is used when `-Backend` is omitted.

## Run the host tests

The Python analyzer has a pytest suite that requires no emulator:

```powershell
cd C:\path\to\mdbug
python -m pytest -v
```

Expected: 55 passed. The suite covers `parse_gdb_dump`, `parse_export`, `parse_watch`, `aggregate`, `gate` (incl. validity/INVALID), `render_report` (incl. trajectory), `render_compare`, `load_config`, the PC-sampling symbolizer, and the CLI round-trip (incl. snapshot/compare modes).

`jsonschema` is an optional dev dependency used to validate configs against `config.schema.json`. If not installed, schema validation is skipped. Install with:

```powershell
pip install jsonschema
```

## Validate a config against the schema

If `jsonschema` is installed:

```python
import json, jsonschema
schema = json.load(open("config.schema.json"))
cfg = json.load(open("path/to/your.config.json"))
jsonschema.validate(cfg, schema)
```

Or use any JSON Schema v7 validator pointed at `config.schema.json`.

## Getting stable / low-noise benchmark numbers

The gate metrics (especially `cpu_load_max` from SGDK `SYS_getCPULoad()`) are sensitive to host machine load. Other programs, browsers, antivirus, indexers, or background builds steal CPU from BlastEm, causing higher peaks and more "overrun" detections even when the emulated 68k work is unchanged.

What the harness does:
- For the `blastem` backend it now sets the emulator process to `High` priority immediately after launch (in `backends/blastem.ps1`).
- `emusplatter` (when configured) is fully headless and uses direct work-RAM dumps per emulated frame — this is the most deterministic/reproducible path.

Recommended procedure for a trustworthy gate run:
1. Close or pause everything heavy (Chrome with many tabs, VSCode watchers, OneDrive sync, Discord, etc.).
2. Optionally set the PowerShell or cmd window to high priority too.
3. Prefer `-Backend emusplatter` if you have a working build of the fork.
4. Run the gate.
5. If variance is still high, run 2-3 times and look at the best (or median) before deciding to rebaseline.

The vcounter-derived numbers (`overrun`, `scroll_max`, `phys_max`, `sprite_max`) are generally more trustworthy than `cpu_load_max` because they are measured inside emulated time.

## Install BlastEm (blastem backend)

```powershell
pwsh -File install_blastem.ps1
```

This is called automatically by `backends/blastem.ps1` when `backends.blastem.path` is null. The installed path is cached in `blastem/path.txt`.

## Adopt mdbug in a new project

1. Add `mdbug` as a submodule (or copy) under your project's `tools/` directory.
2. Author a `<project>.config.json` using `examples/example.config.json` as a template. Fill in: ROM/ELF build paths, perf block symbol + field map, trigger/done-flag symbols, backend paths, checkpoint times, gate ceilings.
3. Run with `-UpdateBaseline` to capture the first baseline.
4. Commit the baseline JSON alongside the config.
5. Wire `pwsh -File tools/mdbug/mdbug.ps1 -Config tools/mdbug.config.json` into CI.
