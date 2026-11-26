# How to run the evaluation yourself

The command `make eval` tests the whole RISC-V core and writes a report with charts (`build/eval/latest/report.html`). This page shows how to do the same tests one at a time, so you can see each result for yourself.

## A few words used on this page

| Word | Meaning |
|---|---|
| **Lint** | A tool (Verilator) reads the hardware code and points out mistakes, without running it. |
| **Unit test** | A small test of one block of the core, for example only the ALU. |
| **Simulator** | A program built from the hardware code. It runs RISC-V programs like the real chip would. |
| **Reference model** | A simple Python version of the CPU. Every program runs on it too, and the results must match the simulator exactly. |
| **Retire log** | A text file with one line for every instruction the core finished: its address, the instruction, and the value it wrote. |
| **Waveform** | A picture of signals changing over time, clock cycle by clock cycle. |
| **Injected bug** | A small mistake added on purpose to a copy of the design, to prove the tests notice it. |

## Before you start (one time)

1. Open the `Risc-V` folder in VS Code (**File > Open Folder**).
2. When VS Code offers to install the recommended extensions, click **Install**. The important ones:
   - **Python**: runs and debugs the test scripts.
   - **Surfer**: shows waveforms inside VS Code.
   - **Verilog-HDL / TerosHDL**: colours and navigation for the hardware code.
3. Open a terminal (**Terminal > New Terminal**). It opens as **Git Bash**, which is what these commands need.
4. Check that all tools are installed:

   ```bash
   make check-env
   ```

   Every tool on the "Required" list must say `[ ok ]`. If one does not, see `setup_require.txt`.

## The easy way: everything at once

```bash
make eval PROFILE=quick
```

This takes about 14 minutes. `PROFILE=full` takes about 37 minutes and also runs the extra tests (arch tests, benchmarks, synthesis). When it finishes, open `build/eval/latest/report.html` in a browser.

## Step by step

You can type each command below in the terminal, or use menus: press **Ctrl+Shift+P**, type **Run Task**, and pick the step with the same number.

### Step 1: Are the tools installed?

```bash
make check-env
```

**Passed if:** every required tool says `[ ok ]`.

### Step 2: Lint the hardware code

```bash
make lint
```

**Passed if:** it prints `lint: clean` and no warnings. (Run it as task 02 and any warning shows up in the **Problems** panel. Click it to jump to the line.)

### Step 3: Test each block on its own

```bash
make unit
```

To test only one block, for example the ALU: `make unit BLOCKS=rv_alu`.

**Passed if:** every block prints `n/n passed`, for example `5/5 passed`. There are 92 tests in 10 blocks.
**Details:** `build/unit/<block>/results.xml` lists every single test.

### Step 4: Build the simulator

```bash
make sim-build
```

**Passed if:** it finishes without errors. The result is `build/sim/Vrv_soc_sim.exe`.

### Step 5: Check the test tools themselves

```bash
make sim-test
```

This checks the simulator's harness and the scripts that compare results, so a broken script cannot report a false "pass".
**Passed if:** each of the four test scripts prints "all checks passed".

### Step 6: Run the small assembly tests

```bash
make asm
```

