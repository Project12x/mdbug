// mdp_label.h -- optional md-profiler inline-function annotations (mdbug drop-in).
//
// md-profiler (a host-side *tracing* profiler; see tools/mdbug/TRACE.md) follows
// JSR/BSR calls, so functions the compiler INLINES (SGDK -O3/-flto) vanish from
// its call graph. These macros emit global asm labels at a function's entry/exit
// points that md-profiler can treat as an interval -- WITHOUT changing the
// generated code -- so you can profile inlined helpers on the exact optimized
// build that ships. (This is the inline-as-statistical PC-sampler's blind spot
// inverted: the PC-sampler + pyelftools DWARF already *sees* inlined code; this
// lets the tracing profiler attribute time to it too.)
//
// Gated behind DEBUG_MDP_LABELS (default OFF -> the macros vanish -> the shipped
// build is byte-identical). When ON, the labels are pure markers: they emit no
// instructions, only symbols, so the optimized codegen is unaffected.
//
// Usage:
//   #include "mdp_label.h"
//   s16 helper(s16 a) {
//     FUNCTION_START("helper");
//     if (a > 0) { FUNCTION_END("helper"); return a + 1; }  // before EVERY return
//     FUNCTION_END("helper");
//     return 0;
//   }
// then put `helper` on its own line in your md-profiler interval file and record
// a trace with mbp/mdp (see TRACE.md).
#ifndef MDP_LABEL_H
#define MDP_LABEL_H

#if defined(SGDK_GCC) && defined(__has_include)
#if __has_include("build_config.h")
#include "build_config.h"
#endif
#endif
#ifndef DEBUG_MDP_LABELS
#define DEBUG_MDP_LABELS 0
#endif

#if DEBUG_MDP_LABELS
// `%=` expands to a unique number per asm instance (so the same FUNCTION_END can
// appear before several returns); `.global` exports the label for md-profiler.
// The emitted symbol is `mdp_label_<name>_start_<n>` / `_end_<n>` (the %= suffix).
// md-profiler matches the BARE name you list in the interval file against this
// prefix (its README example does exactly that). If labels don't resolve, check
// your md-profiler version's matching semantics.
#define MDP_LABEL(name) \
    __asm__ volatile ("mdp_label_" name "_%=: .global mdp_label_" name "_%=" :)
#define FUNCTION_START(name) MDP_LABEL(name "_start")
#define FUNCTION_END(name)   MDP_LABEL(name "_end")
#else
#define MDP_LABEL(name)      do {} while (0)
#define FUNCTION_START(name) do {} while (0)
#define FUNCTION_END(name)   do {} while (0)
#endif

#endif
