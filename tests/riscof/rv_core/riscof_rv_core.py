"""RISCOF DUT plugin: rv_core on the Verilator harness (docs/exec.md M5.3, docs/spec.md §11).

For each test: build it (tests/riscof/arch_build.py), run build/sim-2097152/Vrv_soc_sim
with +signature= +sig_begin= +sig_end= (begin/end_signature from nm), and leave
DUT.signature in the test's work directory for RISCOF to compare. The harness
log and the retire log are kept next to it. A test the harness does not end
with exit 0 (RVMODEL_HALT writes tohost = 1) still gets its signature, which
RISCOF then compares; the exit code is in run.log.
"""

import logging
import subprocess
import sys
from pathlib import Path

from riscof.pluginTemplate import pluginTemplate

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import arch_build  # noqa: E402

logger = logging.getLogger()


class rv_core(pluginTemplate):
    __model__ = "rv_core"
    __version__ = "phase1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        config = kwargs.get("config")
        if config is None:
            raise SystemExit("rv_core plugin: no configuration")
        self.isa_spec = str(Path(config["ispec"]).resolve())
        self.platform_spec = str(Path(config["pspec"]).resolve())
        # A simulator whose RAM matches arch_build.MEM_SIZE_BYTES (make riscof builds it).
        sim = arch_build.ROOT / "build" / f"sim-{arch_build.MEM_SIZE_BYTES}"
        exe = [p for p in (sim / "Vrv_soc_sim.exe", sim / "Vrv_soc_sim") if p.exists()]
        if not exe:
            raise SystemExit(f"rv_core plugin: no simulator in {sim} "
                             f"(make sim-build MEM_SIZE_BYTES={arch_build.MEM_SIZE_BYTES})")
        self.exe = exe[0]

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
            try:
                b = arch_build.build(Path(entry["test_path"]), wd, entry["isa"], entry["macros"], self.archtest_env)
                p = subprocess.run([str(self.exe), f"+hex={b.hexf.as_posix()}", f"+tohost={b.tohost:08x}",
                                    f"+max_cycles={arch_build.MAX_CYCLES}",
                                    f"+retire_log={(wd / 'retire.log').as_posix()}",
                                    f"+signature={sig.as_posix()}", f"+sig_begin={b.sig_begin:08x}",
                                    f"+sig_end={b.sig_end:08x}"], capture_output=True, timeout=600)
                (wd / "run.log").write_bytes(p.stdout + p.stderr)
                if p.returncode != 0:
                    logger.warning(f"rv_core: {Path(name).name}: harness exit {p.returncode}: "
                                   f"{p.stderr.decode(errors='replace').strip().splitlines()[-1:]}")
            except Exception as e:  # noqa: BLE001 - keep going, the test fails on its signature
                logger.error(f"rv_core: {Path(name).name}: {e}")
            if not sig.exists():
                sig.write_text("")   # RISCOF stops the whole run on a missing DUT signature
