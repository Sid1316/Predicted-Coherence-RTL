"""Checks for the evaluation pipeline's own parsers (scripts/evaluate.py, scripts/vcd.py).

Usage: test_evaluate.py

The pipeline reads results from the text the runners print. A parser that
silently drops a line turns a failure into a missing item, and a missing item
into a pass. These checks feed each parser samples in the exact formats the
runners print, including failures and malformed input, and check that the
counts come out right. The runtime self-check (injected RTL bugs, stage
"mutants") covers the other direction: that real defects reach a parser at all.

Exit code: 0 if every check passed, 1 otherwise.
"""

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import evaluate as ev  # noqa: E402
from vcd import read_vcd, sample, to_int  # noqa: E402

checks = 0
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    if not ok:
        failures.append(name)
        print(f"  FAIL  {name}  {detail}")


PROGS_OUT = """\
  PASS  asm/t00_lui_addi             PASS tohost=00000001 cycles=109 exit=0
  PASS  asm/e05_bus_error            ERROR STOP_BUS_ERROR cycles=32 exit=3
  FAIL  asm/t04_branch               FAIL tohost=00000007 cycles=150 exit=1
    exit 1, expected 0
    retire log differs from the model at line 37 (see build/asm/t04_branch.dis):
      rtl   00000025 80000094 2e000ae3
      model 00000025 80000094 2e000ae3 x21 80000b88
  PASS  rv32ui/rv32ui-p-ma_data      ERROR STOP_MISALIGNED_DATA cycles=36 exit=3  waived: misaligned
Microseconds for one run through Dhrystone: 554
Dhrystones per Second:                      1804
tb_top: PASS tohost=00000001 cycles=299858 exit=0
  PASS  bench/dhrystone              PASS tohost=00000001 cycles=299858 exit=0

run_progs: 4/5 passed
"""


def test_parse_progs() -> None:
    items = ev.parse_progs(PROGS_OUT)
    check("progs: every PASS/FAIL line becomes an item", len(items) == 5, f"got {len(items)}")
    by = {i["name"]: i for i in items}
    by = {n: by.get(n, {}) for n in ("t00_lui_addi", "e05_bus_error", "t04_branch", "rv32ui-p-ma_data", "dhrystone")}
    check("progs: a FAIL is not ok", by["t04_branch"].get("ok") is False)
    check("progs: a FAIL keeps its problem lines", "line 37" in by["t04_branch"].get("problem", ""), by["t04_branch"].get("problem"))
    check("progs: cycles and exit code", by["t00_lui_addi"].get("cycles") == 109 and by["t00_lui_addi"].get("exit") == 0)
    check("progs: stop cause", by["e05_bus_error"].get("cause") == "STOP_BUS_ERROR")
    check("progs: waiver noticed", by["rv32ui-p-ma_data"].get("waived") is True and by["e05_bus_error"].get("waived") is False)
    check("progs: suite", by["rv32ui-p-ma_data"].get("suite") == "rv32ui")
    check("progs: console text before a result is kept", "Dhrystones per Second" in by["dhrystone"].get("console", ""))
    check("progs: console does not leak into the next item", by["t00_lui_addi"] != {} and "Dhrystone" not in by["t00_lui_addi"].get("console", ""))
    check("progs: empty output gives no items (and the stage then fails as 'no checks ran')",
          ev.parse_progs("run_progs: 0/0 passed\n") == [])


def test_bench_score() -> None:
    d = ev.bench_score("dhrystone", "Dhrystones per Second:                      1804\n")
    check("bench: DMIPS/MHz = Dhrystones/s / 1757", d.get("score") == round(1804 / 1757, 3), str(d))
    c = ev.bench_score("coremark", "Total ticks      : 721372\nIterations       : 1\n")
    check("bench: CoreMark/MHz = iterations * 1e6 / ticks", c.get("score") == round(1e6 / 721372, 3), str(c))
    check("bench: no score when the console has none", ev.bench_score("coremark", "") == {})


