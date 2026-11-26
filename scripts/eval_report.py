"""Render the evaluation report: PNG charts, a waveform image, report.html and report.md.

Usage: eval_report.py <run directory>     (normally called by scripts/evaluate.py)

Reads <run>/results.json and writes:
  img/overview.png       every stage: status, checks passed, time
  img/unit.png           unit tests per block
  img/programs.png       every directed test, C program and rv32ui test as a tile
  img/random.png         random-program instruction coverage and how the runs ended
  img/bench_*.png        benchmark scores, instruction mix, hazard profile (full profile)
  img/syn_*.png          ECP5 area per module and critical path by stage (full / --syn)
  img/waveform.png       the first cycles of sw/asm/t04_branch from its VCD
  img/mutants.png        self-check: which injected bug each check layer caught
  img/history.png        verdict and duration of every run so far (from history.jsonl)
  report.html            one self-contained page: verdict, key values, every image, tables
  report.md              the key values as markdown tables
Colours: the dataviz reference palette (categorical slots in fixed order;
status colours only for pass/fail, always with a text label).
"""

import base64
import html
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vcd import read_vcd, sample, to_int  # noqa: E402

# dataviz reference palette (light mode)
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
GOOD, CRIT, MUTED = "#0ca30c", "#d03b3b", "#b9b8b2"
STATUS = {"pass": GOOD, "fail": CRIT, "skip": MUTED}

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "font.size": 9, "axes.titlesize": 11, "axes.titleweight": "bold",
    "axes.titlelocation": "left", "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
    "font.family": "DejaVu Sans",
})


