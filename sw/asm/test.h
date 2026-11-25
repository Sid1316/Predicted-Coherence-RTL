// test.h - macros for the directed tests in sw/asm/ (docs/exec.md M3.5, docs/spec.md §11, §15.2).
//
// A test is a .S file (run through the C preprocessor) laid out as:
//
//   // expect: 0                       <- see "Header" below
//   #include "test.h"
//   TEST_BEGIN
//     li     a0, 5
//     CHECK  (2, a0, 5)                 // check 2: a0 must be 5
//   TEST_PASS
//   TEST_DATA
//
// Registers: gp (x3) holds the number of the check being made (TESTNUM, as
// in riscv-tests), t6 (x31) is scratch for CHECK and t5 (x30) for the
// tohost store. Tests leave gp, t5 and t6 to the macros.
//
// Result (spec §11): TEST_PASS stores 1 to tohost; a failing CHECK n stores
// (n << 1) | 1, so the harness exits 1 and prints test=n. Check numbers start
// at 2: 1 would encode as 3, but 0 would encode as 1, the pass value.
//
// Header: the first lines hold "// expect: <exit code> [<stop cause>]", e.g.
// "// expect: 3 STOP_ILLEGAL", which the runner checks; "// console: <text>"
// (Python escapes, e.g. \n) adds a check of the console output. The spec's
// example writes the header with '#', which the C preprocessor rejects in a
// .S file, so these use '//'; the runner accepts both.
//
// Error tests (e*) contain exactly one stopping instruction, followed by
// TEST_UNREACHED: if the core does not stop there, the test fails with
// check number 99 (exit 1), not with a misleading pass.

#ifndef SW_ASM_TEST_H
#define SW_ASM_TEST_H

#define TESTNUM gp

#define CONSOLE_ADDR 0x10000000

// Entry: .text.init at the reset vector; every register zeroed (the register
// file has no reset, spec §2.2), so a test never reads a random value.
#define TEST_BEGIN                                                            \
  .section .text.init, "ax", @progbits;                                       \
  .globl _start;                                                              \
_start:                                                                       \
  li x1, 0;  li x2, 0;  li x3, 0;  li x4, 0;  li x5, 0;  li x6, 0;            \
  li x7, 0;  li x8, 0;  li x9, 0;  li x10, 0; li x11, 0; li x12, 0;           \
  li x13, 0; li x14, 0; li x15, 0; li x16, 0; li x17, 0; li x18, 0;           \
  li x19, 0; li x20, 0; li x21, 0; li x22, 0; li x23, 0; li x24, 0;           \
  li x25, 0; li x26, 0; li x27, 0; li x28, 0; li x29, 0; li x30, 0;           \
  li x31, 0;

// Check that register `reg` holds `value`; on a mismatch, fail with `num`.
// The branch skips a JAL to test_fail rather than branching there itself:
// a branch reaches only +-4 KiB, and some tests put more code than that
// between a check and test_fail.
#define CHECK(num, reg, value)                                                \
  li TESTNUM, num;                                                            \
  li t6, value;                                                               \
  beq reg, t6, 9f;                                                            \
  j test_fail;                                                                \
9:

// Fail unconditionally with check number `num`.
#define FAIL(num)                                                             \
  li TESTNUM, num;                                                            \
  j test_fail;

#define TEST_PASS                                                             \
  fence;                                                                      \
  li TESTNUM, 1;                                                              \
  sw TESTNUM, tohost, t5;                                                     \
  ecall;                                                                      \
test_fail:                                                                    \
  fence;                                                                      \
  slli TESTNUM, TESTNUM, 1;                                                   \
  ori TESTNUM, TESTNUM, 1;                                                    \
  sw TESTNUM, tohost, t5;                                                     \
  ecall;

// After the one stopping instruction of an error test.
#define TEST_UNREACHED                                                        \
  FAIL(99)                                                                    \
  TEST_PASS

// tohost/fromhost as riscv-tests defines them (spec §11), then a data area.
#define TEST_DATA                                                             \
  .section .tohost, "aw", @progbits;                                          \
  .align 6; .globl tohost;   tohost:   .dword 0;                              \
  .align 6; .globl fromhost; fromhost: .dword 0;                              \
  .section .data;                                                             \
  .align 4;

#endif
