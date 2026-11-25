// expect: 3 STOP_MISALIGNED_FETCH
// e04_misaligned_jump: JALR to an address with bit 1 set; before it, a not-taken branch with a misaligned target and a JALR whose target has only bit 0 set do not stop (spec §10, §15.2).
#include "test.h"
TEST_BEGIN
  li    a0, 0
  .word 0x00001363                // bne zero, zero, .+6: not taken, so no stop
  la    t0, 1f
  addi  t0, t0, 1                 // bit 0 set: cleared by JALR, no stop
  jalr  zero, 0(t0)
  FAIL(2)
1: li    a0, 1
  la    t0, 2f
  addi  t0, t0, 2                 // bit 1 set
  jalr  ra, 0(t0)                 // the stopping instruction
2: nop
  nop
TEST_UNREACHED
TEST_DATA
buf:
  .word 0x01020304, 0x05060708
