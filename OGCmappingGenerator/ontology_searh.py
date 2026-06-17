import os
import json
import re
import requests
from rdflib import Graph, Namespace, Literal, URIRef
import rdflib
from rdflib.namespace import OWL, RDF, RDFS, XSD

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv():
        return False

try:
    from groq import Groq
except ImportError:
    Groq = None

DBO = Namespace("http://dbpedia.org/ontology/")
GEO = Namespace("http://www.opengis.net/ont/geosparql#")

load_dotenv()


def _require_groq():
    if Groq is None:
        raise ImportError(
            "The 'groq' package is required for LLM ontology search. "
            "Install requirements.txt."
        )
    return Groq


def _load_sparql_wrapper():
    try:
        from SPARQLWrapper import JSON, SPARQLWrapper
    except ImportError as exc:
        raise ImportError(
            "The 'SPARQLWrapper' package is required for external ontology "
            "lookups. Install requirements.txt."
        ) from exc
    return SPARQLWrapper, JSON


def _load_vector_dependencies():
    try:
        import torch
        from owlready2 import get_ontology
        from sentence_transformers import SentenceTransformer, util
    except ImportError as exc:
        raise ImportError(
            "Vector ontology matching requires torch, owlready2, and "
            "sentence-transformers. Install requirements.txt."
        ) from exc
    return torch, get_ontology, SentenceTransformer, util

GPT_OSS_MODELS = {
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
}


def _json_response_format(model, schema_name, schema):
    if model in GPT_OSS_MODELS:
        return {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": schema,
            },
        }
    return {"type": "json_object"}


def _validate_json_value(value, schema, path="$"):
    schema_type = schema.get("type")
    expected_types = {
        "object": dict,
        "array": list,
        "string": str,
    }
    expected_type = expected_types.get(schema_type)
    if expected_type and not isinstance(value, expected_type):
        raise ValueError(f"{path} must be a JSON {schema_type}.")

    if schema_type == "object":
        missing = [
            key
            for key in schema.get("required", [])
            if key not in value
        ]
        if missing:
            raise ValueError(
                f"{path} is missing required field(s): {', '.join(missing)}."
            )
        if schema.get("additionalProperties") is False:
            unexpected = set(value) - set(schema.get("properties", {}))
            if unexpected:
                raise ValueError(
                    f"{path} has unexpected field(s): "
                    f"{', '.join(sorted(unexpected))}."
                )
        for key, property_schema in schema.get("properties", {}).items():
            if key in value:
                _validate_json_value(
                    value[key],
                    property_schema,
                    f"{path}.{key}",
                )

    if schema_type == "array":
        item_schema = schema.get("items", {})
        for index, item in enumerate(value):
            _validate_json_value(item, item_schema, f"{path}[{index}]")

    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(
            f"{path} must be one of: {', '.join(schema['enum'])}."
        )


def _create_json_completion(
    client,
    messages,
    model,
    schema_name,
    schema,
    temperature,
    max_completion_tokens=1800,
):
    response_format = _json_response_format(model, schema_name, schema)
    request_messages = [dict(message) for message in messages]
    if response_format["type"] == "json_object":
        request_messages[0]["content"] += (
            "\nThe response must satisfy this exact JSON Schema:\n"
            + json.dumps(schema, ensure_ascii=False)
        )

    max_attempts = 1 if response_format["type"] == "json_schema" else 2
    last_error = None
    for attempt in range(max_attempts):
        chat_completion = client.chat.completions.create(
            messages=request_messages,
            model=model,
            temperature=temperature,
            max_completion_tokens=max_completion_tokens,
            response_format=response_format,
        )
        content = chat_completion.choices[0].message.content
        try:
            if not content:
                raise ValueError("Groq returned an empty structured response.")
            result = json.loads(content)
            _validate_json_value(result, schema)
            return result
        except (json.JSONDecodeError, ValueError) as error:
            last_error = error
            if attempt + 1 >= max_attempts:
                break
            request_messages.extend([
                {"role": "assistant", "content": content or ""},
                {
                    "role": "user",
                    "content": (
                        f"The previous response was invalid: {error} "
                        "Return only a corrected JSON object that satisfies "
                        "the schema exactly."
                    ),
                },
            ])

    raise ValueError(f"Groq returned invalid structured output: {last_error}")


