"""cocotb unit tests for rv_lsu (docs/exec.md M2.5, docs/spec.md §5.4, §6.8)."""

import random

import cocotb
from cocotb.triggers import Timer

from rv_model import (
    CTRL_FIELDS, DMEM_REQ_FIELDS, DMEM_RSP_FIELDS, MASK32, MEM_SIZES,
    lsu_ref, struct_pack, struct_unpack, struct_width,
)

LOADS = {  # name -> (size, unsigned)
    "LB": ("MEM_B", 0), "LH": ("MEM_H", 0), "LW": ("MEM_W", 0),
    "LBU": ("MEM_B", 1), "LHU": ("MEM_H", 1),
}
STORES = {"SB": "MEM_B", "SH": "MEM_H", "SW": "MEM_W"}

# A word whose every byte has a different value and both sign bits set in
# some bytes but not others, so a wrong lane or extension shows up.
RDATA_PATTERNS = [0x807F_FF01, 0x7F80_01FF, 0x1234_5678, 0xFEDC_BA98, 0x0000_0000, 0xFFFF_FFFF]
BASE = 0x8000_0100


async def drive(dut, *, size_name="MEM_W", unsigned=0, mem_read=0, mem_write=0, enable=1,
                addr=BASE, store_data=0, rdata=0, err=0, other_ctrl=None, size_code=None,
                ready=1):
    """Apply one set of inputs and return the outputs as a dict (raw LogicArrays kept for X checks)."""
    ctrl = dict(other_ctrl or {})
    ctrl.update(mem_size=MEM_SIZES[size_name] if size_code is None else size_code,
                mem_unsigned=unsigned, mem_read=mem_read, mem_write=mem_write)
    dut.ctrl_i.value = struct_pack(CTRL_FIELDS, **ctrl)
    dut.addr_i.value = addr & MASK32
    dut.store_data_i.value = store_data & MASK32
    dut.enable_i.value = enable
    dut.dmem_rsp_i.value = struct_pack(DMEM_RSP_FIELDS, ready=ready, rdata=rdata & MASK32, err=err)
    await Timer(1, unit="ns")
    outs = {
        "req": dut.dmem_req_o.value,
        "load_data": dut.load_data_o.value,
        "misaligned": dut.misaligned_o.value,
        "bus_err": dut.bus_err_o.value,
    }
    for name, val in outs.items():
        assert val.is_resolvable, f"{name} has X/Z: {val} (inputs: size={size_name} addr={addr:#x})"
    assert len(outs["req"]) == struct_width(DMEM_REQ_FIELDS)
    got = struct_unpack(DMEM_REQ_FIELDS, outs["req"].to_unsigned())
    got["load_data"] = outs["load_data"].to_unsigned()
    got["misaligned"] = int(outs["misaligned"])
    got["bus_err"] = int(outs["bus_err"])
    return got


async def check(dut, **kw):
    """Drive one vector and compare every output with the model."""
    got = await drive(dut, **kw)
    model_kw = {k: kw.get(k, d) for k, d in (
        ("size_name", "MEM_W"), ("unsigned", 0), ("mem_read", 0), ("mem_write", 0), ("enable", 1),
        ("addr", BASE), ("store_data", 0), ("rdata", 0), ("err", 0))}
    exp = lsu_ref(**model_kw)
    ctx = " ".join(f"{k}={v:#x}" if isinstance(v, int) and v > 9 else f"{k}={v}" for k, v in model_kw.items())
    for field in ("valid", "we", "be", "addr", "misaligned", "bus_err"):
        assert got[field] == exp[field], f"{field}: got {got[field]:#x}, expected {exp[field]:#x} ({ctx})"
    # wdata only matters when a store is issued; there it must be lane-placed.
    if exp["we"]:
        assert got["wdata"] == exp["wdata"], f"wdata: got {got['wdata']:#010x}, expected {exp['wdata']:#010x} ({ctx})"
    if exp["load_data"] is not None:
        assert got["load_data"] == exp["load_data"], (
            f"load_data: got {got['load_data']:#010x}, expected {exp['load_data']:#010x} ({ctx})")
    return got


