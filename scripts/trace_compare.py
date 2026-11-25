"""Compare an RTL retire log with a reference trace, instruction by instruction (docs/exec.md M6.1, docs/spec.md §9.2).

Usage: trace_compare.py <rtl.retire.log> <reference> [--ref-format retire|spike] [--context N]
                        [--allow-ref-extra]

Both traces are normalized to the fields spec §9.2 says are compared:
  pc, insn, rd and rd_wdata (no entry for x0 or no write), and for stores the
  bytes written (address -> value), so a reference that logs a store as an
  SB at a byte address and the RTL's word-aligned, lane-placed form compare
  equal. Loads are compared through the register they write.

Reference formats:
  retire  this project's retire log (spec §9.2), e.g. from the Python model
          (tb/sim/harness_model.py) or another RTL run
  spike   Spike's --log-commits output: "core 0: <priv> 0x<pc> (0x<insn>)
          [x<n> 0x<val>] [mem 0x<addr> [0x<data>]]". Instructions with a PC
          below MEM_BASE (Spike's bootrom) are dropped. The store data width
          is taken from the number of hex digits (2/4/8). [Not yet checked
          against a real Spike log: Spike has no Windows build; it runs in CI
          later, exec.md §8.]

--allow-ref-extra: the reference may go on after the RTL trace ends (Spike
keeps running briefly after the tohost write that ends the RTL run).

Prints PASS or the first mismatch with the preceding instructions for context.
Exit code: 0 if the traces match, 1 if they differ, 2 on a usage or parse error.
"""

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

MEM_BASE = 0x8000_0000
MASK32 = 0xFFFF_FFFF

RETIRE = re.compile(
    r"^(?P<order>[0-9a-f]{8}) (?P<pc>[0-9a-f]{8}) (?P<insn>[0-9a-f]{8})"
    r"(?: x(?P<rd>\d+) (?P<rdw>[0-9a-f]{8}))?"
    r"(?: mem W (?P<wa>[0-9a-f]{8}) (?P<wm>[0-9a-f]) (?P<wd>[0-9a-f]{8}))?"
    r"(?: mem R (?P<ra>[0-9a-f]{8}) (?P<rm>[0-9a-f]) (?P<rdd>[0-9a-f]{8}))?"
    r"(?: (?P<stop>HALT|TRAP) (?P<cause>[A-Z_]+))?$")
SPIKE = re.compile(r"^core\s+\d+:\s+\d\s+0x(?P<pc>[0-9a-fA-F]+)\s+\(0x(?P<insn>[0-9a-fA-F]+)\)(?P<rest>.*)$")
SPIKE_REG = re.compile(r"\bx(\d+)\s+0x([0-9a-fA-F]+)")
SPIKE_MEM = re.compile(r"\bmem\s+0x([0-9a-fA-F]+)(?:\s+0x([0-9a-fA-F]+))?")


class TraceError(Exception):
    pass


@dataclass
class Step:
    """One retired instruction, in the compared fields."""
    pc: int
    insn: int
    rd: int = 0                     # 0: no register written
    rd_wdata: int = 0
    stores: dict[int, int] = field(default_factory=dict)   # byte address -> byte
    line: str = ""                  # the source line, for reports

    def key(self):
        return (self.pc, self.insn, self.rd, self.rd_wdata if self.rd else 0, tuple(sorted(self.stores.items())))

    def describe(self) -> str:
        s = f"pc={self.pc:08x} insn={self.insn:08x}"
        if self.rd:
            s += f" x{self.rd}={self.rd_wdata:08x}"
        if self.stores:
            s += " stores " + " ".join(f"[{a:08x}]={b:02x}" for a, b in sorted(self.stores.items()))
        return s


