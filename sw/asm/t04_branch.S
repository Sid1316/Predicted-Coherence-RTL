// expect: 0
// t04_branch: all 6 branches taken and not taken, forward and backward,
// signed vs. unsigned edges, offsets past +-2 KiB (spec §15.2).
#include "test.h"

// Taken: skips the jump to test_fail. Not taken: falls through.
#define TAKEN(n, op, a, b)      li TESTNUM, n; op a, b, 9f; j test_fail; 9:
#define NOT_TAKEN(n, op, a, b)  li TESTNUM, n; op a, b, 8f; j 9f; 8: j test_fail; 9:

TEST_BEGIN
  li    s0, -1
  li    s1, 1
  li    s2, 0x80000000
  li    s3, 0x7fffffff

  // Offsets beyond +-2 KiB (imm bit 11). The skipped words are all-zero,
  // which is illegal, so a branch landing short of its target stops the core.
  li    TESTNUM, 33
  beq   zero, zero, 2f
  .fill 700, 4, 0
2:
  li    TESTNUM, 34
  j     3f
4: j     5f                        // backward target
  .fill 700, 4, 0
3: bne   s0, s1, 4b
  j     test_fail
5:

  TAKEN    (2,  beq,  s1, s1)
  TAKEN    (3,  beq,  zero, zero)
  NOT_TAKEN(4,  beq,  s0, s1)
  NOT_TAKEN(5,  beq,  s2, s3)
  TAKEN    (6,  bne,  s0, s1)
  NOT_TAKEN(7,  bne,  s2, s2)

  TAKEN    (8,  blt,  s0, s1)       // -1 < 1
  TAKEN    (9,  blt,  s2, s3)       // most negative < most positive
  NOT_TAKEN(10, blt,  s1, s0)
  NOT_TAKEN(11, blt,  s1, s1)
  NOT_TAKEN(12, blt,  zero, s0)
  TAKEN    (13, bge,  s1, s0)
  TAKEN    (14, bge,  s1, s1)
  TAKEN    (15, bge,  s3, s2)
  NOT_TAKEN(16, bge,  s0, s1)

  TAKEN    (17, bltu, s1, s0)       // 1 < 0xffffffff
  TAKEN    (18, bltu, s3, s2)
  NOT_TAKEN(19, bltu, s0, s1)
  NOT_TAKEN(20, bltu, s1, s1)
  TAKEN    (21, bgeu, s0, s1)
  TAKEN    (22, bgeu, s1, s1)
  TAKEN    (23, bgeu, s2, s3)
  NOT_TAKEN(24, bgeu, s1, s0)
  TAKEN    (25, bgeu, zero, zero)

  // Backward, one loop per branch type; counts how often the body ran.
  li    a0, 0
  li    a1, 5
1: addi  a0, a0, 1
  blt   a0, a1, 1b
  CHECK(26, a0, 5)
  li    a0, 0
1: addi  a0, a0, 1
  bne   a0, a1, 1b
  CHECK(27, a0, 5)
  li    a0, 0
1: addi  a0, a0, 1
  bltu  a0, a1, 1b
  CHECK(28, a0, 5)
  li    a0, 5
  li    a2, 0
1: addi  a2, a2, 1
  addi  a0, a0, -1
  bge   a0, zero, 1b              // runs for 5..0, ends at -1
  CHECK(29, a2, 6)
  CHECK(30, a0, 0xffffffff)
  li    a0, 0
  li    a3, 3
1: addi  a0, a0, 1
  bgeu  a3, a0, 1b                // runs while a0 <= 3
  CHECK(31, a0, 4)
  li    a0, 0
1: addi  a0, a0, 1
  slti  a4, a0, 3
  beq   a4, s1, 1b                // runs while a0 < 3
  CHECK(32, a0, 3)

TEST_PASS
TEST_DATA
