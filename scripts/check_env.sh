#!/usr/bin/env bash
# Check that the Phase 1 tools are installed and print their versions.
# docs/exec.md M0.2. Runs in Git Bash on Windows, or in a Linux shell.
#
# Usage:   scripts/check_env.sh        (or: make check-env)
# Env:     RISCV_PREFIX   toolchain prefix (default: first one found of
#                         riscv-none-elf-, riscv64-unknown-elf-, riscv32-unknown-elf-)
#          PYTHON         Python 3 interpreter (default: first working one of
#                         python3, python, py)
# Exit:    0 when every required tool is found and works, 1 otherwise.

set -u

missing=0

ok()   { printf '  [ ok ] %-24s %s\n' "$1" "$2"; }
bad()  { printf '  [FAIL] %-24s %s\n' "$1" "$2"; missing=$((missing + 1)); }
skip() { printf '  [ -- ] %-24s %s\n' "$1" "$2"; }

# check <required|optional> <label> <command> [version args...]
check() {
  local kind=$1 label=$2 cmd=$3
  shift 3
  if command -v "$cmd" >/dev/null 2>&1; then
    ok "$label" "$("$cmd" "$@" 2>&1 | head -n 1 | tr -d '\r')"
  elif [ "$kind" = required ]; then
    bad "$label" "'$cmd' not found"
  else
    skip "$label" "optional, '$cmd' not found"
  fi
}

# ---------------------------------------------------------------------------
echo "Platform"
case "$(uname -s)" in
  MINGW*|MSYS*) windows=1; ok "Windows (Git Bash)" "$(uname -s)" ;;
  Linux)        windows=0; ok "Linux" "$(uname -r)" ;;
  *)            windows=0; skip "Platform" "$(uname -s): untested" ;;
esac

# Use the project's virtual environment (.venv) when it exists, so cocotb and
# riscof are found without activating it first.
root=$(cd "$(dirname "$0")/.." && pwd)
for venv_bin in "$root/.venv/Scripts" "$root/.venv/bin"; do
  if [ -d "$venv_bin" ]; then
    PATH="$venv_bin:$PATH"
    break
  fi
done

# Python: Windows has "python3"/"python" stubs that only open the Microsoft
# Store, so pick the first interpreter that really reports Python 3.
if [ -z "${PYTHON:-}" ]; then
  for c in python3 python py; do
    if command -v "$c" >/dev/null 2>&1 && "$c" --version 2>&1 | grep -q '^Python 3'; then
      PYTHON=$c
      break
    fi
  done
fi

# Toolchain prefix: first one with a gcc on PATH.
if [ -z "${RISCV_PREFIX:-}" ]; then
  for p in riscv-none-elf- riscv64-unknown-elf- riscv32-unknown-elf-; do
    if command -v "${p}gcc" >/dev/null 2>&1; then
      RISCV_PREFIX=$p
      break
    fi
  done
fi
RISCV_PREFIX=${RISCV_PREFIX:-riscv-none-elf-}

# Verilator: on Windows, MSYS2's launcher is a Perl script that fails under Git
# Bash's Perl, so use the real binary with VERILATOR_ROOT (same as the Makefile).
if [ -z "${VERILATOR:-}" ]; then
  if [ "$windows" -eq 1 ] && [ -x "C:/msys64/ucrt64/bin/verilator_bin.exe" ]; then
    VERILATOR="C:/msys64/ucrt64/bin/verilator_bin.exe"
    export VERILATOR_ROOT="${VERILATOR_ROOT:-C:/msys64/ucrt64/share/verilator}"
  else
    VERILATOR=verilator
  fi
fi

# ---------------------------------------------------------------------------
echo "Required"
check required "git"            git --version
check required "make"           make --version
if [ -n "${PYTHON:-}" ]; then
  ok "python" "$("$PYTHON" --version 2>&1 | tr -d '\r') ($PYTHON)"
else
  bad "python" "no working Python 3 (python3/python/py)"
fi
check required "verilator"      "$VERILATOR" --version
check required "riscv gcc"      "${RISCV_PREFIX}gcc" --version
check required "riscv objcopy"  "${RISCV_PREFIX}objcopy" --version
check required "riscv objdump"  "${RISCV_PREFIX}objdump" --version
check required "riscv nm"       "${RISCV_PREFIX}nm" --version
check required "yosys"          yosys -V

if [ -n "${PYTHON:-}" ]; then
  if ver=$("$PYTHON" -c "import cocotb; print(cocotb.__version__)" 2>/dev/null); then
    ok "cocotb" "$(printf '%s' "$ver" | tr -d '\r')"
  else
    bad "cocotb" "python module not found (pip install cocotb)"
  fi
fi
check required "riscof"         riscof --version

# Spike has no native Windows build. On Windows it is reported, not required;
# the reference model for M5/M6 is an open decision (docs/exec.md §8).
if [ "$windows" -eq 1 ]; then
  check optional "spike"        spike --help
else
  check required "spike"        spike --help
fi

# ---------------------------------------------------------------------------
echo "Version and capability checks"
# Verilator must be 5.x or newer.
if command -v "$VERILATOR" >/dev/null 2>&1; then
  vmajor=$("$VERILATOR" --version 2>&1 | sed -n 's/^Verilator \([0-9]*\)\..*/\1/p')
  if [ -n "$vmajor" ] && [ "$vmajor" -ge 5 ]; then
    ok "verilator >= 5" "major version $vmajor"
  else
    bad "verilator >= 5" "found major version '${vmajor:-unknown}'"
  fi
fi

# Python must be 3.10 or newer.
if [ -n "${PYTHON:-}" ]; then
  if "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    ok "python >= 3.10" "yes"
  else
    bad "python >= 3.10" "found $("$PYTHON" --version 2>&1 | tr -d '\r')"
  fi
fi

# The toolchain must link an rv32i/ilp32 program against libgcc (software mul/div).
if command -v "${RISCV_PREFIX}gcc" >/dev/null 2>&1; then
  tmp=$(mktemp -d)
  cat > "$tmp/t.c" <<'EOF'
int mul(int a, int b) { return a * b; }
void _start(void) { volatile int r = mul(3, 4); (void)r; for (;;) {} }
EOF
  if "${RISCV_PREFIX}gcc" -march=rv32i -mabi=ilp32 -O0 -nostdlib -ffreestanding \
       "$tmp/t.c" -lgcc -o "$tmp/t.elf" >"$tmp/log" 2>&1; then
    ok "rv32i/ilp32 link" "libgcc for rv32i found (${RISCV_PREFIX})"
  else
    bad "rv32i/ilp32 link" "cannot link rv32i/ilp32 (no 32-bit multilib?)"
    sed 's/^/           /' "$tmp/log" | head -n 5
  fi
  rm -rf "$tmp"
fi

# ---------------------------------------------------------------------------
echo "Optional"
check optional "sail (RISCOF ref)" sail_riscv_sim --version
check optional "nextpnr-ecp5"      nextpnr-ecp5 --version
check optional "gtkwave"           gtkwave --version
check optional "surfer"            surfer --version
check optional "verible-format"    verible-verilog-format --version
check optional "iverilog"          iverilog -V

echo
echo "Using RISCV_PREFIX=${RISCV_PREFIX} PYTHON=${PYTHON:-none} VERILATOR=${VERILATOR}"
if [ "$missing" -eq 0 ]; then
  echo "check_env: all required tools found"
  exit 0
else
  echo "check_env: $missing required check(s) failed"
  exit 1
fi
