"""Evaluation pipeline: run every check on the core, collect the results, render a report.

Usage: evaluate.py [--profile quick|full] [--syn] [--no-mutants] [--jobs N] [--random-seeds N]
       evaluate.py --report-only <run directory>     (re-render an earlier run)
       evaluate.py --only-mutant <name>              (inject one bug, run every check layer on it)

Stages (each records pass/fail, duration, counts and metrics; logs are kept):
  env        scripts/check_env.sh: tools found and their versions
  lint       Verilator -Wall on rtl/ with rv_core as top
  unit       cocotb unit tests on Icarus, per block and per test (JUnit XML)
  sim_build  the Verilator simulator (rv_soc_sim + tb_top.cpp)
  harness    tb/sim tests: harness vs. the Python model, trace compare, stats
  asm, c     directed tests and C programs, each checked against its header and
             replayed on the model (every retire-log line must match)
  rv32ui     riscv-tests, with the documented waivers
  riscof     riscv-arch-test rv32i_m/I (full profile)
  random     random programs vs. the model, with instruction coverage
  bench      Dhrystone, CoreMark, Embench vs. the model, scores and profile (full)
  syn        ECP5 area, Fmax and critical path, read from syn/reports/ (full;
             --syn reruns synthesis first, which takes several minutes)
  waves      a waveform of one program (sw/asm/t04_branch) for the report
  mutants    self-check of the pipeline: injected RTL bugs must be caught, the
             unchanged design and a known-invisible bug must not be
             (scripts/eval_mutants.py)

Profiles (times measured with 8 jobs on the development PC):
  quick (about 14 min): everything except riscof, bench and syn; 50 random
        seeds; each mutant stops at the first check layer that catches it.
  full  (about 37 min): every stage; 200 random seeds; every mutant runs every
        layer (lint, asm, c, rv32ui, 20 random seeds) for the full matrix.

Output: build/eval/<run id>/ with results.json, logs/, img/*.png,
report.html (one self-contained page) and report.md; a copy of the report
in build/eval/latest/; one line per run appended to build/eval/history.jsonl.

A stage that ran no checks counts as failed, not passed: zero tests is not a
pass. Exit code: 0 if every stage passed, 1 otherwise.
"""

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from eval_mutants import MUTANTS, Mutant  # noqa: E402

EVAL = ROOT / "build" / "eval"
IS_WIN = os.name == "nt"
PY = sys.executable

PROG_LINE = re.compile(r"^\s+(PASS|FAIL)\s+(\w[\w.-]*)/(\S+)\s+(.*)$")
RISCOF_LINE = re.compile(r"^\s+(PASS|FAIL)\s+(\S+?)(?::|\s+\()(.*)$")
CHECKS_LINE = re.compile(r"^(test_\w+): (?:all (\d+) checks passed|(\d+)/(\d+) checks passed|(\d+) of (\d+) checks FAILED)")
ENV_LINE = re.compile(r"^\s+\[(?: ok |FAIL| -- )\]\s+(.+?)\s{2,}(.*)$")


# ---------------------------------------------------------------------------
# Running commands
# ---------------------------------------------------------------------------

def tool_path() -> str:
    """PATH with the project's Windows tool folders added if they exist (README Setup)."""
    path = os.environ.get("PATH", "")
    if not IS_WIN:
        return path
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    extra = [Path("C:/msys64/ucrt64/bin"), local / "Microsoft" / "WinGet" / "Links",
             *sorted((local / "Programs").glob("xpack-riscv-none-elf-gcc-*/bin"))]
    have = {p.lower().rstrip("\\/") for p in path.split(os.pathsep)}
    add = [str(p) for p in extra if p.is_dir() and str(p).lower().rstrip("\\/") not in have]
    return os.pathsep.join([path, *add])


ENV = {**os.environ, "PATH": tool_path(), "PYTHONIOENCODING": "utf-8"}


def make_cmd() -> list[str]:
    exe = shutil.which("make", path=ENV["PATH"])
    if exe is None:
        raise SystemExit("evaluate: make not found (README Setup step 1)")
    return [exe, "--no-print-directory", "-C", str(ROOT)]


