// tb_top.cpp - Verilator C++ harness for rv_soc_sim (docs/spec.md §2.1, §2.2, §11; exec.md M3.4).
//
//   Vrv_soc_sim +hex=<file> [+tohost=<hex addr>] [+max_cycles=<n>] [+retire_log=<file>]
//               [+waves[=<file>]] [+verilator+seed+<n>] [+verilator+rand+reset+<0|1|2>]
//               [+signature=<file> +sig_begin=<hex addr> +sig_end=<hex addr>]
//
//   - +hex= is required (rv_mem_model loads it with $readmemh). +tohost= and
//     +retire_log= are read by rv_soc_sim; the harness only checks them.
//   - Reset is held for RESET_CYCLES rising edges, then the core runs until
//     tohost is written, it stops (halted_o), or max_cycles edges have passed.
//     The run ends right after the edge where that happens, so the tohost
//     store is the last line of the retire log.
//   - +waves writes waves.fst (waves.vcd in a VCD build) unless a file is named.
//   - +signature= (RISCOF, spec §11): when the run ends (any result but a
//     harness error), the words in [sig_begin, sig_end) are written to the
//     file, one per line as 8 lower-case hex digits. All three plusargs or
//     none; both addresses word aligned, inside RAM, begin <= end.
//   - stdout carries only the program's console output (rv_soc_sim's $write),
//     byte for byte (binary mode on Windows).
//     The harness writes its result line to stderr, as
//       tb_top: <RESULT> <details> cycles=<n> exit=<code>
//   - Uninitialized state (the register file is not reset) gets random values:
//     the build uses --x-initial unique, and the harness defaults to
//     +verilator+rand+reset+2 with seed 1, so a run is repeatable (spec N-5)
//     and a program that reads a register it never wrote misbehaves visibly
//     (spec §2.2). Both can be overridden with the +verilator+ plusargs.
//
// Exit codes (spec §11):
//   0 tohost == 1                 1 tohost written with any other value
//   2 timeout (max_cycles)        3 core stopped with an error cause (§10)
//   4 ECALL/EBREAK without tohost 5 harness error (missing file, bad plusarg, bad hex)
//   6 simulation error: an RTL assertion, $error/$stop/$fatal or a Verilator
//     runtime error once the run has started
//
// The build defines VL_USER_STOP and VL_USER_FATAL, so the vl_stop/vl_fatal
// below replace Verilator's, which would exit with 1 (the "tohost fail" code).

#include <cctype>
#include <cerrno>
#include <cinttypes>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <string>

#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

// The build defines DPI_DLLISPEC empty: svdpi.h would otherwise declare the
// sv* functions __declspec(dllimport) on Windows, but Verilator links them
// statically (verilated_dpi.cpp).
#include "Vrv_soc_sim.h"
#include "Vrv_soc_sim__Dpi.h"   // rv_mem_peek (sim/rv_mem_model.sv)
#include "svdpi.h"
#include "verilated.h"
// The build picks FST (--trace-fst, needs liblz4) or VCD (--trace-vcd);
// Verilator defines VM_TRACE_FST / VM_TRACE_VCD to match.
#if VM_TRACE_FST
#include "verilated_fst_c.h"
using WaveWriter = VerilatedFstC;
constexpr const char* WAVE_DEFAULT = "waves.fst";
#else
#include "verilated_vcd_c.h"
using WaveWriter = VerilatedVcdC;
constexpr const char* WAVE_DEFAULT = "waves.vcd";
#endif