def save(fig, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return path


def stage(res: dict, name: str) -> dict | None:
    return next((s for s in res["stages"] if s["name"] == name), None)


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def chart_overview(res: dict, img: Path) -> Path:
    st = res["stages"]
    fig, ax = plt.subplots(figsize=(10, 0.42 * len(st) + 1.2))
    y = list(range(len(st)))[::-1]
    for yi, s in zip(y, st):
        ax.barh(yi, max(s["seconds"], 0.5), color=STATUS[s["status"]], height=0.62, edgecolor=SURFACE, linewidth=2)
        label = {"pass": "PASS", "fail": "FAIL", "skip": "skip"}[s["status"]]
        count = f"{s['passed']}/{s['total']}" if s["total"] else ""
        ax.text(-0.01, yi, f"{label}  {s['name']}", transform=ax.get_yaxis_transform(), ha="right", va="center",
                fontweight="bold", color=INK)
        ax.text(max(s["seconds"], 0.5), yi, f"  {count}  {s['summary'][:80]}", va="center", color=INK2, fontsize=8)
    ax.set_yticks([])
    ax.set_xlabel("seconds (bar colour: green pass, red fail, grey skipped)")
    xmax = max([s["seconds"] for s in st] + [1])
    ax.set_xlim(0, xmax * 2.6)
    ax.grid(axis="y", visible=False)
    verdict = res["verdict"].upper()
    ax.set_title(f"Evaluation {res['run_id']}  |  verdict {verdict}  |  {res['seconds'] / 60:.1f} min  |  "
                 f"commit {res['git']['commit']}{' (dirty)' if res['git']['dirty'] else ''}", pad=10)
    return save(fig, img / "overview.png")


def chart_unit(res: dict, img: Path) -> Path | None:
    s = stage(res, "unit")
    if not s or not s["items"]:
        return None
    items = sorted(s["items"], key=lambda b: b["tests"])
    fig, ax = plt.subplots(figsize=(8, 0.38 * len(items) + 1))
    names = [b["block"] for b in items]
    ok = [b["tests"] - b["failed"] - b["skipped"] for b in items]
    bad = [b["failed"] for b in items]
    ax.barh(names, ok, color=SERIES[0], height=0.6, edgecolor=SURFACE, linewidth=2)
    ax.barh(names, bad, left=ok, color=CRIT, height=0.6, edgecolor=SURFACE, linewidth=2)
    for i, b in enumerate(items):
        txt = f" {ok[i]}/{b['tests']} passed, {b['seconds']:.1f} s" + (f", {bad[i]} FAILED" if bad[i] else "")
        ax.text(b["tests"], i, txt, va="center", color=INK2, fontsize=8)
    ax.set_xlim(0, max(b["tests"] for b in items) * 1.55)
    ax.set_xlabel("cocotb tests (Icarus, 4-state: outputs also checked for X/Z)")
    ax.grid(axis="y", visible=False)
    ax.set_title(f"Unit tests: {s['passed']}/{s['total']} passed in {len(items)} blocks")
    return save(fig, img / "unit.png")


def chart_programs(res: dict, img: Path) -> Path | None:
    groups = [(n, stage(res, n)) for n in ("asm", "c", "rv32ui")]
    groups = [(n, s) for n, s in groups if s and s["items"]]
    if not groups:
        return None
    cols = 6
    rows = sum((len(s["items"]) + cols - 1) // cols for _, s in groups) + len(groups)
    fig, ax = plt.subplots(figsize=(13, 0.5 * rows + 0.6))
    short_cause = {"STOP_MISALIGNED_FETCH": "misaligned fetch", "STOP_MISALIGNED_DATA": "misaligned data",
                   "STOP_IFETCH_ERROR": "fetch error", "STOP_BUS_ERROR": "bus error", "STOP_ILLEGAL": "illegal",
                   "STOP_ECALL": "ECALL", "STOP_EBREAK": "EBREAK"}
    ax.set_xlim(0, cols)
    ax.set_ylim(rows, 0)
    ax.axis("off")
    r = 0
    for name, s in groups:
        ax.text(0, r + 0.65, f"{name}: {s['passed']}/{s['total']} passed (each also replayed on the reference model, "
                f"every retire-log line compared)", fontweight="bold", fontsize=9)
        r += 1
        for i, it in enumerate(s["items"]):
            x, yy = i % cols, r + i // cols
            colour = GOOD if it["ok"] else CRIT
            ax.add_patch(Rectangle((x + 0.03, yy + 0.06), 0.94, 0.88, facecolor=colour, alpha=0.16,
                                   edgecolor=colour, linewidth=1.2))
            mark = "PASS" if it["ok"] else "FAIL"
            short = it["name"].removeprefix("rv32ui-p-")
            short = short if len(short) <= 22 else short[:21] + "…"
            detail = f"{it['cycles']:,} cyc" if it["cycles"] is not None else ""
            if it.get("cause"):
                detail += f"  stop: {short_cause.get(it['cause'], it['cause'])}"
            if it.get("waived"):
                short += " (waived)"
            ax.text(x + 0.08, yy + 0.4, f"{mark} {short}", fontsize=7.4, fontweight="bold", color=INK, va="center")
            ax.text(x + 0.08, yy + 0.72, detail, fontsize=6.6, color=INK2, va="center")
        r += (len(s["items"]) + cols - 1) // cols
    return save(fig, img / "programs.png")


def chart_random(res: dict, img: Path) -> Path | None:
    s = stage(res, "random")
    if not s or not s["metrics"].get("per_instruction"):
        return None
    m = s["metrics"]
    per = m["per_instruction"]
    names = list(per)
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(13, 4.2), gridspec_kw={"width_ratios": [4, 1.3]})
    vals = [max(per[n], 0.8) for n in names]
    ax.bar(names, vals, color=[SERIES[0] if per[n] else CRIT for n in names], width=0.7,
           edgecolor=SURFACE, linewidth=1)
    ax.set_yscale("log")
    ax.set_ylabel("times retired (log scale)")
    ax.tick_params(axis="x", rotation=90, labelsize=7)
    ax.grid(axis="x", visible=False)
    covered = sum(1 for v in per.values() if v)
    fig.suptitle(f"Random programs: {s['passed']}/{s['total']} match the model, {m['instructions']:,} instructions, "
                 f"{covered}/40 RV32I instructions covered", x=0.01, ha="left", fontweight="bold", fontsize=11)
    ax.set_title("Times each instruction retired", fontsize=9.5)
    ends = m.get("endings", {})
    causes = m.get("stop_causes", {})
    labels = [f"end: {k}" for k in ends] + [f"stop: {k.removeprefix('STOP_')}" for k in causes]
    counts = list(ends.values()) + list(causes.values())
    ax2.barh(labels[::-1], counts[::-1], color=SERIES[0], height=0.6, edgecolor=SURFACE, linewidth=2)
    for i, c in enumerate(counts[::-1]):
        ax2.text(c, i, f" {c}", va="center", fontsize=8, color=INK2)
    ax2.set_xlim(0, max(counts + [1]) * 1.3)
    ax2.grid(axis="y", visible=False)
    ax2.set_title("How the runs ended")
    ax2.tick_params(axis="y", labelsize=7.5)
    return save(fig, img / "random.png")


def chart_bench(res: dict, img: Path) -> list[Path]:
    s = stage(res, "bench")
    if not s or not s["items"] or not any("stats" in i for i in s["items"]):
        return []
    items = [i for i in s["items"] if "stats" in i]
    names = [i["name"].removeprefix("embench-") for i in items]
    out = []

    # instruction mix (stacked, fixed categorical order)
    classes = ["ALU", "load", "store", "branch", "jump", "upper-imm", "other"]
    fig, ax = plt.subplots(figsize=(10, 0.5 * len(items) + 1.4))
    left = [0.0] * len(items)
    for k, c in enumerate(classes):
        v = [i["stats"]["mix"].get(c, 0) for i in items]
        ax.barh(names, v, left=left, color=SERIES[k], height=0.62, edgecolor=SURFACE, linewidth=2, label=c)
        for j, (l, w) in enumerate(zip(left, v)):
            if w >= 7:
                ax.text(l + w / 2, j, f"{w:.0f}", ha="center", va="center", fontsize=7.5, color="#ffffff")
        left = [a + b for a, b in zip(left, v)]
    ax.set_xlim(0, 100)
    ax.set_xlabel("% of retired instructions (whole program, CPI 1)")
    ax.legend(ncol=7, loc="upper center", bbox_to_anchor=(0.5, -0.22), frameon=False, fontsize=8)
    ax.grid(axis="y", visible=False)
    ax.set_title("Benchmark instruction mix")
    out.append(save(fig, img / "bench_mix.png"))

    # cycles and scores
    fig, ax = plt.subplots(figsize=(10, 0.45 * len(items) + 1))
    cyc = [i["cycles"] or 0 for i in items]
    ax.barh(names, cyc, color=SERIES[0], height=0.6, edgecolor=SURFACE, linewidth=2)
    ax.set_xscale("log")
    for j, i in enumerate(items):
        extra = f"   {i['score']} {i['score_unit']}" if "score" in i else ""
        ax.text(cyc[j], j, f" {cyc[j]:,} cycles{extra}", va="center", fontsize=8, color=INK2)
    ax.set_xlim(min(cyc) / 2, max(cyc) * 30)
    ax.set_xlabel("cycles = instructions for the whole program (log scale)")
    ax.grid(axis="y", visible=False)
    ax.set_title("Benchmark cycles and scores (scores at a notional 1 MHz clock)")
    out.append(save(fig, img / "bench_cycles.png"))

    # hazard and Phase 2 profile: small multiples, one metric per panel
    metrics = [("RAW distance 1 %", lambda st: st["raw"]["1"]), ("load-use pairs %", lambda st: st["load_use"]),
               ("branches taken %", lambda st: st["branch_taken"]), ("libgcc mul/div %", lambda st: st["muldiv"])]
    fig, axes = plt.subplots(1, len(metrics), figsize=(13, 0.4 * len(items) + 1.6), sharey=True)
    for ax, (label, f) in zip(axes, metrics):
        v = [f(i["stats"]) for i in items]
        ax.barh(names, v, color=SERIES[0], height=0.6, edgecolor=SURFACE, linewidth=2)
        for j, x in enumerate(v):
            ax.text(x, j, f" {x:.1f}", va="center", fontsize=7.5, color=INK2)
        ax.set_xlim(0, max(v + [1]) * 1.35)
        ax.set_title(label, fontsize=9.5)
        ax.grid(axis="y", visible=False)
    fig.suptitle("Phase 2 inputs per benchmark: forwarding, load stalls, branch prediction, M extension",
                 x=0.01, ha="left", fontweight="bold", fontsize=11)
    fig.tight_layout()
    out.append(save(fig, img / "bench_profile.png"))
    return out


def chart_syn(res: dict, img: Path) -> list[Path]:
    s = stage(res, "syn")
    if not s or s["status"] == "skip" or not s["metrics"].get("variants"):
        return []
    m = s["metrics"]
    out = []
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(13, 4))
    mods = [x for x in m["modules"] if "flattened" not in x["module"]]
    mods.sort(key=lambda x: x.get("LUT4", 0))
    ax.barh([x["module"].replace(" (own cells)", "") for x in mods], [x.get("LUT4", 0) for x in mods],
            color=SERIES[0], height=0.6, edgecolor=SURFACE, linewidth=2)
    for j, x in enumerate(mods):
        ax.text(x.get("LUT4", 0), j, f" {x.get('LUT4', 0)}", va="center", fontsize=8, color=INK2)
    flat = next((x for x in m["modules"] if "flattened" in x["module"]), {})
    ax.set_title(f"LUT4 per module (yosys, pre-pack); rv_core total {flat.get('LUT4', '?')}")
    ax.set_xlim(0, max(x.get("LUT4", 0) for x in mods) * 1.25)
    ax.grid(axis="y", visible=False)
    v = m["variants"]
    ax2.barh([x["variant"] for x in v][::-1], [x["fmax"] for x in v][::-1], color=SERIES[0], height=0.6,
             edgecolor=SURFACE, linewidth=2)
    for j, x in enumerate(v[::-1]):
        ax2.text(x["fmax"], j, f" {x['fmax']:.1f} MHz  ({x['comb']:,} COMB, {x['lutram']} LUT-RAM, {x['bram']} BRAM)",
                 va="center", fontsize=8, color=INK2)
    ax2.set_xlim(0, max(x["fmax"] for x in v) * 2.1)
    ax2.set_title("Fmax per variant (nextpnr-ecp5, best of seeds)")
    ax2.set_xlabel("MHz")
    ax2.grid(axis="y", visible=False)
    out.append(save(fig, img / "syn_area.png"))

    paths = m.get("paths", {})
    if paths:
        # colour follows the stage type, the same in both variants (not the position along the path)
        kinds = [("fetch", "fetch"), ("decode", "decode"), ("operand", "operand select"), ("ALU", "ALU"),
                 ("memory", "memory / LSU"), ("harness", "harness flops")]
        def kind(stage_name: str) -> str:
            return next((label for key, label in kinds if stage_name.startswith(key)), "control, next-PC, write-back")
        order = [label for _, label in kinds[:5]] + ["control, next-PC, write-back", "harness flops"]
        colour = {label: SERIES[i] for i, label in enumerate(order)}
        fig, axes = plt.subplots(len(paths), 1, figsize=(12, 1.5 * len(paths) + 1.2))
        axes = axes if len(paths) > 1 else [axes]
        for ax, (variant, pth) in zip(axes, paths.items()):
            x = 0.0
            for stg in pth["stages"]:
                c = colour[kind(stg["stage"])]
                ax.barh(0, stg["logic"], left=x, color=c, height=0.55, edgecolor=SURFACE, linewidth=2)
                ax.barh(0, stg["routing"], left=x + stg["logic"], color=c, alpha=0.4, height=0.55,
                        edgecolor=SURFACE, linewidth=2)
                if stg["total"] >= 1.5:
                    ax.text(x + stg["logic"] + stg["routing"] / 2, 0, f"{stg['total']:.1f}", ha="center",
                            va="center", fontsize=7.5, color=INK, fontweight="bold")
                x += stg["total"]
            totals = {}
            for stg in pth["stages"]:
                totals[kind(stg["stage"])] = totals.get(kind(stg["stage"]), 0) + stg["total"]
            top = max(totals, key=totals.get)
            ax.set_yticks([])
            ax.set_xlim(0, x * 1.01)
            ax.set_ylim(-0.45, 0.45)
            ax.grid(axis="y", visible=False)
            ax.set_title(f"{variant}: critical path {x:.1f} ns (hierarchical netlist, {pth['fmax_hier']} MHz); "
                         f"largest share: {top} {100 * totals[top] / x:.0f} %; solid = logic, light = routing",
                         fontsize=9.5)
        handles = [Rectangle((0, 0), 1, 1, color=colour[l]) for l in order]
        fig.legend(handles, order, ncol=len(order), loc="lower center", frameon=False, fontsize=8,
                   bbox_to_anchor=(0.5, -0.02))
        axes[-1].set_xlabel("ns along the path, in path order")
        fig.tight_layout(rect=(0, 0.07, 1, 1))
        out.append(save(fig, img / "syn_path.png"))
    return out


