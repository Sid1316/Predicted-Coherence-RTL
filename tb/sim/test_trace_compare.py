"""Checks for scripts/trace_compare.py (docs/exec.md M6.1).

Usage: test_trace_compare.py            (make sim-test runs it)

Builds small traces by hand: a retire log and the same run as Spike would
log it (bootrom lines, byte/half/word stores at byte addresses, loads, x0),
then checks that equal traces compare equal and that each kind of
difference is reported at the right instruction.

Exit code: 0 if every check passed, 1 otherwise.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from trace_compare import TraceError, compare, parse_retire, parse_spike  # noqa: E402

RETIRE = """\
00000000 80000000 00000093 x1 00000000
00000001 80000004 02a00113 x2 0000002a
00000002 80000008 00001437 x8 00001000
00000003 8000000c 002401a3 mem W 80001000 8 2a2a2a2a
00000004 80000010 00241123 mem W 80001000 c 002a002a
00000005 80000014 00242423 mem W 80001008 f 0000002a
00000006 80000018 00042583 x11 2a2a002a mem R 80001000 f 2a2a002a
00000007 8000001c 00000013
00000008 80000020 00500013
00000009 80000024 00000073 HALT ECALL
"""

SPIKE = """\
core   0: 0x00001000 (0x00000297) auipc   t0, 0x0
core   0: 3 0x00001000 (0x00000297) x5  0x00001000
core   0: 3 0x00001004 (0x02028593) x11 0x00001020
core   0: 3 0x80000000 (0x00000093) x1  0x00000000
core   0: 3 0x80000004 (0x02a00113) x2  0x0000002a
core   0: 3 0x80000008 (0x00001437) x8  0x00001000
core   0: 3 0x8000000c (0x002401a3) mem 0x80001003 0x2a
core   0: 3 0x80000010 (0x00241123) mem 0x80001002 0x002a
core   0: 3 0x80000014 (0x00242423) mem 0x80001008 0x0000002a
core   0: 3 0x80000018 (0x00042583) x11 0x2a2a002a mem 0x80001000
core   0: 3 0x8000001c (0x00000013)
core   0: 3 0x80000020 (0x00500013) x0  0x00000005
core   0: 3 0x80000024 (0x00000073)
"""

failures = 0
checks = 0


def check(name, cond, msg=""):
    global failures, checks
    checks += 1
    if not cond:
        failures += 1
        print(f"  FAIL  {name}: {msg}")


def main() -> int:
    rtl = parse_retire(RETIRE)
    check("parse retire", len(rtl) == 10 and rtl[3].stores == {0x80001003: 0x2a}
          and rtl[4].stores == {0x80001002: 0x2a, 0x80001003: 0x00} and rtl[6].rd == 11, str(rtl[:7]))
    check("retire vs itself", compare(rtl, parse_retire(RETIRE)) is None)

    spike = parse_spike(SPIKE)
    check("spike drops bootrom and non-commit lines", len(spike) == 10 and spike[0].pc == 0x8000_0000,
          f"{len(spike)} steps, first pc {spike[0].pc:#x}" if spike else "no steps")
    check("spike x0 write ignored", spike[8].rd == 0)
    check("spike equals retire", compare(rtl, spike) is None, str(compare(rtl, spike)))

    # Each kind of difference, at instruction 4 or 6.
    def mutated(old, new):
        assert RETIRE.count(old) == 1, old
        return parse_retire(RETIRE.replace(old, new))

    cases = [
        ("rd value", mutated("x11 2a2a002a", "x11 2a2a002b"), 6, "rd/rd_wdata"),
        ("rd number", mutated("x11 2a2a002a", "x12 2a2a002a"), 6, "rd/rd_wdata"),
        ("store data", mutated("mem W 80001000 c 002a002a", "mem W 80001000 c 002b002a"), 4, "store bytes"),
        ("store mask", mutated("mem W 80001000 c 002a002a", "mem W 80001000 e 002a002a"), 4, "store bytes"),
        ("store missing", mutated("00242423 mem W 80001008 f 0000002a", "00242423"), 5, "store bytes"),
        ("pc", mutated("00000007 8000001c", "00000007 80000028"), 7, "pc"),
        ("insn", mutated("8000001c 00000013", "8000001c 00000033"), 7, "insn"),
    ]
    for name, other, at, field in cases:
        rep = compare(rtl, other) or ""
        check(f"mismatch: {name}", f"first mismatch at instruction {at}:" in rep and field in rep, rep)

    # Lengths.
    short = parse_retire("".join(RETIRE.splitlines(keepends=True)[:8]))
    check("reference shorter", "reference trace ends after 8" in (compare(rtl, short) or ""))
    check("rtl shorter", "RTL trace ends after 8" in (compare(short, rtl) or ""))
    check("rtl shorter, --allow-ref-extra", compare(short, rtl, allow_ref_extra=True) is None)

    # A read value is not compared by itself (the register it writes is).
    same = parse_retire(RETIRE.replace("mem R 80001000 f 2a2a002a", "mem R 80001000 f 00000000"))
    check("load data via rd only", compare(rtl, same) is None)

    try:
        parse_retire("not a retire line\n")
        check("bad line rejected", False, "no error")
    except TraceError:
        check("bad line rejected", True)

    print(f"test_trace_compare: {checks - failures}/{checks} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
