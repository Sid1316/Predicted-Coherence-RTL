// model_test.h - riscv-arch-test target macros for this core (docs/spec.md §11, §12; exec.md M5.3).
//
// Based on riscof-plugins/rv32/spike_simple/env/model_test.h in the pinned
// riscv-arch-test (3.10.0):
//   RVMODEL_DATA_BEGIN  tohost/fromhost in .tohost, then begin_signature
//   RVMODEL_DATA_END    end_signature
//   RVMODEL_HALT        stores 1 to tohost; the harness ends the run at that
//                       store (spec §11), the loop is only a fallback
//   RVMODEL_BOOT, IO    empty
// rvtest_mtrap_routine is NOT defined: arch_test.h then installs no CSR trap
// handler, and the rv32i_m/I tests run without CSRs (spec §12).

#ifndef _COMPLIANCE_MODEL_H
#define _COMPLIANCE_MODEL_H

#if XLEN == 64
  #define ALIGNMENT 3
#else
  #define ALIGNMENT 2
#endif

#define RVMODEL_DATA_SECTION                                            \
        .pushsection .tohost,"aw",@progbits;                            \
        .align 8; .global tohost; tohost: .dword 0;                     \
        .align 8; .global fromhost; fromhost: .dword 0;                 \
        .popsection;

#define RVMODEL_HALT                                                    \
        li x1, 1;                                                       \
1:                                                                      \
        sw x1, tohost, t2;                                              \
        j 1b;

#define RVMODEL_BOOT

#define RVMODEL_DATA_BEGIN                                              \
        RVMODEL_DATA_SECTION                                            \
        .align ALIGNMENT;                                               \
        .global begin_signature; begin_signature:

#define RVMODEL_DATA_END                                                \
        .global end_signature; end_signature:

#define RVMODEL_IO_INIT
#define RVMODEL_IO_WRITE_STR(_R, _STR)
#define RVMODEL_IO_CHECK()
#define RVMODEL_IO_ASSERT_GPR_EQ(_S, _R, _I)
#define RVMODEL_IO_ASSERT_SFPR_EQ(_F, _R, _I)
#define RVMODEL_IO_ASSERT_DFPR_EQ(_D, _R, _I)

#define RVMODEL_SET_MSW_INT
#define RVMODEL_CLEAR_MSW_INT
#define RVMODEL_CLEAR_MTIMER_INT
#define RVMODEL_CLEAR_MEXT_INT

#endif // _COMPLIANCE_MODEL_H