WAVE_SIGNALS = [
    ("clk", "rv_soc_sim.u_core.clk_i", "clock"),
    ("pc", "rv_soc_sim.u_core.pc", "hex"),
    ("inst", "rv_soc_sim.u_core.inst", "hex"),
    ("op", "rv_soc_sim.u_core.inst", "mnemonic"),
    ("alu_res", "rv_soc_sim.u_core.alu_res", "hex"),
    ("cmp_true", "rv_soc_sim.u_core.br_taken", "bit"),
    ("next_pc", "rv_soc_sim.u_core.next_pc", "hex"),
    ("rf_we", "rv_soc_sim.u_core.rf_we", "bit"),
    ("rd", "rv_soc_sim.u_core.rd", "dec"),
    ("wb_data", "rv_soc_sim.u_core.wb_data", "hex"),
    ("halted", "rv_soc_sim.u_core.halted_q", "bit"),
]


def chart_waveform(res: dict, run: Path, img: Path, cycles: int = 20) -> Path | None:
    """Digital waveform around the first taken branch or jump of the program."""
    s = stage(res, "waves")
    if not s or s["status"] != "pass":
        return None
    vcd = run / s["metrics"]["vcd"]
    if not vcd.exists():
        return None
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tb" / "unit"))
    from rv_model import decode_ref  # noqa: PLC0415
    paths = sorted({p for _, p, _ in WAVE_SIGNALS} | {"rv_soc_sim.u_core.rst_i"})
    _, ch = read_vcd(vcd, paths)
    rises = [t for t, v in ch["rv_soc_sim.u_core.clk_i"] if v == "1"]
    rst_off = next((t for t, v in ch["rv_soc_sim.u_core.rst_i"] if v == "0"), 0)
    rises = [t for t in rises if t > rst_off]
    if len(rises) < 4:
        return None
    # each signal's value just before every rising edge = the value that cycle commits
    at = {p: [sample(ch[p], t - 1) for t in rises] for p in paths}
    pcs = [to_int(v) for v in at["rv_soc_sim.u_core.pc"]]
    nxt = [to_int(v) for v in at["rv_soc_sim.u_core.next_pc"]]
    first_jump = next((c for c, (a, b) in enumerate(zip(pcs, nxt)) if a is not None and b is not None
                       and b != (a + 4) & 0xFFFFFFFF and b != a), 0)
    c0 = max(0, first_jump - 6)
    c1 = min(len(rises), c0 + cycles)
    cycles = c1 - c0
    fig, ax = plt.subplots(figsize=(15, 0.5 * len(WAVE_SIGNALS) + 1.2))
    ax.set_xlim(0, cycles)
    ax.set_ylim(len(WAVE_SIGNALS), -0.2)
    ax.axis("off")
    for row, (label, path, kind) in enumerate(WAVE_SIGNALS):
        y_hi, y_lo, y_mid = row + 0.12, row + 0.78, row + 0.45
        ax.text(-0.15, y_mid, label, ha="right", va="center", fontsize=8.5, fontweight="bold",
                family="DejaVu Sans Mono")
        if kind == "clock":
            xs, ys = [], []
            for c in range(cycles):
                xs += [c, c + 0.5, c + 0.5, c + 1]
                ys += [y_lo, y_lo, y_hi, y_hi]
            ax.plot(xs, ys, color=INK, linewidth=1.1)
            continue
        vals = at[path][c0:c1]
        if kind == "bit":
            for c, v in enumerate(vals):
                y = y_hi if v == "1" else y_lo
                if v == "1":
                    ax.add_patch(Rectangle((c, y_hi), 1, y_lo - y_hi, facecolor=SERIES[0], alpha=0.14, linewidth=0))
                ax.plot([c, c + 1], [y, y], color=SERIES[0], linewidth=1.6)
                if c + 1 < len(vals) and vals[c + 1] != v:
                    ax.plot([c + 1, c + 1], [y_hi, y_lo], color=SERIES[0], linewidth=1.6)
            continue
        for c, v in enumerate(vals):
            n = to_int(v)
            new_seg = c == 0 or vals[c - 1] != v
            if new_seg:
                ax.plot([c, c + 0.06], [y_mid, y_hi], color=SERIES[0], linewidth=1)
                ax.plot([c, c + 0.06], [y_mid, y_lo], color=SERIES[0], linewidth=1)
                if n is None:
                    text = "x"
                elif kind == "mnemonic":
                    text = decode_ref(n)[0]
                elif kind == "dec":
                    text = f"x{n}"
                elif label in ("pc", "next_pc"):
                    text = f"{n & 0xFFFF:04x}"
                else:
                    text = f"{n:08x}"
                ax.text(c + 0.5, y_mid, text, ha="center", va="center", fontsize=6.8 if kind != "mnemonic" else 7.6,
                        family="DejaVu Sans Mono", color=INK, fontweight="bold" if kind == "mnemonic" else "normal")
            end_next = c + 1 < len(vals) and vals[c + 1] != v
            xa, xb = c + (0.06 if new_seg else 0), c + 1 - (0.06 if end_next else 0)
            ax.plot([xa, xb], [y_hi, y_hi], color=SERIES[0], linewidth=1)
            ax.plot([xa, xb], [y_lo, y_lo], color=SERIES[0], linewidth=1)
            if end_next:
                ax.plot([xb, c + 1], [y_hi, y_mid], color=SERIES[0], linewidth=1)
                ax.plot([xb, c + 1], [y_lo, y_mid], color=SERIES[0], linewidth=1)
    for c in range(cycles + 1):
        ax.axvline(c, color=GRID, linewidth=0.5, zorder=0)
    if c0 <= first_jump < c1:
        ax.axvspan(first_jump - c0, first_jump - c0 + 1, color=SERIES[3], alpha=0.12, zorder=0)
    ax.set_title(f"Waveform: sw/asm/{s['metrics']['program']}, cycles {c0}-{c1 - 1} after reset; shaded column = "
                 f"first taken branch/jump (cycle {first_jump}). Values just before each rising edge; pc/next_pc low 16 bits; "
                 f"cmp_true = branch comparator output", loc="left", fontsize=9.5, fontweight="bold")
    return save(fig, img / "waveform.png")


