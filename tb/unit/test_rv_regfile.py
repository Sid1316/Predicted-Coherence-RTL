"""cocotb unit tests for rv_regfile (docs/exec.md M2.3, docs/spec.md §6.5).

Timing used by every test: inputs change just after a falling edge, the
combinational read ports are checked just before the next rising edge, and
the write lands at that rising edge.
"""

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge, Timer
from cocotb.utils import get_sim_time

from rv_model import MASK32, RegFileModel

PERIOD_NS = 10


async def start(dut) -> None:
    """Start the clock and park all inputs at a harmless value."""
    Clock(dut.clk_i, PERIOD_NS, unit="ns").start()
    dut.we_i.value = 0
    dut.wa_i.value = 0
    dut.wd_i.value = 0
    dut.ra1_i.value = 0
    dut.ra2_i.value = 0
    await FallingEdge(dut.clk_i)


async def cycle(dut, *, ra1=0, ra2=0, we=0, wa=0, wd=0):
    """Apply one cycle of inputs. Returns (rd1, rd2) sampled before the edge."""
    dut.ra1_i.value = ra1
    dut.ra2_i.value = ra2
    dut.we_i.value = we
    dut.wa_i.value = wa
    dut.wd_i.value = wd & MASK32
    await Timer(PERIOD_NS // 2 - 1, unit="ns")  # still before the rising edge
    rd1, rd2 = dut.rd1_o.value, dut.rd2_o.value
    await RisingEdge(dut.clk_i)
    await FallingEdge(dut.clk_i)
    return rd1, rd2


def expect(port: str, addr: int, got, exp: int) -> None:
    assert got.is_resolvable, f"{port} x{addr}: X/Z in output: {got}"
    assert got.to_unsigned() == exp, f"{port} x{addr}: got {got.to_unsigned():#010x}, expected {exp:#010x}"


@cocotb.test()
async def test_no_reset(dut):
    """Registers are not reset (spec §2.2): never-written ones read as X in 4-state sim.

    Must be the FIRST test: all tests share one simulation, and a register file
    without reset cannot be cleared, so any earlier test's writes would show up.
    """
    assert get_sim_time("ns") == 0, "test_no_reset must run first (it is defined first in this file)"
    await start(dut)
    for r in range(1, 32):
        rd1, rd2 = await cycle(dut, ra1=r, ra2=r)
        assert not rd1.is_resolvable and not rd2.is_resolvable, (
            f"x{r} reads {rd1} before any write; expected X because there is no reset"
        )


@cocotb.test()
async def test_x0_reads_zero_and_ignores_writes(dut):
    """Writing x0 (all ones, repeatedly) never changes what x0 reads."""
    await start(dut)
    for wd in (MASK32, 0xDEAD_BEEF, 0x8000_0000):
        await cycle(dut, we=1, wa=0, wd=wd)
        rd1, rd2 = await cycle(dut, ra1=0, ra2=0)
        expect("rd1", 0, rd1, 0)
        expect("rd2", 0, rd2, 0)
    # Writing x0 must not leak into any other register either.
    for r in range(1, 32):
        await cycle(dut, we=1, wa=r, wd=r)
    await cycle(dut, we=1, wa=0, wd=MASK32)
    for r in range(1, 32):
        rd1, _ = await cycle(dut, ra1=r)
        expect("rd1", r, rd1, r)


@cocotb.test()
async def test_every_register_both_ports(dut):
    """Write a distinct value to x1..x31, read every one back on both ports."""
    await start(dut)
    values = {r: (0x1111_1111 * (r % 15 + 1)) ^ (r << 24) for r in range(1, 32)}
    for r, v in values.items():
        await cycle(dut, we=1, wa=r, wd=v)
    for r in range(1, 32):
        rd1, rd2 = await cycle(dut, ra1=r, ra2=32 - r)  # different register on each port
        expect("rd1", r, rd1, values[r])
        expect("rd2", 32 - r, rd2, values[32 - r])


@cocotb.test()
async def test_write_enable_low_does_not_write(dut):
    """With we_i = 0 the write address and data are ignored."""
    await start(dut)
    await cycle(dut, we=1, wa=5, wd=0x0000_0055)
    await cycle(dut, we=0, wa=5, wd=0xFFFF_FFFF)
    rd1, _ = await cycle(dut, ra1=5)
    expect("rd1", 5, rd1, 0x0000_0055)


@cocotb.test()
async def test_read_during_write_returns_old_value(dut):
    """A same-cycle read of the register being written sees the old value (spec §6.5)."""
    await start(dut)
    await cycle(dut, we=1, wa=7, wd=0x0000_0001)
    rd1, rd2 = await cycle(dut, ra1=7, ra2=7, we=1, wa=7, wd=0x0000_0002)
    expect("rd1", 7, rd1, 0x0000_0001)
    expect("rd2", 7, rd2, 0x0000_0001)
    rd1, _ = await cycle(dut, ra1=7)
    expect("rd1", 7, rd1, 0x0000_0002)


@cocotb.test()
async def test_random_against_model(dut):
    """3000 random cycles of reads and writes compared with the Python model."""
    await start(dut)
    model = RegFileModel()
    # Write every register once first, so all reads have a defined value.
    for r in range(1, 32):
        v = random.getrandbits(32)
        await cycle(dut, we=1, wa=r, wd=v)
        model.write(1, r, v)
    for _ in range(3000):
        ra1, ra2, wa = random.randrange(32), random.randrange(32), random.randrange(32)
        if random.random() < 0.2:  # exercise read-during-write often
            ra1 = wa
        we, wd = random.getrandbits(1), random.getrandbits(32)
        rd1, rd2 = await cycle(dut, ra1=ra1, ra2=ra2, we=we, wa=wa, wd=wd)
        expect("rd1", ra1, rd1, model.read(ra1))
        expect("rd2", ra2, rd2, model.read(ra2))
        model.write(we, wa, wd)
