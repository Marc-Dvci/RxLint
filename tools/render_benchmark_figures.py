"""Render current field accuracy from the frozen report, without inference or fitting."""
from pathlib import Path
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    report = json.loads((ROOT / "benchmarks/results/bench_tf-review-v4-nano.json").read_text(encoding="utf-8"))
    fields = report["perception"]["test"]["field_exact"]
    cases = report["scores"]["test"]["rxlint_head"]["cases"]
    measures = [("Prescription dose", "rx.dose"), ("Patient weight", "rx.patient_weight"),
                ("Label strength", "dispensed.strength"), ("Expiry date", "dispensed.expiry")]
    values = [100 * fields[key] for _, key in measures]
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 12, "svg.fonttype": "none"})
    fig, ax = plt.subplots(figsize=(13.33, 5.5), dpi=120, facecolor="#fcfcfb")
    fig.subplots_adjust(left=.18, right=.93, top=.70, bottom=.24)
    fig.text(.045, .91, "Reading the facts behind the verdict", fontsize=24, weight="bold", color="#14201d")
    fig.text(.045, .83, f"Exact field reading on {cases} held-out rendered prescription and bottle cases", fontsize=12, color="#53615a")
    ax.set_facecolor("#fcfcfb")
    ax.barh(range(len(values)), values, height=.5, color="#2a78d6", zorder=3)
    ax.set_yticks(range(len(values)), [label for label, _ in measures])
    ax.invert_yaxis()
    ax.set_xlim(0, 108)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.xaxis.set_major_formatter(PercentFormatter(100, decimals=0))
    ax.tick_params(length=0, pad=10, colors="#53615a")
    ax.set_axisbelow(True)
    ax.grid(axis="x", color="#e6e9e4", linewidth=.8)
    for spine in ax.spines.values():
        spine.set_visible(False)
    for i, value in enumerate(values):
        ax.text(value + 1.5, i, f"{value:.1f}%", va="center", weight="bold", color="#14201d")
    fig.text(.045, .13, "PP-OCRv6 corroboration + focused crop reads + validation-calibrated reliability gate", fontsize=11, color="#203a28")
    fig.text(.045, .065, "Field accuracy is measured before human confirmation. Rendered benchmark; not clinical validation.", fontsize=10, color="#68746d")
    fig.savefig(ROOT / "docs/img/benchmark_fields.png", facecolor=fig.get_facecolor())
    svg = ROOT / "docs/figures/benchmark_fields.svg"
    fig.savefig(svg, facecolor=fig.get_facecolor())
    svg.write_text("\n".join(line.rstrip() for line in svg.read_text(encoding="utf-8").splitlines()) + "\n", encoding="utf-8")
    plt.close(fig)


if __name__ == "__main__":
    main()