def chart_mutants(res: dict, img: Path) -> Path | None:
    s = stage(res, "mutants")
    if not s or not s["items"]:
        return None
    layers = s["metrics"]["layers"]
    items = s["items"]
    fig, ax = plt.subplots(figsize=(3.2 + 2.0 * len(layers), 0.5 * len(items) + 1.6))
    ax.set_xlim(0, len(layers) + 1)
    ax.set_ylim(len(items), -0.9)
    ax.axis("off")
    for j, layer in enumerate(layers):
        ax.text(j + 0.5, -0.35, layer, ha="center", fontweight="bold", fontsize=9)
    ax.text(len(layers) + 0.5, -0.35, "verdict", ha="center", fontweight="bold", fontsize=9)
    for i, it in enumerate(items):
        ax.text(-0.08, i + 0.5, it["name"], ha="right", va="center", fontsize=8.5, family="DejaVu Sans Mono")
        for j, layer in enumerate(layers):
            r = it["layers"].get(layer)
            if r is None:
                colour, text = MUTED, "build failed" if it["build"] != "ok" else "not run"
            elif r["killed"]:
                colour, text = GOOD if it["expect"] == "kill" else CRIT, f"caught {r['failing']}/{r['of']}"
            else:
                # one layer missing a bug is normal; the verdict column says whether ANY layer caught it
                colour, text = MUTED, f"not seen 0/{r['of']}"
            ax.add_patch(Rectangle((j + 0.04, i + 0.08), 0.92, 0.84, facecolor=colour, alpha=0.2, edgecolor=colour))
            ax.text(j + 0.5, i + 0.5, text, ha="center", va="center", fontsize=7.6)
        ok = it["ok"]
        verdict = ("OK caught" if it["killed"] else "OK not seen (expected)") if ok else \
                  ("MISSED (bug not caught)" if it["expect"] == "kill" else "UNEXPECTED catch")
        colour = GOOD if ok else CRIT
        ax.add_patch(Rectangle((len(layers) + 0.04, i + 0.08), 0.92, 0.84, facecolor=colour, alpha=0.2,
                               edgecolor=colour))
        ax.text(len(layers) + 0.5, i + 0.5, verdict, ha="center", va="center", fontsize=7.4, fontweight="bold")
    m = s["metrics"]
    ax.set_title(f"Self-check: {m['killed']}/{m['killable']} injected bugs caught (mutation score "
                 f"{m['mutation_score']} %); 'null' = unchanged design, must pass everything", loc="left",
                 fontsize=10, fontweight="bold")
    return save(fig, img / "mutants.png")


