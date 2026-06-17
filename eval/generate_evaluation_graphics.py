#!/usr/bin/env python3
"""Generate thesis-ready graphics for semantic annotation and VKG results."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path(tempfile.gettempdir()) / "fvkg-json-matplotlib"),
)
os.environ.setdefault(
    "XDG_CACHE_HOME",
    str(Path(tempfile.gettempdir()) / "fvkg-json-cache"),
)

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
except ImportError as exc:
    print(
        "Matplotlib and NumPy are required. Run this script from an "
        "environment that provides them, for example:\n"
        "  /opt/miniconda3/envs/ml-env/bin/python "
        "eval/generate_evaluation_graphics.py",
        file=sys.stderr,
    )
    raise SystemExit(2) from exc


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SEMANTIC_DIR = (
    PROJECT_ROOT / "eval" / "semantic_anotation" / "results"
)
DEFAULT_VKG_DIR = PROJECT_ROOT / "eval" / "vkg" / "results"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "eval" / "graphics"

VARIANT_ORDER = [
    "baseline",
    "binding_injection_random",
    "final",
]
VARIANT_LABELS = {
    "baseline": "No pushdown\n(static)",
    "binding_injection_random": "No order heuristic\n(random)",
    "final": "Final",
}
VARIANT_COLORS = {
    "baseline": "#7A869A",
    "binding_injection_random": "#F2A65A",
    "final": "#2A9D8F",
}
SOURCE_ORDER = ["baseline", "local", "notlocal", "proposal"]
SOURCE_LABELS = {
    "baseline": "Frozen embedding",
    "local": "Local ontology",
    "notlocal": "External ontology",
    "proposal": "New axiom proposal",
}
SOURCE_COLORS = {
    "baseline": "#7A869A",
    "local": "#457B9D",
    "notlocal": "#F2A65A",
    "proposal": "#2A9D8F",
}
SEMANTIC_RUN_ORDER = {
    "english-minilm-l6__embeddings": 0,
    "multilingual-distiluse__embeddings": 1,
    "multilingual-minilm-l12__embeddings": 2,
    "multilingual-minilm-l12__gpt-oss-20b": 3,
    "multilingual-minilm-l12__gpt-oss-120b": 4,
    "multilingual-minilm-l12__llama-3.3-70b": 5,
}
EXCLUDED_VKG_QUERY_IDS = {
    # Q07 depends on a mandatory WCS BBOX binding, so it is outside the
    # optional-pushdown benchmark comparison.
    "q07",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create graphics from semantic annotation JSON results and VKG "
            "benchmark CSV results."
        )
    )
    parser.add_argument(
        "--semantic-results-dir",
        type=Path,
        default=DEFAULT_SEMANTIC_DIR,
        help=f"Semantic result directory (default: {DEFAULT_SEMANTIC_DIR}).",
    )
    parser.add_argument(
        "--vkg-results-dir",
        type=Path,
        default=DEFAULT_VKG_DIR,
        help=f"VKG result directory (default: {DEFAULT_VKG_DIR}).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Figure output directory (default: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--formats",
        nargs="+",
        choices=("png", "pdf", "svg"),
        default=("png", "pdf"),
        help="Output formats (default: png pdf).",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=220,
        help="PNG resolution in dots per inch (default: 220).",
    )
    parser.add_argument(
        "--only",
        choices=("all", "semantic", "vkg"),
        default="all",
        help="Generate all figures or only one evaluation family.",
    )
    args = parser.parse_args()
    if args.dpi < 72:
        parser.error("--dpi must be at least 72.")
    return args


def configure_plot_style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.edgecolor": "#334155",
            "axes.labelcolor": "#1E293B",
            "axes.titlecolor": "#0F172A",
            "axes.titleweight": "bold",
            "axes.grid": True,
            "axes.axisbelow": True,
            "grid.color": "#CBD5E1",
            "grid.alpha": 0.55,
            "grid.linewidth": 0.7,
            "xtick.color": "#334155",
            "ytick.color": "#334155",
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "legend.frameon": False,
            "savefig.bbox": "tight",
        }
    )


def save_figure(
    fig: Any,
    output_dir: Path,
    stem: str,
    formats: Iterable[str],
    dpi: int,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for output_format in dict.fromkeys(formats):
        path = output_dir / f"{stem}.{output_format}"
        options = {"dpi": dpi} if output_format == "png" else {}
        fig.savefig(path, **options)
        paths.append(path)
    plt.close(fig)
    return paths


def load_semantic_results(results_dir: Path) -> list[dict[str, Any]]:
    result_paths = sorted(results_dir.glob("*/results.json"))
    if not result_paths:
        raise FileNotFoundError(
            f"No semantic results.json files found below {results_dir}."
        )

    results = []
    for path in result_paths:
        with path.open(encoding="utf-8") as source:
            result = json.load(source)
        if "statistics" not in result or "run_name" not in result:
            raise ValueError(f"Unsupported semantic result schema: {path}")
        result["_source_path"] = str(path.resolve())
        results.append(result)

    def sort_key(result: dict[str, Any]) -> tuple[int, str]:
        run_name = str(result.get("run_name", "unknown"))
        return (SEMANTIC_RUN_ORDER.get(run_name, len(SEMANTIC_RUN_ORDER)), run_name)

    return sorted(results, key=sort_key)


def semantic_label(
    result: dict[str, Any], *, include_llm_embedding_context: bool = False
) -> str:
    run_name = str(result.get("run_name", "unknown"))
    aliases = {
        "english-minilm-l6__embeddings": "English\nMiniLM L6",
        "multilingual-distiluse__embeddings": "Multilingual\nDistilUSE",
        "multilingual-minilm-l12__embeddings": "Multilingual\nMiniLM L12",
        "multilingual-minilm-l12__gpt-oss-20b": "GPT-OSS\n20B",
        "multilingual-minilm-l12__gpt-oss-120b": "GPT-OSS\n120B",
        "multilingual-minilm-l12__llama-3.3-70b": "Llama 3.3\n70B",
    }
    if include_llm_embedding_context and result.get("configuration", {}).get(
        "mode"
    ) == "llm":
        llm_label = aliases.get(run_name, run_name.split("__")[-1])
        return f"{llm_label} +\nMultilingual\nMiniLM L12"
    return aliases.get(run_name, run_name.replace("__", "\n"))


def semantic_entity_stats(
    result: dict[str, Any], entity_type: str
) -> dict[str, Any]:
    return result["statistics"]["entities"][entity_type]


def plot_semantic_alignment_coverage(
    results: list[dict[str, Any]],
) -> tuple[Any, str]:
    labels = [
        semantic_label(result, include_llm_embedding_context=True)
        for result in results
    ]
    x = np.arange(len(results))
    width = 0.36
    class_rates = []
    property_rates = []
    class_counts = []
    property_counts = []

    for result in results:
        class_stats = semantic_entity_stats(result, "class")
        property_stats = semantic_entity_stats(result, "property")
        class_rates.append(100 * class_stats["aligned"] / class_stats["total"])
        property_rates.append(
            100 * property_stats["aligned"] / property_stats["total"]
        )
        class_counts.append((class_stats["aligned"], class_stats["total"]))
        property_counts.append(
            (property_stats["aligned"], property_stats["total"])
        )

    fig, ax = plt.subplots(figsize=(11.5, 5.8))
    class_bars = ax.bar(
        x - width / 2,
        class_rates,
        width,
        label="Classes",
        color="#457B9D",
    )
    property_bars = ax.bar(
        x + width / 2,
        property_rates,
        width,
        label="Properties",
        color="#E9C46A",
    )
    for bars, counts in (
        (class_bars, class_counts),
        (property_bars, property_counts),
    ):
        for bar, (aligned, total) in zip(bars, counts):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 1.2,
                f"{aligned}/{total}",
                ha="center",
                va="bottom",
                fontsize=8.5,
            )

    ax.set_title("Semantic annotation alignment coverage")
    ax.set_ylabel("Aligned entities (%)")
    ax.set_xticks(x, labels)
    ax.set_ylim(0, max(100, max(class_rates + property_rates) + 12))
    ax.legend(ncols=2, loc="upper left")
    ax.grid(axis="x", visible=False)
    fig.tight_layout()
    return fig, "semantic_alignment_coverage"


def plot_semantic_alignment_sources(
    results: list[dict[str, Any]],
) -> tuple[Any, str]:
    labels = [semantic_label(result) for result in results]
    x = np.arange(len(results))
    totals = {source: [] for source in SOURCE_ORDER}
    for result in results:
        for source in SOURCE_ORDER:
            count = sum(
                semantic_entity_stats(result, entity_type)
                .get("by_source", {})
                .get(source, 0)
                for entity_type in ("class", "property")
            )
            totals[source].append(count)

    fig, ax = plt.subplots(figsize=(11.5, 5.8))
    bottom = np.zeros(len(results))
    for source in SOURCE_ORDER:
        values = np.asarray(totals[source])
        bars = ax.bar(
            x,
            values,
            bottom=bottom,
            label=SOURCE_LABELS[source],
            color=SOURCE_COLORS[source],
        )
        for bar, value, base in zip(bars, values, bottom):
            if value:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    base + value / 2,
                    str(int(value)),
                    ha="center",
                    va="center",
                    fontsize=8.5,
                    color="white" if source != "notlocal" else "#1E293B",
                    fontweight="bold",
                )
        bottom += values

    ax.set_title("Sources of accepted semantic alignments")
    ax.set_ylabel("Aligned classes and properties")
    ax.set_xticks(x, labels)
    ax.legend(ncols=2, loc="upper left")
    ax.grid(axis="x", visible=False)
    fig.tight_layout()
    return fig, "semantic_alignment_sources"


def plot_semantic_runtime(
    results: list[dict[str, Any]],
) -> tuple[Any, str]:
    labels = [semantic_label(result) for result in results]
    durations = [float(result.get("duration_seconds", 0)) / 60 for result in results]
    colors = [
        "#457B9D"
        if result.get("configuration", {}).get("mode") == "embeddings"
        else "#2A9D8F"
        for result in results
    ]

    fig, ax = plt.subplots(figsize=(11.5, 5.5))
    bars = ax.bar(np.arange(len(results)), durations, color=colors)
    for bar, value in zip(bars, durations):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + 0.18,
            f"{value:.1f}",
            ha="center",
            va="bottom",
            fontsize=9,
        )
    ax.set_title("Semantic annotation execution time")
    ax.set_ylabel("Duration (minutes)")
    ax.set_xticks(np.arange(len(results)), labels)
    ax.grid(axis="x", visible=False)
    fig.tight_layout()
    return fig, "semantic_runtime"


def plot_embedding_reviews(
    results: list[dict[str, Any]],
) -> tuple[Any, str] | None:
    embedding_results = [
        result
        for result in results
        if result.get("configuration", {}).get("mode") == "embeddings"
    ]
    if not embedding_results:
        return None

    labels = [semantic_label(result) for result in embedding_results]
    candidate_reviews = []
    accepted = []
    for result in embedding_results:
        reviews = result.get("embedding_reviews", [])
        candidate_reviews.append(
            sum(bool(review.get("candidates")) for review in reviews)
        )
        accepted.append(
            sum(bool(review.get("selected_iri")) for review in reviews)
        )

    x = np.arange(len(embedding_results))
    width = 0.36
    fig, ax = plt.subplots(figsize=(8.8, 5.4))
    reviewed_bars = ax.bar(
        x - width / 2,
        candidate_reviews,
        width,
        label="Entities with candidates",
        color="#7A869A",
    )
    accepted_bars = ax.bar(
        x + width / 2,
        accepted,
        width,
        label="Accepted alignments",
        color="#2A9D8F",
    )
    ax.bar_label(reviewed_bars, padding=3, fontsize=9)
    ax.bar_label(accepted_bars, padding=3, fontsize=9)
    ax.set_title("Embedding candidate review outcomes")
    ax.set_ylabel("Entities")
    ax.set_xticks(x, labels)
    ax.legend(ncols=2, loc="upper right")
    ax.grid(axis="x", visible=False)
    fig.tight_layout()
    return fig, "semantic_embedding_reviews"


def plot_llm_review(
    results: list[dict[str, Any]],
) -> tuple[Any, str] | None:
    llm_results = [
        result
        for result in results
        if result.get("configuration", {}).get("mode") == "llm"
    ]
    if not llm_results:
        return None

    labels = [semantic_label(result) for result in llm_results]
    metric_specs = [
        ("proposals_reviewed", "Reviewed", "#7A869A"),
        ("proposals_accepted", "Accepted", "#2A9D8F"),
        ("proposals_denied", "Denied", "#E76F51"),
        ("triples_accepted", "Axiom triples accepted", "#457B9D"),
    ]
    x = np.arange(len(llm_results))
    width = 0.19
    fig, ax = plt.subplots(figsize=(9.5, 5.5))
    for index, (key, label, color) in enumerate(metric_specs):
        values = [
            result["statistics"].get("llm_axiom_review", {}).get(key, 0)
            for result in llm_results
        ]
        offset = (index - (len(metric_specs) - 1) / 2) * width
        bars = ax.bar(x + offset, values, width, label=label, color=color)
        ax.bar_label(bars, padding=2, fontsize=8)

    ax.set_title("LLM axiom proposal review")
    ax.set_ylabel("Count")
    ax.set_xticks(x, labels)
    ax.legend(ncols=2, loc="upper left")
    ax.grid(axis="x", visible=False)
    fig.tight_layout()
    return fig, "semantic_llm_review"


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Required VKG result file not found: {path}")
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def load_vkg_runs(results_dir: Path) -> list[dict[str, Any]]:
    raw_runs = read_csv(results_dir / "runs.csv")
    numeric_fields = {
        "execution_order": int,
        "repetition": int,
        "timeout_seconds": float,
        "total_time_seconds": float,
        "api_time_seconds": float,
        "engine_time_seconds": float,
        "api_calls": float,
        "api_response_bytes": float,
        "intermediate_triples": float,
        "triple_add_attempts": float,
        "result_rows": float,
    }
    runs = []
    for raw_run in raw_runs:
        run: dict[str, Any] = dict(raw_run)
        for field, converter in numeric_fields.items():
            value = raw_run.get(field, "")
            run[field] = converter(value) if value not in ("", None) else None
        if str(run["query_id"]) in EXCLUDED_VKG_QUERY_IDS:
            continue
        runs.append(run)
    if not runs:
        raise ValueError(f"No VKG runs found in {results_dir / 'runs.csv'}.")

    expected_hashes: dict[str, str] = {}
    for query in {str(run["query_id"]) for run in runs}:
        hashes = [
            str(run["result_hash"])
            for run in runs
            if run["query_id"] == query
            and run["status"] == "success"
            and run.get("result_hash")
        ]
        if hashes:
            expected_hashes[query] = max(set(hashes), key=hashes.count)
    for run in runs:
        expected_hash = expected_hashes.get(str(run["query_id"]))
        run["valid_result"] = (
            run["status"] == "success"
            and bool(expected_hash)
            and run.get("result_hash") == expected_hash
        )
    return runs


def ordered_queries(runs: list[dict[str, Any]]) -> list[str]:
    return sorted({str(run["query_id"]) for run in runs})


def present_variants(runs: list[dict[str, Any]]) -> list[str]:
    present = {str(run["variant"]) for run in runs}
    return [variant for variant in VARIANT_ORDER if variant in present] + sorted(
        present - set(VARIANT_ORDER)
    )


def grouped_values(
    runs: list[dict[str, Any]],
    *,
    metric: str,
    successful_only: bool,
) -> dict[tuple[str, str], list[float]]:
    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    for run in runs:
        if successful_only and not run.get("valid_result"):
            continue
        value = run.get(metric)
        if value is not None:
            grouped[(run["query_id"], run["variant"])].append(float(value))
    return grouped


def plot_vkg_runtime(runs: list[dict[str, Any]]) -> tuple[Any, str]:
    queries = ordered_queries(runs)
    variants = present_variants(runs)
    grouped = grouped_values(
        runs, metric="total_time_seconds", successful_only=True
    )
    x = np.arange(len(queries))
    width = 0.8 / len(variants)

    fig, ax = plt.subplots(figsize=(12, 6.1))
    timeout_label_added = False
    for index, variant in enumerate(variants):
        means = []
        deviations = []
        annotations = []
        timeout_means = []
        for query in queries:
            values = grouped.get((query, variant), [])
            means.append(statistics.fmean(values) if values else 0)
            deviations.append(
                statistics.stdev(values) if len(values) > 1 else 0
            )
            executed = [
                run
                for run in runs
                if run["query_id"] == query and run["variant"] == variant
            ]
            valid = sum(bool(run.get("valid_result")) for run in executed)
            annotations.append(f"{valid}/{len(executed)}")
            timeout_values = [
                float(run["total_time_seconds"])
                for run in executed
                if run["status"] == "timeout"
                and run.get("total_time_seconds") is not None
            ]
            timeout_means.append(
                statistics.fmean(timeout_values) if timeout_values else 0
            )

        positions = x + (index - (len(variants) - 1) / 2) * width
        if any(timeout_means):
            ax.bar(
                positions,
                timeout_means,
                width,
                facecolor="none",
                edgecolor="#B91C1C",
                linewidth=1.25,
                hatch="//",
                label=(
                    "Timed-out executions"
                    if not timeout_label_added
                    else "_nolegend_"
                ),
                zorder=1,
            )
            timeout_label_added = True
        bars = ax.bar(
            positions,
            means,
            width,
            yerr=deviations,
            capsize=2.5,
            color=VARIANT_COLORS.get(variant, "#64748B"),
            label=VARIANT_LABELS.get(variant, variant),
            zorder=2,
        )
        for bar, annotation, timeout_mean in zip(
            bars, annotations, timeout_means
        ):
            label_height = max(bar.get_height(), timeout_mean)
            if label_height > 0:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    label_height + 11,
                    annotation,
                    ha="center",
                    va="bottom",
                    fontsize=7.5,
                    rotation=90,
                )

    ax.set_title("VKG valid execution time by query")
    ax.set_ylabel("Mean valid-run time (seconds)")
    ax.set_xticks(x, [query.upper() for query in queries])
    ax.set_ylim(0, 690)
    ax.legend(ncols=4, loc="upper center")
    ax.text(
        0.01,
        0.98,
        "Solid bars show valid-run means; red hatched bars mark timed-out runs.",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=8.5,
        color="#475569",
    )
    ax.grid(axis="x", visible=False)
    fig.tight_layout()
    return fig, "vkg_runtime_by_query"


def plot_vkg_success_rate(runs: list[dict[str, Any]]) -> tuple[Any, str]:
    queries = ordered_queries(runs)
    variants = present_variants(runs)
    rates = np.zeros((len(queries), len(variants)))
    counts: list[list[tuple[int, int]]] = []
    for query_index, query in enumerate(queries):
        row_counts = []
        for variant_index, variant in enumerate(variants):
            selected = [
                run
                for run in runs
                if run["query_id"] == query and run["variant"] == variant
            ]
            successful = sum(bool(run.get("valid_result")) for run in selected)
            total = len(selected)
            rates[query_index, variant_index] = (
                100 * successful / total if total else math.nan
            )
            row_counts.append((successful, total))
        counts.append(row_counts)

    fig, ax = plt.subplots(figsize=(8.7, 6.2))
    image = ax.imshow(rates, cmap="RdYlGn", vmin=0, vmax=100, aspect="auto")
    for query_index in range(len(queries)):
        for variant_index in range(len(variants)):
            successful, total = counts[query_index][variant_index]
            rate = rates[query_index, variant_index]
            text = "not run" if total == 0 else f"{rate:.0f}%\n({successful}/{total})"
            ax.text(
                variant_index,
                query_index,
                text,
                ha="center",
                va="center",
                color="white" if total and (rate < 30 or rate > 75) else "#172033",
                fontweight="bold",
                fontsize=9,
            )

    ax.set_title("VKG valid execution rate")
    ax.set_xticks(
        np.arange(len(variants)),
        [VARIANT_LABELS.get(variant, variant) for variant in variants],
    )
    ax.set_yticks(np.arange(len(queries)), [query.upper() for query in queries])
    ax.grid(visible=False)
    colorbar = fig.colorbar(image, ax=ax, shrink=0.86)
    colorbar.set_label("Valid runs (%)")
    fig.tight_layout()
    return fig, "vkg_success_rate"


def plot_vkg_result_cardinality(
    runs: list[dict[str, Any]],
) -> tuple[Any, str]:
    queries = ordered_queries(runs)
    variants = present_variants(runs)
    x = np.arange(len(queries))
    width = 0.8 / len(variants)

    fig, ax = plt.subplots(figsize=(12, 5.9))
    for variant in variants:
        ax.scatter(
            [],
            [],
            s=48,
            color=VARIANT_COLORS.get(variant, "#64748B"),
            label=VARIANT_LABELS.get(variant, variant),
        )
    ax.scatter(
        [],
        [],
        s=55,
        marker="X",
        color="#B91C1C",
        label="Multiple result hashes",
    )

    for query_index, query in enumerate(queries):
        for variant_index, variant in enumerate(variants):
            position = (
                x[query_index]
                + (variant_index - (len(variants) - 1) / 2) * width
            )
            selected = [
                run
                for run in runs
                if run["query_id"] == query
                and run["variant"] == variant
                and run.get("valid_result")
                and run.get("result_rows") is not None
            ]
            if not selected:
                ax.text(
                    position,
                    0,
                    "no valid",
                    ha="center",
                    va="bottom",
                    rotation=90,
                    fontsize=6.8,
                    color="#B91C1C",
                )
                continue

            values = np.asarray(
                [float(run["result_rows"]) for run in selected]
            )
            offsets = (
                np.linspace(-0.18, 0.18, len(values)) * width
                if len(values) > 1
                else np.zeros(1)
            )
            ax.scatter(
                position + offsets,
                values,
                s=48,
                color=VARIANT_COLORS.get(variant, "#64748B"),
                edgecolor="white",
                linewidth=0.7,
                zorder=3,
            )
            mean = statistics.fmean(values)
            ax.hlines(
                mean,
                position - width * 0.28,
                position + width * 0.28,
                color="#111827",
                linewidth=1.4,
                zorder=4,
            )

            result_hashes = {
                str(run.get("result_hash", ""))
                for run in selected
                if run.get("result_hash")
            }
            if len(result_hashes) > 1:
                annotation_y = max(max(values), 1.0) * 1.35
                ax.scatter(
                    position,
                    annotation_y,
                    s=55,
                    marker="X",
                    color="#B91C1C",
                    zorder=5,
                )

    ax.set_yscale("symlog", linthresh=1)
    ax.set_title(
        "VKG result cardinality and consistency\n"
        "Points represent valid runs; horizontal lines show means"
    )
    ax.set_ylabel("Result rows per valid run (symmetric log scale)")
    ax.set_xticks(x, [query.upper() for query in queries])
    ax.legend(
        ncols=1,
        loc="center left",
        bbox_to_anchor=(1.01, 0.5),
    )
    ax.grid(axis="x", visible=False)
    fig.tight_layout()
    return fig, "vkg_result_cardinality"


def plot_success_metric(
    runs: list[dict[str, Any]],
    *,
    metric: str,
    title: str,
    ylabel: str,
    stem: str,
    scale: str = "linear",
) -> tuple[Any, str]:
    queries = ordered_queries(runs)
    variants = present_variants(runs)
    grouped = grouped_values(runs, metric=metric, successful_only=True)
    x = np.arange(len(queries))
    width = 0.8 / len(variants)

    fig, ax = plt.subplots(figsize=(12, 5.9))
    for index, variant in enumerate(variants):
        means = []
        deviations = []
        missing = []
        for query in queries:
            values = grouped.get((query, variant), [])
            means.append(statistics.fmean(values) if values else 0)
            deviations.append(
                statistics.stdev(values) if len(values) > 1 else 0
            )
            missing.append(not values)

        positions = x + (index - (len(variants) - 1) / 2) * width
        bars = ax.bar(
            positions,
            means,
            width,
            yerr=deviations,
            capsize=2.5,
            color=VARIANT_COLORS.get(variant, "#64748B"),
            label=VARIANT_LABELS.get(variant, variant),
        )
        for position, is_missing in zip(positions, missing):
            if is_missing:
                ax.text(
                    position,
                    0,
                    "no valid",
                    ha="center",
                    va="bottom",
                    rotation=90,
                    fontsize=6.8,
                    color="#B91C1C",
                )
        for bar, value in zip(bars, means):
            if value and scale == "linear":
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height(),
                    f"{value:.1f}",
                    ha="center",
                    va="bottom",
                    fontsize=7,
                    rotation=90,
                )

    if scale == "symlog":
        ax.set_yscale("symlog", linthresh=1)
    elif scale != "linear":
        ax.set_yscale(scale)
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.set_xticks(x, [query.upper() for query in queries])
    ax.legend(ncols=3, loc="upper left")
    ax.grid(axis="x", visible=False)
    fig.tight_layout()
    return fig, stem


def plot_vkg_final_time_breakdown(
    runs: list[dict[str, Any]],
) -> tuple[Any, str] | None:
    final_runs = [
        run
        for run in runs
        if run["variant"] == "final" and run.get("valid_result")
    ]
    if not final_runs:
        return None

    queries = ordered_queries(final_runs)
    api_grouped = grouped_values(
        final_runs, metric="api_time_seconds", successful_only=True
    )
    engine_grouped = grouped_values(
        final_runs, metric="engine_time_seconds", successful_only=True
    )
    api_means = [
        statistics.fmean(api_grouped[(query, "final")]) for query in queries
    ]
    engine_means = [
        statistics.fmean(engine_grouped[(query, "final")]) for query in queries
    ]

    x = np.arange(len(queries))
    fig, ax = plt.subplots(figsize=(10.8, 5.7))
    ax.bar(x, api_means, label="API time", color="#457B9D")
    ax.bar(
        x,
        engine_means,
        bottom=api_means,
        label="VKG engine time",
        color="#2A9D8F",
    )
    totals = np.asarray(api_means) + np.asarray(engine_means)
    for position, total in zip(x, totals):
        ax.text(
            position,
            total + max(totals) * 0.015,
            f"{total:.1f}s",
            ha="center",
            va="bottom",
            fontsize=8.5,
        )

    ax.set_title("Final VKG variant time breakdown")
    ax.set_ylabel("Mean time (seconds)")
    ax.set_xticks(x, [query.upper() for query in queries])
    ax.legend(ncols=2, loc="upper left")
    ax.grid(axis="x", visible=False)
    fig.tight_layout()
    return fig, "vkg_final_time_breakdown"


def generate_semantic_graphics(
    results_dir: Path,
    output_dir: Path,
    formats: Iterable[str],
    dpi: int,
) -> tuple[list[Path], list[str]]:
    results = load_semantic_results(results_dir)
    plots = [
        plot_semantic_alignment_coverage(results),
        plot_semantic_alignment_sources(results),
        plot_semantic_runtime(results),
        plot_embedding_reviews(results),
        plot_llm_review(results),
    ]
    generated = []
    for plot in plots:
        if plot is None:
            continue
        fig, stem = plot
        generated.extend(save_figure(fig, output_dir, stem, formats, dpi))
    sources = [result["_source_path"] for result in results]
    return generated, sources


def generate_vkg_graphics(
    results_dir: Path,
    output_dir: Path,
    formats: Iterable[str],
    dpi: int,
) -> tuple[list[Path], list[str]]:
    runs = load_vkg_runs(results_dir)
    plots = [
        plot_vkg_runtime(runs),
        plot_vkg_success_rate(runs),
        plot_vkg_result_cardinality(runs),
        plot_success_metric(
            runs,
            metric="api_calls",
            title="VKG API calls for valid runs",
            ylabel="Mean API calls",
            stem="vkg_api_calls",
        ),
        plot_success_metric(
            runs,
            metric="intermediate_triples",
            title="VKG intermediate triples for valid runs",
            ylabel="Mean intermediate triples (symmetric log scale)",
            stem="vkg_intermediate_triples",
            scale="symlog",
        ),
        plot_vkg_final_time_breakdown(runs),
    ]
    generated = []
    for plot in plots:
        if plot is None:
            continue
        fig, stem = plot
        generated.extend(save_figure(fig, output_dir, stem, formats, dpi))
    return generated, [str((results_dir / "runs.csv").resolve())]


def main() -> int:
    args = parse_args()
    configure_plot_style()
    output_dir = args.output_dir.resolve()
    generated: list[Path] = []
    sources: dict[str, list[str]] = {}

    if args.only in ("all", "semantic"):
        semantic_generated, semantic_sources = generate_semantic_graphics(
            args.semantic_results_dir.resolve(),
            output_dir / "semantic_annotation",
            args.formats,
            args.dpi,
        )
        generated.extend(semantic_generated)
        sources["semantic_annotation"] = semantic_sources

    if args.only in ("all", "vkg"):
        vkg_generated, vkg_sources = generate_vkg_graphics(
            args.vkg_results_dir.resolve(),
            output_dir / "vkg",
            args.formats,
            args.dpi,
        )
        generated.extend(vkg_generated)
        sources["vkg"] = vkg_sources

    manifest = {
        "semantic_results_dir": str(args.semantic_results_dir.resolve()),
        "vkg_results_dir": str(args.vkg_results_dir.resolve()),
        "output_dir": str(output_dir),
        "formats": list(dict.fromkeys(args.formats)),
        "dpi": args.dpi,
        "sources": sources,
        "generated_files": [str(path.resolve()) for path in generated],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "graphics_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"Generated {len(generated)} graphics in {output_dir}")
    for path in generated:
        print(path)
    print(manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
