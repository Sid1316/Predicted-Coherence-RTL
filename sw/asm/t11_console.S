// expect: 0
// console: Hello, RISC-V\n
// t11_console: write a string to CONSOLE (spec §2.3, §15.2).
#include "test.h"
TEST_BEGIN
  li    s0, CONSOLE_ADDR
  la    s1, msg
1: lbu   a0, 0(s1)
  beqz  a0, 2f
  sb    a0, 0(s0)
  addi  s1, s1, 1
  j     1b
2: lw    a1, 0(s0)                // CONSOLE reads return 0
  CHECK(2, a1, 0)
TEST_PASS
TEST_DATA
msg:
  .asciz "Hello, RISC-V\n"