def run(cmd: list[str], log: Path, timeout: int = 3600) -> tuple[int, str]:
    """Run a command, save stdout+stderr to log, return (exit code, output)."""
    log.parent.mkdir(parents=True, exist_ok=True)
    start = time.time()
    try:
        p = subprocess.run(cmd, cwd=ROOT, env=ENV, capture_output=True, timeout=timeout)
        out = (p.stdout + p.stderr).decode("utf-8", errors="replace").replace("\r\n", "\n")
        code = p.returncode
    except subprocess.TimeoutExpired as e:
        out = ((e.stdout or b"") + (e.stderr or b"")).decode("utf-8", errors="replace")
        out += f"\nevaluate: TIMEOUT after {timeout} s\n"
        code = 124
    log.write_text(f"$ {' '.join(map(str, cmd))}\n# exit {code}, {time.time() - start:.1f} s\n\n{out}",
                   encoding="utf-8", newline="\n")
    return code, out


# ---------------------------------------------------------------------------
# Stage records
# ---------------------------------------------------------------------------

@dataclass
class Stage:
    name: str
    title: str
    status: str = "skip"            # pass | fail | skip
    seconds: float = 0.0
    passed: int = 0                 # checks that passed
    total: int = 0                  # checks that ran
    summary: str = ""
    log: str = ""                   # relative to the run directory
    metrics: dict = field(default_factory=dict)
    items: list = field(default_factory=list)


