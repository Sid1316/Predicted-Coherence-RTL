"""cocotb unit tests for rv_pc (docs/exec.md M3.1, docs/spec.md §2.2, §5.2, §6.2).

Timing: inputs change just after a falling edge; the combinational outputs
(next_pc_o, misaligned_fetch_o, pc_plus4_o) are checked just before the next
rising edge, and pc_o is checked after it.
"""

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge, Timer

from rv_model import MASK32, RESET_PC, next_pc_ref

PERIOD_NS = 10
CTRL_INPUTS = ("halted", "stop", "jump", "jalr", "branch", "br_taken")


def resolved(sig, name):
    v = sig.value
    assert v.is_resolvable, f"{name} has X/Z: {v}"
    return int(v)


async def start(dut, reset_cycles=2):
    """Start the clock, hold reset (spec §2.2: at least 2 cycles), release it."""
    Clock(dut.clk_i, PERIOD_NS, unit="ns").start()
    await drive(dut)
    dut.rst_i.value = 1
    for _ in range(reset_cycles):
        await RisingEdge(dut.clk_i)
    await FallingEdge(dut.clk_i)
    dut.rst_i.value = 0
    assert resolved(dut.pc_o, "pc_o") == RESET_PC


async def drive(dut, target=0, **ctrl):
    for name in CTRL_INPUTS:
        getattr(dut, f"{name}_i").value = ctrl.get(name, 0)
    dut.target_i.value = target & MASK32


