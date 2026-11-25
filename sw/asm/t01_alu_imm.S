// expect: 0
// t01_alu_imm: every OP-IMM instruction; shamt 0/31; negative immediates; SLTIU with -1 (spec §15.2).
#include "test.h"
TEST_BEGIN
  li    a0, 0x12345678
  // ADDI
  addi  a1, a0, -1
  CHECK(2, a1, 0x12345677)
  addi  a1, a0, 2047
  CHECK(3, a1, 0x12345e77)
  addi  a1, a0, -2048
  CHECK(4, a1, 0x12344e78)
  li    a2, 0x7fffffff
  addi  a1, a2, 1                 // overflow wraps
  CHECK(5, a1, 0x80000000)
  li    a2, -1
  addi  a1, a2, 1
  CHECK(6, a1, 0)
  // SLTI (signed)
  li    a2, -5
  slti  a1, a2, -4
  CHECK(7, a1, 1)
  slti  a1, a2, -5
  CHECK(8, a1, 0)
  slti  a1, a2, 2047
  CHECK(9, a1, 1)
  li    a2, 0x80000000
  slti  a1, a2, -2048
  CHECK(10, a1, 1)
  li    a2, 5
  slti  a1, a2, -1
  CHECK(11, a1, 0)
  // SLTIU (immediate sign-extended, then compared unsigned)
  sltiu a1, a2, -1                // 5 < 0xffffffff
  CHECK(12, a1, 1)
  li    a2, -1
  sltiu a1, a2, -1                // equal
  CHECK(13, a1, 0)
  sltiu a1, zero, 1               // seqz
  CHECK(14, a1, 1)
  li    a2, 1
  sltiu a1, a2, 1
  CHECK(15, a1, 0)
  li    a2, 0x800
  sltiu a1, a2, -2048             // 0x800 < 0xfffff800
  CHECK(16, a1, 1)
  // XORI / ORI / ANDI
  xori  a1, a0, -1                // not
  CHECK(17, a1, 0xedcba987)
  xori  a1, a0, 0xff
  CHECK(18, a1, 0x12345687)
  xori  a1, a0, -2048
  CHECK(19, a1, 0xedcbae78)
  ori   a1, a0, 0xf0
  CHECK(20, a1, 0x123456f8)
  ori   a1, a0, -2048
  CHECK(21, a1, 0xfffffe78)
  andi  a1, a0, 0xff
  CHECK(22, a1, 0x78)
  andi  a1, a0, -2048
  CHECK(23, a1, 0x12345000)
  andi  a1, a0, -1
  CHECK(24, a1, 0x12345678)
  // Shifts by 0, 1, 31
  li    a2, 0x80000001
  slli  a1, a2, 0
  CHECK(25, a1, 0x80000001)
  slli  a1, a2, 1
  CHECK(26, a1, 0x00000002)
  slli  a1, a2, 31
  CHECK(27, a1, 0x80000000)
  srli  a1, a2, 0
  CHECK(28, a1, 0x80000001)
  srli  a1, a2, 1
  CHECK(29, a1, 0x40000000)
  srli  a1, a2, 31
  CHECK(30, a1, 1)
  srai  a1, a2, 0
  CHECK(31, a1, 0x80000001)
  srai  a1, a2, 1
  CHECK(32, a1, 0xc0000000)
  srai  a1, a2, 31
  CHECK(33, a1, 0xffffffff)
  li    a3, 0x40000000
  srai  a1, a3, 30                // positive: zeros shifted in
  CHECK(34, a1, 1)
TEST_PASS
TEST_DATA
