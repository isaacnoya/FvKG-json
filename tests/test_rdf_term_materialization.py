import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import XSD
from rdflib.plugins.sparql import CUSTOM_EVALS

from fvkg_json import sparql_virtualizer, virtual
from fvkg_json.classes import RML_BLANK_NODE, RML_IRI, VirtualMapping
from fvkg_json.mappings import getMappings
from fvkg_json.virtual import materialize_object_term


class RdfTermMaterializationTests(unittest.TestCase):
    def test_materializes_typed_literal(self):
        mapping = VirtualMapping(datatype=XSD.gYear)

        term = materialize_object_term(mapping, 2025)

        self.assertEqual(term, Literal("2025", datatype=XSD.gYear))

    def test_materializes_language_literal(self):
        mapping = VirtualMapping(language=Literal("es"))

        term = materialize_object_term(mapping, "Madrid")

        self.assertEqual(term, Literal("Madrid", lang="es"))

    def test_materializes_xsd_string_as_query_compatible_literal(self):
        mapping = VirtualMapping(datatype=XSD.string)

        term = materialize_object_term(mapping, "Madrid")

        self.assertEqual(term, Literal("Madrid"))

    def test_materializes_iri_term_type(self):
        mapping = VirtualMapping(term_type=URIRef(RML_IRI))

        term = materialize_object_term(mapping, "https://example.com/resource")

        self.assertEqual(term, URIRef("https://example.com/resource"))

    def test_materializes_blank_node_term_type(self):
        mapping = VirtualMapping(term_type=URIRef(RML_BLANK_NODE))

        term = materialize_object_term(mapping, "resource")

        self.assertEqual(term, BNode("resource"))

    def test_parser_preserves_object_map_metadata(self):
        mapping_text = """
            @prefix ex: <https://example.com/> .
            @prefix htv: <http://www.w3.org/2011/http#> .
            @prefix rml: <http://w3id.org/rml/> .
            @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

            ex:source htv:absoluteURI "https://example.com/data" .

            ex:logicalSource
                rml:iterator "$.*" ;
                rml:referenceFormulation rml:HTTPAPI ;
                rml:source ex:source .

            ex:triplesMap a rml:TriplesMap ;
                rml:logicalSource ex:logicalSource ;
                rml:subjectMap [ rml:template "https://example.com/{id}" ] ;
                rml:predicateObjectMap [
                    rml:predicate ex:year ;
                    rml:objectMap [
                        rml:datatype xsd:gYear ;
                        rml:reference "year"
                    ]
                ] .
        """

        with tempfile.TemporaryDirectory() as directory:
            mapping_path = Path(directory) / "mapping.ttl"
            mapping_path.write_text(mapping_text, encoding="utf-8")
            mappings = getMappings(mapping_path)

        year_mapping = next(
            mapping
            for mapping in mappings
            if mapping.p == URIRef("https://example.com/year")
        )
        self.assertEqual(year_mapping.datatype, XSD.gYear)

    def test_q05_matches_typed_year_in_baseline_and_final(self):
        payload = [{
            "COD": "series-1",
            "Nombre": "Madrid. Total",
            "Unidad": {"Id": 1, "Nombre": "Personas"},
            "Escala": {"Factor": 1},
            "MetaData": [
                {"Variable": {"Id": 18}, "Nombre": "Total"},
                {"Variable": {"Id": 19}, "Nombre": "Madrid"},
                {"Variable": {"Id": 349}, "Nombre": "Total"},
            ],
            "Data": [{
                "Valor": 42.0,
                "Secreto": False,
                "Fecha": 2025,
                "TipoDato": {"Nombre": "Definitivo"},
                "Anyo": 2025,
                "CodigoPeriodo": "2025",
            }],
        }]

        class Response:
            def json(self):
                return payload

        project_root = Path(__file__).resolve().parent.parent
        query = (
            project_root / "eval" / "vkg" / "queries" / "q05.rq"
        ).read_text(encoding="utf-8")
        mappings = getMappings(
            project_root
            / "eval"
            / "vkg"
            / "mappings"
            / "68065_det0_tip_mappings.rml.ttl"
        )
        previous_mappings = sparql_virtualizer.mappings
        previous_evaluator = CUSTOM_EVALS["virtual_bgp"]
        results = {}

        try:
            sparql_virtualizer.mappings = mappings
            with (
                patch.object(virtual.requests, "get", return_value=Response()),
                redirect_stdout(io.StringIO()),
            ):
                for name, evaluator in (
                    ("baseline", sparql_virtualizer.virtual_bgp_evalBaseline),
                    ("final", sparql_virtualizer.virtual_bgp_evalFinal),
                ):
                    CUSTOM_EVALS["virtual_bgp"] = evaluator
                    graph = Graph()
                    results[name] = (list(graph.query(query)), len(graph))
        finally:
            sparql_virtualizer.mappings = previous_mappings
            CUSTOM_EVALS["virtual_bgp"] = previous_evaluator

        self.assertEqual(results["baseline"], results["final"])
        rows, triple_count = results["baseline"]
        self.assertEqual(triple_count, 6)
        self.assertEqual(
            rows[0][0],
            Literal("42.0", datatype=XSD.float),
        )


if __name__ == "__main__":
    unittest.main()
