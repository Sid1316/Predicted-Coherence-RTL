"""What sim/tb_top.cpp should report for a program, from the Python model (docs/spec.md §9.2, §11).

model_run() steps rv_model.CoreModel the way the harness clocks rv_soc_sim:
the run ends at the cycle a store to tohost retires, the cycle the core
stops, or after max_cycles. Shared by tb/sim/test_tb_top.py and
scripts/run_asm.py.
"""

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))

from rv_model import STOP_CAUSES, CoreModel, SimMemory, retire_log_line  # noqa: E402

CAUSE_NAMES = {v: k for k, v in STOP_CAUSES.items()}


@dataclass
class ModelResult:
    code: int              # harness exit code (spec §11)
    cycles: int            # cycles after reset, including the last one
    lines: list[str]       # retire log (spec §9.2)
    console: bytes
    tohost: int | None     # tohost word, if it was written
    cause: str             # stop_cause_t name the core latched (STOP_NONE if it did not stop)


def model_run(image: dict[int, int] | None, tohost: int | None, max_cycles: int) -> ModelResult:
    m = CoreModel(SimMemory(image))
    m.reset()
    lines = []
    for cycle in range(1, max_cycles + 1):
        r = m.step()
        if r["valid"]:
            lines.append(retire_log_line(r, m.status))
        if tohost is not None and r["valid"] and r["mem_wmask"] and r["mem_addr"] == tohost & ~3:
            v = m.mem.word(tohost & ~3)
            return ModelResult(0 if v == 1 else 1, cycle, lines, bytes(m.mem.console), v,
                               CAUSE_NAMES[m.status])
        if m.halted:
            cause = CAUSE_NAMES[m.status]
            code = 4 if cause in ("STOP_ECALL", "STOP_EBREAK") else 3
            return ModelResult(code, cycle, lines, bytes(m.mem.console), None, cause)
    return ModelResult(2, max_cycles, lines, bytes(m.mem.console), None, CAUSE_NAMES[m.status])
