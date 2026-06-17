import importlib
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import rdflib


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GENERATOR_ROOT = os.path.join(PROJECT_ROOT, "OGCmappingGenerator")
sys.path.insert(0, GENERATOR_ROOT)

ontology_search = importlib.import_module("ontology_searh")


class FakeCompletions:
    def __init__(self, content):
        self.contents = (
            list(content)
            if isinstance(content, (list, tuple))
            else [content]
        )
        self.kwargs = None
        self.calls = []

    def create(self, **kwargs):
        self.kwargs = kwargs
        self.calls.append(kwargs)
        content = self.contents[min(len(self.calls) - 1, len(self.contents) - 1)]
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=content),
                )
            ]
        )


class FakeGroq:
    instances = []

    def __init__(self, api_key=None):
        self.api_key = api_key
        self.chat = SimpleNamespace(
            completions=FakeCompletions(json.dumps({
                "term": "Dam",
                "wikidata_qid": "Q12323",
                "dbpedia_uri": "http://dbpedia.org/ontology/Dam",
            }))
        )
        self.instances.append(self)


class StructuredOutputTests(unittest.TestCase):
    def setUp(self):
        FakeGroq.instances.clear()

    def test_gpt_oss_uses_strict_json_schema(self):
        with patch.object(ontology_search, "Groq", FakeGroq):
            result = ontology_search.searchLLM(
                "Dam",
                model="openai/gpt-oss-20b",
            )

        self.assertEqual(result["wikidata_qid"], "Q12323")
        response_format = FakeGroq.instances[0].chat.completions.kwargs[
            "response_format"
        ]
        self.assertEqual(response_format["type"], "json_schema")
        self.assertTrue(response_format["json_schema"]["strict"])
        schema = response_format["json_schema"]["schema"]
        self.assertEqual(set(schema["required"]), set(schema["properties"]))
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            FakeGroq.instances[0].chat.completions.kwargs[
                "max_completion_tokens"
            ],
            1800,
        )

    def test_other_models_keep_json_object_mode(self):
        with patch.object(ontology_search, "Groq", FakeGroq):
            ontology_search.searchLLM(
                "Dam",
                model="llama-3.3-70b-versatile",
            )

        response_format = FakeGroq.instances[0].chat.completions.kwargs[
            "response_format"
        ]
        self.assertEqual(response_format, {"type": "json_object"})
        system_prompt = FakeGroq.instances[0].chat.completions.kwargs[
            "messages"
        ][0]["content"]
        self.assertIn('"dbpedia_uri"', system_prompt)
        self.assertIn('"wikidata_qid"', system_prompt)

    def test_llama_retries_when_required_fields_are_missing(self):
        invalid = json.dumps({
            "wikidata": "Q12323",
            "dbpedia": "http://dbpedia.org/resource/Dam",
        })
        valid = json.dumps({
            "term": "Dam",
            "wikidata_qid": "Q12323",
            "dbpedia_uri": "http://dbpedia.org/resource/Dam",
        })

        class RetryGroq(FakeGroq):
            def __init__(self, api_key=None):
                self.api_key = api_key
                self.chat = SimpleNamespace(
                    completions=FakeCompletions([invalid, valid])
                )
                self.instances.append(self)

        with patch.object(ontology_search, "Groq", RetryGroq):
            result = ontology_search.searchLLM(
                "Dam",
                model="llama-3.3-70b-versatile",
            )

        self.assertEqual(result["dbpedia_uri"], "http://dbpedia.org/resource/Dam")
        calls = RetryGroq.instances[0].chat.completions.calls
        self.assertEqual(len(calls), 2)
        self.assertIn("missing required field", calls[1]["messages"][-1]["content"])

    def test_search_not_local_ignores_incomplete_mapping(self):
        with (
            patch.object(ontology_search, "buscar_dbpedia_label", return_value=None),
            patch.object(
                ontology_search,
                "searchLLM",
                return_value={"wikidata": "Q12323"},
            ),
        ):
            result = ontology_search.searchNotLocal("Dam")

        self.assertIsNone(result)

    def test_axiom_prompt_context_is_bounded(self):
        graph = rdflib.Graph()
        for index in range(100):
            entity = rdflib.URIRef(f"http://example.org/Class{index}")
            graph.add((entity, rdflib.RDF.type, rdflib.OWL.Class))
            graph.add((
                entity,
                rdflib.RDFS.label,
                rdflib.Literal(f"Class {index}"),
            ))

        class AxiomGroq(FakeGroq):
            def __init__(self, api_key=None):
                self.api_key = api_key
                self.chat = SimpleNamespace(
                    completions=FakeCompletions(json.dumps({
                        "rationale": "Test proposal",
                        "restrictions": [],
                    }))
                )
                self.instances.append(self)

        with patch.object(ontology_search, "Groq", AxiomGroq):
            ontology_search.llm_propose_axiom(
                graph,
                model="openai/gpt-oss-20b",
                history=[{"decision": "denied"}] * 10,
            )

        request = AxiomGroq.instances[0].chat.completions.kwargs
        user_message = next(
            message["content"]
            for message in request["messages"]
            if message["role"] == "user"
        )
        payload = json.loads(user_message)
        self.assertLessEqual(len(payload["entities"]), 67)
        self.assertLessEqual(len(payload["existing_axioms_sample"]), 30)
        self.assertEqual(len(payload["previous_user_decisions"]), 5)


if __name__ == "__main__":
    unittest.main()
