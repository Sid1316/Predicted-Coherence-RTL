/* core_portme.h - CoreMark port to rv_soc_sim (docs/exec.md M7.1).
 *
 * Adapted from CoreMark's barebones/core_portme.h (sw/bench/third_party/coremark).
 *   - Timer: the CYCLE counter MMIO (spec §2.3, sim/rv_soc_sim.sv), read by
 *     barebones_clock() in core_portme.c. EE_TICKS_PER_SEC = 1000000, a
 *     notional 1 MHz clock: "Total ticks" is cycles in the timed portion, and
 *     CoreMark/MHz = 1e6 * Iterations / Total ticks.
 *   - No floating point (HAS_FLOAT 0) and printf from rvlib (HAS_PRINTF 1).
 *   - 2K performance run (seeds 0, 0, 0x66), data on the stack.
 * A 1-iteration simulation runs far short of the 10 seconds CoreMark's
 * reporting rules ask for, so CoreMark prints that error; the CRC checks
 * that validate the run are unaffected (build.txt checks them).
 */
#ifndef CORE_PORTME_H
#define CORE_PORTME_H

#include <stddef.h>

#include "rvlib.h"   /* printf (ee_printf with HAS_PRINTF), rv_cycles */

#define HAS_FLOAT 0
#define HAS_TIME_H 0
#define USE_CLOCK 0
#define HAS_STDIO 0
#define HAS_PRINTF 1

#ifndef COMPILER_VERSION
#ifdef __GNUC__
#define COMPILER_VERSION "GCC"__VERSION__
#else
#define COMPILER_VERSION "unknown"
#endif
#endif
#ifndef COMPILER_FLAGS
#define COMPILER_FLAGS FLAGS_STR
#endif
#ifndef MEM_LOCATION
#define MEM_LOCATION "STACK"
#endif

typedef signed short   ee_s16;
typedef unsigned short ee_u16;
typedef signed int     ee_s32;
typedef double         ee_f32;
typedef unsigned char  ee_u8;
typedef unsigned int   ee_u32;
typedef ee_u32         ee_ptr_int;
typedef size_t         ee_size_t;

#define align_mem(x) (void *)(4 + (((ee_ptr_int)(x) - 1) & ~3))

#define CORETIMETYPE ee_u32
typedef ee_u32 CORE_TICKS;

#ifndef SEED_METHOD
#define SEED_METHOD SEED_VOLATILE
#endif
#ifndef MEM_METHOD
#define MEM_METHOD MEM_STACK
#endif
#ifndef MULTITHREAD
#define MULTITHREAD 1
#define USE_PTHREAD 0
#define USE_FORK 0
#define USE_SOCKET 0
#endif
#ifndef MAIN_HAS_NOARGC
#define MAIN_HAS_NOARGC 0
#endif
#ifndef MAIN_HAS_NORETURN
#define MAIN_HAS_NORETURN 0
#endif

extern ee_u32 default_num_contexts;

typedef struct CORE_PORTABLE_S {
  ee_u8 portable_id;
} core_portable;

void portable_init(core_portable *p, int *argc, char *argv[]);
void portable_fini(core_portable *p);

#if !defined(PROFILE_RUN) && !defined(PERFORMANCE_RUN) && !defined(VALIDATION_RUN)
#if (TOTAL_DATA_SIZE == 1200)
#define PROFILE_RUN 1
#elif (TOTAL_DATA_SIZE == 2000)
#define PERFORMANCE_RUN 1
#else
#define VALIDATION_RUN 1
#endif
#endif

int ee_printf(const char *fmt, ...);

#endif /* CORE_PORTME_H */