class Pipeline:
    def __init__(self, out: Path, jobs: int):
        self.out = out
        self.jobs = jobs
        self.stages: list[Stage] = []
        self.logs = out / "logs"
        self.sim_exe = ROOT / "build" / "sim" / ("Vrv_soc_sim.exe" if IS_WIN else "Vrv_soc_sim")

    def stage(self, name: str, title: str):
        st = Stage(name, title, log=f"logs/{name}.log")
        self.stages.append(st)
        print(f"[eval] {name:10s} {title} ...", flush=True)
        st._t0 = time.time()  # type: ignore[attr-defined]
        return st

    def done(self, st: Stage, ok: bool, summary: str) -> None:
        st.seconds = round(time.time() - st._t0, 1)  # type: ignore[attr-defined]
        if ok and st.total == 0 and st.name not in ("sim_build", "waves", "syn"):
            ok, summary = False, f"no checks ran ({summary})"
        st.status = "pass" if ok else "fail"
        st.summary = summary
        mark = "PASS" if ok else "FAIL"
        print(f"[eval] {st.name:10s} {mark}  {summary}  ({st.seconds:.0f} s)", flush=True)

    def skip(self, name: str, title: str, why: str) -> None:
        self.stages.append(Stage(name, title, status="skip", summary=why))
        print(f"[eval] {name:10s} skip  {why}", flush=True)

    def get(self, name: str) -> Stage | None:
        return next((s for s in self.stages if s.name == name), None)

    # -- stages ------------------------------------------------------------

    def env(self) -> None:
        st = self.stage("env", "Tools and versions")
        code, out = run(["bash", str(ROOT / "scripts" / "check_env.sh")], self.logs / "env.log")
        for line in out.splitlines():
            m = ENV_LINE.match(line)
            if m:
                state = "ok" if "[ ok ]" in line else "missing" if "[FAIL]" in line else "optional-missing"
                st.items.append({"tool": m[1].strip(), "state": state, "version": m[2].strip()})
        req = [i for i in st.items if i["state"] != "optional-missing"]
        st.total, st.passed = len(req), sum(i["state"] == "ok" for i in req)
        self.done(st, code == 0, f"{st.passed}/{st.total} required tools found")

    def lint(self) -> None:
        st = self.stage("lint", "Verilator -Wall lint (rv_core as top)")
        code, out = run([*make_cmd(), "lint"], self.logs / "lint.log")
        warnings = len(re.findall(r"^%(Warning|Error)", out, re.M))
        m = re.search(r"lint: clean \((\d+) files\)", out)
        st.metrics = {"files": int(m[1]) if m else 0, "warnings": warnings}
        st.total, st.passed = 1, int(code == 0 and warnings == 0)
        self.done(st, code == 0 and warnings == 0, f"{st.metrics['files']} files, {warnings} warnings")

    def unit(self) -> None:
        st = self.stage("unit", "cocotb unit tests on Icarus")
        unit_dir = ROOT / "build" / "unit"
        if unit_dir.exists():
            shutil.rmtree(unit_dir)          # only this run's results.xml files
        code, out = run([PY, str(ROOT / "tb" / "unit" / "run_unit.py")], self.logs / "unit.log", timeout=5400)
        # run_unit's own summary is the authority; the JUnit XML adds per-test detail and must agree.
        claimed = {m[2]: int(m[4]) for m in re.finditer(r"^\s+(PASS|FAIL)\s+(\w+)\s+(\d+)/(\d+) passed$", out, re.M)}
        blocks: dict[str, dict] = {}
        for xml in sorted(unit_dir.glob("*/results*.xml")):
            block = xml.parent.name
            b = blocks.setdefault(block, {"block": block, "tests": 0, "failed": 0, "skipped": 0,
                                          "seconds": 0.0, "cases": []})
            for tc in ET.parse(xml).getroot().iter("testcase"):
                failed = tc.find("failure") is not None or tc.find("error") is not None
                skipped = tc.find("skipped") is not None
                secs = float(tc.get("time", "0") or 0)
                b["tests"] += 1
                b["failed"] += failed
                b["skipped"] += skipped
                b["seconds"] += secs
                b["cases"].append({"name": tc.get("name"), "status": "fail" if failed else "skip" if skipped
                                   else "pass", "seconds": round(secs, 3),
                                   "sim_ns": float(tc.get("sim_time_ns", "0") or 0)})
        st.items = list(blocks.values())
        st.total = sum(b["tests"] for b in st.items)
        st.passed = sum(b["tests"] - b["failed"] - b["skipped"] for b in st.items)
        found = {b["block"]: b["tests"] for b in st.items}
        mismatch = {k: (claimed.get(k), found.get(k)) for k in set(claimed) | set(found) if claimed.get(k) != found.get(k)}
        st.metrics = {"blocks": len(st.items), "xml_vs_summary_mismatch": mismatch}
        ok = code == 0 and st.passed == st.total and len(st.items) > 0 and not mismatch
        extra = f"; result files disagree with run_unit's summary for {sorted(mismatch)}" if mismatch else ""
        self.done(st, ok, f"{st.passed}/{st.total} tests in {len(st.items)} blocks{extra}")

    def sim_build(self) -> bool:
        st = self.stage("sim_build", "Verilator simulator build")
        code, _ = run([*make_cmd(), "sim-build"], self.logs / "sim_build.log")
        st.total, st.passed = 1, int(code == 0 and self.sim_exe.exists())
        self.done(st, bool(st.passed), str(self.sim_exe.relative_to(ROOT)))
        return bool(st.passed)

    def harness(self) -> None:
        st = self.stage("harness", "Harness and tool tests vs. the Python model")
        code, out = run([*make_cmd(), "sim-test"], self.logs / "harness.log")
        for line in out.splitlines():
            m = CHECKS_LINE.match(line)
            if m:
                if m[2]:
                    n, f = int(m[2]), 0
                elif m[3]:
                    n, f = int(m[4]), int(m[4]) - int(m[3])
                else:
                    n, f = int(m[6]), int(m[5])
                st.items.append({"suite": m[1], "checks": n, "failed": f})
        st.total = sum(i["checks"] for i in st.items)
        st.passed = st.total - sum(i["failed"] for i in st.items)
        self.done(st, code == 0 and st.passed == st.total,
                  ", ".join(f"{i['suite']} {i['checks'] - i['failed']}/{i['checks']}" for i in st.items))

    def progs(self, name: str, title: str, suites: list[str], verbose: bool = False) -> Stage:
        st = self.stage(name, title)
        cmd = [PY, str(ROOT / "scripts" / "run_progs.py"), "--exe", str(self.sim_exe), "-j", str(self.jobs),
               *(["-v"] if verbose else []), *suites]
        code, out = run(cmd, self.logs / f"{name}.log", timeout=7200)
        st.items = parse_progs(out)
        st.total, st.passed = len(st.items), sum(i["ok"] for i in st.items)
        self.done(st, code == 0 and st.passed == st.total, f"{st.passed}/{st.total} programs")
        return st

    def riscof(self) -> None:
        st = self.stage("riscof", "riscv-arch-test rv32i_m/I through RISCOF")
        code, out = run([*make_cmd(), "riscof"], self.logs / "riscof.log", timeout=7200)
        for line in out.splitlines():
            m = re.match(r"^\s+(PASS|FAIL)\s+(\S+?)(?::\s+(.*)|\s+\((\d+) signature words, (\d+) instructions traced\))$",
                         line)
            if m:
                test = m[2].rsplit("/", 1)[-1].removesuffix(".S")
                st.items.append({"name": test, "ok": m[1] == "PASS", "problem": m[3] or "",
                                 "sig_words": int(m[4] or 0), "insns": int(m[5] or 0)})
        st.total, st.passed = len(st.items), sum(i["ok"] for i in st.items)
        self.done(st, code == 0 and st.passed == st.total, f"{st.passed}/{st.total} arch tests")

    def random(self, seeds: int) -> None:
        st = self.stage("random", f"Random programs vs. the model ({seeds} seeds)")
        js = self.out / "random.json"
        code, _ = run([PY, str(ROOT / "scripts" / "run_random.py"), "--exe", str(self.sim_exe), "--seeds", str(seeds),
                       "-j", str(self.jobs), "--json", str(js)], self.logs / "random.log", timeout=7200)
        data = json.loads(js.read_text()) if js.exists() else {}
        st.metrics = data
        st.total = data.get("programs", 0)
        st.passed = st.total - len(data.get("failed", []))
        cov = sum(1 for v in data.get("per_instruction", {}).values() if v)
        self.done(st, code == 0 and st.passed == st.total,
                  f"{st.passed}/{st.total} programs match, {data.get('instructions', 0):,} instructions, "
                  f"{cov}/40 instructions covered")

    def bench(self) -> None:
        st = self.progs("bench", "Benchmarks vs. the model, scores and profile", ["bench"], verbose=True)
        t0 = time.time()
        from stats import analyse  # noqa: PLC0415  (needs the tools on PATH, set below)
        os.environ["PATH"] = ENV["PATH"]
        for item in st.items:
            log = ROOT / "build" / "bench" / f"{item['name']}.retire.log"
            elf = log.with_name(item["name"] + ".elf")
            if log.exists() and elf.exists():
                s = analyse(item["name"], elf, log)
                item["stats"] = stats_dict(s)
            item.update(bench_score(item["name"], item.get("console", "")))
        st.metrics = {"stats_seconds": round(time.time() - t0, 1)}

    def syn(self, rerun: bool, seeds: int) -> None:
        st = self.stage("syn", "ECP5 synthesis: area, Fmax, critical path")
        if rerun:
            code, _ = run([PY, str(ROOT / "scripts" / "syn.py"), "--seeds", str(seeds)], self.logs / "syn.log",
                          timeout=7200)
            if code != 0:
                self.done(st, False, "make syn failed")
                return
        else:
            (self.logs / "syn.log").write_text("read from syn/reports/summary.md (run with --syn to redo)\n")
        summary = ROOT / "syn" / "reports" / "summary.md"
        if not summary.exists():
            self.done(st, False, "syn/reports/summary.md not found (run make syn)")
            return
        st.metrics = parse_syn(summary.read_text(encoding="utf-8"))
        st.metrics["source"] = "rerun" if rerun else f"syn/reports (dated {datetime.fromtimestamp(summary.stat().st_mtime):%Y-%m-%d %H:%M})"
        fmax = {v["variant"]: v["fmax"] for v in st.metrics.get("variants", [])}
        st.total = st.passed = len(fmax)
        self.done(st, bool(fmax), ", ".join(f"{k} {v:.1f} MHz" for k, v in fmax.items()))

    def waves(self, prog: str = "t04_branch") -> None:
        st = self.stage("waves", f"Waveform of sw/asm/{prog}")
        vcd = self.out / f"{prog}.vcd"
        code, out = run([PY, str(ROOT / "scripts" / "run_progs.py"), "--exe", str(self.sim_exe), "--waves",
                         str(vcd), prog], self.logs / "waves.log")
        if vcd.exists() and vcd.suffix == ".vcd":
            st.metrics = {"vcd": vcd.name, "program": prog, "bytes": vcd.stat().st_size}
        self.done(st, code == 0 and vcd.exists(), f"{vcd.name}, {vcd.stat().st_size // 1024 if vcd.exists() else 0} KiB")

    def mutants(self, layers: list[str], random_seeds: int, first_catch: bool,
                selected: list[Mutant] | None = None) -> None:
        """first_catch: stop a mutant at the first layer that catches it (quick); else run every layer (matrix).
        selected: only these mutants (--only-mutant); default all of scripts/eval_mutants.py."""
        st = self.stage("mutants", "Self-check: injected bugs must be caught")
        rtl_files = [l.strip() for l in (ROOT / "rtl" / "rtl.f").read_text().splitlines()
                     if l.strip() and not l.strip().startswith("//")]
        mdir = self.out / "mutants"
        for m in selected or MUTANTS:
            t0 = time.time()
            print(f"[eval]   mutant {m.name} ...", flush=True)
            item = {"name": m.name, "what": m.what, "expect": m.expect, "why": m.why, "file": m.file,
                    "layers": {}, "build": "ok"}
            src_dir = mdir / m.name / "rtl"
            src_dir.mkdir(parents=True, exist_ok=True)
            for rel in rtl_files:
                text = (ROOT / rel).read_text(encoding="utf-8")
                if m.file == rel:
                    if text.count(m.old) != 1:
                        raise SystemExit(f"evaluate: mutant {m.name}: {m.old!r} found {text.count(m.old)} times in "
                                         f"{rel}, expected once (update scripts/eval_mutants.py)")
                    text = text.replace(m.old, m.new)
                (src_dir / Path(rel).name).write_text(text, encoding="utf-8", newline="\n")
            sim_dir = mdir / m.name / "sim"
            exe = sim_dir / self.sim_exe.name
            srcs = " ".join((src_dir / Path(r).name).as_posix() for r in rtl_files)
            # Lint is a check layer of its own; the simulator is built with -Wno-fatal so that a
            # lint-visible bug still reaches the simulation layers.
            code, out = run([*make_cmd(), "lint", f"RTL_SRCS={srcs}"], self.logs / f"mutant_{m.name}_lint.log")
            n_warn = len(re.findall(r"^%(Warning|Error)", out, re.M))
            item["layers"]["lint"] = {"killed": code != 0, "failing": n_warn, "of": 1,
                                      "first": re.findall(r"^%(?:Warning|Error)-(\w+)", out, re.M)[:3]}
            code, _ = run([*make_cmd(), "sim-build", f"RTL_SRCS={srcs}", f"SIM_DIR={sim_dir.as_posix()}",
                           "SIM_EXTRA=-Wno-fatal"], self.logs / f"mutant_{m.name}_build.log")
            if code != 0 or not exe.exists():
                item["build"] = "failed"
            else:
                for layer in layers:
                    if first_catch and any(v["killed"] for v in item["layers"].values()):
                        break
                    log = self.logs / f"mutant_{m.name}_{layer}.log"
                    if layer == "random":
                        js = mdir / m.name / "random.json"
                        c, _ = run([PY, str(ROOT / "scripts" / "run_random.py"), "--exe", str(exe), "--seeds",
                                    str(random_seeds), "-j", str(self.jobs), "--no-save", "--json", str(js)], log)
                        data = json.loads(js.read_text()) if js.exists() else {}
                        failing = data.get("failed", [])
                        item["layers"][layer] = {"killed": c != 0, "failing": len(failing),
                                                 "of": data.get("programs", 0), "first": failing[:3]}
                    else:
                        c, out = run([PY, str(ROOT / "scripts" / "run_progs.py"), "--exe", str(exe), "-j",
                                      str(self.jobs), layer], log, timeout=3600)
                        res = parse_progs(out)
                        failing = [r["name"] for r in res if not r["ok"]]
                        item["layers"][layer] = {"killed": c != 0, "failing": len(failing), "of": len(res),
                                                 "first": failing[:3]}
            item["killed"] = item["build"] == "ok" and any(v["killed"] for v in item["layers"].values())
            item["ok"] = item["build"] == "ok" and (item["killed"] == (m.expect == "kill"))
            item["seconds"] = round(time.time() - t0, 1)
            st.items.append(item)
            state = "BUILD FAILED" if item["build"] != "ok" else "KILLED" if item["killed"] else "survived"
            by = [k for k, v in item["layers"].items() if v["killed"]]
            print(f"[eval]   mutant {m.name}: {state}{' by ' + ', '.join(by) if by else ''} "
                  f"({'as expected' if item['ok'] else 'NOT AS EXPECTED'}, {item['seconds']:.0f} s)", flush=True)
            shutil.rmtree(sim_dir, ignore_errors=True)     # 30+ MB of Verilator output each
        real = [i for i in st.items if i["expect"] == "kill"]
        killed = sum(i["killed"] for i in real)
        st.total, st.passed = len(st.items), sum(i["ok"] for i in st.items)
        st.metrics = {"layers": ["lint", *layers], "random_seeds": random_seeds if "random" in layers else 0,
                      "first_catch": first_catch,
                      "mutation_score": round(100 * killed / len(real), 1) if real else 0.0,
                      "killed": killed, "killable": len(real)}
        self.done(st, st.passed == st.total,
                  f"{killed}/{len(real)} injected bugs caught; control and equivalent mutant "
                  f"{'behaved' if all(i['ok'] for i in st.items if i['expect'] == 'survive') else 'DID NOT behave'} "
                  f"as expected")


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def parse_progs(out: str) -> list[dict]:
    """PASS/FAIL lines of run_progs.py, with the console text shown before each (with -v)."""
    items, console = [], []
    lines = out.splitlines()
    for i, line in enumerate(lines):
        m = PROG_LINE.match(line)
        if not m:
            if not line.startswith("tb_top:") and not line.startswith("run_progs:"):
                console.append(line)
            continue
        rest = m[4]
        problem = ""
        if m[1] == "FAIL":     # the problem lines follow, indented
            follow = []
            for nxt in lines[i + 1:]:
                if PROG_LINE.match(nxt) or nxt.startswith("run_progs:"):
                    break
                follow.append(nxt.strip())
            problem = " / ".join(x for x in [rest, *follow] if x)[:400]
        cyc = re.search(r"cycles=(\d+)", rest)
        ex = re.search(r"exit=(\d+)", rest)
        cause = re.search(r"\b(STOP_\w+)", rest)
        items.append({"suite": m[2], "name": m[3], "ok": m[1] == "PASS", "cycles": int(cyc[1]) if cyc else None,
                      "exit": int(ex[1]) if ex else None, "cause": cause[1] if cause else None,
                      "waived": "waiv" in rest.lower(), "result": rest[:200], "problem": problem,
                      "console": "\n".join(console[-40:])})
        console = []
    return items


