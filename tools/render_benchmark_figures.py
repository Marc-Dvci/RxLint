"""Render the judge-facing comparison from frozen reports, without running inference.

    pip install -e ".[bench]"
    python tools/render_benchmark_figures.py
"""
from pathlib import Path
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter, MaxNLocator

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    comparison = json.loads((ROOT / "benchmarks/results/review_comparison.json").read_text(encoding="utf-8"))
    baseline = json.loads((ROOT / "benchmarks/results/bench_tf-deepseek-nemotron-nano.json").read_text(encoding="utf-8"))
    current = json.loads((ROOT / "benchmarks/results/bench_tf-review-v4-nano.json").read_text(encoding="utf-8"))
    assert comparison["test_cases"] == baseline["scores"]["test"]["rxlint_head"]["cases"] == current["scores"]["test"]["rxlint_head"]["cases"]
    assert comparison["after"] == current["scores"]["test"]["rxlint_head"]
    assert comparison["field_exact_after"] == current["perception"]["test"]["field_exact"]
    before, after = comparison["before"], comparison["after"]
    cases = comparison["test_cases"]
    panels = [
        ("Cases needing confirmation", "Lower is better", [before["confirmation_requests"] * 100, after["confirmation_requests"] * 100],
         [f"{round(before['confirmation_requests'] * cases)}/{cases}  (50.83%)", f"{round(after['confirmation_requests'] * cases)}/{cases}  (45.0%)"], True),
        ("Incorrect high-risk accepts", "Lower is better", [comparison["wrong_high_risk_before"], comparison["wrong_high_risk_after"]], ["2", "0"], False),
        ("Exact dose reading", "Higher is better", [comparison["field_exact_before"]["rx.dose"] * 100, comparison["field_exact_after"]["rx.dose"] * 100], ["70.0%", "82.5%"], True),
        ("Exact label-strength reading", "Higher is better", [comparison["field_exact_before"]["dispensed.strength"] * 100, comparison["field_exact_after"]["dispensed.strength"] * 100], ["80.0%", "93.3%"], True),
    ]
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "svg.fonttype": "none"})
    fig, axes = plt.subplots(1, 4, figsize=(16, 5.5), dpi=120, facecolor="#fcfcfb")
    fig.subplots_adjust(left=.045, right=.975, top=.66, bottom=.31, wspace=.52)
    fig.text(.04, .91, "Stronger reading. Fewer confirmations.", fontsize=25, weight="bold", color="#14201d")
    fig.text(.04, .84, "Same 120 held-out cases | PP-OCRv6 + focused crop recovery + validation-calibrated reliability gate", fontsize=11, color="#53615a")
    fig.text(.04, .77, "PREVIOUS VERSION", fontsize=10, weight="bold", color="#818c87")
    fig.text(.215, .77, "CURRENT VERSION", fontsize=10, weight="bold", color="#29783f")
    for ax, (title, direction, values, labels, percent) in zip(axes, panels):
        ax.set_facecolor("#fcfcfb")
        ax.set_title(title + "\n" + direction, loc="left", fontsize=11, pad=15)
        limit = 140 if percent else 3.6
        ax.set_xlim(0, limit)
        ax.set_ylim(-.65, 1.65)
        ax.set_yticks([])
        ax.set_axisbelow(True)
        ax.grid(axis="x", color="#e6e9e4", linewidth=.8)
        ax.tick_params(axis="x", colors="#7c8580", labelsize=8, length=0, pad=7)
        if percent:
            ax.set_xticks([0, 25, 50, 75, 100])
            ax.xaxis.set_major_formatter(PercentFormatter(100, decimals=0))
        else:
            ax.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=3))
            ax.set_xticks([0, 1, 2, 3])
        for spine in ax.spines.values():
            spine.set_visible(False)
        for y, value, label, color in zip([1, 0], values, labels, ["#b4bdb7", "#69a735"]):
            ax.barh(y, value, height=.36, color=color, zorder=3)
            if value == 0:
                ax.plot([0, 0], [y - .18, y + .18], linewidth=3, color=color, zorder=3)
            ax.text(value + (3 if percent else .13), y, label, va="center", fontsize=10, weight="bold" if y == 0 else "normal", color="#15231c", clip_on=False)
    fig.text(.04, .20, "Current: 95.0% exact verdicts after simulated confirmation | 9/10 overwritten doses held | 0/80 false-safe cases", fontsize=11, weight="bold", color="#203a28")
    fig.text(.04, .125, "Head frozen before test extraction. High-risk readings: 566 previous, 677 current; incorrect accepts are counts, not rates.", fontsize=9, color="#68746d")
    fig.text(.04, .075, "Full comparison: exact verdicts 115/120 to 114/120; clean PASS after confirmation 40/40 to 38/40. Rendered benchmark, not clinical validation.", fontsize=9, color="#68746d")
    fig.savefig(ROOT / "docs/img/benchmark_improvements.png", dpi=120, facecolor=fig.get_facecolor())
    svg = ROOT / "docs/figures/benchmark_improvements.svg"
    fig.savefig(svg, facecolor=fig.get_facecolor())
    svg.write_text("\n".join(line.rstrip() for line in svg.read_text(encoding="utf-8").splitlines()) + "\n", encoding="utf-8")
    plt.close(fig)


if __name__ == "__main__":
    main()
