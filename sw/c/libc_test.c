// expect: 0
// console: libc_test: printf -7 7 abc ok Z|   12|3   |\nlibc_test: all checks passed\n
// max_cycles: 2000000
// libc_test.c - checks crt0, rvlib and libgcc on the core (docs/exec.md M4.2, M4.3).
//
// Each check has a number; the first failing one is printed and returned
// from main, so the harness reports it as tohost = (n << 1) | 1 (exit 1).
#include "rvlib.h"

static int checks;

#define CHECK(cond)                                                  \
  do {                                                               \
    ++checks;                                                        \
    if (!(cond)) {                                                   \
      printf("libc_test: check %d failed (line %d)\n", checks, __LINE__); \
      return checks;                                                 \
    }                                                                \
  } while (0)

static char buf[64];

#define CHECK_FMT(expected, ...)                                     \
  do {                                                               \
    snprintf(buf, sizeof buf, __VA_ARGS__);                          \
    ++checks;                                                        \
    if (strcmp(buf, expected) != 0) {                                \
      printf("libc_test: check %d failed: got \"%s\", expected \"%s\"\n", checks, buf, expected); \
      return checks;                                                 \
    }                                                                \
  } while (0)

// Section setup by crt0 / link.ld.
static int           zeros[64];                         // .bss
static int           counter;                           // .sbss
static int           init[4] = {1, 2, 3, 0x12345678};   // .data
static const char    text[]  = "rodata";                // .rodata

// Kept opaque to the optimizer, so the operations below really run.
static volatile int32_t  vi[4] = {12345, 6789, -7, 2};
static volatile uint32_t vu[3] = {0xffffffffu, 3u, 100000u};
static volatile int64_t  vl[2] = {1000000000000LL, -1000000000000LL};

static int fib(int n) { return n < 2 ? n : fib(n - 1) + fib(n - 2); }

static int add(int a, int b) { return a + b; }
static int sub(int a, int b) { return a - b; }

__attribute__((noinline)) static int classify(int x) {   // dense switch: a jump table
  switch (x) {
    case 0: return 10;
    case 1: return 11;
    case 2: return 12;
    case 3: return 13;
    case 4: return 14;
    case 5: return 15;
    case 6: return 16;
    case 7: return 17;
    case 8: return 18;
    default: return -1;
  }
}

struct big { int v[16]; };
__attribute__((noinline)) static struct big make_big(int seed) {
  struct big b;
  for (int i = 0; i < 16; ++i) b.v[i] = seed + i;
  return b;
}

static int test_formats(void) {
  CHECK_FMT("0", "%d", 0);
  CHECK_FMT("-42", "%d", -42);
  CHECK_FMT("-2147483648", "%d", (int)INT32_MIN);
  CHECK_FMT("2147483647", "%i", (int)INT32_MAX);
  CHECK_FMT("4294967295", "%u", 0xffffffffu);
  CHECK_FMT("deadbeef", "%x", 0xdeadbeefu);
  CHECK_FMT("DEADBEEF", "%X", 0xdeadbeefu);
  CHECK_FMT("17", "%o", 15u);
  CHECK_FMT("   42", "%5d", 42);
  CHECK_FMT("42   |", "%-5d|", 42);
  CHECK_FMT("00042", "%05d", 42);
  CHECK_FMT("-0042", "%05d", -42);
  CHECK_FMT("  -42", "%5d", -42);
  CHECK_FMT("00ff", "%04x", 255u);
  CHECK_FMT("007", "%.3d", 7);
  CHECK_FMT("    007", "%7.3d", 7);
  CHECK_FMT("  7", "%*d", 3, 7);
  CHECK_FMT("7  |", "%*d|", -3, 7);
  CHECK_FMT("0x80000000", "%p", (void *)0x80000000u);
  CHECK_FMT("[  abc]", "[%5s]", "abc");
  CHECK_FMT("[abc  ]", "[%-5s]", "abc");
  CHECK_FMT("[ab]", "[%.2s]", "abcdef");
  CHECK_FMT("[x]", "[%c]", 'x');
  CHECK_FMT("100%", "%d%%", 100);
  CHECK_FMT("12345678901", "%lld", 12345678901LL);
  CHECK_FMT("-9223372036854775808", "%lld", (long long)INT64_MIN);
  CHECK_FMT("18446744073709551615", "%llu", (unsigned long long)UINT64_MAX);
  CHECK_FMT("123456789abcdef0", "%llx", 0x123456789abcdef0ULL);
  CHECK_FMT("-5 5", "%ld %lu", -5L, 5UL);
  CHECK_FMT("a1b2", "%c%d%c%d", 'a', 1, 'b', 2);

  // Truncation: the return value is the full length, the buffer is cut and terminated.
  int n = snprintf(buf, 5, "%s", "abcdefgh");
  CHECK(n == 8 && strcmp(buf, "abcd") == 0);
  buf[0] = 'Q';
  n = snprintf(buf, 0, "%d", 12345);
  CHECK(n == 5 && buf[0] == 'Q');
  return 0;
}

