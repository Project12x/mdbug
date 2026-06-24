#include "pc_sample.h"
#if DEBUG_PC_SAMPLE

volatile u32 g_pc_samples[PC_SAMPLE_MAX];
volatile u16 g_pc_sample_idx = 0;
volatile u16 g_pc_sample_armed = 0;

// The per-scanline HInt is a tiny asm trampoline (pc_sample_hint.s) that reads the
// interrupted 68000 PC straight from the hardware interrupt frame and calls this
// recorder. (A C interrupt handler can't recover the PC reliably -- the frame
// offset depends on the compiler-chosen prologue saves, and
// __builtin_return_address lands on the saved SR.) __attribute__((used)) keeps the
// recorder under -flto: its only caller is the asm `jsr`.
extern void pc_sample_hint(void);  // asm trampoline

// Breakpoint anchor: the harness can break here and run ONE `continue` so the
// emulator fills the ring at full speed, then dump. noinline+used so the symbol
// survives -O3/-flto.
__attribute__((noinline, used)) void pc_sample_done(void) {}

__attribute__((used)) void pc_sample_record(u32 pc) {
  if (g_pc_sample_armed && g_pc_sample_idx < PC_SAMPLE_MAX) {
    g_pc_samples[g_pc_sample_idx++] = pc;
    if (g_pc_sample_idx >= PC_SAMPLE_MAX) pc_sample_done();
  }
}

void pc_sample_install(void) {
  g_pc_sample_idx = 0;
  g_pc_sample_armed = 0;
  // Hardware subsample: fire the HInt every PC_SAMPLE_SKIP-th scanline (counter N
  // => every N+1 lines) instead of firing every line and discarding in software --
  // same sample density, ~PC_SAMPLE_SKIP x less observer overhead.
  SYS_setHIntCallback(pc_sample_hint);
  VDP_setHIntCounter(PC_SAMPLE_SKIP - 1);
  VDP_setHInterrupt(TRUE);
}

void pc_sample_arm(void) { g_pc_sample_armed = 1; }
#endif
