// stdio.c - console output and printf for rvlib (docs/exec.md M4.3, docs/spec.md §2.3).
//
// One formatter, format(), writes through a sink: the console for printf,
// a buffer for snprintf. See rvlib.h for the supported conversions.

#include "rvlib.h"

int putchar(int c) {
  *(volatile uint8_t *)RV_CONSOLE_ADDR = (uint8_t)c;
  return (unsigned char)c;
}

int puts(const char *s) {
  while (*s) putchar(*s++);
  putchar('\n');
  return 1;
}

// ---------------------------------------------------------------------------
// Formatter
// ---------------------------------------------------------------------------

typedef struct {
  char  *buf;     // NULL: console
  size_t size;    // buffer size, including the terminating NUL
  size_t len;     // characters produced so far (may exceed size)
} sink_t;

static void emit(sink_t *s, char c) {
  if (s->buf == NULL) {
    putchar(c);
  } else if (s->len + 1 < s->size) {
    s->buf[s->len] = c;
  }
  s->len++;
}

static void emit_n(sink_t *s, char c, int n) {
  while (n-- > 0) emit(s, c);
}

// Digits of v in `base`, least significant first; returns the count.
static int digits(char *out, uint64_t v, unsigned base, int upper) {
  const char *set = upper ? "0123456789ABCDEF" : "0123456789abcdef";
  int n = 0;
  do {
    out[n++] = set[v % base];
    v /= base;
  } while (v != 0);
  return n;
}

typedef struct {
  int left;       // '-'
  int zero;       // '0'
  int width;      // -1: none
  int prec;       // -1: none
} spec_t;

// A number: sign/prefix, then zero padding (from '0' or the precision), then digits.
static void emit_number(sink_t *s, const spec_t *sp, uint64_t mag, int negative, unsigned base,
                        int upper, const char *prefix) {
  char d[24];
  int  nd = digits(d, mag, base, upper);
  if (sp->prec == 0 && mag == 0) nd = 0;           // "%.0d" of 0 prints nothing
  int  plen  = (int)strlen(prefix) + (negative ? 1 : 0);
  int  zeros = sp->prec > nd ? sp->prec - nd : 0;
  int  body  = plen + zeros + nd;
  int  pad   = sp->width > body ? sp->width - body : 0;
  if (sp->zero && !sp->left && sp->prec < 0) {     // '0' flag pads with zeros after the sign
    zeros += pad;
    pad = 0;
  }
  if (!sp->left) emit_n(s, ' ', pad);
  if (negative) emit(s, '-');
  for (const char *p = prefix; *p; ++p) emit(s, *p);
  emit_n(s, '0', zeros);
  while (nd > 0) emit(s, d[--nd]);
  if (sp->left) emit_n(s, ' ', pad);
}

static void emit_string(sink_t *s, const spec_t *sp, const char *str) {
  if (str == NULL) str = "(null)";
  int n = 0;
  while (str[n] && (sp->prec < 0 || n < sp->prec)) ++n;
  int pad = sp->width > n ? sp->width - n : 0;
  if (!sp->left) emit_n(s, ' ', pad);
  for (int i = 0; i < n; ++i) emit(s, str[i]);
  if (sp->left) emit_n(s, ' ', pad);
}

static int format(sink_t *s, const char *fmt, va_list ap) {
  for (const char *p = fmt; *p; ++p) {
    if (*p != '%') {
      emit(s, *p);
      continue;
    }
    ++p;
    spec_t sp = {0, 0, -1, -1};
    for (;; ++p) {                                   // flags
      if (*p == '-') sp.left = 1;
      else if (*p == '0') sp.zero = 1;
      else break;
    }
    if (*p == '*') {                                 // width
      sp.width = va_arg(ap, int);
      if (sp.width < 0) { sp.left = 1; sp.width = -sp.width; }
      ++p;
    } else {
      for (; *p >= '0' && *p <= '9'; ++p) sp.width = (sp.width < 0 ? 0 : sp.width * 10) + (*p - '0');
    }
    if (*p == '.') {                                 // precision
      ++p;
      sp.prec = 0;
      if (*p == '*') {
        sp.prec = va_arg(ap, int);
        if (sp.prec < 0) sp.prec = -1;
        ++p;
      } else {
        for (; *p >= '0' && *p <= '9'; ++p) sp.prec = sp.prec * 10 + (*p - '0');
      }
    }
    int is64 = 0;                                    // length
    if (*p == 'h') { ++p; if (*p == 'h') ++p; }
    else if (*p == 'l') { ++p; if (*p == 'l') { is64 = 1; ++p; } }
    else if (*p == 'j') { is64 = 1; ++p; }
    else if (*p == 'z' || *p == 't') ++p;

    switch (*p) {
      case 'd':
      case 'i': {
        int64_t v = is64 ? va_arg(ap, int64_t) : va_arg(ap, int);
        uint64_t mag = v < 0 ? (uint64_t)0 - (uint64_t)v : (uint64_t)v;
        emit_number(s, &sp, mag, v < 0, 10, 0, "");
        break;
      }
      case 'u':
      case 'x':
      case 'X':
      case 'o': {
        uint64_t v = is64 ? va_arg(ap, uint64_t) : va_arg(ap, unsigned);
        unsigned base = *p == 'u' ? 10 : (*p == 'o' ? 8 : 16);
        emit_number(s, &sp, v, 0, base, *p == 'X', "");
        break;
      }
      case 'p':
        emit_number(s, &sp, (uintptr_t)va_arg(ap, void *), 0, 16, 0, "0x");
        break;
      case 'c': {
        char c[2] = {(char)va_arg(ap, int), 0};
        spec_t one = sp;
        one.prec = 1;
        if (c[0] == 0) {                             // %c of NUL still prints one character
          emit_n(s, ' ', (!sp.left && sp.width > 1) ? sp.width - 1 : 0);
          emit(s, 0);
          emit_n(s, ' ', (sp.left && sp.width > 1) ? sp.width - 1 : 0);
        } else {
          emit_string(s, &one, c);
        }
        break;
      }
      case 's':
        emit_string(s, &sp, va_arg(ap, const char *));
        break;
      case '%':
        emit(s, '%');
        break;
      case '\0':                                     // format ends after '%'
        return (int)s->len;
      default:
        emit(s, '%');
        emit(s, '?');
        break;
    }
  }
  return (int)s->len;
}

int vprintf(const char *fmt, va_list ap) {
  sink_t s = {NULL, 0, 0};
  return format(&s, fmt, ap);
}

int printf(const char *fmt, ...) {
  va_list ap;
  va_start(ap, fmt);
  int n = vprintf(fmt, ap);
  va_end(ap);
  return n;
}

int vsnprintf(char *buf, size_t size, const char *fmt, va_list ap) {
  sink_t s = {buf, size, 0};
  int n = format(&s, fmt, ap);
  if (size > 0) buf[s.len < size ? s.len : size - 1] = '\0';
  return n;
}

int snprintf(char *buf, size_t size, const char *fmt, ...) {
  va_list ap;
  va_start(ap, fmt);
  int n = vsnprintf(buf, size, fmt, ap);
  va_end(ap);
  return n;
}
