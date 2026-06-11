#!/usr/bin/env python3
"""Benchmark configured MorphGEO VKG evaluator variants."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import platform
import re
import statistics
import sys
import time
import traceback
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from unittest.mock import patch

import rdflib
import requests
from rdflib.plugins.sparql import CUSTOM_EVALS
from rdflib.plugins.sparql.parser import parseQuery


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from morphgeo import sparql_virtualizer  # noqa: E402
from morphgeo import virtual  # noqa: E402
from morphgeo.classes import geoBindings  # noqa: E402
from morphgeo.mappings import getMappings  # noqa: E402


SCHEMA_VERSION = 2
VARIANTS = {
    "baseline": {
        "bgp_function": sparql_virtualizer.virtual_bgp_evalBaseline,
        "bgp_function_name": "virtual_bgp_evalBaseline",
        "virtual_geo_filter": False,
        "url_binding_injection": False,
        "triple_order": "query",
    },
    "binding_injection_random": {
        "bgp_function": (
            sparql_virtualizer.virtual_bgp_evalBindingInjectionRandom
        ),
        "bgp_function_name": "virtual_bgp_evalBindingInjectionRandom",
        "virtual_geo_filter": True,
        "url_binding_injection": True,
        "triple_order": "random",
    },
    "final": {
        "bgp_function": sparql_virtualizer.virtual_bgp_evalFinal,
        "bgp_function_name": "virtual_bgp_evalFinal",
        "virtual_geo_filter": True,
        "url_binding_injection": True,
        "triple_order": "static",
    },
}

RUN_FIELDS = [
    "schema_version",
    "benchmark_id",
    "run_id",
    "execution_order",
    "query_id",
    "query_file",
    "query_sha256",
    "query_bytes",
    "geo_filter_count",
    "variant",
    "virtual_bgp_function",
    "virtual_geo_filter_enabled",
    "url_binding_injection_enabled",
    "triple_order_mode",
    "triple_order_seed",
    "triple_pattern_order",
    "repetition",
    "status",
    "error_type",
    "error_message",
    "started_at_utc",
    "total_time_seconds",
    "api_time_seconds",
    "engine_time_seconds",
    "api_calls",
    "api_calls_succeeded",
    "api_calls_failed",
    "api_response_bytes",
    "intermediate_triples",
    "triple_add_attempts",
    "duplicate_triple_adds",
    "result_type",
    "result_rows",
    "result_hash",
    "result_variables",
    "mapping_files",
    "mapping_rules",
    "engine_log_file",
]

API_CALL_FIELDS = [
    "benchmark_id",
    "run_id",
    "execution_order",
    "query_id",
    "variant",
    "repetition",
    "api_call_index",
    "method",
    "requested_url",
    "final_url",
    "status_code",
    "elapsed_seconds",
    "response_bytes",
    "succeeded",
    "error_type",
    "error_message",
]

SUMMARY_METRICS = (
    "total_time_seconds",
    "api_time_seconds",
    "engine_time_seconds",
    "api_calls",
    "intermediate_triples",
    "triple_add_attempts",
    "result_rows",
)


class CountingGraph(rdflib.Graph):
    """Graph that records materialization attempts without changing semantics."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.add_attempts = 0

    def add(self, triple: tuple[Any, Any, Any]) -> "CountingGraph":
        self.add_attempts += 1
        super().add(triple)
        return self

    def addN(self, quads: Iterable[tuple[Any, Any, Any, Any]]) -> "CountingGraph":
        buffered_quads = list(quads)
        self.add_attempts += len(buffered_quads)
        super().addN(buffered_quads)
        return self


@dataclass
class ApiCallRecorder:
    original_get: Any
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __call__(self, url: str, *args: Any, **kwargs: Any) -> Any:
        call_index = len(self.calls) + 1
        started = time.perf_counter()
        record = {
            "api_call_index": call_index,
            "method": "GET",
            "requested_url": str(url),
            "final_url": None,
            "status_code": None,
            "elapsed_seconds": None,
            "response_bytes": None,
            "succeeded": False,
            "error_type": None,
            "error_message": None,
        }

        try:
            response = self.original_get(url, *args, **kwargs)
            record["final_url"] = str(
                getattr(getattr(response, "request", None), "url", url)
            )
            record["status_code"] = getattr(response, "status_code", None)
            content = getattr(response, "content", None)
            record["response_bytes"] = len(content) if content is not None else None
            status_code = record["status_code"]
            record["succeeded"] = (
                status_code is None or 200 <= status_code < 400
            )
            return response
        except Exception as exc:
            record["error_type"] = type(exc).__name__
            record["error_message"] = str(exc)
            raise
        finally:
            record["elapsed_seconds"] = round(
                time.perf_counter() - started,
                9,
            )
            self.calls.append(record)

    @property
    def total_seconds(self) -> float:
        return sum(call["elapsed_seconds"] or 0.0 for call in self.calls)


