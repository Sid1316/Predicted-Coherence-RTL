# RISC-V Core

A RISC-V CPU core in SystemVerilog, built in phases.

- **Phase 1 (current):** a single-cycle RV32I core, simulated with Verilator and checked against Spike.
- **Phase 2:** microarchitecture choices (pipelining, memory system, extensions), made once Phase 1 is done.

| Document | Contents |
|---|---|
| [docs/exec.md](docs/exec.md) | Execution plan: milestones M0–M9, definition of done, risks, Phase 2 decision inputs |
| [docs/spec.md](docs/spec.md) | Phase 1 architecture and system design, conventions, instruction coverage checklist |

## Repository layout

```
docs/            plans and specification
rtl/             synthesizable RTL; rtl.f lists the sources in compile order
sim/             simulation-only SoC, memory model, Verilator C++ harness
tb/unit/         cocotb unit tests, one per RTL block
sw/common/       linker script, startup code, custom riscv-tests env (env/p/)
sw/asm/          directed assembly tests
sw/c/            C programs and benchmarks
tests/           upstream test suites (git submodules) and RISCOF config
scripts/         helper scripts (environment check, trace compare, ...)
syn/             Yosys synthesis scripts and reports
```

## Setup

The project runs **natively on Windows**. Commands run in **Git Bash**, with Windows builds of each tool on `PATH`. (A Linux shell works too; the scripts detect which one they are in.)

