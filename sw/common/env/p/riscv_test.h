// riscv_test.h - custom riscv-tests environment for this core (docs/spec.md §12; exec.md M5.1).
//
// Replaces tests/riscv-tests/env/p/riscv_test.h, which sets up CSRs (mtvec,
// mstatus, PMP, ...) that Phase 1 does not have. The rv32ui tests include
// this file and isa/macros/scalar/test_macros.h, and use only the macros
// below (spec §12 lists them and the behaviour each must have):
//
//   RVTEST_RV32U / RVTEST_RV64U  empty markers (the rv32ui wrappers redefine
//                                RVTEST_RV64U to RVTEST_RV32U)
//   RVTEST_CODE_BEGIN            entry at _start in .text.init, all registers zeroed
//   RVTEST_CODE_END              unimp, as upstream: never reached, and if it
//                                were, the core stops with STOP_ILLEGAL (exit 3)
//   TESTNUM                      gp, the number of the failing test case
//   RVTEST_PASS                  tohost = 1
//   RVTEST_FAIL                  tohost = (TESTNUM << 1) | 1; TEST_PASSFAIL puts
//                                FAIL right before PASS, so FAIL must end the test
//   RVTEST_DATA_BEGIN / _END     as upstream: tohost/fromhost, begin/end_signature
//
// Both PASS and FAIL end with ECALL; the harness has already ended the run
// at the tohost store (spec §11), so the ECALL only matters if it has not.

#ifndef SW_ENV_P_RISCV_TEST_H
#define SW_ENV_P_RISCV_TEST_H

#define RVTEST_RV64U
#define RVTEST_RV32U

#define TESTNUM gp

#define INIT_XREG                                                       \
  li x1, 0;  li x2, 0;  li x3, 0;  li x4, 0;  li x5, 0;  li x6, 0;      \
  li x7, 0;  li x8, 0;  li x9, 0;  li x10, 0; li x11, 0; li x12, 0;     \
  li x13, 0; li x14, 0; li x15, 0; li x16, 0; li x17, 0; li x18, 0;     \
  li x19, 0; li x20, 0; li x21, 0; li x22, 0; li x23, 0; li x24, 0;     \
  li x25, 0; li x26, 0; li x27, 0; li x28, 0; li x29, 0; li x30, 0;     \
  li x31, 0;

#define RVTEST_CODE_BEGIN                                               \
        .section .text.init, "ax", @progbits;                           \
        .align  6;                                                      \
        .globl  _start;                                                 \
_start:                                                                 \
        INIT_XREG

#define RVTEST_CODE_END                                                 \
        unimp

#define RVTEST_PASS                                                     \
        fence;                                                          \
        li TESTNUM, 1;                                                  \
        sw TESTNUM, tohost, t5;                                         \
        ecall

#define RVTEST_FAIL                                                     \
        fence;                                                          \
1:      beqz TESTNUM, 1b;                                               \
        sll TESTNUM, TESTNUM, 1;                                        \
        or TESTNUM, TESTNUM, 1;                                         \
        sw TESTNUM, tohost, t5;                                         \
        ecall

#define EXTRA_DATA

#define RVTEST_DATA_BEGIN                                               \
        EXTRA_DATA                                                      \
        .pushsection .tohost,"aw",@progbits;                            \
        .align 6; .global tohost; tohost: .dword 0; .size tohost, 8;    \
        .align 6; .global fromhost; fromhost: .dword 0; .size fromhost, 8;\
        .popsection;                                                    \
        .align 4; .global begin_signature; begin_signature:

#define RVTEST_DATA_END .align 4; .global end_signature; end_signature:

#endif