@cocotb.test()
async def test_loads_every_offset(dut):
    """LB/LH/LW/LBU/LHU at every byte offset: extension, lane select, misalignment."""
    for name, (size, uns) in LOADS.items():
        for off in range(4):
            for rdata in RDATA_PATTERNS:
                await check(dut, size_name=size, unsigned=uns, mem_read=1, addr=BASE + off, rdata=rdata)


@cocotb.test()
async def test_loads_hand_checked(dut):
    """A few load results worked out by hand, so a model bug cannot hide an RTL bug."""
    rdata = 0x807F_FF01  # bytes (lane 0..3): 01 FF 7F 80
    cases = [
        ("LB", 0, 0x0000_0001), ("LB", 1, 0xFFFF_FFFF), ("LB", 2, 0x0000_007F), ("LB", 3, 0xFFFF_FF80),
        ("LBU", 1, 0x0000_00FF), ("LBU", 3, 0x0000_0080),
        ("LH", 0, 0xFFFF_FF01), ("LH", 2, 0xFFFF_807F),
        ("LHU", 0, 0x0000_FF01), ("LHU", 2, 0x0000_807F),
        ("LW", 0, 0x807F_FF01),
    ]
    for name, off, exp in cases:
        size, uns = LOADS[name]
        got = await drive(dut, size_name=size, unsigned=uns, mem_read=1, addr=BASE + off, rdata=rdata)
        assert got["load_data"] == exp, f"{name} off {off}: got {got['load_data']:#010x}, expected {exp:#010x}"
        assert got["valid"] == 1 and got["we"] == 0


@cocotb.test()
async def test_stores_every_offset(dut):
    """SB/SH/SW at every byte offset: byte enables, lane placement, misalignment."""
    for name, size in STORES.items():
        for off in range(4):
            for data in (0x1122_3344, 0xA5C3_E10F, 0xFFFF_FFFF):
                await check(dut, size_name=size, mem_write=1, addr=BASE + off, store_data=data)


@cocotb.test()
async def test_stores_hand_checked(dut):
    """Store be/wdata from the spec §5.4 table, written out by hand."""
    data = 0x1122_3344
    cases = [  # (name, off, be, wdata)
        ("SB", 0, 0b0001, 0x4444_4444), ("SB", 1, 0b0010, 0x4444_4444),
        ("SB", 2, 0b0100, 0x4444_4444), ("SB", 3, 0b1000, 0x4444_4444),
        ("SH", 0, 0b0011, 0x3344_3344), ("SH", 2, 0b1100, 0x3344_3344),
        ("SW", 0, 0b1111, 0x1122_3344),
    ]
    for name, off, be, wdata in cases:
        got = await drive(dut, size_name=STORES[name], mem_write=1, addr=BASE + off, store_data=data)
        assert (got["valid"], got["we"], got["be"], got["wdata"]) == (1, 1, be, wdata), (
            f"{name} off {off}: got valid={got['valid']} we={got['we']} be={got['be']:04b} "
            f"wdata={got['wdata']:#010x}")


@cocotb.test()
async def test_misaligned(dut):
    """Misaligned half/word loads and stores: valid, we and be low, misaligned_o high, no bus error."""
    cases = [("MEM_H", 1), ("MEM_H", 3), ("MEM_W", 1), ("MEM_W", 2), ("MEM_W", 3)]
    for size, off in cases:
        for rd, wr in ((1, 0), (0, 1)):
            got = await drive(dut, size_name=size, mem_read=rd, mem_write=wr, addr=BASE + off,
                              store_data=0xFFFF_FFFF, err=1)
            assert (got["valid"], got["we"], got["be"], got["misaligned"], got["bus_err"]) == (0, 0, 0, 1, 0), (
                f"{size} off {off} {'load' if rd else 'store'}: {got}")


