import unittest
from unittest.mock import patch

from rdflib import Literal, URIRef, Variable

from eval.vkg.evaluate_vkg import VARIANTS, build_comparisons
from fvkg_json import sparql_virtualizer
from fvkg_json.classes import TriplePattern


class Part:
    name = "BGP"
    triples = [
        (
            Variable("feature"),
            URIRef("https://example.com/value"),
            Variable("value"),
        ),
        (
            Variable("feature"),
            URIRef("https://example.com/name"),
            Literal("Madrid"),
        ),
    ]


class BenchmarkBaselineTests(unittest.TestCase):
    def test_baseline_differs_from_final_only_in_url_binding_injection(self):
        baseline = VARIANTS["baseline"]
        final = VARIANTS["final"]

        self.assertFalse(baseline["url_binding_injection"])
        self.assertTrue(final["url_binding_injection"])
        self.assertTrue(baseline["virtual_geo_filter"])
        self.assertEqual(
            baseline["virtual_geo_filter"],
            final["virtual_geo_filter"],
        )
        self.assertEqual(baseline["triple_order"], "static")
        self.assertEqual(
            baseline["triple_order"],
            final["triple_order"],
        )

    def test_random_variant_is_final_without_order_heuristic(self):
        random_order = VARIANTS["binding_injection_random"]
        final = VARIANTS["final"]

        self.assertTrue(random_order["url_binding_injection"])
        self.assertEqual(
            random_order["url_binding_injection"],
            final["url_binding_injection"],
        )
        self.assertEqual(
            random_order["virtual_geo_filter"],
            final["virtual_geo_filter"],
        )
        self.assertEqual(random_order["triple_order"], "random")
        self.assertEqual(final["triple_order"], "static")

    def test_baseline_and_final_share_static_triple_order(self):
        ordered = [
            TriplePattern(
                Variable("feature"),
                URIRef("https://example.com/name"),
                Literal("Madrid"),
            ),
            TriplePattern(
                Variable("feature"),
                URIRef("https://example.com/value"),
                Variable("value"),
            ),
        ]
        baseline_selected = []
        final_selected = []

        def select_without_bindings(_ctx, triple_patterns, _mappings):
            baseline_selected.extend(triple_patterns)
            return []

        def select_with_bindings(_ctx, triple_patterns, _mappings):
            final_selected.extend(triple_patterns)
            return []

        with (
            patch.object(
                sparql_virtualizer,
                "get_static_triple_patterns",
                return_value=ordered,
            ) as orderer,
            patch.object(
                sparql_virtualizer,
                "getMappingsFromBGPWithoutBindings",
                side_effect=select_without_bindings,
            ),
            patch.object(
                sparql_virtualizer,
                "getMappingsFromBGP",
                side_effect=select_with_bindings,
            ),
            patch.object(
                sparql_virtualizer,
                "evalVirtualBGPWithoutBindings",
                return_value=iter(()),
            ),
            patch.object(
                sparql_virtualizer,
                "evalVirtualBGP",
                return_value=iter(()),
            ),
        ):
            sparql_virtualizer.virtual_bgp_evalBaseline(None, Part())
            sparql_virtualizer.virtual_bgp_evalFinal(None, Part())

        self.assertEqual(orderer.call_count, 2)
        self.assertEqual(baseline_selected, ordered)
        self.assertEqual(final_selected, ordered)

    def test_random_order_is_reproducible_for_same_seed(self):
        sparql_virtualizer.configure_random_triple_order(123)
        first = sparql_virtualizer.get_random_triple_patterns(Part.triples)
        sparql_virtualizer.configure_random_triple_order(123)
        second = sparql_virtualizer.get_random_triple_patterns(Part.triples)

        self.assertEqual(
            [(pattern.s, pattern.p, pattern.o) for pattern in first],
            [(pattern.s, pattern.p, pattern.o) for pattern in second],
        )

    def test_comparisons_isolate_pushdown_and_order_heuristic(self):
        summary = [
            {
                "query_id": "q01",
                "variant": variant,
                "runs_successful": 3,
                "result_rows": 1,
                "result_hash": "same",
                "total_time_seconds_mean": time,
                "api_calls_mean": 1,
                "api_response_bytes_mean": 100,
                "intermediate_triples_mean": 10,
            }
            for variant, time in (
                ("baseline", 8),
                ("binding_injection_random", 5),
                ("final", 4),
            )
        ]

        comparisons = build_comparisons(summary)

        self.assertEqual(
            {
                (
                    row["comparison"],
                    row["reference_variant"],
                    row["candidate_variant"],
                )
                for row in comparisons
            },
            {
                ("pushdown", "baseline", "final"),
                (
                    "order_heuristic",
                    "binding_injection_random",
                    "final",
                ),
            },
        )


if __name__ == "__main__":
    unittest.main()