def chart_history(img: Path, history: Path) -> Path | None:
    if not history.exists():
        return None
    runs = [json.loads(l) for l in history.read_text(encoding="utf-8").splitlines() if l.strip()]
    if len(runs) < 2:
        return None
    runs = runs[-30:]
    fig, ax = plt.subplots(figsize=(10, 2.8))
    x = list(range(len(runs)))
    ax.bar(x, [r["seconds"] / 60 for r in runs], color=[STATUS.get(r["verdict"], MUTED) for r in runs], width=0.6,
           edgecolor=SURFACE, linewidth=2)
    for i, r in enumerate(runs):
        ax.text(i, r["seconds"] / 60, f"{r['verdict'].upper()}\n{r['profile']}", ha="center", va="bottom", fontsize=6.5)
    ax.set_xticks(x, [r["run_id"][4:13] for r in runs], rotation=45, fontsize=7)
    ax.set_ylabel("minutes")
    ax.grid(axis="x", visible=False)
    ax.set_title("Run history (bar colour: green pass, red fail)")
    return save(fig, img / "history.png")


# ---------------------------------------------------------------------------
# Report pages
# ---------------------------------------------------------------------------

def key_values(res: dict) -> list[tuple[str, str, str]]:
    """(label, value, note) tiles for the top of the report."""
    kv = []
    total = sum(s["total"] for s in res["stages"] if s["status"] != "skip")
    passed = sum(s["passed"] for s in res["stages"] if s["status"] != "skip")
    kv.append(("Verdict", res["verdict"].upper(), f"{sum(s['status'] == 'pass' for s in res['stages'])} stages pass, "
               f"{sum(s['status'] == 'fail' for s in res['stages'])} fail, {sum(s['status'] == 'skip' for s in res['stages'])} skipped"))
    kv.append(("Checks passed", f"{passed:,}/{total:,}", "every counted check across all stages"))
    u = stage(res, "unit")
    if u and u["total"]:
        kv.append(("Unit tests", f"{u['passed']}/{u['total']}", f"{len(u['items'])} blocks, cocotb on Icarus"))
    progs = [stage(res, n) for n in ("asm", "c", "rv32ui", "riscof")]
    pp = sum(s["passed"] for s in progs if s and s["status"] != "skip")
    pt = sum(s["total"] for s in progs if s and s["status"] != "skip")
    if pt:
        kv.append(("Programs vs. model", f"{pp}/{pt}", "asm, C, rv32ui" + (", arch-test" if stage(res, "riscof")["status"] != "skip" else "")))
    r = stage(res, "random")
    if r and r["total"]:
        cov = sum(1 for v in r["metrics"].get("per_instruction", {}).values() if v)
        kv.append(("Random programs", f"{r['passed']}/{r['total']}", f"{r['metrics'].get('instructions', 0):,} instr., {cov}/40 covered"))
    mu = stage(res, "mutants")
    if mu and mu["status"] != "skip":
        kv.append(("Injected bugs caught", f"{mu['metrics']['killed']}/{mu['metrics']['killable']}",
                   f"mutation score {mu['metrics']['mutation_score']} %"))
    b = stage(res, "bench")
    if b and b["status"] != "skip":
        for it in b["items"]:
            if "score" in it:
                kv.append((it["name"].capitalize(), f"{it['score']}", it["score_unit"]))
    sy = stage(res, "syn")
    if sy and sy["status"] == "pass":
        for v in sy["metrics"]["variants"]:
            kv.append((f"Fmax {v['variant']}", f"{v['fmax']:.1f} MHz", f"{v['comb']:,} TRELLIS_COMB"))
    kv.append(("Run time", f"{res['seconds'] / 60:.1f} min", f"profile {res['profile']}, {res['host']['jobs']} jobs"))
    return kv


