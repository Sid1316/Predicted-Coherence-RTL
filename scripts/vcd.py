"""Minimal VCD reader for the evaluation report's waveform image (scripts/eval_report.py).

read_vcd(path, wanted) -> (timescale_ns, {name: [(time, value_str), ...]})
  wanted: hierarchical names relative to the top scope, e.g. "rv_soc_sim.u_core.pc".
  Values are the raw VCD strings: "0"/"1"/"x"/"z" for 1-bit signals, the bit
  string for vectors (without the leading "b").

sample(changes, t) -> the value of a signal at time t (the last change at or before t).
"""

import bisect
from pathlib import Path

UNITS = {"s": 1e9, "ms": 1e6, "us": 1e3, "ns": 1.0, "ps": 1e-3, "fs": 1e-6}


def read_vcd(path: Path, wanted: list[str]) -> tuple[float, dict[str, list[tuple[int, str]]]]:
    scope: list[str] = []
    code_to_names: dict[str, list[str]] = {}
    timescale = 1.0
    changes: dict[str, list[tuple[int, str]]] = {w: [] for w in wanted}
    want = set(wanted)
    t = 0
    header = True
    pending_ts = False
    with open(path, encoding="ascii", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if header:
                tok = line.split()
                if pending_ts:
                    timescale = _ts(line)
                    pending_ts = False
                if tok[0] == "$timescale":
                    rest = " ".join(t for t in tok[1:] if t != "$end")
                    if rest:
                        timescale = _ts(rest)
                    else:
                        pending_ts = True
                elif tok[0] == "$scope":
                    scope.append(tok[2])
                elif tok[0] == "$upscope":
                    scope.pop()
                elif tok[0] == "$var":
                    code, name = tok[3], tok[4]
                    full = ".".join(scope[1:] + [name])      # drop the TOP scope
                    if full in want:
                        code_to_names.setdefault(code, []).append(full)
                elif tok[0] == "$enddefinitions":
                    header = False
                continue
            c = line[0]
            if c == "#":
                t = int(line[1:])
            elif c in "01xzXZ":
                for n in code_to_names.get(line[1:], ()):
                    changes[n].append((t, c.lower()))
            elif c in "bBrR":
                val, code = line[1:].split()
                for n in code_to_names.get(code, ()):
                    changes[n].append((t, val.lower()))
    return timescale, changes


def _ts(text: str) -> float:
    text = text.replace("$end", "").strip()
    num = "".join(ch for ch in text if ch.isdigit()) or "1"
    unit = "".join(ch for ch in text if ch.isalpha())
    return int(num) * UNITS.get(unit, 1.0)


def sample(changes: list[tuple[int, str]], t: int) -> str:
    if not changes:
        return "x"
    i = bisect.bisect_right([c[0] for c in changes], t) - 1
    return changes[i][1] if i >= 0 else "x"


def to_int(v: str) -> int | None:
    """Bit string to int, None if it has x/z."""
    if any(ch in "xz" for ch in v):
        return None
    return int(v, 2) if v else 0
