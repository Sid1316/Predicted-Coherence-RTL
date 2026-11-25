// expect: 3 STOP_MISALIGNED_DATA
// e02b_misaligned_lh: LH at byte offset 1 (spec §10, §15.2).
#include "test.h"
TEST_BEGIN
  la    s0, buf
  lh    a0, 1(s0)
TEST_UNREACHED
TEST_DATA
buf:
  .word 0x01020304, 0x05060708
