// expect: 1
// tohost: 0000000b
// ret_code.c - main's return value reaches tohost as (ret << 1) | 1 (sw/common/crt0.S, spec §11).
int main(void) {
  return 5;
}
