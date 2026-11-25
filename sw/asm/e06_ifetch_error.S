// expect: 3 STOP_IFETCH_ERROR
// e06_ifetch_error: JALR to 0x8001_0000, the first address past RAM (spec §10, §15.2).
#include "test.h"
TEST_BEGIN
  li    t0, 0x80010000
  jalr  zero, 0(t0)
TEST_UNREACHED
TEST_DATA
buf:
  .word 0x01020304, 0x05060708
