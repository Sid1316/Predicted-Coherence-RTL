// expect: 0
// console: exit\n
// exit_nested.c - exit() from a nested call ends the program; nothing after it runs.
#include "rvlib.h"

__attribute__((noinline)) static void level3(void) {
  puts("exit");
  exit(0);
}

__attribute__((noinline)) static void level2(void) {
  level3();
}

__attribute__((noinline)) static int level1(int x) {
  level2();
  return x + 1;            // unreachable
}

int main(void) {
  int r = level1(2);
  puts("unreachable");
  return r;
}