@cocotb.test()
async def test_no_access(dut):
    """No mem_read/mem_write: no request and no flags, even at misaligned addresses or with err set."""
    for size in MEM_SIZES:
        for off in range(4):
            await check(dut, size_name=size, addr=BASE + off, err=1, store_data=0xFFFF_FFFF)


@cocotb.test()
async def test_enable_gates_everything(dut):
    """enable_i = 0 (halted / fetch error): no request, no misaligned_o, no bus_err_o."""
    for size in MEM_SIZES:
        for off in range(4):
            for rd, wr in ((1, 0), (0, 1)):
                got = await check(dut, size_name=size, mem_read=rd, mem_write=wr, enable=0,
                                  addr=BASE + off, err=1)
                assert got["valid"] == 0 and got["misaligned"] == 0 and got["bus_err"] == 0


@cocotb.test()
async def test_bus_error(dut):
    """bus_err_o follows dmem_rsp.err only for an issued request."""
    for rd, wr in ((1, 0), (0, 1)):
        for err in (0, 1):
            got = await check(dut, size_name="MEM_W", mem_read=rd, mem_write=wr, addr=0x2000_0000, err=err)
            assert got["bus_err"] == err


@cocotb.test()
async def test_ignores_other_inputs(dut):
    """Non-memory ctrl_t fields and dmem_rsp.ready do not change the outputs."""
    all_ones = {name: (1 << w) - 1 for name, w in CTRL_FIELDS
                if name not in ("mem_size", "mem_unsigned", "mem_read", "mem_write")}
    for name, (size, uns) in LOADS.items():
        for off in range(4):
            kw = dict(size_name=size, unsigned=uns, mem_read=1, addr=BASE + off, rdata=0x807F_FF01)
            ref = await drive(dut, **kw)
            other = await drive(dut, **kw, other_ctrl=all_ones, ready=0)
            assert ref == other, f"{name} off {off}: {ref} vs {other}"


@cocotb.test()
async def test_undefined_size(dut):
    """mem_size = 3 is never decoded: outputs must still be X-free and issue no byte enables."""
    for rd, wr in ((1, 0), (0, 1)):
        for off in range(4):
            got = await drive(dut, size_code=3, mem_read=rd, mem_write=wr, addr=BASE + off,
                              rdata=0xFFFF_FFFF, store_data=0xFFFF_FFFF)
            assert got["be"] == 0 and got["load_data"] == 0 and got["misaligned"] == 0, got


@cocotb.test()
async def test_random(dut):
    """Random sizes, signedness, read/write, enable, addresses and data vs. the model."""
    for _ in range(3000):
        rw = random.choice(((1, 0), (0, 1), (0, 0)))
        await check(
            dut,
            size_name=random.choice(list(MEM_SIZES)),
            unsigned=random.getrandbits(1),
            mem_read=rw[0], mem_write=rw[1],
            enable=int(random.random() < 0.9),
            addr=random.getrandbits(32),
            store_data=random.getrandbits(32),
            rdata=random.getrandbits(32),
            err=int(random.random() < 0.1),
        )


@cocotb.test()
async def test_model_self_check(dut):
    """Sanity-check the struct packing against the widths in spec §8."""
    del dut  # model-only test
    assert struct_width(CTRL_FIELDS) == 28
    assert struct_width(DMEM_REQ_FIELDS) == 70
    assert struct_width(DMEM_RSP_FIELDS) == 34
    assert struct_pack(DMEM_REQ_FIELDS, valid=1) == 1 << 69
    assert struct_pack(CTRL_FIELDS, illegal=1) == 1
    word = struct_pack(DMEM_REQ_FIELDS, valid=1, we=0, be=0b1100, addr=0x8000_0002, wdata=0xDEAD_BEEF)
    assert struct_unpack(DMEM_REQ_FIELDS, word) == dict(valid=1, we=0, be=0b1100, addr=0x8000_0002, wdata=0xDEAD_BEEF)
