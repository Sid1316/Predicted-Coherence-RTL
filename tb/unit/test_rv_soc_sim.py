"""cocotb tests for rv_soc_sim (docs/exec.md M3.3, docs/spec.md §2, §6.10, §9.2, §11).

run_unit.py starts one simulation per run in sim_scenarios.SOC_RUNS, with
+hex=, +tohost= and +retire_log= set for that run and its name in $SIM_RUN.
The test only drives clk_i and rst_i, as the C++ harness will, and checks:
  - every cycle: the retire port against CoreModel (whose SimMemory has the
    same memory map, spec §2.3), console_valid_o/console_data_o against the
    bytes the model printed, and after the edge done_o / tohost_value_o /
    halted_o / status_o;
  - at the end: the retire log file line for line against the model's trace
    formatted as spec §9.2, every RAM word in u_mem against the model, and the
    run's directed expectations (stop cause, done, tohost value, console text).
"""

import os
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge, Timer

import sim_scenarios
from rv_model import (
    MEM_BASE, MEM_SIZE_BYTES, RETIRE_FIELDS, STOP_CAUSES, CoreModel, SimMemory, decode_ref,
    read_hex, retire_log_line, struct_unpack,
)

RUN = sim_scenarios.find(os.environ.get("SIM_RUN", "pass"))
CAUSE_NAMES = {v: k for k, v in STOP_CAUSES.items()}


def resolved(sig, name):
    v = sig.value
    assert v.is_resolvable, f"{name} has X/Z: {v}"
    return int(v)


@cocotb.test()
async def test_run(dut):
    """One program through rv_soc_sim, lockstep with the model."""
    image = RUN.image()
    if image is not None:
        assert read_hex(os.environ["SIM_HEX"]) == image, "hex file does not match the run's image"
    model = CoreModel(SimMemory(image))

    Clock(dut.clk_i, 10, unit="ns").start()
    dut.rst_i.value = 1
    for _ in range(2):
        await FallingEdge(dut.clk_i)
        assert resolved(dut.retire_o, "retire_o") == 0 and resolved(dut.done_o, "done_o") == 0
        assert resolved(dut.console_valid_o, "console_valid_o") == 0
    dut.rst_i.value = 0
    model.reset()

    lines = []
    done, tohost_value = False, 0
    retired = idle = 0
    for _ in range(RUN.max_cycles):
        await Timer(1, unit="ns")
        got = struct_unpack(RETIRE_FIELDS, resolved(dut.retire_o, "retire_o"))
        printed = len(model.mem.console)
        exp = model.step()
        if got != exp:
            diff = {k: (f"{got[k]:#x}", f"{exp[k]:#x}") for k in exp if got[k] != exp[k]}
            name = decode_ref(exp["insn"])[0] if exp["valid"] else "-"
            raise AssertionError(f"retire mismatch at pc={exp['pc_rdata']:#010x} ({name}), "
                                 f"(got, expected): {diff}")
        cv = resolved(dut.console_valid_o, "console_valid_o")
        if len(model.mem.console) > printed:
            assert cv == 1 and resolved(dut.console_data_o, "console_data_o") == model.mem.console[-1], \
                f"console byte {model.mem.console[-1]:#04x} not shown"
        else:
            assert cv == 0, "console_valid_o without a console byte"
        if exp["valid"]:
            retired += 1
            lines.append(retire_log_line(exp, model.status))
            if (RUN.tohost is not None and not done and exp["mem_wmask"]
                    and exp["mem_addr"] == RUN.tohost & ~3):
                done, tohost_value = True, model.mem.word(RUN.tohost)

        await RisingEdge(dut.clk_i)
        await Timer(1, unit="ns")
        assert resolved(dut.done_o, "done_o") == int(done), f"done_o, expected {done}"
        if done:
            assert resolved(dut.tohost_value_o, "tohost_value_o") == tohost_value, \
                f"tohost_value_o = {int(dut.tohost_value_o.value):#x}, expected {tohost_value:#x}"
        assert resolved(dut.halted_o, "halted_o") == int(model.halted)
        assert resolved(dut.status_o, "status_o") == model.status, \
            f"status_o = {CAUSE_NAMES.get(int(dut.status_o.value))}, expected {CAUSE_NAMES[model.status]}"
        await FallingEdge(dut.clk_i)
        if model.halted:
            idle += 1
            if idle > 3:
                break

    cause = CAUSE_NAMES[model.status]
    dut._log.info(f"{RUN.name}: {retired} retired, {cause}, done={done}, tohost={tohost_value:#x}, "
                  f"console={bytes(model.mem.console)!r}")

    # RAM, word for word (catches a store the retire port does not show, or aliasing).
    for i in range(MEM_SIZE_BYTES // 4):
        exp_word = model.mem.word(MEM_BASE + 4 * i)
        got_word = resolved(dut.u_mem.mem[i], f"mem[{i}]")
        assert got_word == exp_word, f"RAM word {MEM_BASE + 4 * i:#010x} = {got_word:#010x}, " \
                                     f"expected {exp_word:#010x}"

    # Retire log: flushed when the core stops or tohost is written, so it is
    # complete here if the run stopped.
    if model.halted:
        text = Path(os.environ["SIM_LOG"]).read_text(encoding="ascii")
        got_lines = text.splitlines()
        for n, (g, e) in enumerate(zip(got_lines, lines)):
            assert g == e, f"retire log line {n}:\n  got      {g}\n  expected {e}"
        assert len(got_lines) == len(lines), f"retire log has {len(got_lines)} lines, expected {len(lines)}"
        assert text.endswith("\n")
    else:
        dut._log.info("did not stop within max_cycles; retire log not checked")

    x = RUN.expect
    if "cause" in x:
        assert cause == x["cause"], f"stopped with {cause}, expected {x['cause']}"
    if "done" in x:
        assert done == x["done"]
    if "tohost" in x:
        assert tohost_value == x["tohost"], f"tohost {tohost_value:#x}, expected {x['tohost']:#x}"
    if "console" in x:
        assert bytes(model.mem.console) == x["console"], model.mem.console
    if "retired" in x:
        assert retired == x["retired"]