def table_html(head: list[str], rows: list[list]) -> str:
    h = "".join(f"<th>{html.escape(str(c))}</th>" for c in head)
    body = "".join("<tr>" + "".join(f"<td>{c if str(c).startswith('<span') else html.escape(str(c))}</td>" for c in r)
                   + "</tr>" for r in rows)
    return f"<table><thead><tr>{h}</tr></thead><tbody>{body}</tbody></table>"


def badge(status: str) -> str:
    return f'<span class="b {status}">{ {"pass": "PASS", "fail": "FAIL", "skip": "skip"}[status] }</span>'


def render(run: Path) -> None:
    res = json.loads((run / "results.json").read_text(encoding="utf-8"))
    img = run / "img"
    images: list[tuple[str, Path]] = []

    def add(title: str, p):
        for q in (p if isinstance(p, list) else [p]):
            if q:
                images.append((title, q))

    add("Stages", chart_overview(res, img))
    add("Unit tests", chart_unit(res, img))
    add("Programs", chart_programs(res, img))
    add("Random programs", chart_random(res, img))
    add("Benchmarks", chart_bench(res, img))
    add("Synthesis", chart_syn(res, img))
    add("Waveform", chart_waveform(res, run, img))
    add("Self-check", chart_mutants(res, img))
    add("History", chart_history(img, run.parent / "history.jsonl"))

    kv = key_values(res)
    tiles = "".join(f'<div class="tile"><div class="k">{html.escape(k)}</div><div class="v">{html.escape(v)}</div>'
                    f'<div class="n">{html.escape(n)}</div></div>' for k, v, n in kv)
    stage_rows = [[badge(s["status"]), s["name"], s["title"], f"{s['passed']}/{s['total']}" if s["total"] else "",
                   f"{s['seconds']:.0f} s", s["summary"], s["log"]] for s in res["stages"]]
    sections = [f"<h2>Stages</h2>{table_html(['', 'stage', 'what', 'checks', 'time', 'result', 'log'], stage_rows)}"]
    for title, p in images:
        data = base64.b64encode(p.read_bytes()).decode()
        sections.append(f'<h2>{html.escape(title)}</h2><img alt="{html.escape(title)} chart" '
                        f'src="data:image/png;base64,{data}">')
    # detail tables (the table view of every chart)
    fails = [(s["name"], i) for s in res["stages"] for i in s["items"]
             if isinstance(i, dict) and i.get("ok") is False]
    if fails:
        sections.append("<h2>Failures</h2>" + table_html(["stage", "item", "problem"],
                        [[n, i.get("name", ""), i.get("problem", "") or i.get("what", "")] for n, i in fails]))
    u = stage(res, "unit")
    if u and u["items"]:
        sections.append("<h2>Unit tests per block</h2>" + table_html(
            ["block", "tests", "failed", "seconds"], [[b["block"], b["tests"], b["failed"], f"{b['seconds']:.2f}"]
                                                      for b in u["items"]]))
    mu = stage(res, "mutants")
    if mu and mu["items"]:
        layers = mu["metrics"]["layers"]
        sections.append("<h2>Injected bugs</h2>" + table_html(
            ["mutant", "bug", "expected", *layers, "result"],
            [[i["name"], i["what"] + (f" ({i['why']})" if i["why"] else ""), i["expect"],
              *[(("caught " if i["layers"][l]["killed"] else "missed ") + f"{i['layers'][l]['failing']}/{i['layers'][l]['of']}"
                 + (f": {', '.join(i['layers'][l]['first'])}" if i["layers"][l]["first"] else ""))
                if l in i["layers"] else i["build"] for l in layers],
              badge("pass" if i["ok"] else "fail")] for i in mu["items"]]))
    b = stage(res, "bench")
    if b and b["status"] != "skip" and b["items"]:
        sections.append("<h2>Benchmarks</h2>" + table_html(
            ["benchmark", "result", "cycles", "score", "ALU %", "load %", "store %", "branch %", "RAW d1 %",
             "load-use %", "mul/div %", ".text bytes"],
            [[i["name"], badge("pass" if i["ok"] else "fail"), f"{i['cycles']:,}" if i["cycles"] else "",
              f"{i['score']} {i['score_unit']}" if "score" in i else "",
              *([i["stats"]["mix"].get(c, 0) for c in ("ALU", "load", "store", "branch")] +
                [i["stats"]["raw"]["1"], i["stats"]["load_use"], i["stats"]["muldiv"], f"{i['stats']['text']:,}"]
                if "stats" in i else [""] * 8)] for i in b["items"]]))
    env = stage(res, "env")
    if env and env["items"]:
        sections.append("<h2>Tools</h2>" + table_html(["tool", "state", "version"],
                        [[i["tool"], i["state"], i["version"]] for i in env["items"]]))

    css = f"""body{{font-family:Segoe UI,DejaVu Sans,sans-serif;background:{SURFACE};color:{INK};margin:24px auto;max-width:1400px;padding:0 16px}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:16px;margin:28px 0 8px;border-bottom:1px solid {GRID};padding-bottom:4px}}
.sub{{color:{INK2};margin-bottom:16px}} .tiles{{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:10px}}
.tile{{border:1px solid {GRID};border-radius:8px;padding:10px 12px;background:#fff}} .k{{color:{INK2};font-size:12px}}
.v{{font-size:22px;font-weight:700;margin:2px 0}} .n{{color:{INK2};font-size:11px}}
img{{max-width:100%;border:1px solid {GRID};border-radius:6px;background:#fff}}
table{{border-collapse:collapse;font-size:12px;width:100%}} th,td{{border-bottom:1px solid {GRID};padding:4px 6px;text-align:left;vertical-align:top}}
th{{color:{INK2};font-weight:600}} .b{{font-weight:700;padding:1px 6px;border-radius:4px;font-size:11px}}
.b.pass{{background:#e3f4e3;color:#0a6e0a}} .b.fail{{background:#fbe4e4;color:#a12a2a}} .b.skip{{background:#efeeea;color:{INK2}}}"""
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>RV32I core evaluation {res['run_id']}</title>
<style>{css}</style></head><body>
<h1>RV32I core evaluation: {badge(res['verdict'])}</h1>
<div class="sub">Run {res['run_id']} &middot; profile {res['profile']} &middot; commit {html.escape(res['git']['commit'])}
{' (uncommitted changes)' if res['git']['dirty'] else ''} &middot; {html.escape(res['git']['subject'])} &middot;
started {res['started']} &middot; {res['seconds'] / 60:.1f} min &middot; {html.escape(res['host']['os'])}</div>
<div class="tiles">{tiles}</div>
{''.join(sections)}
<p class="sub">Generated by scripts/evaluate.py; data in results.json; logs in logs/.</p></body></html>"""
    (run / "report.html").write_text(page, encoding="utf-8")

    md = [f"# Evaluation {res['run_id']}: {res['verdict'].upper()}", "",
          f"Profile {res['profile']}, commit {res['git']['commit']}{' (dirty)' if res['git']['dirty'] else ''}, "
          f"{res['seconds'] / 60:.1f} min.", "", "| Key value | | |", "|---|---:|---|"]
    md += [f"| {k} | {v} | {n} |" for k, v, n in kv]
    md += ["", "| Stage | Status | Checks | Time | Result |", "|---|---|---:|---:|---|"]
    md += [f"| {s['name']} | {s['status'].upper()} | {s['passed']}/{s['total']} | {s['seconds']:.0f} s | {s['summary']} |"
           for s in res["stages"]]
    md += ["", "Images: " + ", ".join(f"img/{p.name}" for _, p in images)]
    (run / "report.md").write_text("\n".join(md) + "\n", encoding="utf-8")


if __name__ == "__main__":
    render(Path(sys.argv[1]).resolve())
