// expect: 0
// t02_alu_reg: every OP instruction; shift amount is rs2[4:0]; overflow wraps (spec §15.2).
#include "test.h"
TEST_BEGIN
  // ADD / SUB
  li    a0, 0x7fffffff
  li    a1, 1
  add   a2, a0, a1
  CHECK(2, a2, 0x80000000)
  li    a0, -1
  add   a2, a0, a1
  CHECK(3, a2, 0)
  sub   a2, zero, a1
  CHECK(4, a2, 0xffffffff)
  li    a0, 0x80000000
  sub   a2, a0, a1
  CHECK(5, a2, 0x7fffffff)
  sub   a2, a0, a0
  CHECK(6, a2, 0)
  // SLL / SRL / SRA: only rs2[4:0] counts
  li    a0, 1
  li    a1, 31
  sll   a2, a0, a1
  CHECK(7, a2, 0x80000000)
  li    a1, 32                    // rs2[4:0] = 0
  sll   a2, a0, a1
  CHECK(8, a2, 1)
  li    a1, 0xffffffe1            // rs2[4:0] = 1
  sll   a2, a0, a1
  CHECK(9, a2, 2)
  li    a0, 0x80000000
  li    a1, 31
  srl   a2, a0, a1
  CHECK(10, a2, 1)
  li    a1, 0x3f                  // rs2[4:0] = 31
  srl   a2, a0, a1
  CHECK(11, a2, 1)
  li    a1, 4
  srl   a2, a0, a1
  CHECK(12, a2, 0x08000000)
  sra   a2, a0, a1
  CHECK(13, a2, 0xf8000000)
  li    a1, -1                    // rs2[4:0] = 31
  sra   a2, a0, a1
  CHECK(14, a2, 0xffffffff)
  li    a1, 32                    // shift by 0
  sra   a2, a0, a1
  CHECK(15, a2, 0x80000000)
  // SLT / SLTU
  li    a0, -1
  li    a1, 1
  slt   a2, a0, a1
  CHECK(16, a2, 1)
  slt   a2, a1, a0
  CHECK(17, a2, 0)
  slt   a2, a0, a0
  CHECK(18, a2, 0)
  sltu  a2, a0, a1
  CHECK(19, a2, 0)
  sltu  a2, a1, a0
  CHECK(20, a2, 1)
  sltu  a2, zero, a1              // snez
  CHECK(21, a2, 1)
  li    a0, 0x80000000
  li    a1, 0x7fffffff
  slt   a2, a0, a1                // most negative < most positive
  CHECK(22, a2, 1)
  sltu  a2, a0, a1
  CHECK(23, a2, 0)
  // XOR / OR / AND
  li    a0, 0x12345678
  li    a1, 0xf0f0f0f0
  xor   a2, a0, a1
  CHECK(24, a2, 0xe2c4a688)
  or    a2, a0, a1
  CHECK(25, a2, 0xf2f4f6f8)
  and   a2, a0, a1
  CHECK(26, a2, 0x10305070)
  xor   a2, a0, a0
  CHECK(27, a2, 0)
  // rd = rs1 = rs2
  li    a3, 3
  add   a3, a3, a3
  CHECK(28, a3, 6)
TEST_PASS
TEST_DATA