def parse_retire(text: str) -> list[Step]:
    steps = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        m = RETIRE.match(line.strip())
        if not m:
            raise TraceError(f"line {n}: not a retire-log line: {line!r}")
        s = Step(int(m["pc"], 16), int(m["insn"], 16), line=line.strip())
        if m["rd"] is not None and int(m["rd"]) != 0:
            s.rd, s.rd_wdata = int(m["rd"]), int(m["rdw"], 16)
        if m["wa"] is not None:
            addr, mask, data = int(m["wa"], 16), int(m["wm"], 16), int(m["wd"], 16)
            for lane in range(4):
                if mask >> lane & 1:
                    s.stores[addr + lane] = data >> (8 * lane) & 0xFF
        steps.append(s)
    return steps


def parse_spike(text: str) -> list[Step]:
    steps = []
    for line in text.splitlines():
        m = SPIKE.match(line.strip())
        if not m:
            continue                # Spike prints other lines too (warnings, the bootrom banner)
        pc = int(m["pc"], 16) & MASK32
        if pc < MEM_BASE:
            continue                # bootrom
        s = Step(pc, int(m["insn"], 16) & MASK32, line=line.strip())
        rest = m["rest"]
        r = SPIKE_REG.search(rest)
        if r and int(r[1]) != 0:
            s.rd, s.rd_wdata = int(r[1]), int(r[2], 16) & MASK32
        mm = SPIKE_MEM.search(rest)
        if mm and mm[2] is not None:            # address and data: a store
            addr, digits = int(mm[1], 16) & MASK32, mm[2]
            size = {2: 1, 4: 2, 8: 4}.get(len(digits))
            if size is None:
                raise TraceError(f"store data width {len(digits)} hex digits not understood: {line!r}")
            data = int(digits, 16)
            for i in range(size):
                s.stores[addr + i] = data >> (8 * i) & 0xFF
        steps.append(s)
    return steps


def compare(rtl: list[Step], ref: list[Step], context: int = 3, allow_ref_extra: bool = False) -> str | None:
    """None if the traces match, else a report of the first difference."""
    for i, (a, b) in enumerate(zip(rtl, ref)):
        if a.key() != b.key():
            lines = [f"first mismatch at instruction {i}:"]
            for j in range(max(0, i - context), i):
                lines.append(f"      {j:6d}  {rtl[j].describe()}")
            lines.append(f"  rtl {i:6d}  {a.describe()}")
            lines.append(f"  ref {i:6d}  {b.describe()}")
            diffs = []
            if a.pc != b.pc:
                diffs.append("pc")
            if a.insn != b.insn:
                diffs.append("insn")
            if (a.rd, a.rd_wdata) != (b.rd, b.rd_wdata):
                diffs.append("rd/rd_wdata")
            if a.stores != b.stores:
                diffs.append("store bytes")
            lines.append(f"  differs in: {', '.join(diffs)}")
            return "\n".join(lines)
    if len(rtl) > len(ref):
        return f"reference trace ends after {len(ref)} instructions; RTL goes on: {rtl[len(ref)].describe()}"
    if len(ref) > len(rtl) and not allow_ref_extra:
        return f"RTL trace ends after {len(rtl)} instructions; reference goes on: {ref[len(rtl)].describe()}"
    return None


def load(path: Path, fmt: str) -> list[Step]:
    text = path.read_text(encoding="ascii", errors="replace")
    return parse_retire(text) if fmt == "retire" else parse_spike(text)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("rtl", type=Path)
    ap.add_argument("reference", type=Path)
    ap.add_argument("--ref-format", choices=["retire", "spike"], default="retire")
    ap.add_argument("--context", type=int, default=3)
    ap.add_argument("--allow-ref-extra", action="store_true")
    args = ap.parse_args()
    try:
        rtl = load(args.rtl, "retire")
        ref = load(args.reference, args.ref_format)
    except (OSError, TraceError) as e:
        print(f"trace_compare: {e}", file=sys.stderr)
        return 2
    report = compare(rtl, ref, args.context, args.allow_ref_extra)
    if report:
        print(f"trace_compare: FAIL ({args.rtl.name} vs {args.reference.name})\n{report}")
        return 1
    print(f"trace_compare: PASS, {len(rtl)} instructions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
