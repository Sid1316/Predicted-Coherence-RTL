// expect: 3 STOP_MISALIGNED_DATA
// e02a_misaligned_lw: LW at byte offset 2 (spec §10, §15.2).
#include "test.h"
TEST_BEGIN
  la    s0, buf
  lw    a0, 2(s0)
TEST_UNREACHED
TEST_DATA
buf:
  .word 0x01020304, 0x05060708