def stats_dict(s) -> dict:
    pct = s.pct
    return {
        "instructions": s.insns,
        "mix": {k: round(pct(v), 2) for k, v in s.classes.items()},
        "branch_taken": round(pct(s.br_taken, s.br_taken + s.br_not), 1),
        "backward_taken": round(pct(s.br_bwd_taken, s.br_bwd), 1),
        "forward_taken": round(pct(s.br_fwd_taken, s.br_fwd), 1),
        "load_use": round(pct(s.load_use), 2),
        "load_use_of_loads": round(pct(s.load_use, s.classes["load"]), 1),
        "raw": {str(d): round(pct(s.raw[d]), 1) for d in (1, 2, 3)},
        "muldiv": round(pct(s.in_muldiv), 1),
        "text": s.text, "data": s.data, "stack": s.stack,
    }


def bench_score(name: str, console: str) -> dict:
    """Scores from the benchmark's own console output, at a notional 1 MHz clock (CPI 1)."""
    if name == "dhrystone":
        m = re.search(r"Dhrystones per Second:\s+(\d+)", console)
        if m:
            return {"score": round(int(m[1]) / 1757, 3), "score_unit": "DMIPS/MHz"}
    if name == "coremark":
        t, it = re.search(r"Total ticks\s*:\s*(\d+)", console), re.search(r"Iterations\s*:\s*(\d+)", console)
        if t and it:
            return {"score": round(int(it[1]) * 1e6 / int(t[1]), 3), "score_unit": "CoreMark/MHz",
                    "measured_cycles": int(t[1])}
    m = re.search(r"(\d+) cycles", console)
    return {"measured_cycles": int(m[1])} if m else {}


