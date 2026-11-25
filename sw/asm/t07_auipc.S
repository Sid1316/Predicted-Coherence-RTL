// expect: 0
// t07_auipc: AUIPC at different PCs, used for PC-relative addressing (spec §15.2).
#include "test.h"
TEST_BEGIN
  // JAL leaves the address of the next instruction in a1, without AUIPC.
  jal   a1, 1f
1: auipc a0, 0
  sub   a2, a0, a1
  CHECK(2, a2, 0)
  jal   a1, 1f
1: auipc a0, 1                    // pc + 0x1000
  sub   a2, a0, a1
  CHECK(3, a2, 0x1000)
  jal   a1, 1f
1: auipc a0, 0xfffff              // pc - 0x1000
  sub   a2, a1, a0
  CHECK(4, a2, 0x1000)
  jal   a1, 1f
1: auipc a0, 0x80000              // pc + 0x8000_0000 (wraps)
  sub   a2, a0, a1
  CHECK(5, a2, 0x80000000)
  // PC-relative load, as la/lw expand.
1: auipc a0, %pcrel_hi(word)
  lw    a2, %pcrel_lo(1b)(a0)
  CHECK(6, a2, 0x600df00d)
  // At a 4 KiB-aligned PC (0x8000_1000 or higher).
  j     2f
  .balign 4096, 0
2: jal   a1, 3f
3: auipc a0, 0
  sub   a2, a0, a1
  CHECK(7, a2, 0)
  slli  a2, a0, 20                // low 12 bits of the PC, at the top
  CHECK(8, a2, 0x00400000)
  srli  a2, a0, 12
  li    TESTNUM, 9
  li    t6, 0x80000
  bne   a2, t6, 4f                // the page is above the first one
  j     test_fail
4:
TEST_PASS
TEST_DATA
word:
  .word 0x600df00d