SYN_MD = """\
## Area of rv_core (yosys, pre-pack)

| Module | LUT4 | PFUMX | L6MUX21 | CCU2C | TRELLIS_DPR16X4 | TRELLIS_FF |
|---|---:|---:|---:|---:|---:|---:|
| **rv_core (flattened)** | 2163 | 517 | 223 | 95 | 32 | 100 |
| rv_alu (own cells) | 745 | 237 | 84 | 32 | 0 | 0 |

## Utilisation and Fmax (nextpnr-ecp5, post-pack)

| Variant | TRELLIS_COMB | TRELLIS_FF | TRELLIS_RAMW | DP16KD | Fmax (MHz) | Seeds |
|---|---:|---:|---:|---:|---:|---|
| core | 2203 (9%) | 651 (2%) | 32 (1%) | 0 (0%) | **41.3** | 41.3, 40.5, 40.0 |

### core (hierarchical Fmax 29.0 MHz)

| Stage | Logic (ns) | Routing (ns) | Total (ns) | Share |
|---|---:|---:|---:|---:|
| ALU | 3.57 | 3.87 | 7.44 | 22% |
| decode | 1.24 | 4.24 | 5.48 | 16% |
"""


def test_parse_syn() -> None:
    s = ev.parse_syn(SYN_MD)
    check("syn: module rows, bold markers stripped", s["modules"][0]["module"] == "rv_core (flattened)"
          and s["modules"][0]["LUT4"] == 2163 and len(s["modules"]) == 2, str(s["modules"]))
    v = s["variants"][0] if s["variants"] else {}
    check("syn: Fmax and seeds", v.get("fmax") == 41.3 and v.get("seeds") == [41.3, 40.5, 40.0], str(v))
    check("syn: utilisation with a percentage suffix", v.get("comb") == 2203 and v.get("lutram") == 32, str(v))
    p = s["paths"].get("core", {})
    check("syn: critical path stages under their heading", p.get("fmax_hier") == 29.0 and len(p.get("stages", [])) == 2
          and p["stages"][0]["total"] == 7.44, str(p))


VCD = """\
$timescale 1ns $end
$scope module TOP $end
 $var wire 1 ! clk_i $end
 $scope module rv_soc_sim $end
  $scope module u_core $end
   $var wire 1 ! clk_i $end
   $var wire 32 # pc [31:0] $end
   $var wire 1 $ rf_we $end
  $upscope $end
 $upscope $end
$upscope $end
$enddefinitions $end
#0
0!
bx #
0$
#5
1!
b10000000000000000000000000000000 #
#10
0!
1$
#15
1!
b10000000000000000000000000000100 #
"""


def test_vcd() -> None:
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "t.vcd"
        f.write_text(VCD, encoding="ascii")
        ts, ch = read_vcd(f, ["rv_soc_sim.u_core.clk_i", "rv_soc_sim.u_core.pc", "rv_soc_sim.u_core.rf_we",
                              "rv_soc_sim.u_core.missing"])
    check("vcd: timescale", ts == 1.0, str(ts))
    check("vcd: one code shared by two scopes reaches the wanted one",
          [v for _, v in ch["rv_soc_sim.u_core.clk_i"]] == ["0", "1", "0", "1"], str(ch["rv_soc_sim.u_core.clk_i"]))
    check("vcd: x before the first value", to_int(sample(ch["rv_soc_sim.u_core.pc"], 4)) is None)
    check("vcd: vector value", to_int(sample(ch["rv_soc_sim.u_core.pc"], 14)) == 0x8000_0000)
    check("vcd: value just before an edge", sample(ch["rv_soc_sim.u_core.rf_we"], 14) == "1"
          and sample(ch["rv_soc_sim.u_core.rf_we"], 9) == "0")
    check("vcd: a signal that is not in the file has no changes", ch["rv_soc_sim.u_core.missing"] == [])


def test_mutants_apply() -> None:
    """Every injected bug must still match exactly one RTL line (else it silently becomes 'no change')."""
    from eval_mutants import MUTANTS  # noqa: PLC0415
    names = [m.name for m in MUTANTS]
    check("mutants: names are unique", len(names) == len(set(names)))
    check("mutants: the null control is first", MUTANTS[0].file is None and MUTANTS[0].expect == "survive")
    for m in MUTANTS[1:]:
        n = (ROOT / m.file).read_text(encoding="utf-8").count(m.old)
        check(f"mutants: {m.name} matches exactly one line", n == 1, f"{n} matches in {m.file}")
        check(f"mutants: {m.name} changes the line", m.old != m.new)


def main() -> int:
    for fn in (test_parse_progs, test_bench_score, test_parse_syn, test_vcd, test_mutants_apply):
        fn()
    if failures:
        print(f"test_evaluate: {len(failures)} of {checks} checks FAILED")
        return 1
    print(f"test_evaluate: {checks}/{checks} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
