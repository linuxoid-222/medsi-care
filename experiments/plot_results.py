"""Export research figures from an archived JSON, without rerunning detectors."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


METHOD_LABELS = {"baseline_a": "Baseline A", "baseline_b": "Baseline B",
                 "method_c_no_text": "C without text", "method_c": "Method C"}
COLORS = ("#486580", "#bc7d31", "#6e699a", "#248073")


def plot(result_path: Path, output_dir: Path) -> None:
    report = json.loads(result_path.read_text())
    metrics = report["metrics"]
    evaluation = report["evaluation"]
    n_profiles = len(report["split"]["test_profile_ids"])
    caption = f"SYNTHETIC / HELD-OUT · {n_profiles} profiles · {evaluation['person_days']} person-days"
    output_dir.mkdir(parents=True, exist_ok=True)
    targets = [output_dir / f"{name}.{ext}" for name in (
        "precision_recall_f1", "false_alerts", "timeline"
    ) for ext in ("png", "svg")]
    manifest_path = output_dir / "manifest.json"
    if any(path.exists() for path in targets + [manifest_path]):
        raise FileExistsError("figure output already exists; choose a new directory")
    plt.rcParams.update({"font.size": 11, "svg.fonttype": "none", "axes.spines.top": False,
                         "axes.spines.right": False, "savefig.dpi": 180})

    def save(fig, name):
        for extension in ("png", "svg"):
            fig.savefig(output_dir / f"{name}.{extension}", bbox_inches="tight")
        plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 5.8), layout="constrained")
    positions = np.arange(len(metrics))
    for index, (key, color) in enumerate(zip(("precision", "recall", "f1"), COLORS)):
        bars = ax.bar(positions + (index - 1) * .24, [row[key] for row in metrics],
                      width=.24, label=key.title(), color=color)
        ax.bar_label(bars, fmt="%.3f", fontsize=10, padding=3)
    ax.set(xticks=positions, xticklabels=[METHOD_LABELS[row["method"]] for row in metrics],
           ylim=(0, 1.12), ylabel="Score (0–1)", title="Precision / Recall / F1\n" + caption)
    ax.legend(loc="upper right", ncols=3)
    fig.supxlabel("One seed; descriptive results; no confidence intervals", fontsize=10)
    save(fig, "precision_recall_f1")

    fig, ax = plt.subplots(figsize=(11, 5.8), layout="constrained")
    bars = ax.bar(positions, [row["false_alerts_per_100_person_days"] for row in metrics], color=COLORS)
    for bar, row in zip(bars, metrics):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + .18,
                f"{row['false_alerts_per_100_person_days']:.3f}\nFP={row['false_positives']}",
                ha="center", va="bottom")
    ax.set(xticks=positions, xticklabels=[METHOD_LABELS[row["method"]] for row in metrics],
           ylabel="False alert-days per 100 person-days",
           ylim=(0, max(row["false_alerts_per_100_person_days"] for row in metrics) * 1.28 + 1),
           title="False alert rate\n" + caption)
    fig.supxlabel(f"FP / {evaluation['person_days']} × 100; includes warm-up and insufficient_data; repeated days counted", fontsize=10)
    save(fig, "false_alerts")

    # Selection is fixed by scenario name and ID ordering, never by performance.
    records = report["held_out_records"]
    candidates = sorted({row["profile_id"] for row in records if row["scenario_type"] == "multimodal"})
    if not candidates:
        candidates = sorted({row["profile_id"] for row in records if row["change_start_day"] is not None})
    profile_id = candidates[0] if candidates else sorted({row["profile_id"] for row in records})[0]
    rows = sorted((row for row in records if row["profile_id"] == profile_id), key=lambda row: row["day_index"])
    days = [row["day_index"] for row in rows]
    onset = rows[0]["change_start_day"]
    fig, axes = plt.subplots(5, 1, figsize=(12, 11), sharex=True, layout="constrained",
                             gridspec_kw={"height_ratios": [1, 1, 1, .8, 1.3]})
    fig.suptitle(f"Example history · {profile_id} · {rows[0]['scenario_type']}\n{caption}")
    for ax, key, label, color in zip(axes[:3], ("sleep_hours", "activity_minutes", "pulse_bpm"),
                                     ("Sleep (hours)", "Activity (min)", "Pulse (bpm)"), COLORS):
        ax.plot(days, [row[key] if row[key] is not None else np.nan for row in rows],
                marker="o", markersize=3, color=color)
        ax.set_ylabel(label)
        ax.grid(alpha=.2)
    extracted = {row["day_index"]: row for row in report["extractions"] if row["profile_id"] == profile_id}
    polarity_codes = {"present": 1, "absent": -1, "uncertain": .5}
    fact_values = [next((polarity_codes[fact["polarity"]] for fact in extracted[day]["facts"]
                         if fact["category"] == "weakness"), 0) for day in days]
    axes[3].step(days, fact_values, where="post", color=COLORS[-1])
    axes[3].set(yticks=[-1, 0, .5, 1], yticklabels=["absent", "none", "uncertain", "present"],
                ylabel="Text fact", ylim=(-1.25, 1.25))
    for index, row in enumerate(metrics):
        method = row["method"]
        predictions = [item for item in report["predictions"][method] if item["profile_id"] == profile_id]
        axes[4].scatter([item["day_index"] for item in predictions if item["attention"]],
                        [index] * sum(item["attention"] for item in predictions),
                        marker="s", color=COLORS[index], s=35)
        axes[4].scatter([item["day_index"] for item in predictions if item["insufficient_data"]],
                        [index] * sum(item["insufficient_data"] for item in predictions),
                        marker="x", color="#888888", s=26)
    axes[4].set(yticks=range(len(metrics)), yticklabels=[METHOD_LABELS[row["method"]] for row in metrics],
                ylabel="Alert-days", ylim=(-.6, len(metrics) - .4), xlabel="Day index (0-based); square = alert, × = insufficient_data")
    for ax in axes:
        if onset is not None:
            ax.axvline(onset, ls="--", color="#a43838", linewidth=1.4)
        ax.set_xlim(-.5, max(days) + .5)
    axes[0].text(.01, .95, f"Dashed red line: ground-truth onset, day {onset}",
                 transform=axes[0].transAxes, va="top", fontsize=10)
    save(fig, "timeline")
    manifest = {"result": str(result_path), "result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
                "source_commit": report["provenance"]["commit"], "matplotlib": matplotlib.__version__,
                "example_profile_id": profile_id,
                "example_selection": "lexicographically first held-out multimodal profile; fallback first onset profile",
                "figures_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in targets}}
    with manifest_path.open("x") as output:
        output.write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    plot(args.result, args.output_dir)
