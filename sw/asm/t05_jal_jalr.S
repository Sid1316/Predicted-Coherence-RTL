// expect: 0
// t05_jal_jalr: call/return, rd = x0 jumps, JALR bit-0 clearing, link values (spec §15.2).
#include "test.h"

// rd must hold the address of `label`.
#define CHECK_ADDR(n, rd, label)  li TESTNUM, n; la t6, label; beq rd, t6, 9f; j test_fail; 9:

TEST_BEGIN
  li    a0, 0
  // JAL call; ra = the address after the JAL.
  jal   ra, inc
ret1:
  CHECK(2, a0, 1)
  CHECK_ADDR(3, ra, ret1)
  // JAL with rd = x0 (plain jump), forward and backward.
  li    TESTNUM, 4
  j     1f
  j     test_fail
2: j     3f
1: j     2b
3:
  // JALR call through a register, with zero, positive and negative offsets.
  la    t0, inc
  jalr  ra, 0(t0)
ret2:
  CHECK(5, a0, 2)
  CHECK_ADDR(6, ra, ret2)
  la    t0, inc - 8
  jalr  ra, 8(t0)
  CHECK(7, a0, 3)
  la    t0, inc + 16
  jalr  ra, -16(t0)
  CHECK(8, a0, 4)
  // Bit 0 of the target is cleared (no stop).
  la    t0, inc
  addi  t0, t0, 1
  jalr  ra, 0(t0)
  CHECK(9, a0, 5)
  la    t0, inc - 1
  jalr  ra, 2(t0)                 // rs1 + imm = inc + 1
  CHECK(10, a0, 6)
  // rd = rs1: the target uses the old value, then rd gets the link.
  la    t1, inc_t1
  jalr  t1, 0(t1)
ret3:
  CHECK(11, a0, 7)
  // JALR with rd = x0 (jr), and a nested call that saves ra.
  la    t0, 1f
  jalr  zero, 0(t0)
  j     test_fail
1: jal   ra, outer
  CHECK(12, a0, 9)
  // The link value of a JAL with a large forward offset.
  jal   s1, far
far_ret:
  CHECK(13, a0, 10)
TEST_PASS

inc:                              // a0 += 1, return through ra
  addi  a0, a0, 1
  ret
  j     test_fail
inc_t1:                           // returns through t1, which must hold ret3
  la    t6, ret3
  bne   t1, t6, fail_t1
  addi  a0, a0, 1
  jr    t1
fail_t1:
  FAIL(14)
outer:                            // calls inc twice
  mv    s0, ra
  jal   ra, inc
  jal   ra, inc
  mv    ra, s0
  ret
  .fill 600, 4, 0
far:
  la    t6, far_ret
  bne   s1, t6, fail_far
  addi  a0, a0, 1
  jr    s1
fail_far:
  FAIL(15)
TEST_DATA