namespace {

constexpr int      EXIT_PASS     = 0;
constexpr int      EXIT_FAIL     = 1;
constexpr int      EXIT_TIMEOUT  = 2;
constexpr int      EXIT_ERROR    = 3;
constexpr int      EXIT_NOTOHOST = 4;
constexpr int      EXIT_HARNESS  = 5;
constexpr int      EXIT_SIM      = 6;

#ifndef MEM_SIZE_BYTES   // the Makefile passes the same value to Verilator (-G)
#define MEM_SIZE_BYTES 65536
#endif
constexpr uint64_t MEM_WORDS          = MEM_SIZE_BYTES / 4;
constexpr uint64_t DEFAULT_MAX_CYCLES = 1000000;
constexpr int      RESET_CYCLES       = 2;  // spec §2.2: at least 2
constexpr uint64_t HALF_PERIOD        = 5;  // time units (--timescale 1ns/1ns): 10 ns clock

// stop_cause_t (rtl/rv_pkg.sv §8.4), in encoding order.
const char* const CAUSE_NAMES[8] = {
    "STOP_NONE",        "STOP_ECALL",           "STOP_EBREAK",    "STOP_ILLEGAL",
    "STOP_MISALIGNED_FETCH", "STOP_MISALIGNED_DATA", "STOP_BUS_ERROR", "STOP_IFETCH_ERROR",
};
constexpr unsigned STOP_ECALL  = 1;
constexpr unsigned STOP_EBREAK = 2;

// retire_t field positions (rtl/rv_pkg.sv §8.4): a packed struct puts its
// first field in the most significant bits, so offsets count up from halt.
constexpr int RT_HALT_LO     = 0;
constexpr int RT_PC_RDATA_LO = 249;
constexpr int RT_INSN_LO     = 281;
constexpr int RT_VALID_LO    = 377;
constexpr int RT_WIDTH       = 378;

// Harness state the vl_stop/vl_fatal callbacks need.
VerilatedContext*            g_ctx     = nullptr;
std::unique_ptr<WaveWriter> g_trace;
bool                         g_running = false;   // reset released: errors are EXIT_SIM
uint64_t                     g_time    = 0;       // mirrors ctx->time() for sc_time_stamp()

uint32_t bits(const VlWide<(RT_WIDTH + 31) / 32>& w, int lo, int width) {
  uint64_t v = 0;
  for (int i = 0; i < width; ++i) {
    const int b = lo + i;
    v |= static_cast<uint64_t>((w[b / 32] >> (b % 32)) & 1u) << i;
  }
  return static_cast<uint32_t>(v);
}

[[noreturn]] void harness_error(const char* fmt, const char* arg) {
  std::fflush(stdout);
  std::fprintf(stderr, "tb_top: harness error: ");
  std::fprintf(stderr, fmt, arg);
  std::fprintf(stderr, " exit=%d\n", EXIT_HARNESS);
  std::exit(EXIT_HARNESS);
}

// Parse an unsigned number in `base`; the whole string must be digits.
bool parse_u64(const char* s, int base, uint64_t max, uint64_t* out) {
  if (*s == '\0' || *s == '-' || *s == '+' || std::isspace(static_cast<unsigned char>(*s))) return false;
  errno = 0;
  char* end = nullptr;
  const unsigned long long v = std::strtoull(s, &end, base);
  if (errno != 0 || *end != '\0' || v > max) return false;
  *out = v;
  return true;
}

struct Args {
  std::string hex;
  bool        have_tohost = false;
  uint32_t    tohost      = 0;
  uint64_t    max_cycles  = DEFAULT_MAX_CYCLES;
  std::string retire_log;
  std::string waves;          // empty: no waves
  std::string signature;      // empty: no signature dump
  bool        have_sig_begin = false, have_sig_end = false;
  uint32_t    sig_begin = 0, sig_end = 0;
};

// A 32-bit hex address as nm prints it (no 0x).
uint32_t parse_addr(const char* arg, const char* v) {
  uint64_t n = 0;
  if (std::strchr(v, 'x') != nullptr || std::strchr(v, 'X') != nullptr || !parse_u64(v, 16, 0xFFFFFFFFull, &n))
    harness_error("bad %s (expected a 32-bit hex address without 0x)", arg);
  return static_cast<uint32_t>(n);
}

bool starts_with(const char* s, const char* prefix, const char** rest) {
  const size_t n = std::strlen(prefix);
  if (std::strncmp(s, prefix, n) != 0) return false;
  *rest = s + n;
  return true;
}

Args parse_args(int argc, char** argv) {
  Args a;
  for (int i = 1; i < argc; ++i) {
    const char* s = argv[i];
    const char* v = nullptr;
    uint64_t    n = 0;
    if (starts_with(s, "+hex=", &v)) {
      a.hex = v;
    } else if (starts_with(s, "+tohost=", &v)) {
      // Plain hex as nm prints it. No 0x prefix: rv_soc_sim reads the same
      // plusarg with %h, which would not accept one, and both must agree.
      // (strtoull would accept 0x, hence the explicit check.)
      if (std::strchr(v, 'x') != nullptr || std::strchr(v, 'X') != nullptr ||
          !parse_u64(v, 16, 0xFFFFFFFFull, &n))
        harness_error("bad +tohost=%s (expected a 32-bit hex address without 0x)", v);
      a.have_tohost = true;
      a.tohost      = static_cast<uint32_t>(n);
    } else if (starts_with(s, "+max_cycles=", &v)) {
      if (!parse_u64(v, 10, UINT64_MAX, &n) || n == 0) harness_error("bad +max_cycles=%s (expected a positive decimal number)", v);
      a.max_cycles = n;
    } else if (starts_with(s, "+retire_log=", &v)) {
      if (*v == '\0') harness_error("empty +retire_log=%s", v);
      a.retire_log = v;
    } else if (std::strcmp(s, "+waves") == 0) {
      a.waves = WAVE_DEFAULT;
    } else if (starts_with(s, "+waves=", &v)) {
      if (*v == '\0') harness_error("empty +waves=%s", v);
      a.waves = v;
    } else if (starts_with(s, "+signature=", &v)) {
      if (*v == '\0') harness_error("empty +signature=%s", v);
      a.signature = v;
    } else if (starts_with(s, "+sig_begin=", &v)) {
      a.sig_begin      = parse_addr(s, v);
      a.have_sig_begin = true;
    } else if (starts_with(s, "+sig_end=", &v)) {
      a.sig_end      = parse_addr(s, v);
      a.have_sig_end = true;
    } else if (std::strncmp(s, "+verilator+", 11) == 0) {
      // Verilator's own runtime options; VerilatedContext::commandArgs reads them.
    } else {
      harness_error("unknown argument '%s'", s);
    }
  }
  if (a.hex.empty()) harness_error("missing +hex=<file>%s", "");
  const bool any_sig = !a.signature.empty() || a.have_sig_begin || a.have_sig_end;
  if (any_sig) {
    if (a.signature.empty() || !a.have_sig_begin || !a.have_sig_end)
      harness_error("+signature=, +sig_begin= and +sig_end= go together%s", "");
    const uint64_t lo = 0x80000000ull, hi = lo + MEM_SIZE_BYTES;
    if ((a.sig_begin | a.sig_end) & 3u) harness_error("+sig_begin=/+sig_end= must be word aligned%s", "");
    if (a.sig_begin > a.sig_end) harness_error("+sig_begin= is above +sig_end=%s", "");
    if (a.sig_begin < lo || a.sig_end > hi) harness_error("signature range is outside RAM%s", "");
  }
  return a;
}

// Check the +hex= image before $readmemh sees it: Verilator reads a word like
// ZZZZZZZZ without complaint (as random bits) and its handling of addresses
// past the array is not an error we control. Accepted: what rv_mem_model
// documents (objcopy -O verilog --verilog-data-width=4 and write_hex): //
// comments, @<hex word index>, and words of 1-8 hex digits, all inside RAM.
void check_hex(const std::string& path) {
  FILE* f = std::fopen(path.c_str(), "rb");
  if (f == nullptr) harness_error("cannot open +hex=%s", path.c_str());
  uint64_t idx = 0, words = 0, line = 1;
  int      c   = std::fgetc(f);
  char     msg[200];
  auto bad = [&](const char* what) {
    std::fclose(f);
    std::snprintf(msg, sizeof msg, "%s, line %" PRIu64, what, line);
    harness_error("bad +hex image: %s", msg);
  };
  while (c != EOF) {
    if (c == '\n') { ++line; c = std::fgetc(f); continue; }
    if (std::isspace(c)) { c = std::fgetc(f); continue; }
    if (c == '/') {
      if (std::fgetc(f) != '/') bad("'/' that does not start a // comment");
      while (c != EOF && c != '\n') c = std::fgetc(f);
      continue;
    }
    const bool at = (c == '@');
    if (at) c = std::fgetc(f);
    uint64_t v = 0;
    int      n = 0;
    while (c != EOF && std::isxdigit(c)) {
      v = (v << 4) | static_cast<uint64_t>(std::isdigit(c) ? c - '0' : (std::tolower(c) - 'a' + 10));
      if (++n > (at ? 16 : 8)) bad(at ? "address too long" : "word longer than 8 hex digits");
      c = std::fgetc(f);
    }
    if (n == 0 || (c != EOF && !std::isspace(c) && c != '/')) bad("not a hex word or @address");
    if (at) {
      if (v >= MEM_WORDS) bad("@address outside RAM");
      idx = v;
    } else {
      if (idx >= MEM_WORDS) bad("data past the end of RAM");
      ++idx;
      ++words;
    }
  }
  std::fclose(f);
  if (words == 0) harness_error("bad +hex image: %s holds no data", path.c_str());
}

void check_writable(const std::string& path, const char* what) {
  FILE* f = std::fopen(path.c_str(), "wb");
  if (f == nullptr) harness_error(what, path.c_str());
  std::fclose(f);
}

}  // namespace

