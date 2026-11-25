// expect: 0
// t06_x0: writes to x0 from every write-capable class are discarded (spec §15.2).
#include "test.h"
TEST_BEGIN
  la    s0, buf
  li    a0, 0x12345678
  addi  zero, zero, 5             // OP-IMM (a HINT, legal)
  CHECK(2, zero, 0)
  slli  zero, a0, 3
  CHECK(3, zero, 0)
  add   zero, a0, a0              // OP
  CHECK(4, zero, 0)
  sub   zero, zero, a0
  CHECK(5, zero, 0)
  lui   zero, 0x12345             // LUI
  CHECK(6, zero, 0)
  auipc zero, 0x1                 // AUIPC
  CHECK(7, zero, 0)
  lw    zero, 0(s0)               // LOAD
  CHECK(8, zero, 0)
  lbu   zero, 3(s0)
  CHECK(9, zero, 0)
  jal   zero, 1f                  // JAL
1: CHECK(10, zero, 0)
  la    t0, 2f
  jalr  zero, 0(t0)               // JALR
2: CHECK(11, zero, 0)
  // x0 as a source reads 0 after all of the above.
  add   a1, zero, a0
  CHECK(12, a1, 0x12345678)
  sw    zero, 0(s0)               // and stores 0
  lw    a1, 0(s0)
  CHECK(13, a1, 0)
TEST_PASS
TEST_DATA
buf:
  .word 0xcafef00d