def md_tables(text: str) -> list[tuple[str, list[list[str]]]]:
    """Every markdown table with the nearest heading above it."""
    out, heading, rows = [], "", []
    for line in text.splitlines() + [""]:
        if line.startswith("#"):
            heading = line.lstrip("# ").strip()
        if line.startswith("|"):
            cells = [c.strip().strip("*") for c in line.strip().strip("|").split("|")]
            if not all(re.fullmatch(r":?-+:?", c) for c in cells):
                rows.append(cells)
        elif rows:
            out.append((heading, rows))
            rows = []
    return out


def num(s: str) -> float:
    m = re.search(r"-?[\d,]*\.?\d+", s)
    return float(m[0].replace(",", "")) if m else 0.0


def parse_syn(text: str) -> dict:
    res: dict = {"modules": [], "variants": [], "paths": {}}
    for heading, rows in md_tables(text):
        head, body = rows[0], rows[1:]
        if head[0] == "Module":
            for r in body:
                res["modules"].append({"module": r[0], **{h: int(num(c)) for h, c in zip(head[1:], r[1:])}})
        elif head[0] == "Variant":
            for r in body:
                d = dict(zip(head, r))
                res["variants"].append({"variant": r[0], "comb": int(num(d["TRELLIS_COMB"])),
                                        "ff": int(num(d["TRELLIS_FF"])), "lutram": int(num(d["TRELLIS_RAMW"])),
                                        "bram": int(num(d["DP16KD"])), "fmax": num(d["Fmax (MHz)"]),
                                        "seeds": [num(x) for x in d["Seeds"].split(",")]})
        elif head[0] == "Stage":
            m = re.match(r"(\w+) \(hierarchical Fmax ([\d.]+) MHz\)", heading)
            if m:
                res["paths"][m[1]] = {"fmax_hier": float(m[2]), "stages": [
                    {"stage": r[0], "logic": num(r[1]), "routing": num(r[2]), "total": num(r[3])} for r in body]}
    return res


