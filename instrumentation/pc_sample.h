// PC-sampling profiler instrumentation -- mdbug reusable drop-in.
//
// A per-scanline HInt captures the *interrupted* 68k PC into a RAM ring; gdb dumps
// g_pc_samples once after a deterministic run, and mdbug's analyzer/profile.py
// symbolizes them into a function-level flame split. Gated behind DEBUG_PC_SAMPLE
// (default OFF -> zero cost / byte-identical shipped build).
//
// Drop-in: copy pc_sample.{h,c} + pc_sample_hint.s into your project's inc/ + src/,
// add a DEBUG_PC_SAMPLE build flag (see PROFILING.md), and from your scene/level:
//   pc_sample_install();  // once, at scene start (installs the per-scanline HInt)
//   pc_sample_arm();      // once, after the settle (begin capturing)
#ifndef PC_SAMPLE_H
#define PC_SAMPLE_H

#if defined(SGDK_GCC) && defined(__has_include)
#if __has_include("build_config.h")
#include "build_config.h"
#endif
#endif
#ifndef DEBUG_PC_SAMPLE
#define DEBUG_PC_SAMPLE 0
#endif

#if DEBUG_PC_SAMPLE
#include <genesis.h>

#ifndef PC_SAMPLE_MAX
#define PC_SAMPLE_MAX 1024        // ring capacity (PC_SAMPLE_MAX * 4 bytes RAM)
#endif
#ifndef PC_SAMPLE_SKIP
#define PC_SAMPLE_SKIP 8          // store every Nth scanline -> spread over more frames
#endif
#ifndef PC_SAMPLE_ARM_FRAME
#define PC_SAMPLE_ARM_FRAME 60u   // arm after the settle so samples land in the hot section
#endif

extern volatile u32 g_pc_samples[PC_SAMPLE_MAX];
extern volatile u16 g_pc_sample_idx;     // # samples captured (caps at PC_SAMPLE_MAX)
extern volatile u16 g_pc_sample_armed;

void pc_sample_install(void);  // install the per-scanline HInt (once, at scene start)
void pc_sample_arm(void);      // begin capturing
#endif

#endif
