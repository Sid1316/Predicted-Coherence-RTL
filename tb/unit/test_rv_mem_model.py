"""cocotb unit tests for rv_mem_model (docs/exec.md M3.3, docs/spec.md §2.3, §6.9, §8.3).

The run is started by run_unit.py with +hex= pointing at the image from
sim_scenarios.mem_model_image(). The tests check:
  - the image is loaded word for word, at the @ addresses, and every other
    word is 0 (both ports, every word of RAM);
  - err exactly outside [MEM_BASE, MEM_BASE + MEM_SIZE_BYTES), on both ports,
    only for a valid request; rdata = 0 and ready = 1 otherwise;
  - writes: only for valid & we & in range, only the lanes in be, visible at
    the next edge (same-cycle reads return the old word, on both ports), and
    an out-of-range store never aliases into RAM;
  - random traffic on both ports against a Python memory, then every word of
    the array compared with it.
"""

import os
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge, Timer

import sim_scenarios
from rv_model import (
    CONSOLE_ADDR, DMEM_REQ_FIELDS, DMEM_RSP_FIELDS, IMEM_REQ_FIELDS, IMEM_RSP_FIELDS, MASK32,
    MEM_BASE, MEM_SIZE_BYTES, read_hex, struct_pack, struct_unpack,
)

WORDS = MEM_SIZE_BYTES // 4
MEM_END = MEM_BASE + MEM_SIZE_BYTES
RUN = sim_scenarios.find(os.environ.get("SIM_RUN", "mem_image"))

# Addresses outside RAM, including ones whose low bits would alias into it.
OUTSIDE = [0x0000_0000, 0x0000_0004, CONSOLE_ADDR, MEM_BASE - 4, MEM_BASE - 1, MEM_END, MEM_END + 4,
           MEM_END + 0x1000, 0x8010_0000, 0xC000_0000, 0xFFFF_FFFC, 0x7FFF_FFFC, 0x0001_0000]
EDGES = [MEM_BASE, MEM_BASE + 1, MEM_BASE + 3, MEM_END - 4, MEM_END - 1]


def resolved(sig, name):
    v = sig.value
    assert v.is_resolvable, f"{name} has X/Z: {v}"
    return int(v)