@contextmanager
def configured_evaluator(variant: str):
    previous_evaluators = list(CUSTOM_EVALS.items())
    configuration = VARIANTS[variant]

    CUSTOM_EVALS.pop("virtual_bgp", None)
    CUSTOM_EVALS.pop("virtualGeofilter", None)
    CUSTOM_EVALS["virtual_bgp"] = configuration["bgp_function"]
    if configuration["virtual_geo_filter"]:
        CUSTOM_EVALS["virtualGeofilter"] = sparql_virtualizer.virtualGeoFilter

    try:
        yield configuration
    finally:
        CUSTOM_EVALS.clear()
        CUSTOM_EVALS.update(previous_evaluators)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def derive_random_seed(
    base_seed: int,
    query_id: str,
    repetition: int,
) -> int:
    seed_material = f"{base_seed}:{query_id}:{repetition}".encode("utf-8")
    return int.from_bytes(
        hashlib.sha256(seed_material).digest()[:8],
        byteorder="big",
    )


def safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, rdflib.term.Node):
        return value.n3()
    return str(value)


def result_digest(result: Any) -> dict[str, Any]:
    result_type = str(getattr(result, "type", "UNKNOWN"))
    variables = [str(variable) for variable in (getattr(result, "vars", None) or [])]

    if result_type == "ASK":
        answer = bool(getattr(result, "askAnswer", bool(result)))
        canonical_rows = [str(answer).lower()]
    elif result_type in {"CONSTRUCT", "DESCRIBE"}:
        result_graph = getattr(result, "graph", None)
        canonical_rows = sorted(
            " ".join(term.n3() for term in triple)
            for triple in (result_graph or [])
        )
    else:
        canonical_rows = []
        for row in result:
            values = {
                str(variable): value
                for variable, value in row.asdict().items()
            }
            canonical_rows.append(
                "\t".join(
                    f"{variable}={safe_text(values.get(variable))}"
                    for variable in variables
                )
            )
        canonical_rows.sort()

    digest = hashlib.sha256(
        "\n".join(canonical_rows).encode("utf-8")
    ).hexdigest()
    return {
        "result_type": result_type,
        "result_rows": len(canonical_rows),
        "result_hash": digest,
        "result_variables": variables,
    }


def query_metadata(path: Path, query_text: str) -> dict[str, Any]:
    encoded = query_text.encode("utf-8")
    return {
        "query_id": path.stem,
        "query_file": str(path.resolve()),
        "query_sha256": hashlib.sha256(encoded).hexdigest(),
        "query_bytes": len(encoded),
        "geo_filter_count": len(
            re.findall(r"\bgeof:[A-Za-z0-9_-]+\s*\(", query_text)
        ),
    }


def discover_queries(queries_dir: Path, selected: list[str] | None) -> list[Path]:
    query_paths = sorted(queries_dir.glob("*.rq"))
    if selected:
        selected_names = {
            item if item.endswith(".rq") else f"{item}.rq"
            for item in selected
        }
        query_paths = [
            path
            for path in query_paths
            if path.name in selected_names
        ]
        missing = selected_names - {path.name for path in query_paths}
        if missing:
            raise ValueError(
                "Unknown query file(s): " + ", ".join(sorted(missing))
            )

    if not query_paths:
        raise ValueError(f"No .rq query files found in {queries_dir}.")
    return query_paths


def load_mappings(mappings_dir: Path) -> tuple[list[Any], list[Path], float]:
    mapping_paths = sorted(mappings_dir.glob("*.ttl"))
    if not mapping_paths:
        raise ValueError(f"No .ttl mapping files found in {mappings_dir}.")

    started = time.perf_counter()
    mapping_rules = []
    for path in mapping_paths:
        mapping_rules.extend(getMappings(path))
    elapsed = time.perf_counter() - started

    if not mapping_rules:
        raise ValueError(
            f"The mappings in {mappings_dir} produced no virtual mapping rules."
        )
    return mapping_rules, mapping_paths, elapsed


