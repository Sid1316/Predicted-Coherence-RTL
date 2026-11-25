// rvlib.h - the minimal C library for programs on rv_soc_sim (docs/exec.md M4.3, docs/spec.md §12).
//
// Freestanding: only the compiler's own headers (stdarg.h, stddef.h,
// stdint.h) are used. The functions keep their standard names and
// prototypes, so GCC's format checking works on printf/snprintf, and code
// GCC generates (struct copies, zeroing) finds memcpy/memset.
//
// printf/snprintf conversions: %d %i %u %x %X %o %c %s %p %%, with the flags
// '-' and '0', a field width (digits or *), a precision for %s and the
// integers (digits or *), and the length modifiers h, hh, l (all 32-bit on
// ilp32), ll and j/z/t. Unsupported conversions print as "%?".
//
// Software multiply/divide (rv32i has no M extension) comes from libgcc.

#ifndef RVLIB_H
#define RVLIB_H

#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>

// Console MMIO (spec §2.3): a byte store prints it.
#define RV_CONSOLE_ADDR 0x10000000u

int  putchar(int c);
int  puts(const char *s);         // s and a newline
int  printf(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
int  vprintf(const char *fmt, va_list ap);
int  snprintf(char *buf, size_t size, const char *fmt, ...) __attribute__((format(printf, 3, 4)));
int  vsnprintf(char *buf, size_t size, const char *fmt, va_list ap);

void  *memcpy(void *dst, const void *src, size_t n);
void  *memmove(void *dst, const void *src, size_t n);
void  *memset(void *dst, int c, size_t n);
int    memcmp(const void *a, const void *b, size_t n);
size_t strlen(const char *s);
int    strcmp(const char *a, const char *b);

// Ends the program: tohost = (code << 1) | 1 (sw/common/crt0.S, spec §11).
void exit(int code) __attribute__((noreturn));

#endif
