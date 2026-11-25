// string.c - memory and string functions for rvlib (docs/exec.md M4.3).
//
// Byte loops, kept simple: the programs are small, and these run on a
// single-cycle core where a word loop saves little. Built with
// -fno-tree-loop-distribute-patterns (scripts/run_progs.py), so GCC does not
// turn the loops below back into calls to memset/memcpy.

#include "rvlib.h"

void *memcpy(void *dst, const void *src, size_t n) {
  unsigned char       *d = dst;
  const unsigned char *s = src;
  while (n--) *d++ = *s++;
  return dst;
}

void *memmove(void *dst, const void *src, size_t n) {
  unsigned char       *d = dst;
  const unsigned char *s = src;
  if (d < s) {
    while (n--) *d++ = *s++;
  } else {
    while (n--) d[n] = s[n];
  }
  return dst;
}

void *memset(void *dst, int c, size_t n) {
  unsigned char *d = dst;
  while (n--) *d++ = (unsigned char)c;
  return dst;
}

int memcmp(const void *a, const void *b, size_t n) {
  const unsigned char *x = a, *y = b;
  for (; n; --n, ++x, ++y) {
    if (*x != *y) return *x < *y ? -1 : 1;
  }
  return 0;
}

size_t strlen(const char *s) {
  const char *p = s;
  while (*p) ++p;
  return (size_t)(p - s);
}

int strcmp(const char *a, const char *b) {
  while (*a && *a == *b) { ++a; ++b; }
  return (unsigned char)*a - (unsigned char)*b;
}