# ---------------------------------------------------------------------------

def git_info() -> dict:
    def g(*a):
        p = subprocess.run(["git", *a], cwd=ROOT, capture_output=True, env=ENV)
        return p.stdout.decode(errors="replace").strip()
    return {"commit": g("rev-parse", "--short", "HEAD"), "subject": g("log", "-1", "--format=%s"),
            "dirty": bool(g("status", "--porcelain", "--untracked-files=no"))}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--profile", choices=["quick", "full"], default="quick")
    ap.add_argument("--syn", action="store_true", help="rerun synthesis (several minutes) instead of reading syn/reports/")
    ap.add_argument("--syn-seeds", type=int, default=3)
    ap.add_argument("--no-mutants", action="store_true", help="skip the self-check")
    ap.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 4))
    ap.add_argument("--random-seeds", type=int, help="override the profile's random seed count")
    ap.add_argument("--report-only", type=Path, help="re-render the report of an earlier run directory")
    ap.add_argument("--only-mutant", metavar="NAME",
                    help="inject just this bug (scripts/eval_mutants.py) and run every check layer on it")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.only_mutant:
        chosen = [m for m in MUTANTS if m.name == args.only_mutant]
        if not chosen:
            ap.error(f"unknown mutant {args.only_mutant}; known: {', '.join(m.name for m in MUTANTS)}")
        out = EVAL / f"mutant-{args.only_mutant}-{datetime.now():%Y%m%d-%H%M%S}"
        p = Pipeline(out, args.jobs)
        m = chosen[0]
        print(f"[eval] injecting {m.name}: {m.what}" + (f"\n       in {m.file}:\n       - {m.old}\n       + {m.new}"
                                                       if m.file else ""))
        p.mutants(["asm", "c", "rv32ui", "random"], 20, first_catch=False, selected=chosen)
        item = p.stages[-1].items[0]
        print(f"\n[eval] {m.name}: expected to be {'caught' if m.expect == 'kill' else 'missed'}")
        for layer, r in item["layers"].items():
            seen = "CAUGHT" if r["killed"] else "not seen"
            print(f"  {layer:7s} {seen:9s} {r['failing']}/{r['of']} failing  {', '.join(r['first'])}")
        print(f"[eval] patched RTL: {(out / 'mutants' / m.name / 'rtl').relative_to(ROOT)}; "
              f"logs: {(out / 'logs').relative_to(ROOT)}")
        return 0 if item["ok"] else 1

    from eval_report import render  # noqa: PLC0415
    if args.report_only:
        render(args.report_only.resolve())
        print(f"evaluate: report re-rendered in {args.report_only / 'report.html'}")
        return 0

    full = args.profile == "full"
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + f"-{args.profile}"
    out = EVAL / run_id
    out.mkdir(parents=True, exist_ok=True)
    p = Pipeline(out, args.jobs)
    started = datetime.now()
    print(f"[eval] run {run_id}: profile {args.profile}, {args.jobs} jobs, output {out.relative_to(ROOT)}")

    p.env()
    p.lint()
    p.unit()
    if p.sim_build():
        p.harness()
        p.progs("asm", "Directed assembly tests", ["asm"])
        p.progs("c", "C programs", ["c"])
        p.progs("rv32ui", "riscv-tests rv32ui (with waivers)", ["rv32ui"])
        if full:
            p.riscof()
        else:
            p.skip("riscof", "riscv-arch-test via RISCOF", "full profile only")
        p.random(args.random_seeds or (200 if full else 50))
        if full:
            p.bench()
        else:
            p.skip("bench", "Benchmarks", "full profile only")
        p.waves()
    else:
        for n in ("harness", "asm", "c", "rv32ui", "riscof", "random", "bench", "waves"):
            p.skip(n, n, "simulator did not build")
    if full or args.syn:
        p.syn(args.syn, args.syn_seeds)
    else:
        p.skip("syn", "ECP5 synthesis", "full profile only (or --syn)")
    if args.no_mutants:
        p.skip("mutants", "Self-check with injected bugs", "--no-mutants")
    elif p.get("sim_build").status == "pass":
        # quick: stop each mutant at its first catch; full: every layer, for the full matrix
        p.mutants(["asm", "c", "rv32ui", "random"], 20, first_catch=not full)
    else:
        p.skip("mutants", "Self-check with injected bugs", "simulator did not build")

    ran = [s for s in p.stages if s.status != "skip"]
    verdict = "pass" if ran and all(s.status == "pass" for s in ran) else "fail"
    results = {
        "run_id": run_id, "profile": args.profile, "verdict": verdict,
        "started": started.isoformat(timespec="seconds"), "finished": datetime.now().isoformat(timespec="seconds"),
        "seconds": round((datetime.now() - started).total_seconds(), 1),
        "git": git_info(), "host": {"os": platform.platform(), "python": platform.python_version(), "jobs": args.jobs},
        "stages": [{k: v for k, v in asdict(s).items()} for s in p.stages],
    }
    (out / "results.json").write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
    render(out)

    latest = EVAL / "latest"
    if latest.exists():
        shutil.rmtree(latest)
    shutil.copytree(out, latest, ignore=shutil.ignore_patterns("mutants", "*.vcd", "logs"))
    with open(EVAL / "history.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"run_id": run_id, "profile": args.profile, "verdict": verdict,
                            "seconds": results["seconds"], "commit": results["git"]["commit"],
                            "stages": {s.name: {"status": s.status, "seconds": s.seconds, "passed": s.passed,
                                                "total": s.total} for s in p.stages}}) + "\n")

    print(f"\n[eval] verdict: {verdict.upper()} in {results['seconds'] / 60:.1f} min")
    for s in p.stages:
        print(f"  {s.status.upper():4s}  {s.name:10s} {s.summary}")
    print(f"[eval] report: {(out / 'report.html').relative_to(ROOT)}  (copy in build/eval/latest/)")
    return 0 if verdict == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
