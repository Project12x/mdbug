/* PC-sampling HInt trampoline -- mdbug reusable drop-in.
 *
 * A C __attribute__((interrupt)) handler cannot reliably recover the interrupted
 * PC: its prologue saves an unknown number of registers, so the [SR,PC] hardware
 * frame sits at a non-fixed offset (and __builtin_return_address lands on the SR).
 * This asm trampoline controls its own pushes, so the PC offset is FIXED:
 *   68000 interrupt entry pushes SR(word) + PC(long); sp -> SR.
 *   after movem of 4 longs (16 bytes): SR at sp+16, PC (long) at sp+18.
 * It reads that PC, calls the C recorder, restores, and rte's. Built only when
 * DEBUG_PC_SAMPLE is set (cpp gate). Assembled with --register-prefix-optional
 * (bare register names) per SGDK's makefile.gen .s rule. */
#if defined(__has_include)
#if __has_include("build_config.h")
#include "build_config.h"
#endif
#endif
#ifndef DEBUG_PC_SAMPLE
#define DEBUG_PC_SAMPLE 0
#endif

#if DEBUG_PC_SAMPLE
    .text
    .even
    .global pc_sample_hint
pc_sample_hint:
    movem.l d0-d1/a0-a1,-(sp)   /* save caller-saved (16 bytes) */
    move.l  18(sp),d0           /* interrupted PC: 16 saved + 2 (SR word) */
    move.l  d0,-(sp)            /* push as the recorder's u32 pc arg */
    jsr     pc_sample_record
    addq.l  #4,sp               /* pop arg */
    movem.l (sp)+,d0-d1/a0-a1   /* restore */
    rte
#endif
