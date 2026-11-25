// expect: 0
// t08_fence_nop: FENCE, FENCE.TSO, PAUSE and reserved FENCE fields change nothing (spec §4, §15.2).
#include "test.h"
TEST_BEGIN
  la    s0, buf
  li    a0, 0x11111111
  li    a1, 0x22222222
  li    a2, 0x33333333
  sw    a0, 0(s0)
  fence
  fence rw, rw
  fence i, o
  fence iorw, iorw
  .word 0x8330000f                // fence.tso
  .word 0x0100000f                // pause (fence w, 0)
  .word 0x0000000f                // fence 0, 0
  .word 0xfff5850f                // fm=1111, pred=succ=1111, rs1=a1, rd=a0 (reserved fields set)
  .word 0x0ff6018f                // rs1=a2, rd=x3 (gp)
  CHECK(2, a0, 0x11111111)
  CHECK(3, a1, 0x22222222)
  CHECK(4, a2, 0x33333333)
  lw    a3, 0(s0)
  CHECK(5, a3, 0x11111111)
  // The core still runs on: the instruction after the fences executes once.
  li    a4, 0
  fence
  addi  a4, a4, 1
  fence
  CHECK(6, a4, 1)
TEST_PASS
TEST_DATA
buf:
  .word 0
