"""Synthesis characterization of rv_core for Lattice ECP5 with yosys + nextpnr (docs/exec.md M8).

Usage: syn.py [--seeds N] [--no-pnr]

Steps (outputs in build/syn/, the report in syn/reports/):
  1. sv2v converts rtl/ (and the syn/ harnesses) to Verilog-2005 with
     SYNTHESIS defined: yosys's own SystemVerilog frontend cannot read the
     package types the RTL uses in its ports (spec §14.1).
  2. yosys synth_ecp5:
       - rv_core alone, memories as ports: cell counts (pre-pack), and with
         -noflatten the same per module;
       - three timing variants, see syn/rv_timing_core.sv and syn/rv_timing_soc.sv:
           core        rv_core alone, memory responses from flops
           soc_bram    rv_core + 1 KiB instruction and data memory; yosys may
                       choose: the instruction memory goes to block RAM
           soc_lutram  the same with the instruction memory forced into LUT RAM
  3. nextpnr-ecp5 (LFE5U-25F, CABGA256, speed grade 6) places and routes each
     variant for --seeds seeds and reports post-pack utilisation and Fmax
     (the best seed is reported, all seeds are listed). Every tool run has a
     timeout.
  4. For the stage breakdown the variants are synthesized again with
     -noflatten, so nextpnr names every cell by its instance path; the
     critical path's logic and routing delay is then summed per stage
     (fetch, decode, register file, ALU/branch, memory, write-back). The
     hierarchical netlist has no optimization across module boundaries, so
     its Fmax is a little lower than the flattened one; it is only used for
     the breakdown.
  5. syn/reports/summary.md: the tables; syn/reports/*.log: the tool logs.

Tools: SV2V (default %LOCALAPPDATA%/Programs/sv2v-0.0.13/sv2v-Windows/sv2v.exe),
yosys and nextpnr-ecp5 on PATH (MSYS2 UCRT64).
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "syn"
REPORTS = ROOT / "syn" / "reports"
DEVICE = ["--25k", "--package", "CABGA256", "--speed", "6"]
TARGET_MHZ = 20
YOSYS_TIMEOUT = 1800
PNR_TIMEOUT = 1800

# name: (harness, parameters, stage breakdown?). soc_bram gets no breakdown:
# in the hierarchical netlist yosys cannot fold u_core.u_pc's pc_q into the
# block RAM across the module boundary, so that netlist is not block RAM.
VARIANTS = {
    "core": ("rv_timing_core", {}, True),
    "soc_bram": ("rv_timing_soc", {"IMEM_LUTRAM": 0}, False),
    "soc_lutram": ("rv_timing_soc", {"IMEM_LUTRAM": 1}, True),
}

# Instance-path prefix -> stage of the single-cycle datapath (spec §5.1).
# Checked in order; the first matching prefix wins.
STAGES = [
    ("g_imem", "fetch: instruction memory"),
    ("imem_", "fetch: instruction memory read mux"),
    ("u_core.inst", "fetch: instruction word (fetch-error gating)"),
    ("u_core.u_pc", "PC / next-PC"),
    ("u_core.pc", "PC / next-PC"),
    ("u_core.next_pc", "PC / next-PC"),
    ("u_core.u_decoder", "decode"),
    ("u_core.u_imm_gen", "decode: immediate"),
    ("u_core.u_regfile", "register file"),
    ("u_core.op_", "operand select"),
    ("u_core.u_alu", "ALU"),
    ("u_core.u_branch", "branch compare"),
    ("dmem_rsp", "memory: data memory read mux"),
    ("dmem", "memory: data memory"),
    ("didx", "memory: data memory"),
    ("u_core.u_lsu", "memory: load/store unit"),
    ("u_core.wb_", "write-back mux"),
    ("u_core.", "core control (active, stop logic, retire port)"),
]


def sv2v() -> str:
    exe = os.environ.get("SV2V") or str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "sv2v-0.0.13"
                                       / "sv2v-Windows" / "sv2v.exe")
    if not Path(exe).exists() and not shutil.which(exe):
        raise SystemExit(f"syn: sv2v not found at {exe} (set SV2V)")
    return exe


def need(tool: str) -> str:
    exe = shutil.which(tool)
    if exe is None:
        raise SystemExit(f"syn: {tool} not found on PATH")
    return exe


def run(cmd: list[str], log: Path, timeout: int) -> None:
    with open(log, "wb") as f:
        p = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, timeout=timeout)
    if p.returncode != 0:
        tail = log.read_text(errors="replace").splitlines()[-15:]
        raise SystemExit(f"syn: {Path(cmd[0]).name} failed (exit {p.returncode}), see {log}:\n" + "\n".join(tail))


def rtl_sources() -> list[str]:
    lines = (ROOT / "rtl" / "rtl.f").read_text().splitlines()
    return [str(ROOT / l.split("//")[0].strip()) for l in lines if l.split("//")[0].strip()]


def convert(top_file: Path | None, out: Path) -> None:
    srcs = rtl_sources() + ([str(top_file)] if top_file else [])
    p = subprocess.run([sv2v(), "-DSYNTHESIS", *srcs, "-w", str(out)], capture_output=True, timeout=300)
    if p.returncode != 0:
        raise SystemExit(f"syn: sv2v failed:\n{p.stderr.decode(errors='replace')}")


def cell_counts(stat: str) -> dict[str, int]:
    """Cell counts from the top-level (whole design) part of a yosys stat."""
    counts = {}
    for m in re.finditer(r"^\s+(\d+)\s+(\S+)$", stat, re.M):
        counts[m[2]] = int(m[1])
    return counts


def module_counts(stat: str) -> dict[str, dict[str, int]]:
    """Per-module cell counts from a -noflatten yosys stat."""
    out, cur = {}, None
    for line in stat.splitlines():
        m = re.match(r"^=== (\S+) ===", line)
        if m:
            cur = m[1]
            out[cur] = {}
            continue
        if line.startswith("=== design hierarchy"):
            cur = None
            continue
        m = re.match(r"^\s+(\d+)\s+((?:LUT4|TRELLIS_\w+|CCU2C|PFUMX|L6MUX21|DP16KD))$", line)
        if cur and m:
            out[cur][m[2]] = int(m[1])
    return out


def yosys(src: Path, top: str, params: dict, json_out: Path, log: Path, flatten: bool) -> str:
    chp = "".join(f"chparam -set {k} {v} {top}; " for k, v in params.items())
    script = (f"read_verilog {src.as_posix()}; {chp}synth_ecp5 -top {top} {'' if flatten else '-noflatten '}"
              f"-json {json_out.as_posix()}; tee -o {log.with_suffix('.stat').as_posix()} stat")
    run([need("yosys"), "-q", "-l", str(log), "-p", script], log.with_suffix(".out"), YOSYS_TIMEOUT)
    return log.with_suffix(".stat").read_text(errors="replace")


def nextpnr(json_in: Path, seed: int, log: Path, report: Path) -> dict:
    cmd = [need("nextpnr-ecp5"), *DEVICE, "--json", str(json_in), "--freq", str(TARGET_MHZ),
           "--lpf-allow-unconstrained", "--timing-allow-fail", "--seed", str(seed),
           "--report", str(report), "--detailed-timing-report", "-l", str(log), "-q"]
    run(cmd, log.with_suffix(".out"), PNR_TIMEOUT)
    text = log.read_text(errors="replace")
    res = {"seed": seed, "util": {}, "fmax": None}
    for m in re.finditer(r"^Info:\s+(\w+):\s+(\d+)/\s*(\d+)\s+(\d+)%", text, re.M):
        res["util"][m[1]] = (int(m[2]), int(m[3]), int(m[4]))
    fm = re.findall(r"Max frequency for clock\s+'[^']*':\s+([\d.]+) MHz", text)
    if fm:
        res["fmax"] = float(fm[-1])
    res["report"] = report
    return res


def stage_of(cell: str) -> str:
    for prefix, stage in STAGES:
        if cell.startswith(prefix):
            return stage
    return "harness (input/output flops)"


def breakdown(report: Path) -> tuple[list[tuple[str, float, float]], float, str, str]:
    """Critical path of the clock domain: [(stage, logic ns, routing ns)] in path order, total, start, end."""
    data = json.loads(report.read_text())
    # Only the clock-to-clock path: it sets Fmax. nextpnr also lists paths
    # from and to unconstrained I/O (<async>), which are not the core's.
    paths = [p for p in data.get("critical_paths", [])
             if p.get("from", "").startswith("posedge") and p.get("to", "").startswith("posedge")]
    if not paths:
        return [], 0.0, "", ""
    path = max(paths, key=lambda p: sum(s.get("delay", 0.0) for s in p.get("path", [])))["path"]
    rows: list[tuple[str, float, float]] = []
    for seg in path:
        cell = seg.get("to", {}).get("cell", "") if seg.get("type") == "routing" else seg.get("from", {}).get("cell", "")
        stage = stage_of(cell)
        d = float(seg.get("delay", 0.0))
        logic, route = (0.0, d) if seg.get("type") == "routing" else (d, 0.0)
        if rows and rows[-1][0] == stage:
            rows[-1] = (stage, rows[-1][1] + logic, rows[-1][2] + route)
        else:
            rows.append((stage, logic, route))
    # nextpnr packs LUTs and flops from different modules into one slice and
    # names the slice cell after one of them, so a harness flop's name can
    # appear inside the core's logic. The harness only starts and ends a
    # clock-to-clock path: a harness row in the middle belongs to the stage
    # before it.
    merged: list[tuple[str, float, float]] = []
    for i, (stage, lo, ro) in enumerate(rows):
        inner = 0 < i < len(rows) - 1
        if inner and stage.startswith("harness") and merged:
            stage = merged[-1][0]
        if merged and merged[-1][0] == stage:
            merged[-1] = (stage, merged[-1][1] + lo, merged[-1][2] + ro)
        else:
            merged.append((stage, lo, ro))
    rows = merged
    total = sum(l + r for _, l, r in rows)
    start = path[0].get("from", {}).get("cell", "")
    end = path[-1].get("to", {}).get("cell", "")
    return rows, total, start, end


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--no-pnr", action="store_true", help="yosys only (no nextpnr)")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    md = ["# rv_core synthesis report (ECP5)", "",
          "Generated by `make syn` (`scripts/syn.py`); see docs/exec.md M8. "
          f"Device: LFE5U-25F, CABGA256, speed grade 6 (nextpnr-ecp5); target clock {TARGET_MHZ} MHz "
          "(only the achieved Fmax matters).", ""]

    # 1-2: rv_core alone.
    core_v = OUT / "rv_core.v"
    convert(None, core_v)
    print("syn: yosys rv_core (flattened, then per module)")
    flat = cell_counts(yosys(core_v, "rv_core", {}, OUT / "rv_core.json", OUT / "yosys_rv_core.log", True))
    hier = module_counts(yosys(core_v, "rv_core", {}, OUT / "rv_core_hier.json", OUT / "yosys_rv_core_hier.log", False))
    kinds = ["LUT4", "PFUMX", "L6MUX21", "CCU2C", "TRELLIS_DPR16X4", "TRELLIS_FF"]
    md += ["## Area of rv_core (yosys, pre-pack)", "",
           "rv_core alone, memories outside as ports. Pre-pack cell counts from `synth_ecp5`; "
           "post-pack slice usage (TRELLIS_COMB) is in the nextpnr table below (with the harness). "
           "The per-module rows come from a -noflatten run and count each module's own cells only "
           "(rv_core: its glue logic, flops and retire port).", "",
           "| Module | " + " | ".join(kinds) + " |", "|---|" + "---:|" * len(kinds),
           "| **rv_core (flattened)** | " + " | ".join(str(flat.get(k, 0)) for k in kinds) + " |"]
    def short(mod: str) -> str:
        """yosys names a module with parameters $paramod\\<name>\\<params>: keep <name>."""
        return mod.split(chr(92))[1] if mod.startswith("$paramod") else mod

    for mod in sorted(hier, key=short):
        if hier[mod]:
            md.append(f"| {short(mod)} (own cells) | " + " | ".join(str(hier[mod].get(k, 0)) for k in kinds) + " |")
    md.append("")

    # Timing variants.
    results = {}
    for name, (top, params, want_breakdown) in VARIANTS.items():
        src = OUT / f"{top}.v"
        convert(ROOT / "syn" / f"{top}.sv", src)
        for flatten in ((True, False) if want_breakdown else (True,)):
            tag = f"{name}{'' if flatten else '_hier'}"
            print(f"syn: yosys {tag}")
            stat = yosys(src, top, params, OUT / f"{tag}.json", OUT / f"yosys_{tag}.log", flatten)
            results.setdefault(name, {})[("cells", flatten)] = cell_counts(stat)
            if args.no_pnr:
                continue
            seeds = range(1, args.seeds + 1) if flatten else [1]
            runs = []
            for s in seeds:
                print(f"syn: nextpnr {tag} seed {s}")
                runs.append(nextpnr(OUT / f"{tag}.json", s, OUT / f"nextpnr_{tag}_s{s}.log", OUT / f"nextpnr_{tag}_s{s}.json"))
            results[name][("pnr", flatten)] = runs

    if not args.no_pnr:
        md += ["## Utilisation and Fmax (nextpnr-ecp5, post-pack)", "",
               "Flattened netlists. Fmax: best of the seeds; all seeds in the last column.", "",
               "| Variant | TRELLIS_COMB | TRELLIS_FF | TRELLIS_RAMW | DP16KD | Fmax (MHz) | Seeds |",
               "|---|---:|---:|---:|---:|---:|---|"]
        for name in VARIANTS:
            runs = results[name][("pnr", True)]
            best = max(runs, key=lambda r: r["fmax"] or 0)
            u = best["util"]
            def ut(k):
                return f"{u[k][0]} ({u[k][2]}%)" if k in u else "0"
            md.append(f"| {name} | {ut('TRELLIS_COMB')} | {ut('TRELLIS_FF')} | {ut('TRELLIS_RAMW')} | {ut('DP16KD')} | "
                      f"**{best['fmax']:.1f}** | " + ", ".join(f"{r['fmax']:.1f}" for r in runs) + " |")
        md += ["", "## Critical path by stage", "",
               "From the hierarchical (-noflatten) netlists: the clock-to-clock critical path of each "
               "variant, logic and routing delay summed per stage in path order. The hierarchical netlist "
               "is not optimized across module boundaries, so its Fmax is lower than the flattened one "
               "above; it shows where the delay is, not the achievable clock. soc_bram has no breakdown "
               "(its hierarchical netlist cannot use block RAM).", ""]
        for name in [n for n, v in VARIANTS.items() if v[2]]:
            run1 = results[name][("pnr", False)][0]
            rows, total, start, end = breakdown(run1["report"])
            md += [f"### {name} (hierarchical Fmax {run1['fmax']:.1f} MHz)", "",
                   f"From `{start}` to `{end}`, {total:.2f} ns.", "",
                   "| Stage | Logic (ns) | Routing (ns) | Total (ns) | Share |", "|---|---:|---:|---:|---:|"]
            for stage, lo, ro in rows:
                md.append(f"| {stage} | {lo:.2f} | {ro:.2f} | {lo + ro:.2f} | {100 * (lo + ro) / total:.0f}% |")
            md.append("")
    # Copy only what this run produced (build/syn/ may hold files from older runs),
    # into a report directory emptied first.
    for f in REPORTS.glob("*"):
        f.unlink()
    tags = ["rv_core", "rv_core_hier"] + [f"{n}{s}" for n, v in VARIANTS.items()
                                          for s in ([""] + (["_hier"] if v[2] else []))]
    for tag in tags:
        for f in [OUT / f"yosys_{tag}.stat"] + ([OUT / f"nextpnr_{tag}_s1.log"] if not args.no_pnr else []):
            if f.exists():
                shutil.copy(f, REPORTS / f.name)
    (REPORTS / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8", newline="\n")
    print(f"syn: report written to {(REPORTS / 'summary.md').relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