static int test_strings(void) {
  char a[16], b[16];
  memset(a, 0x5a, sizeof a);
  for (int i = 0; i < 16; ++i) CHECK(a[i] == 0x5a);
  memcpy(b, "0123456789abcdef", 16);
  CHECK(memcmp(b, "0123456789abcdef", 16) == 0);
  memmove(b + 2, b, 8);                       // overlapping, forward
  CHECK(memcmp(b, "0101234567abcdef", 16) == 0);
  memmove(b, b + 4, 8);                       // overlapping, backward
  CHECK(memcmp(b, "234567ab67abcdef", 16) == 0);
  CHECK(memcmp("abc", "abd", 3) < 0 && memcmp("abd", "abc", 3) > 0 && memcmp("abc", "abd", 2) == 0);
  CHECK(strlen("") == 0 && strlen(text) == 6);
  CHECK(strcmp("abc", "abc") == 0 && strcmp("abc", "abd") < 0 && strcmp("b", "abc") > 0);
  CHECK(strcmp("ab", "abc") < 0);
  return 0;
}

static int test_runtime(void) {
  for (int i = 0; i < 64; ++i) CHECK(zeros[i] == 0);
  CHECK(counter == 0);
  counter += 3;
  CHECK(counter == 3);
  CHECK(init[0] == 1 && init[1] == 2 && init[2] == 3 && init[3] == 0x12345678);
  CHECK(memcmp(text, "rodata", 7) == 0);

  // Stack: 16-byte aligned on entry to main's callees (ilp32 ABI), inside RAM.
  uintptr_t sp = (uintptr_t)__builtin_frame_address(0);
  CHECK(sp % 16 == 0 && sp > 0x80000000u && sp <= 0x80010000u);

  // libgcc: 32-bit multiply/divide/remainder, signed and unsigned.
  CHECK(vi[0] * vi[1] == 83810205);
  CHECK(vi[2] / vi[3] == -3 && vi[2] % vi[3] == -1);
  CHECK(-vi[0] * vi[1] == -83810205);
  CHECK(vu[0] / vu[1] == 0x55555555u && vu[0] % vu[1] == 0);
  CHECK(vu[2] % 7u == 5u && vu[2] / 7u == 14285u);
  // libgcc: 64-bit.
  CHECK(vl[0] / 7 == 142857142857LL && vl[0] % 7 == 1);
  CHECK(vl[1] / 3 == -333333333333LL && vl[1] % 3 == -1);
  CHECK((uint64_t)vu[0] * vu[0] == 0xfffffffe00000001ULL);

  CHECK(fib(15) == 610);

  int (*ops[2])(int, int) = {add, sub};
  CHECK(ops[vi[3] - 2](5, 3) == 8 && ops[vi[3] - 1](5, 3) == 2);

  for (int i = 0; i < 9; ++i) CHECK(classify(i) == 10 + i);
  CHECK(classify(9) == -1 && classify(-1) == -1);

  struct big x = make_big(100);
  struct big y = x;                             // struct copy (memcpy)
  for (int i = 0; i < 16; ++i) CHECK(y.v[i] == 100 + i);
  return 0;
}

int main(void) {
  int r;
  if ((r = test_formats()) != 0) return r;
  if ((r = test_strings()) != 0) return r;
  if ((r = test_runtime()) != 0) return r;
  printf("libc_test: printf %d %u %x %s %c|%5d|%-4d|\n", -7, 7u, 0xabcu, "ok", 'Z', 12, 3);
  printf("libc_test: all checks passed\n");
  return 0;
}