// ---------------------------------------------------------------------------
// Verilator runtime hooks (VL_USER_STOP / VL_USER_FATAL)
// ---------------------------------------------------------------------------

// $stop, and $error/assertion failures past +verilator+error+limit. Recorded
// and returned from; the main loop ends the run after the current eval.
void vl_stop(const char* filename, int linenum, const char* hier) {
  (void)hier;
  std::fflush(stdout);
  std::fprintf(stderr, "tb_top: %%Error: %s:%d: Verilog $stop\n", filename, linenum);
  g_ctx->gotError(true);
  g_ctx->gotFinish(true);
}

// $fatal and Verilator runtime errors (e.g. a malformed $readmemh file). The
// generated code does not expect this to return, so it exits here.
void vl_fatal(const char* filename, int linenum, const char* hier, const char* msg) {
  (void)hier;
  std::fflush(stdout);
  std::fprintf(stderr, "tb_top: %%Error: %s:%d: %s\n", filename, linenum, msg);
  if (g_trace) g_trace->close();
  const int code = g_running ? EXIT_SIM : EXIT_HARNESS;
  std::fprintf(stderr, "tb_top: %s exit=%d\n", g_running ? "SIMERROR" : "harness error", code);
  std::fflush(nullptr);   // also flushes the retire log rv_soc_sim has open
  std::exit(code);
}