def preprocess_local_search_text(text):
    """Normalize API-style identifiers only for local embedding search."""
    if not text:
        return ""

    text = str(text)
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    text = re.sub(r"[_\-.:/\\]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text
    
def searchLLM(term, type="class", description="", model="llama-3.3-70b-versatile"):  
    api_key = os.getenv("GROQ_API_KEY")
    client = _require_groq()(api_key=api_key)

    prompt_sistema = f"""You are an expert in Semantic Web.
    Map the requested {type} to Wikidata and DBpedia.
    Use an empty string when no reliable identifier or URI exists.
    Respond only with the requested JSON object."""

    prompt_usuario = json.dumps({
        "entity_type": type,
        "term": term,
        "description": description,
    }, ensure_ascii=False)
    schema = {
        "type": "object",
        "properties": {
            "term": {"type": "string"},
            "wikidata_qid": {"type": "string"},
            "dbpedia_uri": {"type": "string"},
        },
        "required": ["term", "wikidata_qid", "dbpedia_uri"],
        "additionalProperties": False,
    }

    try:
        return _create_json_completion(
            client,
            [
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": prompt_usuario}
            ],
            model,
            "external_semantic_mapping",
            schema,
            temperature=0.1,
        )
    except Exception as e:
        print(f"Error con Groq: {e}")
        return None
    

def _compact_ontology_classes(ontology_path, max_classes=100):
    """Build a compact class list so the LLM can choose a valid parent."""
    ontology = rdflib.Graph()
    ontology.parse(ontology_path)

    class_uris = set(ontology.subjects(RDF.type, OWL.Class))
    class_uris.update(ontology.subjects(RDF.type, RDFS.Class))
    class_uris.update(ontology.subjects(RDFS.subClassOf, None))
    class_uris.update(ontology.objects(None, RDFS.subClassOf))

    classes = []
    for class_uri in class_uris:        
        label = ontology.value(class_uri, RDFS.label)
        comment = ontology.value(class_uri, RDFS.comment)
        classes.append({
            "iri": str(class_uri),
            "label": str(label) if label else "",
            "comment": str(comment) if comment else ""
        }) if not isinstance(class_uri, rdflib.BNode) else None
        if len(classes) >= max_classes:
            break
    return classes


def _compact_graph_entities(ontology, max_entities=120):
    """Build a compact entity list from an rdflib graph for axiom proposals."""
    entities = set()
    for entity_type in (OWL.Class, RDFS.Class, RDF.Property, OWL.ObjectProperty, OWL.DatatypeProperty):
        entities.update(ontology.subjects(RDF.type, entity_type))
    entities.update(ontology.subjects(RDFS.subClassOf, None))
    entities.update(ontology.objects(None, RDFS.subClassOf))
    entities.update(ontology.subjects(RDFS.domain, None))
    entities.update(ontology.objects(None, RDFS.domain))
    entities.update(ontology.subjects(RDFS.range, None))
    entities.update(ontology.objects(None, RDFS.range))

    compact_entities = []
    for entity in entities:
        if isinstance(entity, rdflib.BNode):
            continue
        label = ontology.value(entity, RDFS.label)
        comment = ontology.value(entity, RDFS.comment)
        rdf_types = [str(t) for t in ontology.objects(entity, RDF.type) if not isinstance(t, rdflib.BNode)]
        compact_entities.append({
            "iri": str(entity),
            "label": str(label) if label else "",
            "comment": str(comment) if comment else "",
            "types": rdf_types[:3]
        })
        if len(compact_entities) >= max_entities:
            break
    compact_entities.extend([
        {
            "iri": str(GEO.Feature),
            "label": "Feature",
            "comment": "GeoSPARQL feature class",
            "types": [str(OWL.Class)]
        },
        {
            "iri": str(GEO.Geometry),
            "label": "Geometry",
            "comment": "GeoSPARQL geometry class",
            "types": [str(OWL.Class)]
        },
        {
            "iri": str(GEO.hasGeometry),
            "label": "hasGeometry",
            "comment": "GeoSPARQL property linking a feature to a geometry",
            "types": [str(RDF.Property)]
        },
        {
            "iri": str(XSD.string),
            "label": "string",
            "comment": "XML Schema string datatype",
            "types": ["datatype"]
        },
        {
            "iri": str(XSD.integer),
            "label": "integer",
            "comment": "XML Schema integer datatype",
            "types": ["datatype"]
        },
        {
            "iri": str(XSD.float),
            "label": "float",
            "comment": "XML Schema float datatype",
            "types": ["datatype"]
        },
        {
            "iri": str(XSD.boolean),
            "label": "boolean",
            "comment": "XML Schema boolean datatype",
            "types": ["datatype"]
        }
    ])
    return compact_entities


def _compact_graph_properties(ontology, max_properties=100):
    """Build a compact property list from an rdflib graph for extension proposals."""
    properties = set()
    for property_type in (RDF.Property, OWL.ObjectProperty, OWL.DatatypeProperty):
        properties.update(ontology.subjects(RDF.type, property_type))
    properties.update(ontology.subjects(RDFS.subPropertyOf, None))
    properties.update(ontology.objects(None, RDFS.subPropertyOf))

    compact_properties = []
    for property_uri in properties:
        if isinstance(property_uri, rdflib.BNode):
            continue
        label = ontology.value(property_uri, RDFS.label)
        comment = ontology.value(property_uri, RDFS.comment)
        compact_properties.append({
            "iri": str(property_uri),
            "label": str(label) if label else "",
            "comment": str(comment) if comment else ""
        })
        if len(compact_properties) >= max_properties:
            break
    return compact_properties


def _safe_fragment(term):
    fragment = "".join(char if char.isalnum() else "_" for char in term.strip())
    fragment = "_".join(part for part in fragment.split("_") if part)
    return fragment or "NewClass"


def llm_propose(ontology, term, type="class", description="", model=None, prefix="http://example.org/ontology#", interactive=True):
    api_key = os.getenv("GROQ_API_KEY")
    client = _require_groq()(api_key=api_key)
    existing_classes = _compact_ontology_classes(ontology) 
    default_iri = f"{prefix}{_safe_fragment(term)}"
    prompt_sistema = f"""
    You are an expert in Semantic Web and Linked Data.
    Your task is to identify the equivalent class in the ontology or, in case there isn't, propose an extension of the ontology to include the following {type}: '{term}' with the following description: '{description}'.
    Choose the most specific parent class from the ontology classes provided by the user and use a generic label and comment for the new class based on the term and description.
    Respond only with the requested JSON object.
    The parent_iri value MUST be one of the existing ontology class IRIs provided by the user.
    """
    prompt_usuario = json.dumps({
        "task": f"Propose where to attach the {type} in the ontology and a new IRI in that ontology for the attached concept",
        "term": term,
        "description": description,
        "existing_classes": existing_classes
    }, ensure_ascii=False)
    schema = {
        "type": "object",
        "properties": {
            "iri": {"type": "string"},
            "parent_iri": {"type": "string"},
            "label": {"type": "string"},
            "comment": {"type": "string"},
        },
        "required": ["iri", "parent_iri", "label", "comment"],
        "additionalProperties": False,
    }
    try:
        respuesta_json = _create_json_completion(
            client,
            [
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": prompt_usuario}
            ],
            model,
            "ontology_class_extension",
            schema,
            temperature=0.1,
        )
        respuesta_json.setdefault("iri", default_iri)
        respuesta_json.setdefault("label", term)
        respuesta_json.setdefault("comment", description)

        parent_iri = respuesta_json.get("parent_iri")
        valid_parent_iris = {c["iri"] for c in existing_classes}
        if parent_iri not in valid_parent_iris:
            print(f"Parent IRI proposed by Groq is not in the ontology: {parent_iri}")
            print("Continuing anyway")
            #return None
        
        if not interactive:
            return None

        # Manual validation by the user
        proposed_iri = respuesta_json.get("iri", "")
        print(f"Proposed IRI: {proposed_iri}")
        print(f"Proposed parent: {parent_iri}")
        print(f"Proposed label: {respuesta_json.get('label', '')}")
        print(f"Proposed comment: {respuesta_json.get('comment', '')}")
        user_input = input("Do you want to add this extension to the ontology? (yes/no): ").strip().lower()
        if user_input in {"yes", "y", "si", "sí", "s"}:
            return respuesta_json
        else:
            return None

    except Exception as e:
        print(f"Error con Groq: {e}")
        return None


def llm_propose_property(ontology, term, description="", datatype="", domain_iri="", model=None, prefix="http://example.org/ontology#", interactive=True):
    api_key = os.getenv("GROQ_API_KEY")
    client = _require_groq()(api_key=api_key)
    existing_properties = _compact_graph_properties(ontology)
    default_iri = f"{prefix}{_safe_fragment(term)}"
    prompt_sistema = f"""
    You are an expert in Semantic Web, RDFS, and OWL ontology engineering.
    The user has a first draft ontology and needs to represent a data property from an OGC API collection.
    If there is no suitable existing property, propose a conservative ontology extension for this property.
    Prefer attaching the new property with rdfs:subPropertyOf to the most specific compatible property from the provided list.
    Respond only with the requested JSON object.
    The parent_iri value, when present, MUST be one of the existing property IRIs provided by the user.
    """
    prompt_usuario = json.dumps({
        "task": "Propose an ontology property extension for an unaligned OGC API property.",
        "term": term,
        "description": description,
        "datatype": datatype,
        "domain_iri": domain_iri,
        "existing_properties": existing_properties
    }, ensure_ascii=False)
    schema = {
        "type": "object",
        "properties": {
            "iri": {"type": "string"},
            "parent_iri": {"type": "string"},
            "label": {"type": "string"},
            "comment": {"type": "string"},
        },
        "required": ["iri", "parent_iri", "label", "comment"],
        "additionalProperties": False,
    }
    try:
        respuesta_json = _create_json_completion(
            client,
            [
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": prompt_usuario}
            ],
            model,
            "ontology_property_extension",
            schema,
            temperature=0.1,
        )
        respuesta_json.setdefault("iri", default_iri)
        respuesta_json.setdefault("label", term)
        respuesta_json.setdefault("comment", description)
        respuesta_json.setdefault("parent_iri", "")

        parent_iri = respuesta_json.get("parent_iri")
        valid_parent_iris = {p["iri"] for p in existing_properties}
        if parent_iri and parent_iri not in valid_parent_iris:
            print(f"Parent property IRI proposed by Groq is not in the ontology: {parent_iri}")
            print("Continuing without parent property")
            respuesta_json["parent_iri"] = ""

        if not interactive:
            return None

        print(f"Proposed property IRI: {respuesta_json.get('iri', '')}")
        print(f"Proposed parent property: {respuesta_json.get('parent_iri', '')}")
        print(f"Proposed label: {respuesta_json.get('label', '')}")
        print(f"Proposed comment: {respuesta_json.get('comment', '')}")
        user_input = input("Do you want to add this property extension to the ontology? (yes/no): ").strip().lower()
        if user_input in {"yes", "y", "si", "sí", "s"}:
            return respuesta_json
        return None

    except Exception as e:
        print(f"Error con Groq: {e}")
        return None


def llm_propose_axiom(ontology, model=None, history=None):
    api_key = os.getenv("GROQ_API_KEY")
    client = _require_groq()(api_key=api_key)
    entities = _compact_graph_entities(ontology, max_entities=60)
    existing_axioms_sample = []
    for s, p, o in ontology.triples((None, None, None)):
        if isinstance(s, rdflib.BNode) or isinstance(o, rdflib.BNode):
            continue
        existing_axioms_sample.append({"subject": str(s), "predicate": str(p), "object": str(o)})
        if len(existing_axioms_sample) >= 30:
            break

    prompt_sistema = """
    You are an expert in OWL, RDFS, GeoSPARQL, and ontology engineering.
    Propose exactly one useful local OWL class restriction for the ontology.
    Do NOT propose global rdfs:domain or rdfs:range axioms. They are too rigid because they make
    any subject/object using a property inherit the global class/range.
    Model property constraints locally on the class with an anonymous owl:Restriction attached via rdfs:subClassOf.
    Prefer conservative restrictions:
    - owl:someValuesFrom for required existence, e.g. a class has at least one value for a property.
    - owl:allValuesFrom for local value typing, e.g. every value of that property for this class has a datatype/class.
    - owl:cardinality, owl:minCardinality, or owl:maxCardinality for local cardinality constraints.
    Use only class, property, datatype, and value IRIs from the provided entity list.
    Respond ONLY with JSON using this structure:
    {
      "rationale": "short explanation",
      "restrictions": [
        {
          "class_iri": "existing class IRI receiving the restriction",
          "property_iri": "existing property IRI used in owl:onProperty",
          "quantifier": "someValuesFrom | allValuesFrom | cardinality | minCardinality | maxCardinality",
          "value_iri": "existing class/datatype IRI for someValuesFrom/allValuesFrom, otherwise empty string",
          "cardinality": "non-negative integer for cardinality/minCardinality/maxCardinality, otherwise empty string"
        }
      ]
    }
    """
    prompt_usuario = json.dumps({
        "task": "Propose one local OWL class restriction that improves the ontology without global domain/range axioms.",
        "entities": entities,
        "existing_axioms_sample": existing_axioms_sample,
        "previous_user_decisions": (history or [])[-5:]
    }, ensure_ascii=False)
    schema = {
        "type": "object",
        "properties": {
            "rationale": {"type": "string"},
            "restrictions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "class_iri": {"type": "string"},
                        "property_iri": {"type": "string"},
                        "quantifier": {
                            "type": "string",
                            "enum": [
                                "someValuesFrom",
                                "allValuesFrom",
                                "cardinality",
                                "minCardinality",
                                "maxCardinality",
                            ],
                        },
                        "value_iri": {"type": "string"},
                        "cardinality": {"type": "string"},
                    },
                    "required": [
                        "class_iri",
                        "property_iri",
                        "quantifier",
                        "value_iri",
                        "cardinality",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["rationale", "restrictions"],
        "additionalProperties": False,
    }

    try:
        proposal = _create_json_completion(
            client,
            [
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": prompt_usuario}
            ],
            model,
            "ontology_axiom_proposal",
            schema,
            temperature=0.2,
        )
        restrictions = proposal.get("restrictions", [])
        if not restrictions:
            return None
        return proposal
    except Exception as e:
        print(f"Error con Groq: {e}")
        return None

def existe_en_wikidata(id_recurso):
    """Consulta si un ID (ej: Q42, P31) existe en Wikidata."""
    SPARQLWrapper, JSON = _load_sparql_wrapper()
    sparql = SPARQLWrapper("https://query.wikidata.org/sparql")
    # El User-Agent es obligatorio para Wikidata
    sparql.agent = "MiBotVerificador/1.0" 
    
    query = f"""
    ASK {{
      wd:{id_recurso} ?p ?o .
    }}
    """
    sparql.setQuery(query)
    sparql.setReturnFormat(JSON)
    try:
        resultado = sparql.query().convert()
    except Exception as e:
        return False
    return resultado["boolean"]

def existe_en_dbpedia(recurso_ontologia):
    """Consulta si una clase o propiedad (ej: City, birthDate) existe en la ontología de DBpedia."""
    SPARQLWrapper, JSON = _load_sparql_wrapper()
    sparql = SPARQLWrapper("https://dbpedia.org/sparql")
    
    query = f"""
    PREFIX dbo: <http://dbpedia.org/ontology/>
    ASK {{
      dbo:{recurso_ontologia} ?p ?o .
    }}
    """
    sparql.setQuery(query)
    sparql.setReturnFormat(JSON)
    try:
        resultado = sparql.query().convert()
        return resultado["boolean"]
    except Exception as e:
        return False

def buscar_dbpedia_label(label):
    """Busca una clase o propiedad en DBpedia por su label."""
    SPARQLWrapper, JSON = _load_sparql_wrapper()
    sparql = SPARQLWrapper("https://dbpedia.org/sparql")
    
    query = f"""
    SELECT ?resource WHERE {{
      ?resource rdfs:label "{label}"@es .
    }} LIMIT 1
    """
    sparql.setQuery(query)
    sparql.setReturnFormat(JSON)
    try:
        resultado = sparql.query().convert()
    except Exception as e:
        return None
    if resultado["results"]["bindings"]:
        return resultado["results"]["bindings"][0]["resource"]["value"]
    return None

def searchNotLocal(term, description="", type="class", model="llama-3.3-70b-versatile"):
    if not (result:= buscar_dbpedia_label(term)):
        result = searchLLM(term, type=type, description=description, model=model)
        if not result:
            return None

        dbpedia_uri = result.get("dbpedia_uri")
        wikidata_qid = result.get("wikidata_qid")
        if not dbpedia_uri or not wikidata_qid:
            return None
        dbpedia_resource = dbpedia_uri.rstrip("/").split("/")[-1]
        if existe_en_dbpedia(dbpedia_resource) and existe_en_wikidata(wikidata_qid):
            return DBO[dbpedia_resource]
        else:
            return None
    else:
        return URIRef(result)

class VectorialOntologyMatcher:
    def __init__(self, owl_paths, index_cache="onto_index.pt", model=None):
        torch, get_ontology, SentenceTransformer, util = _load_vector_dependencies()
        self._torch = torch
        self._semantic_util = util
        self.model = SentenceTransformer(model)
        self.cache_path = index_cache
        
        self.entity_uris = []
        self.entity_metadata = []
        self.ontology_embeddings = None
        
        # Cargamos todas las ontologías en el mismo mundo
        self.ontos = []
        for path in owl_paths:
            self.ontos.append(get_ontology(path).load())

        if os.path.exists(self.cache_path):
            self._load_index()
        else:
            self._build_index()

    def _get_entity_text(self, entity, entity_type):
        """Extrae texto representativo de cualquier entidad OWL."""
        label = entity.label.first() if entity.label else ""
        comment = entity.comment.first() if entity.comment else ""
        # Añadimos el tipo de entidad al texto para dar contexto al modelo
        return f"{entity_type}: {entity.name}. Etiqueta: {label}. Descripción: {comment}".strip()

    def _build_index(self):
        all_texts = []
        self.entity_uris = [] # Limpiamos para evitar duplicados si se llama dos veces
        self.entity_metadata = []

        for onto in self.ontos:
            entities_to_index = [
                (list(onto.classes()), "Clase"),
                (list(onto.object_properties()), "Propiedad de Objeto"),
                (list(onto.data_properties()), "Propiedad de Datos")
            ]

            for entities, e_type in entities_to_index:
                for e in entities:
                    text = self._get_entity_text(e, e_type)
                    all_texts.append(text)
                    self.entity_uris.append(str(e.iri)) 
                    self.entity_metadata.append({
                        "name": e.name, 
                        "type": e_type,
                        "ontology": onto.name
                    })
        
        self.ontology_embeddings = self.model.encode(all_texts, convert_to_tensor=True)

        self._torch.save({
            'embeddings': self.ontology_embeddings,
            'uris': self.entity_uris,
            'metadata': self.entity_metadata
        }, self.cache_path)
    
    def _load_index(self):
        print("Cargando índice desde cache...")
        data = self._torch.load(self.cache_path, weights_only=False) 
        self.ontology_embeddings = data['embeddings']
        self.entity_uris = data['uris']
        self.entity_metadata = data['metadata']

    def search(self, name, description, top_k=1, threshold=0.7):
        """Busca en el espacio vectorial y devuelve los más cercanos."""
        results = self.search_top(name, description, top_k=top_k, threshold=threshold)
        return results[0] if results else None

    def search_top(self, name, description, top_k=5, threshold=0.7):
        """Busca en el espacio vectorial y devuelve hasta top_k candidatos."""
        search_name = preprocess_local_search_text(name)
        search_description = description
        query_text = f"{search_name}: {search_description}"
        query_embedding = self.model.encode(query_text, convert_to_tensor=True)

        hits = self._semantic_util.semantic_search(
            query_embedding,
            self.ontology_embeddings,
            top_k=top_k,
        )[0]
        results = []
        for hit in hits:
            if threshold is not None and hit["score"] <= threshold:
                continue
            idx = hit['corpus_id']
            results.append({
                "iri": self.entity_uris[idx],
                "type": self.entity_metadata[idx]['type'],
                "name": self.entity_metadata[idx]['name'],
                "confidence": round(hit['score'], 4),
                "query_text": query_text
            })
        return results
    
if __name__ == "__main__":
    oe = VectorialOntologyMatcher(["/Users/kekojohns/Library/CloudStorage/OneDrive-Personal/muia/oeg/tfm/ontologiasReferencia/hydrOntology_GeoLinkedData.owl"])
    title = "HY-P Cruce"
    description = "Objeto artificial que permite el paso del agua por encima o por debajo de un obstáculo. Puede ser de tipo acueducto, puente, alcantarilla o sifón."
    resultado = oe.search(title, description, threshold=0.7)
    if resultado:
        equivalentClass = resultado['iri']
    if not resultado:
        equivalentClass = searchNotLocal(title, description, "class")

    print(f"Resultado de búsqueda: {equivalentClass}")
    pass