async def step(dut, target=0, **ctrl):
    """One cycle: drive inputs, check combinational outputs vs. the model, clock, check pc_o.

    Returns (next_pc, misaligned_fetch) as seen before the edge."""
    pc = resolved(dut.pc_o, "pc_o")
    await drive(dut, target, **ctrl)
    await Timer(PERIOD_NS // 2 - 1, unit="ns")  # still before the rising edge
    exp_next, exp_mis = next_pc_ref(pc=pc, target=target, **{n: ctrl.get(n, 0) for n in CTRL_INPUTS})
    ctx = f"pc={pc:#010x} target={target:#010x} {ctrl}"
    assert resolved(dut.pc_plus4_o, "pc_plus4_o") == (pc + 4) & MASK32, ctx
    got_next = resolved(dut.next_pc_o, "next_pc_o")
    got_mis = resolved(dut.misaligned_fetch_o, "misaligned_fetch_o")
    assert got_next == exp_next, f"next_pc: got {got_next:#010x}, expected {exp_next:#010x} ({ctx})"
    assert got_mis == exp_mis, f"misaligned_fetch: got {got_mis}, expected {exp_mis} ({ctx})"
    await RisingEdge(dut.clk_i)
    await FallingEdge(dut.clk_i)
    got_pc = resolved(dut.pc_o, "pc_o")
    assert got_pc == exp_next, f"pc_o after edge: got {got_pc:#010x}, expected {exp_next:#010x} ({ctx})"
    return got_next, got_mis


@cocotb.test()
async def test_reset(dut):
    """Reset loads RESET_PC, and wins over halted/stop/jump and an in-flight PC."""
    await start(dut)
    for _ in range(5):
        await step(dut)
    assert resolved(dut.pc_o, "pc_o") == RESET_PC + 20
    # Reset in the middle of a run, with every other input trying to move the PC.
    await drive(dut, target=0x1234_5678, jump=1, branch=1, br_taken=1, halted=1, stop=1)
    dut.rst_i.value = 1
    await RisingEdge(dut.clk_i)
    await FallingEdge(dut.clk_i)
    assert resolved(dut.pc_o, "pc_o") == RESET_PC, "reset must load RESET_PC regardless of other inputs"
    dut.rst_i.value = 0
    await drive(dut)


@cocotb.test()
async def test_reset_is_synchronous(dut):
    """Raising rst_i mid-cycle does not change pc_o until the next rising edge (spec §2.2)."""
    await start(dut)
    for _ in range(3):
        await step(dut)
    pc = resolved(dut.pc_o, "pc_o")
    assert pc != RESET_PC
    dut.rst_i.value = 1
    await Timer(1, unit="ns")
    assert resolved(dut.pc_o, "pc_o") == pc, "pc_o changed as soon as rst_i rose: reset is asynchronous"
    await Timer(PERIOD_NS // 2 - 2, unit="ns")  # just before the rising edge
    assert resolved(dut.pc_o, "pc_o") == pc, "pc_o changed before the clock edge: reset is asynchronous"
    await RisingEdge(dut.clk_i)
    await Timer(1, unit="ns")
    assert resolved(dut.pc_o, "pc_o") == RESET_PC
    await FallingEdge(dut.clk_i)
    dut.rst_i.value = 0


@cocotb.test()
async def test_sequential(dut):
    """No redirect: PC advances by 4 every cycle."""
    await start(dut)
    for _ in range(64):
        await step(dut)
    assert resolved(dut.pc_o, "pc_o") == RESET_PC + 256


@cocotb.test()
async def test_branches(dut):
    """Taken branch goes to the target; not taken, or taken without branch_i, goes to pc+4."""
    await start(dut)
    nxt, _ = await step(dut, target=RESET_PC + 0x100, branch=1, br_taken=1)   # forward, taken
    assert nxt == RESET_PC + 0x100
    nxt, _ = await step(dut, target=RESET_PC + 0x40, branch=1, br_taken=0)    # not taken
    assert nxt == RESET_PC + 0x104
    nxt, _ = await step(dut, target=RESET_PC, branch=1, br_taken=1)           # backward, taken
    assert nxt == RESET_PC
    nxt, _ = await step(dut, target=0x1000, branch=0, br_taken=1)             # not a branch
    assert nxt == RESET_PC + 4


@cocotb.test()
async def test_jal_jalr(dut):
    """JAL goes to the target as is; JALR clears bit 0 (spec §4 row 4)."""
    await start(dut)
    nxt, mis = await step(dut, target=RESET_PC + 0x800, jump=1)
    assert (nxt, mis) == (RESET_PC + 0x800, 0)
    nxt, mis = await step(dut, target=RESET_PC + 0x201, jump=1, jalr=1)        # bit 0 set: cleared, legal
    assert (nxt, mis) == (RESET_PC + 0x200, 0)
    nxt, mis = await step(dut, target=0xFFFF_FFFF & ~0b10, jump=1, jalr=1)    # 0x...FD -> 0x...FC
    assert (nxt, mis) == (0xFFFF_FFFC, 0)


@cocotb.test()
async def test_misaligned_fetch(dut):
    """Bit 1 set on a redirect is misaligned; a not-taken branch to such a target is not (spec §5.2)."""
    await start(dut)
    cases = [  # (inputs, expected misaligned)
        (dict(target=RESET_PC + 0x102, jump=1), 1),                     # JAL to +2
        (dict(target=RESET_PC + 0x102, jump=1, jalr=1), 1),             # JALR, bit 1 set
        (dict(target=RESET_PC + 0x103, jump=1, jalr=1), 1),             # JALR, bits 1 and 0 set
        (dict(target=RESET_PC + 0x101, jump=1, jalr=1), 0),             # JALR, only bit 0 set
        (dict(target=RESET_PC + 0x102, branch=1, br_taken=1), 1),       # taken branch to +2
        (dict(target=RESET_PC + 0x102, branch=1, br_taken=0), 0),       # not taken: never misaligned
        (dict(target=RESET_PC + 0x102), 0),                             # no redirect at all
    ]
    for inputs, exp in cases:
        # Stop the core when the model says so, as rv_core will (stop includes misaligned_fetch).
        _, mis = await step(dut, **inputs, stop=exp)
        assert mis == exp, f"{inputs}: misaligned_fetch={mis}, expected {exp}"


@cocotb.test()
async def test_hold(dut):
    """halted_i or stop_i keeps the PC, even with a redirect; misaligned_fetch ignores both."""
    await start(dut)
    await step(dut)
    pc = resolved(dut.pc_o, "pc_o")
    for halted, stop in ((1, 0), (0, 1), (1, 1)):
        for redirect in (dict(), dict(jump=1, target=0x8000_1000), dict(branch=1, br_taken=1, target=0x10)):
            nxt, _ = await step(dut, halted=halted, stop=stop, **redirect)
            assert nxt == pc, f"halted={halted} stop={stop} {redirect}: PC moved to {nxt:#010x}"
    # misaligned_fetch_o must not depend on stop_i/halted_i (no loop when the core feeds it back).
    for halted, stop in ((0, 0), (1, 0), (0, 1), (1, 1)):
        await drive(dut, target=0x8000_0002, jump=1, halted=halted, stop=stop)
        await Timer(1, unit="ns")
        assert resolved(dut.misaligned_fetch_o, "misaligned_fetch_o") == 1, f"halted={halted} stop={stop}"
    await drive(dut)


@cocotb.test()
async def test_wraparound(dut):
    """pc + 4 wraps at 2^32 (no special case)."""
    await start(dut)
    await step(dut, target=0xFFFF_FFF8, jump=1)
    nxt, _ = await step(dut)
    assert nxt == 0xFFFF_FFFC
    nxt, _ = await step(dut)
    assert nxt == 0x0000_0000


@cocotb.test()
async def test_random(dut):
    """3000 random cycles vs. the model, including occasional resets."""
    await start(dut)
    for _ in range(3000):
        if random.random() < 0.01:
            await start(dut, reset_cycles=random.randint(1, 3))
            continue
        ctrl = {n: int(random.random() < p) for n, p in
                (("halted", 0.05), ("stop", 0.05), ("jump", 0.2), ("jalr", 0.5), ("branch", 0.3), ("br_taken", 0.5))}
        await step(dut, target=random.getrandbits(32), **ctrl)


@cocotb.test()
async def test_model_self_check(dut):
    """Sanity-check the Python model on hand-computed values."""
    del dut  # model-only test
    base = dict(pc=0x100, halted=0, stop=0, jump=0, jalr=0, branch=0, br_taken=0, target=0x203)
    assert next_pc_ref(**base) == (0x104, 0)
    assert next_pc_ref(**{**base, "jump": 1, "jalr": 1}) == (0x202, 1)
    assert next_pc_ref(**{**base, "jump": 1, "jalr": 1, "target": 0x201}) == (0x200, 0)
    assert next_pc_ref(**{**base, "branch": 1, "br_taken": 1, "target": 0x202}) == (0x202, 1)
    assert next_pc_ref(**{**base, "branch": 1, "target": 0x202}) == (0x104, 0)
    assert next_pc_ref(**{**base, "stop": 1, "jump": 1}) == (0x100, 1)