def validate_queries(query_paths: list[Path]) -> list[dict[str, str]]:
    errors = []
    for path in query_paths:
        try:
            parseQuery(path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append({
                "query_file": str(path),
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            })
    return errors


def execute_run(
    *,
    benchmark_id: str,
    execution_order: int,
    query_path: Path,
    variant: str,
    repetition: int,
    mapping_file_count: int,
    mapping_rule_count: int,
    logs_dir: Path,
    random_seed_base: int = 42,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    query_text = query_path.read_text(encoding="utf-8")
    metadata = query_metadata(query_path, query_text)
    run_id = (
        f"{metadata['query_id']}__{variant}__r{repetition:02d}"
    )
    graph = CountingGraph()
    recorder = ApiCallRecorder(virtual.requests.get)
    engine_output = io.StringIO()
    result_data = {
        "result_type": None,
        "result_rows": None,
        "result_hash": None,
        "result_variables": [],
    }
    status = "success"
    error_type = None
    error_message = None
    error_traceback = None
    started_at = utc_now()
    triple_order_seed = None
    triple_pattern_order = []

    geoBindings.clear()
    with configured_evaluator(variant) as configuration:
        if configuration["triple_order"] == "random":
            triple_order_seed = derive_random_seed(
                random_seed_base,
                metadata["query_id"],
                repetition,
            )
        sparql_virtualizer.configure_random_triple_order(triple_order_seed)

        started = time.perf_counter()
        try:
            with (
                patch.object(virtual.requests, "get", recorder),
                redirect_stdout(engine_output),
                redirect_stderr(engine_output),
            ):
                result_data = result_digest(graph.query(query_text))
        except Exception as exc:
            status = "error"
            error_type = type(exc).__name__
            error_message = str(exc)
            error_traceback = traceback.format_exc()
        finally:
            total_seconds = time.perf_counter() - started
            triple_pattern_order = (
                sparql_virtualizer.get_random_triple_orders()
            )
            geoBindings.clear()

    engine_log_path = logs_dir / f"{run_id}.log"
    log_text = engine_output.getvalue()
    if error_traceback:
        log_text += "\n" + error_traceback
    engine_log_path.write_text(log_text, encoding="utf-8")

    api_seconds = recorder.total_seconds
    intermediate_triples = len(graph)
    duplicate_adds = max(graph.add_attempts - intermediate_triples, 0)
    run_record = {
        "schema_version": SCHEMA_VERSION,
        "benchmark_id": benchmark_id,
        "run_id": run_id,
        "execution_order": execution_order,
        **metadata,
        "variant": variant,
        "virtual_bgp_function": configuration["bgp_function_name"],
        "virtual_geo_filter_enabled": configuration["virtual_geo_filter"],
        "url_binding_injection_enabled": (
            configuration["url_binding_injection"]
        ),
        "triple_order_mode": configuration["triple_order"],
        "triple_order_seed": triple_order_seed,
        "triple_pattern_order": triple_pattern_order,
        "repetition": repetition,
        "status": status,
        "error_type": error_type,
        "error_message": error_message,
        "started_at_utc": started_at,
        "total_time_seconds": round(total_seconds, 9),
        "api_time_seconds": round(api_seconds, 9),
        "engine_time_seconds": round(max(total_seconds - api_seconds, 0.0), 9),
        "api_calls": len(recorder.calls),
        "api_calls_succeeded": sum(call["succeeded"] for call in recorder.calls),
        "api_calls_failed": sum(not call["succeeded"] for call in recorder.calls),
        "api_response_bytes": sum(
            call["response_bytes"] or 0
            for call in recorder.calls
        ),
        "intermediate_triples": intermediate_triples,
        "triple_add_attempts": graph.add_attempts,
        "duplicate_triple_adds": duplicate_adds,
        **result_data,
        "mapping_files": mapping_file_count,
        "mapping_rules": mapping_rule_count,
        "engine_log_file": str(engine_log_path.resolve()),
    }

    api_records = [
        {
            "benchmark_id": benchmark_id,
            "run_id": run_id,
            "execution_order": execution_order,
            "query_id": metadata["query_id"],
            "variant": variant,
            "repetition": repetition,
            **call,
        }
        for call in recorder.calls
    ]
    return run_record, api_records


def csv_value(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, bool):
        return str(value).lower()
    return value


def append_csv(
    path: Path,
    fieldnames: list[str],
    records: list[dict[str, Any]],
) -> None:
    if not records:
        return
    write_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        for record in records:
            writer.writerow({
                field: csv_value(record.get(field))
                for field in fieldnames
            })


def initialize_csv(path: Path, fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        csv.DictWriter(output, fieldnames=fieldnames).writeheader()


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as output:
        json.dump(record, output, ensure_ascii=False, sort_keys=True)
        output.write("\n")


def metric_stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {
            "mean": None,
            "stdev": None,
            "min": None,
            "max": None,
        }
    return {
        "mean": statistics.fmean(values),
        "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
    }


def build_summary(run_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for record in run_records:
        groups.setdefault(
            (record["query_id"], record["variant"]),
            [],
        ).append(record)

    summary = []
    for (query_id, variant), records in sorted(groups.items()):
        successful = [
            record
            for record in records
            if record["status"] == "success"
        ]
        row: dict[str, Any] = {
            "query_id": query_id,
            "variant": variant,
            "runs_total": len(records),
            "runs_successful": len(successful),
            "runs_failed": len(records) - len(successful),
        }
        for metric in SUMMARY_METRICS:
            values = [
                float(record[metric])
                for record in successful
                if record.get(metric) is not None
            ]
            for statistic_name, value in metric_stats(values).items():
                row[f"{metric}_{statistic_name}"] = value

        hashes = {
            (record["result_rows"], record["result_hash"])
            for record in successful
        }
        row["result_consistent"] = len(hashes) <= 1
        row["result_rows"] = successful[0]["result_rows"] if successful else None
        row["result_hash"] = successful[0]["result_hash"] if successful else None
        summary.append(row)
    return summary


def build_comparisons(summary: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_query: dict[str, dict[str, dict[str, Any]]] = {}
    for row in summary:
        by_query.setdefault(row["query_id"], {})[row["variant"]] = row

    comparisons = []
    for query_id, variants in sorted(by_query.items()):
        final = variants.get("final")
        if not final:
            continue

        for comparison_variant, compared in sorted(variants.items()):
            if comparison_variant == "final":
                continue

            row: dict[str, Any] = {
                "query_id": query_id,
                "comparison_variant": comparison_variant,
                "comparison_runs_successful": compared["runs_successful"],
                "final_runs_successful": final["runs_successful"],
                "result_rows_match": (
                    compared.get("result_rows") == final.get("result_rows")
                ),
                "result_hash_match": (
                    compared.get("result_hash") == final.get("result_hash")
                ),
            }
            for metric in (
                "total_time_seconds",
                "api_calls",
                "intermediate_triples",
            ):
                comparison_mean = compared.get(f"{metric}_mean")
                final_mean = final.get(f"{metric}_mean")
                row[f"comparison_{metric}_mean"] = comparison_mean
                row[f"final_{metric}_mean"] = final_mean
                if comparison_mean is None or final_mean is None:
                    row[f"{metric}_reduction_pct"] = None
                    continue
                row[f"{metric}_reduction_pct"] = (
                    ((comparison_mean - final_mean) / comparison_mean) * 100
                    if comparison_mean
                    else 0.0
                )
                if metric == "total_time_seconds":
                    row["speedup"] = (
                        comparison_mean / final_mean
                        if final_mean
                        else None
                    )
            comparisons.append(row)
    return comparisons


def write_table(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                field: csv_value(row.get(field))
                for field in fieldnames
            })


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark configured MorphGEO VKG evaluator variants."
    )
    parser.add_argument(
        "--queries-dir",
        type=Path,
        default=SCRIPT_DIR / "queries",
        help="Directory containing .rq files.",
    )
    parser.add_argument(
        "--mappings-dir",
        type=Path,
        default=SCRIPT_DIR / "mappings",
        help="Directory containing RML .ttl mappings.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=SCRIPT_DIR / "results",
        help="Directory where CSV, JSONL, manifest, and logs are written.",
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        default=1,
        help="Number of executions per query and variant.",
    )
    parser.add_argument(
        "--random-seed",
        type=int,
        default=42,
        help=(
            "Base seed for reproducible randomized triple orders. "
            "Each query and repetition derives its own seed."
        ),
    )
    parser.add_argument(
        "--variants",
        nargs="+",
        choices=tuple(VARIANTS),
        default=list(VARIANTS),
        help="Variants to execute, in order.",
    )
    parser.add_argument(
        "--queries",
        nargs="+",
        default=None,
        help="Optional query IDs or filenames, for example q01 q03.rq.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop after the first failed query execution.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate queries and mappings without executing API calls.",
    )
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("--repetitions must be at least 1.")
    return args


def main() -> int:
    args = parse_args()
    queries_dir = args.queries_dir.resolve()
    mappings_dir = args.mappings_dir.resolve()
    output_dir = args.output_dir.resolve()

    query_paths = discover_queries(queries_dir, args.queries)
    query_errors = validate_queries(query_paths)
    if query_errors:
        for error in query_errors:
            print(
                f"{error['query_file']}: {error['error_type']}: "
                f"{error['error_message']}",
                file=sys.stderr,
            )
        return 2

    try:
        mapping_rules, mapping_paths, mapping_load_seconds = load_mappings(
            mappings_dir
        )
    except Exception as exc:
        print(f"Mapping error: {exc}", file=sys.stderr)
        return 2

    if args.validate_only:
        print(
            f"Validated {len(query_paths)} queries, {len(mapping_paths)} mapping "
            f"files, and {len(mapping_rules)} mapping rules."
        )
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    benchmark_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    logs_dir = output_dir / "logs" / benchmark_id
    logs_dir.mkdir(parents=True, exist_ok=True)

    runs_path = output_dir / "runs.csv"
    details_path = output_dir / "runs.jsonl"
    api_calls_path = output_dir / "api_calls.csv"
    summary_path = output_dir / "summary.csv"
    comparisons_path = output_dir / "comparisons.csv"
    manifest_path = output_dir / "manifest.json"

    initialize_csv(runs_path, RUN_FIELDS)
    initialize_csv(api_calls_path, API_CALL_FIELDS)
    details_path.write_text("", encoding="utf-8")

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "benchmark_id": benchmark_id,
        "created_at_utc": utc_now(),
        "project_root": str(PROJECT_ROOT),
        "queries_dir": str(queries_dir),
        "query_files": [str(path.resolve()) for path in query_paths],
        "mappings_dir": str(mappings_dir),
        "mapping_files": [str(path.resolve()) for path in mapping_paths],
        "mapping_rule_count": len(mapping_rules),
        "mapping_load_seconds": round(mapping_load_seconds, 9),
        "output_dir": str(output_dir),
        "repetitions": args.repetitions,
        "random_seed_base": args.random_seed,
        "variants": args.variants,
        "variant_definitions": {
            name: {
                "virtual_bgp_function": configuration["bgp_function_name"],
                "virtual_geo_filter_enabled": configuration["virtual_geo_filter"],
                "url_binding_injection_enabled": (
                    configuration["url_binding_injection"]
                ),
                "triple_order_mode": configuration["triple_order"],
            }
            for name, configuration in VARIANTS.items()
            if name in args.variants
        },
        "python_version": sys.version,
        "platform": platform.platform(),
        "rdflib_version": rdflib.__version__,
        "requests_version": requests.__version__,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    previous_mappings = sparql_virtualizer.mappings
    sparql_virtualizer.mappings = mapping_rules
    run_records = []
    execution_order = 0
    try:
        for repetition in range(1, args.repetitions + 1):
            for query_path in query_paths:
                for variant in args.variants:
                    execution_order += 1
                    print(
                        f"[{execution_order}] {query_path.stem} "
                        f"{variant} repetition={repetition}"
                    )
                    run_record, api_records = execute_run(
                        benchmark_id=benchmark_id,
                        execution_order=execution_order,
                        query_path=query_path,
                        variant=variant,
                        repetition=repetition,
                        mapping_file_count=len(mapping_paths),
                        mapping_rule_count=len(mapping_rules),
                        logs_dir=logs_dir,
                        random_seed_base=args.random_seed,
                    )
                    run_records.append(run_record)
                    append_csv(runs_path, RUN_FIELDS, [run_record])
                    append_csv(api_calls_path, API_CALL_FIELDS, api_records)
                    append_jsonl(
                        details_path,
                        {
                            **run_record,
                            "api_call_details": api_records,
                        },
                    )

                    print(
                        f"  status={run_record['status']} "
                        f"time={run_record['total_time_seconds']:.6f}s "
                        f"api_calls={run_record['api_calls']} "
                        f"triples={run_record['intermediate_triples']} "
                        f"rows={run_record['result_rows']}"
                    )
                    if args.fail_fast and run_record["status"] != "success":
                        raise RuntimeError(
                            f"Run {run_record['run_id']} failed: "
                            f"{run_record['error_message']}"
                        )
    finally:
        sparql_virtualizer.mappings = previous_mappings
        geoBindings.clear()

    summary = build_summary(run_records)
    comparisons = build_comparisons(summary)
    write_table(summary_path, summary)
    write_table(comparisons_path, comparisons)

    print(f"Run data: {runs_path}")
    print(f"API call data: {api_calls_path}")
    print(f"Summary: {summary_path}")
    print(f"Comparisons: {comparisons_path}")
    return 0 if all(record["status"] == "success" for record in run_records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
