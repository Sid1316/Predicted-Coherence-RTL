// expect: 0
// t03_load_store: all widths at every legal offset; sign vs. zero extension; store-then-load (spec §15.2).
#include "test.h"
TEST_BEGIN
  la    s0, buf
  // Loads from the initial image: buf[0] = 0x80ff7f01 (bytes 01 7f ff 80).
  lb    a0, 0(s0)
  CHECK(2, a0, 0x00000001)
  lb    a0, 1(s0)
  CHECK(3, a0, 0x0000007f)
  lb    a0, 2(s0)
  CHECK(4, a0, 0xffffffff)
  lb    a0, 3(s0)
  CHECK(5, a0, 0xffffff80)
  lbu   a0, 0(s0)
  CHECK(6, a0, 0x01)
  lbu   a0, 1(s0)
  CHECK(7, a0, 0x7f)
  lbu   a0, 2(s0)
  CHECK(8, a0, 0xff)
  lbu   a0, 3(s0)
  CHECK(9, a0, 0x80)
  lh    a0, 0(s0)
  CHECK(10, a0, 0x00007f01)
  lh    a0, 2(s0)
  CHECK(11, a0, 0xffff80ff)
  lhu   a0, 0(s0)
  CHECK(12, a0, 0x7f01)
  lhu   a0, 2(s0)
  CHECK(13, a0, 0x80ff)
  lw    a0, 0(s0)
  CHECK(14, a0, 0x80ff7f01)
  lw    a0, 4(s0)
  CHECK(15, a0, 0x11223344)
  lh    a0, 6(s0)                 // positive upper half
  CHECK(16, a0, 0x00001122)
  // Stores, each read back right away.
  li    a1, 0xdeadbeef
  sw    a1, 8(s0)
  lw    a0, 8(s0)
  CHECK(17, a0, 0xdeadbeef)
  li    a1, 0x55
  sb    a1, 9(s0)
  lw    a0, 8(s0)
  CHECK(18, a0, 0xdead55ef)
  sb    a1, 11(s0)
  lw    a0, 8(s0)
  CHECK(19, a0, 0x55ad55ef)
  li    a1, 0x1234
  sh    a1, 10(s0)
  lw    a0, 8(s0)
  CHECK(20, a0, 0x123455ef)
  sh    a1, 8(s0)
  lw    a0, 8(s0)
  CHECK(21, a0, 0x12341234)
  li    a1, 0xffffffaa            // SB/SH store only the low bits
  sb    a1, 12(s0)
  lw    a0, 12(s0)
  CHECK(22, a0, 0x000000aa)
  sh    a1, 14(s0)
  lw    a0, 12(s0)
  CHECK(23, a0, 0xffaa00aa)
  sb    a1, 13(s0)
  lbu   a0, 13(s0)
  CHECK(24, a0, 0xaa)
  lb    a0, 13(s0)
  CHECK(25, a0, 0xffffffaa)
  // Negative offsets.
  addi  s1, s0, 16
  lw    a0, -12(s1)
  CHECK(26, a0, 0x11223344)
  li    a1, 0x0badf00d
  sw    a1, -4(s1)
  lw    a0, 12(s0)
  CHECK(27, a0, 0x0badf00d)
  lhu   a0, -2(s1)
  CHECK(28, a0, 0x0bad)
  // The first word is unchanged by all of the above.
  lw    a0, 0(s0)
  CHECK(29, a0, 0x80ff7f01)
TEST_PASS
TEST_DATA
buf:
  .word 0x80ff7f01, 0x11223344, 0, 0