class Bench:
    def __init__(self, dut):
        self.dut = dut
        image = RUN.image()
        assert read_hex(os.environ["SIM_HEX"]) == image, "hex file does not match the run's image"
        self.ram = [0] * WORDS
        for addr, word in image.items():
            self.ram[(addr - MEM_BASE) // 4] = word
        self.idle()

    def idle(self):
        self.dut.imem_req_i.value = struct_pack(IMEM_REQ_FIELDS, valid=0, addr=random.getrandbits(32))
        self.dut.dmem_req_i.value = struct_pack(DMEM_REQ_FIELDS, valid=0, we=random.getrandbits(1),
                                                be=random.getrandbits(4), addr=random.getrandbits(32),
                                                wdata=random.getrandbits(32))

    @staticmethod
    def in_ram(addr):
        return MEM_BASE <= addr < MEM_END

    def expected(self, valid, addr):
        """(rdata, err) the memory should answer."""
        if not valid:
            return 0, 0
        if not self.in_ram(addr):
            return 0, 1
        return self.ram[(addr - MEM_BASE) // 4], 0

    async def fetch(self, addr, valid=1):
        self.dut.imem_req_i.value = struct_pack(IMEM_REQ_FIELDS, valid=valid, addr=addr)
        await Timer(1, unit="ns")
        rsp = struct_unpack(IMEM_RSP_FIELDS, resolved(self.dut.imem_rsp_o, "imem_rsp_o"))
        return rsp

    async def data(self, addr, valid=1, we=0, be=0, wdata=0):
        self.dut.dmem_req_i.value = struct_pack(DMEM_REQ_FIELDS, valid=valid, we=we, be=be,
                                                addr=addr, wdata=wdata)
        await Timer(1, unit="ns")
        return struct_unpack(DMEM_RSP_FIELDS, resolved(self.dut.dmem_rsp_o, "dmem_rsp_o"))

    def check(self, rsp, valid, addr, port):
        rdata, err = self.expected(valid, addr)
        exp = {"ready": 1, "rdata": rdata, "err": err}
        assert rsp == exp, f"port {port} valid={valid} addr={addr:#010x}: got {rsp}, expected {exp}"

    def apply_store(self, valid, we, be, addr, wdata):
        if valid and we and self.in_ram(addr):
            i = (addr - MEM_BASE) // 4
            for lane in range(4):
                if be >> lane & 1:
                    m = 0xFF << (8 * lane)
                    self.ram[i] = (self.ram[i] & ~m | wdata & m) & MASK32

    async def store(self, addr, be, wdata, valid=1, we=1):
        """Present a request on port B for one clock edge (called after a falling edge)."""
        old = await self.data(addr, valid=valid, we=we, be=be, wdata=wdata)
        self.check(old, valid, addr, "B (during store)")
        await RisingEdge(self.dut.clk_i)
        self.apply_store(valid, we, be, addr, wdata)
        await FallingEdge(self.dut.clk_i)
        self.idle()

    def array_word(self, i):
        return resolved(self.dut.mem[i], f"mem[{i}]")

    def check_array(self):
        for i in range(WORDS):
            got = self.array_word(i)
            assert got == self.ram[i], f"mem[{i:#x}] = {got:#010x}, expected {self.ram[i]:#010x}"


_bench = None


async def start(dut):
    """The tests share one simulation, so they share one Bench: its Python RAM
    carries the stores of earlier tests, as the simulated memory does."""
    global _bench
    if _bench is None:
        _bench = Bench(dut)
    Clock(dut.clk_i, 10, unit="ns").start()
    _bench.idle()
    await FallingEdge(dut.clk_i)
    return _bench


@cocotb.test()
async def test_image_loaded(dut):
    """Every RAM word through both ports: image words where the hex file put them, 0 elsewhere."""
    b = await start(dut)   # first test: RAM is still the image
    assert any(b.ram) and b.ram[WORDS - 1] != 0, "image should cover the last word"
    for i in range(WORDS):
        addr = MEM_BASE + 4 * i
        b.check(await b.fetch(addr), 1, addr, "A")
        b.check(await b.data(addr), 1, addr, "B")
    b.idle()
    b.check_array()


@cocotb.test()
async def test_ranges(dut):
    """err exactly outside RAM on both ports, for valid requests only; byte offsets are ignored."""
    b = await start(dut)
    for addr in OUTSIDE + EDGES + [random.getrandbits(32) for _ in range(500)]:
        for valid in (1, 0):
            b.check(await b.fetch(addr, valid=valid), valid, addr, "A")
            # The clock runs, so only out-of-range addresses get we = 1 (a store
            # there must be dropped; check_array() at the end of test_writes
            # would show one that was not).
            we = random.getrandbits(1) if not b.in_ram(addr) else 0
            b.check(await b.data(addr, valid=valid, we=we, be=0xF), valid, addr, "B")
    # rdata is the aligned word whatever the byte offset.
    for off in range(4):
        rsp = await b.data(MEM_BASE + 8 + off)
        assert rsp["rdata"] == b.ram[2]


@cocotb.test()
async def test_writes(dut):
    """Byte enables, same-cycle read of the old word on both ports, no write without valid/we or out of range."""
    b = await start(dut)
    base = MEM_BASE + 0x400
    for be in range(16):
        addr = base + 4 * be
        wdata = random.getrandbits(32)
        before = b.ram[(addr - MEM_BASE) // 4]
        # Port A reads the same word in the cycle of the store: the old word.
        b.dut.imem_req_i.value = struct_pack(IMEM_REQ_FIELDS, valid=1, addr=addr)
        rsp_b = await b.data(addr + random.randrange(4), we=1, be=be, wdata=wdata)
        rsp_a = struct_unpack(IMEM_RSP_FIELDS, resolved(b.dut.imem_rsp_o, "imem_rsp_o"))
        assert rsp_a["rdata"] == before and rsp_b["rdata"] == before, "same-cycle read must return the old word"
        await RisingEdge(dut.clk_i)
        b.apply_store(1, 1, be, addr, wdata)
        await FallingEdge(dut.clk_i)
        b.check(await b.fetch(addr), 1, addr, "A (after store)")
        b.check(await b.data(addr), 1, addr, "B (after store)")
        b.idle()

    snapshot = list(b.ram)
    # valid = 0, or we = 0, never writes.
    await b.store(base, 0xF, 0xDEAD_BEEF, valid=0)
    await b.store(base, 0xF, 0xDEAD_BEEF, we=0)
    # Out-of-range stores never alias into RAM (MEM_END wraps to word 0 and
    # MEM_BASE - 4 to the last word if the range check is missing).
    for addr in OUTSIDE:
        await b.store(addr, 0xF, 0xDEAD_BEEF)
    assert b.ram == snapshot
    b.check_array()


@cocotb.test()
async def test_random_traffic(dut):
    """Random requests on both ports every cycle against a Python memory; then the whole array."""
    b = await start(dut)
    hot = [MEM_BASE + 4 * random.randrange(WORDS) for _ in range(8)] + [MEM_BASE, MEM_END - 4]

    def rand_addr():
        k = random.random()
        if k < 0.5:
            return random.choice(hot) + random.randrange(4)
        if k < 0.9:
            return MEM_BASE + random.randrange(MEM_SIZE_BYTES)
        return random.choice(OUTSIDE + [random.getrandbits(32)])

    for _ in range(4000):
        ia = rand_addr() & ~3
        iv = int(random.random() < 0.9)
        req = dict(valid=int(random.random() < 0.8), we=random.getrandbits(1), be=random.getrandbits(4),
                   addr=rand_addr(), wdata=random.getrandbits(32))
        b.dut.imem_req_i.value = struct_pack(IMEM_REQ_FIELDS, valid=iv, addr=ia)
        b.dut.dmem_req_i.value = struct_pack(DMEM_REQ_FIELDS, **req)
        await Timer(1, unit="ns")
        b.check(struct_unpack(IMEM_RSP_FIELDS, resolved(dut.imem_rsp_o, "imem_rsp_o")), iv, ia, "A")
        b.check(struct_unpack(DMEM_RSP_FIELDS, resolved(dut.dmem_rsp_o, "dmem_rsp_o")),
                req["valid"], req["addr"], "B")
        await RisingEdge(dut.clk_i)
        b.apply_store(**req)
        await FallingEdge(dut.clk_i)
    b.idle()
    b.check_array()
