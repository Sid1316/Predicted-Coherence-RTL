"""RISCOF reference plugin: the project's Python RV32I model (docs/exec.md M5.3, §8).

Phase 1 reference, chosen because Spike has no native Windows build (exec.md
§8): tb/unit/rv_model.py's CoreModel, stepped by tb/sim/harness_model.py the
way the harness clocks the RTL (the run ends at the tohost store). It is not
independent of the RTL's authors; an independent reference (Spike on a Linux
CI runner) is to be added later.

For each test: build it with the same command as the DUT (arch_build.py),
run the image on the model, and write Reference.signature from the model's
memory at the end of the run.
"""

import logging
import sys
from pathlib import Path

from riscof.pluginTemplate import pluginTemplate

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import arch_build  # noqa: E402
from harness_model import model_run  # noqa: E402  (path set up by arch_build)
from rv_model import read_hex  # noqa: E402

logger = logging.getLogger()


class pymodel(pluginTemplate):
    __model__ = "pymodel"
    __version__ = "phase1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def initialise(self, suite, work_dir, archtest_env):
        self.work_dir = Path(work_dir)
        self.suite_dir = suite
        self.archtest_env = Path(archtest_env)

    def build(self, isa_yaml, platform_yaml):
        pass

    def runTests(self, testList):
        for name, entry in testList.items():
            wd = Path(entry["work_dir"])
            sig = wd / (self.name[:-1] + ".signature")
            b = arch_build.build(Path(entry["test_path"]), wd, entry["isa"], entry["macros"], self.archtest_env)
            r = model_run(read_hex(b.hexf), b.tohost, arch_build.MAX_CYCLES, arch_build.MEM_SIZE_BYTES)
            if r.code != 0:
                logger.warning(f"pymodel: {Path(name).name}: model ends with exit {r.code} ({r.cause})")
            sig.write_text(r.signature(b.sig_begin, b.sig_end), encoding="ascii", newline="\n")