// Legacy time callback. Verilator declares it weak, but MinGW's PE linker
// still needs a definition. It must not call VerilatedContext::time(): while
// the time is 0, time() falls back to sc_time_stamp() (infinite recursion).
double sc_time_stamp() { return static_cast<double>(g_time); }

// ---------------------------------------------------------------------------

int main(int argc, char** argv) {
#ifdef _WIN32
  // Console bytes go out unchanged (text mode would turn LF into CR LF).
  _setmode(_fileno(stdout), _O_BINARY);
#endif
  const Args args = parse_args(argc, argv);
  check_hex(args.hex);
  if (!args.signature.empty()) check_writable(args.signature, "cannot write +signature=%s");
  if (!args.retire_log.empty()) check_writable(args.retire_log, "cannot write +retire_log=%s");

  auto ctx = std::make_unique<VerilatedContext>();
  g_ctx = ctx.get();
  ctx->randReset(2);   // defaults; +verilator+rand+reset+ / +verilator+seed+ override
  ctx->randSeed(1);
  ctx->commandArgs(argc, argv);
  if (!args.waves.empty()) ctx->traceEverOn(true);

  auto top = std::make_unique<Vrv_soc_sim>(ctx.get(), "TOP");
  if (!args.waves.empty()) {
    g_trace = std::make_unique<WaveWriter>();
    top->trace(g_trace.get(), 99);
    g_trace->open(args.waves.c_str());
    if (!g_trace->isOpen()) harness_error("cannot write +waves=%s", args.waves.c_str());
  }

  auto half_cycle = [&](uint8_t clk) {
    top->clk_i = clk;
    top->eval();
    if (g_trace) g_trace->dump(ctx->time());
    ctx->timeInc(HALF_PERIOD);
    g_time += HALF_PERIOD;
  };

  // Reset: initial blocks ($readmemh, plusargs) run in the first eval.
  top->rst_i = 1;
  for (int i = 0; i < RESET_CYCLES; ++i) {
    half_cycle(0);
    half_cycle(1);
  }
  top->rst_i = 0;
  g_running  = true;

  uint64_t    cycles   = 0;
  uint32_t    last_pc  = 0;
  uint32_t    last_ins = 0;
  int         code     = EXIT_TIMEOUT;
  bool        console_open = false;   // console output so far does not end in \n
  char        result[160];
  std::snprintf(result, sizeof result, "TIMEOUT after max_cycles=%" PRIu64, args.max_cycles);

  while (cycles < args.max_cycles) {
    half_cycle(0);
    // The retire port shows the instruction that retires at the coming edge.
    if (bits(top->retire_o, RT_VALID_LO, 1)) {
      last_pc  = bits(top->retire_o, RT_PC_RDATA_LO, 32);
      last_ins = bits(top->retire_o, RT_INSN_LO, 32);
    }
    if (top->console_valid_o) console_open = (top->console_data_o != '\n');
    half_cycle(1);
    ++cycles;

    if (ctx->gotError()) {
      code = EXIT_SIM;
      std::snprintf(result, sizeof result, "SIMERROR (assertion or $stop) pc=%08x insn=%08x",
                    last_pc, last_ins);
      break;
    }
    if (top->done_o) {
      const uint32_t v = top->tohost_value_o;
      if (v == 1u) {
        code = EXIT_PASS;
        std::snprintf(result, sizeof result, "PASS tohost=%08x", v);
      } else {
        code = EXIT_FAIL;
        std::snprintf(result, sizeof result, "FAIL tohost=%08x test=%u", v, v >> 1);
      }
      break;
    }
    if (top->halted_o) {
      const unsigned cause = top->status_o & 7u;
      if (cause == STOP_ECALL || cause == STOP_EBREAK) {
        code = EXIT_NOTOHOST;
        std::snprintf(result, sizeof result, "NOTOHOST %s without a tohost write pc=%08x",
                      CAUSE_NAMES[cause], last_pc);
      } else {
        code = EXIT_ERROR;
        std::snprintf(result, sizeof result, "ERROR %s pc=%08x insn=%08x", CAUSE_NAMES[cause],
                      last_pc, last_ins);
      }
      break;
    }
  }

  half_cycle(0);   // one more half cycle so the waves show the final state

  if (!args.signature.empty()) {
    FILE* sig = std::fopen(args.signature.c_str(), "wb");
    if (sig == nullptr) harness_error("cannot write +signature=%s", args.signature.c_str());
    svSetScope(svGetScopeFromName("TOP.rv_soc_sim.u_mem"));
    for (uint32_t a = args.sig_begin; a < args.sig_end; a += 4)
      std::fprintf(sig, "%08x\n", rv_mem_peek((a - 0x80000000u) / 4));
    std::fclose(sig);
  }
  top->final();    // closes the retire log
  if (g_trace) g_trace->close();
  std::fflush(stdout);
  // On a terminal stdout and stderr share a line: start the result on a new
  // one. The newline goes to stderr, so stdout stays byte for byte.
  if (console_open) std::fputc('\n', stderr);
  std::fprintf(stderr, "tb_top: %s cycles=%" PRIu64 " exit=%d\n", result, cycles, code);
  return code;
}
