// expect: 0
// t00_lui_addi: LUI/ADDI constant building, li of full 32-bit values, sign edges (spec §15.2).
#include "test.h"
TEST_BEGIN
  lui   a0, 0x12345
  CHECK(2, a0, 0x12345000)
  addi  a0, a0, 0x678
  CHECK(3, a0, 0x12345678)
  lui   a1, 0xfffff               // upper bits all set
  CHECK(4, a1, 0xfffff000)
  addi  a1, a1, -1
  CHECK(5, a1, 0xffffefff)
  lui   a2, 0x80000
  CHECK(6, a2, 0x80000000)
  lui   a3, 0                     // LUI with 0 clears the register
  CHECK(7, a3, 0)
  addi  a4, zero, -2048           // most negative 12-bit immediate
  CHECK(8, a4, 0xfffff800)
  addi  a4, zero, 2047            // most positive
  CHECK(9, a4, 0x000007ff)
  addi  a4, a4, 1                 // 0x800 needs LUI: here built by ADDI twice
  CHECK(10, a4, 0x00000800)
  // li of values where the low 12 bits are negative (LUI rounds up).
  li    a5, 0x12345fff
  CHECK(11, a5, 0x12345fff)
  li    a5, 0x7fffffff
  CHECK(12, a5, 0x7fffffff)
  li    a5, 0x80000000
  CHECK(13, a5, 0x80000000)
  li    a5, -1
  CHECK(14, a5, 0xffffffff)
  li    a5, 0xfffff800
  CHECK(15, a5, 0xfffff800)
  // Built without LUI (shifts), so a broken LUI cannot hide in li.
  addi  a6, zero, 0x123
  slli  a6, a6, 12
  addi  a6, a6, 0x456
  slli  a6, a6, 8
  addi  a6, a6, 0x78
  lui   a7, 0x12345
  addi  a7, a7, 0x678
  sub   a6, a6, a7
  CHECK(16, a6, 0)
TEST_PASS
TEST_DATA
