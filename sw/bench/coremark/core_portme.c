/* core_portme.c - CoreMark port to rv_soc_sim (docs/exec.md M7.1); see core_portme.h.
 * Adapted from CoreMark's barebones/core_portme.c. */
#include "coremark.h"
#include "core_portme.h"
#include "rvlib.h"

#if VALIDATION_RUN
volatile ee_s32 seed1_volatile = 0x3415;
volatile ee_s32 seed2_volatile = 0x3415;
volatile ee_s32 seed3_volatile = 0x66;
#endif
#if PERFORMANCE_RUN
volatile ee_s32 seed1_volatile = 0x0;
volatile ee_s32 seed2_volatile = 0x0;
volatile ee_s32 seed3_volatile = 0x66;
#endif
#if PROFILE_RUN
volatile ee_s32 seed1_volatile = 0x8;
volatile ee_s32 seed2_volatile = 0x8;
volatile ee_s32 seed3_volatile = 0x8;
#endif
volatile ee_s32 seed4_volatile = ITERATIONS;
volatile ee_s32 seed5_volatile = 0;

/* The CYCLE counter: cycles since reset (fits 32 bits for these runs). */
static CORETIMETYPE barebones_clock(void) { return (CORETIMETYPE)rv_cycles(); }

#define EE_TICKS_PER_SEC 1000000u      /* notional 1 MHz: one tick per cycle */

static CORETIMETYPE start_time_val, stop_time_val;

void start_time(void) { start_time_val = barebones_clock(); }
void stop_time(void) { stop_time_val = barebones_clock(); }
CORE_TICKS get_time(void) { return (CORE_TICKS)(stop_time_val - start_time_val); }
secs_ret time_in_secs(CORE_TICKS ticks) { return (secs_ret)ticks / (secs_ret)EE_TICKS_PER_SEC; }

ee_u32 default_num_contexts = 1;

void portable_init(core_portable *p, int *argc, char *argv[]) {
  (void)argc;
  (void)argv;
  if (sizeof(ee_ptr_int) != sizeof(ee_u8 *)) ee_printf("ERROR! Please define ee_ptr_int to a type that holds a pointer!\n");
  if (sizeof(ee_u32) != 4) ee_printf("ERROR! Please define ee_u32 to a 32b unsigned type!\n");
  p->portable_id = 1;
}

void portable_fini(core_portable *p) { p->portable_id = 0; }
