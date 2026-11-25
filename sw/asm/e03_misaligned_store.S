// expect: 3 STOP_MISALIGNED_DATA
// e03_misaligned_store: SW at byte offset 1 (spec §10, §15.2).
#include "test.h"
TEST_BEGIN
  la    s0, buf
  li    a1, -1
  sw    a1, 1(s0)
TEST_UNREACHED
TEST_DATA
buf:
  .word 0x01020304, 0x05060708