| Tool | Windows source | Provides |
|---|---|---|
| Git for Windows | already installed | `git`, Git Bash (`bash`, `sed`, `grep`, `awk`) |
| GNU make | `winget install ezwinports.make` | `make` |
| MSYS2 (UCRT64 packages) | `winget install MSYS2.MSYS2` | Verilator 5, the C++ compiler Verilator needs, Yosys, Icarus Verilog, GTKWave |
| xPack GNU RISC-V Embedded GCC | zip from [xpack-dev-tools/riscv-none-elf-gcc-xpack releases](https://github.com/xpack-dev-tools/riscv-none-elf-gcc-xpack/releases) | `riscv-none-elf-gcc` with rv32i/ilp32 libraries |
| Python 3.10+ | already installed (`py`) | cocotb, RISCOF |

Steps:

1. Install make and MSYS2:
   ```powershell
   winget install ezwinports.make
   ```
   ```powershell
   winget install MSYS2.MSYS2
   ```
2. Open the **MSYS2 UCRT64** shell from the Start menu and install the hardware tools:
   ```bash
   pacman -S --needed mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-verilator \
       mingw-w64-ucrt-x86_64-yosys mingw-w64-ucrt-x86_64-iverilog mingw-w64-ucrt-x86_64-gtkwave \n       mingw-w64-ucrt-x86_64-lz4
   ```
   `lz4` is what Verilator needs for FST waveforms; without it `make sim-build` falls back to VCD and prints a warning. Also install `mingw-w64-ucrt-x86_64-perl`. Then add `C:\msys64\ucrt64\bin` to your user `PATH`. Add only that folder, **not** `C:\msys64\usr\bin`, which would clash with Git Bash.

   MSYS2's `verilator` command is a Perl launcher script that fails under Git Bash's own Perl. The Makefile and `check_env.sh` therefore call `C:/msys64/ucrt64/bin/verilator_bin.exe` directly with `VERILATOR_ROOT` set. To run Verilator by hand in Git Bash, do the same:
   ```bash
   VERILATOR_ROOT=C:/msys64/ucrt64/share/verilator C:/msys64/ucrt64/bin/verilator_bin.exe --version
   ```
3. Extract the xPack RISC-V GCC zip to `%LOCALAPPDATA%\Programs\` and add its `bin` folder to your user `PATH`. This machine uses version 15.2.0-1 at `%LOCALAPPDATA%\Programs\xpack-riscv-none-elf-gcc-15.2.0-1\bin`.
4. In Git Bash, in the repo root, create a Python virtual environment and install cocotb:
   ```bash
   py -m venv .venv
   source .venv/Scripts/activate
   pip install cocotb
   ```
   RISCOF needs a workaround on Python 3.14. Its dependency `riscv-config` pins PyYAML 5.2, which has no 3.14 build. So install RISCOF without its pins, then add its dependencies with the current PyYAML:
   ```bash
   pip install --no-deps riscof riscv-config riscv-isac
   pip install "GitPython==3.1.17" click Jinja2 pytz Cerberus ruamel.yaml pyyaml "pyelftools==0.26" colorlog pytablewriter
   ```
   `pip check` then reports the PyYAML mismatch; that is expected. The Makefile and `check_env.sh` use `.venv` automatically, so you don't need to activate it for `make`.
5. Open a **new** Git Bash window (so the `PATH` changes apply) and check everything:
   ```bash
   make check-env
   ```
   It lists each tool as found or missing and test-links an `rv32i`/`ilp32` program. You can override the detected tools, e.g. `make RISCV_PREFIX=riscv64-unknown-elf- check-env`.

**Spike** (the reference simulator in docs/exec.md M5–M6) has no native Windows build, so `check-env` reports it without failing. Choosing a replacement reference model is an open decision; see docs/exec.md §8.

## Make targets

Run `make help` for the current list. Targets marked *not implemented* print the milestone that adds them and exit successfully.

| Target | Milestone | Action |
|---|---|---|
| `make check-env` | M0 | Check tool versions |
| `make lint` | M0 | Verilator `-Wall` lint of the sources in `rtl/rtl.f` |
| `make unit` | M2 | cocotb unit tests |
| `make sim-build` | M3 | Build the Verilator simulator `build/sim/Vrv_soc_sim` (rv_soc_sim + `sim/tb_top.cpp`) |
| `make sim-test` | M3 | Check the simulator against the Python model: every SoC scenario, exit codes, retire log, waves, random reset |
| `make sim HEX=... [TOHOST=addr]` | M3 | Run a ready-made `$readmemh` image (`MAX_CYCLES=`, `SEED=`, `WAVES=1`, `RETIRE_LOG=`) |
| `make asm [TESTS="t00 e01"]` | M3 | Build and run the directed tests in `sw/asm/`, checking each against its `// expect:` header and the Python model |
| `make c [TESTS="hello"]` | M4 | Build and run the C programs in `sw/c/` (crt0, rvlib, libgcc), checked the same way |
| `make progs` | M4 | Both of the above |
| `make sim PROG=sw/c/hello` | M3/M4 | Build, convert and run one program (`sw/c/<prog>` or `sw/asm/<test>`), showing its console output; `WAVES=1`, `SEED=` |
| `make spike PROG=...` | M6 | Run one program on Spike |
| `make compare PROG=...` | M6 | RTL vs. Spike lockstep comparison |
| `scripts/trace_compare.py <rtl.log> <ref> [--ref-format spike]` | M6 | Compare a retire log with a reference trace (retire-log or Spike `--log-commits` format), report the first mismatch |
| `make riscv-tests` | M5 | `rv32ui-p-*` suite with the custom env; waived tests must fail as `tests/riscv-tests-waivers.txt` records |
| `make riscof` | M5 | riscv-arch-test `rv32i_m/I` (39 tests) via RISCOF: DUT on a 2 MiB-RAM simulator (`build/sim-2097152/`) vs. the Python reference model |
| `make random [SEEDS=200] [START=1]` | M6 | Random programs (`scripts/randgen.py`) on the RTL vs. the Python reference model, trace by trace; failing seeds are saved in `tests/random/`; prints instruction and stop-cause coverage |
| `make regress` | M9 | Everything, in order |
| `make syn` | M8 | Yosys synthesis |
| `make clean` | M0 | Remove build output |
