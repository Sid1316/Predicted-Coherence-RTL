// expect: 3 STOP_ILLEGAL
// e01c_illegal_funct7: XOR with funct7 = 0100000 is illegal (spec §10, §15.2).
#include "test.h"
TEST_BEGIN
  .word 0x40c5c533                // xor a0, a1, a2 with funct7 0x20
TEST_UNREACHED
TEST_DATA
buf:
  .word 0x01020304, 0x05060708
