// expect: 3 STOP_ILLEGAL
// e01b_illegal_csr: a CSR instruction (csrrs a0, mstatus, x0) is illegal (spec §10, §15.2).
#include "test.h"
TEST_BEGIN
  .word 0x30002573                // csrr a0, mstatus
TEST_UNREACHED
TEST_DATA
buf:
  .word 0x01020304, 0x05060708
