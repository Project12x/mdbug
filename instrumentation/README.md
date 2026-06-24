# mdbug instrumentation — drop-in target code

Reusable, project-agnostic ROM-side instrumentation that a Mega Drive / SGDK project copies
in to be measurable by mdbug. All of it is **build-flag gated** (default OFF → byte-identical
shipped build).

## `pc_sample.{h,c}` + `pc_sample_hint.s` — PC-sampling profiler
A per-scanline HInt that captures the **interrupted 68000 PC** (via an asm trampoline that
reads it from the hardware interrupt frame) into a RAM ring, for statistical function-level
profiling. Gated behind `DEBUG_PC_SAMPLE`.

**Use:**
1. Copy `pc_sample.h` → your `inc/`; `pc_sample.c` + `pc_sample_hint.s` → your `src/` (SGDK
   assembles `src/*.s`).
2. Add a `DEBUG_PC_SAMPLE` build flag to `build_config.h` (default 0).
3. Call `pc_sample_install()` once at scene start and `pc_sample_arm()` once after the settle
   (both `#if DEBUG_PC_SAMPLE`).
4. Follow **`../PROFILING.md`** to dump + symbolize.

Knobs: `PC_SAMPLE_MAX`, `PC_SAMPLE_SKIP`, `PC_SAMPLE_ARM_FRAME` (see the header).

> The reference live instance is jazzmd (`src/pc_sample.*`, `inc/pc_sample.h`,
> `build.bat … pc-sample`). Keep this template and that instance in sync.