**Passed if:** 22 of 22 say `PASS`.
**Details:** `build/asm/<test>.retire.log` (what ran) and `build/asm/<test>.dis` (the program's code).

### Step 7: Run the C programs

```bash
make c
```

**Passed if:** 4 of 4 say `PASS`.

### Step 8: Run the official RISC-V tests

```bash
make riscv-tests
```

**Passed if:** 42 of 42 say `PASS`. Two of them (`fence_i` and `ma_data`) test features this core leaves out on purpose. They count as passed when they fail in exactly the expected way (listed in `tests/riscv-tests-waivers.txt`).

### Step 9: Run the RISC-V compliance tests

```bash
make riscof
```

**Passed if:** 39 of 39 say `PASS`. A full report is in `build/riscof/report.html`.

### Step 10: Run random programs

```bash
make random SEEDS=200
```

This makes 200 random programs and runs each one on both the simulator and the reference model.
**Passed if:** every program matches the model, and all 40 RISC-V instructions were used at least once (the counts are printed at the end).

### Step 11: Run the benchmarks

```bash
make bench
```

Runs Dhrystone, CoreMark and five Embench programs.
**Passed if:** 7 of 7 say `PASS`. It also prints a table of how each program uses the CPU.

### Step 12: Synthesis (slow, optional)

```bash
make syn
```

Turns the design into FPGA hardware to measure its size and speed.
**Result:** `syn/reports/summary.md`, with the maximum clock speed (Fmax) of each version.

### Step 13: Look at a waveform

```bash
make sim PROG=sw/asm/t04_branch WAVES=1
```

**Passed if:** the program says `PASS`. It writes the waveform to `build/sim/waves.vcd`. See "Looking at waveforms" below.

### Step 14: Prove the tests catch bugs

```bash
.venv/Scripts/python.exe scripts/evaluate.py --only-mutant alu_sra_logical
```

This adds one known bug to a copy of the design (the original files are not changed) and runs the tests on it. It prints which tests noticed the bug.
**Passed if:** at least one test notices a real bug. Two cases must NOT be noticed: `null` (no bug at all) and `regfile_x0_writable` (a bug no program can ever see).
The bug names are listed in `scripts/eval_mutants.py`.

### Step 15: Redraw a report

```bash
.venv/Scripts/python.exe scripts/evaluate.py --report-only build/eval/<run>
```

Redraws the charts and `report.html` of an earlier run, without running any tests again.

## Why "PASS" can be trusted

Every program in steps 6 to 11 also runs on the reference model. The scripts then compare the two, line by line: the exit code, the printed output, and every instruction in the retire log. One wrong value anywhere makes the test fail, even when the program itself thinks it passed.

## Looking at the results

### What a program did

Open `build/asm/<test>.retire.log` next to `build/asm/<test>.dis`. Each log line is one finished instruction: its address, the instruction, and the register and value it wrote. (C programs are in `build/c/`, the official tests in `build/rv32ui/`.)

### Looking at waveforms

After step 13, either:

- **In VS Code:** click `build/sim/waves.vcd` in the file list and Surfer opens it. Open `TOP > rv_soc_sim > u_core` and add these signals: `clk_i`, `pc`, `inst`, `alu_res`, `br_taken`, `next_pc`, `rf_we`, `rd`, `wb_data`, `halted_q`.
- **In GTKWave**, with those signals already set up:

  ```bash
  gtkwave build/sim/waves.vcd sim/waves.gtkw &
  ```

For a block's own waveform, run `make unit BLOCKS=rv_alu WAVES=1`. The file appears in `build/unit/rv_alu/` and opens the same way.

### Benchmark numbers

After step 11:

```bash
.venv/Scripts/python.exe scripts/stats.py --bench --markdown
```

prints the benchmark table. Paste it into a `.md` file and press **Ctrl+Shift+V** to see it as a table.

### The report

- `build/eval/latest/report.html`: the full report with all charts. Open it in a browser.
- `build/eval/<run>/results.json`: every number in the report.
- `build/eval/<run>/logs/`: the full output of every step.
- `build/eval/history.jsonl`: one line per run, to compare runs.

## Adding your own bug

Step 14 uses ready-made bugs. To try your own change without touching the real design:

```bash
# 1. Copy the design to a scratch folder
mkdir -p build/mut/rtl
for f in $(grep -v '^//' rtl/rtl.f | grep .); do cp "$f" build/mut/rtl/; done

# 2. Change one line in the copy (here: break the SRA instruction)
sed -i 's/$unsigned($signed(a_i) >>> shamt)/a_i >> shamt/' build/mut/rtl/rv_alu.sv
git diff --no-index rtl/rv_alu.sv build/mut/rtl/rv_alu.sv

# 3. Lint the copy and build a simulator from it
SRCS=$(for f in $(grep -v '^//' rtl/rtl.f | grep .); do printf 'build/mut/rtl/%s ' "$(basename "$f")"; done)
make lint RTL_SRCS="$SRCS"
make sim-build RTL_SRCS="$SRCS" SIM_DIR=build/mut/sim SIM_EXTRA=-Wno-fatal

# 4. Run tests on the broken copy: some should now FAIL
.venv/Scripts/python.exe scripts/run_progs.py --exe build/mut/sim/Vrv_soc_sim.exe asm
.venv/Scripts/python.exe scripts/run_random.py --exe build/mut/sim/Vrv_soc_sim.exe --seeds 20 --no-save
```

- `--no-save` stops the failing random programs from being saved as permanent tests.
- Delete `build/mut/` when you are done.
- If no test fails, the tests have a gap: add a test that would catch that bug.

## Debugging the scripts

Press **Ctrl+Shift+D** (Run and Debug) and pick a ready-made setup, for example "one program vs. the model". Click left of a line number in a script to set a breakpoint, then press **F5**.
