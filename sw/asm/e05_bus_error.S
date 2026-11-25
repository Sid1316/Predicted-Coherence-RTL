// expect: 3 STOP_BUS_ERROR
// e05_bus_error: a load from 0x0000_0000 (unmapped) (spec §10, §15.2).
#include "test.h"
TEST_BEGIN
  lw    a0, 0(zero)
TEST_UNREACHED
TEST_DATA
buf:
  .word 0x01020304, 0x05060708
