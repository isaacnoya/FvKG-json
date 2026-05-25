import os
import json
import re
from groq import Groq
from dotenv import load_dotenv
import requests
from rdflib import Graph, Namespace, Literal, URIRef
import rdflib
from rdflib.namespace import OWL, RDF, RDFS

DBO = Namespace("http://dbpedia.org/ontology/")

load_dotenv()


def preprocess_local_search_text(text):
    """Normalize API-style identifiers only for local embedding search."""
    if not text:
        return ""

    text = str(text)
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    text = re.sub(r"[_\-.:/\\]+", " ", text)
    text = re.sub(r"\b(gdb|geomattr|attr|data|tbl|tmp|id|pk|fk)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\d+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text
    
def searchLLM(term, type="class", description="", model="llama-3.3-70b-versatile"):  
    api_key = os.getenv("GROQ_API_KEY")
    client = Groq(api_key=api_key)
    
    # Usamos f-string con doble llave para el esquema JSON
    prompt_sistema = f"""You are an expert in Semantic Web. 
    Return a JSON object mapping the {type} to Wikidata and DBpedia.
    JSON structure:
    {{
    "{type}": "{term}",
    "wikidata_qid": "QID here",
    "dbpedia_uri": "URI here"
    }}
    Respond ONLY with JSON."""
    
    prompt_usuario = f"Mapping for {type}: '{term}'"
    if description:
        prompt_usuario += f" Description: {description}"

    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": prompt_usuario}
            ],
            model=model,
            temperature=0.1,
            response_format={"type": "json_object"} 
        )

        content = chat_completion.choices[0].message.content
        return json.loads(content)

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
    return compact_entities


def _safe_fragment(term):
    fragment = "".join(char if char.isalnum() else "_" for char in term.strip())
    fragment = "_".join(part for part in fragment.split("_") if part)
    return fragment or "NewClass"


def llm_propose(ontology, term, type="class", description="", model=None, prefix="http://example.org/ontology#", interactive=True):
    api_key = os.getenv("GROQ_API_KEY")
    client = Groq(api_key=api_key)
    existing_classes = _compact_ontology_classes(ontology) 
    default_iri = f"{prefix}{_safe_fragment(term)}"
    prompt_sistema = f"""
    You are an expert in Semantic Web and Linked Data.
    Your task is to identify the equivalent class in the ontology or, in case there isn't, propose an extension of the ontology to include the following {type}: '{term}' with the following description: '{description}'.
    Choose the most specific parent class from the ontology classes provided by the user and use a generic label and comment for the new class based on the term and description.
    Respond ONLY in JSON format with the following structure:
    {{
        "iri": "proposed IRI",
        "parent_iri": "existing ontology class IRI",
        "label": "{term}",
        "comment": "{description}"
    }}
    The parent_iri value MUST be one of the existing ontology class IRIs provided by the user.
    """
    prompt_usuario = json.dumps({
        "task": f"Propose where to attach the {type} in the ontology and a new IRI in that ontology for the attached concept",
        "term": term,
        "description": description,
        "existing_classes": existing_classes
    }, ensure_ascii=False)
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": prompt_usuario}
            ],
            model=model, # Usamos el modelo grande para mejor precisión
            temperature=0.1, # Temperatura baja para que sea determinista
            response_format={"type": "json_object"} # Forzamos salida JSON
        )

        respuesta_json = json.loads(chat_completion.choices[0].message.content)
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


def llm_propose_axiom(ontology, model=None, history=None):
    api_key = os.getenv("GROQ_API_KEY")
    client = Groq(api_key=api_key)
    entities = _compact_graph_entities(ontology)
    existing_axioms = []
    for s, p, o in ontology.triples((None, None, None)):
        if isinstance(s, rdflib.BNode) or isinstance(o, rdflib.BNode):
            continue
        existing_axioms.append({"subject": str(s), "predicate": str(p), "object": str(o)})
        if len(existing_axioms) >= 120:
            break

    prompt_sistema = """
    You are an expert in OWL, RDFS, GeoSPARQL, and ontology engineering.
    Propose exactly one useful ontology axiom that connects existing concepts in the ontology.
    Prefer conservative axioms such as rdfs:subClassOf, owl:equivalentClass, rdfs:domain, rdfs:range,
    owl:disjointWith, or a meaningful existing object property.
    Do not invent new class or property IRIs. Use only IRIs from the provided entity list for subject and object.
    Respond ONLY with JSON using this structure:
    {
      "rationale": "short explanation",
      "axioms": [
        {
          "subject": "existing subject IRI",
          "predicate": "predicate IRI",
          "object": "existing object IRI"
        }
      ]
    }
    """
    prompt_usuario = json.dumps({
        "task": "Propose one ontology axiom that connects existing ontology concepts.",
        "entities": entities,
        "existing_axioms_sample": existing_axioms,
        "previous_user_decisions": history or []
    }, ensure_ascii=False)

    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": prompt_usuario}
            ],
            model=model,
            temperature=0.2,
            response_format={"type": "json_object"}
        )
        proposal = json.loads(chat_completion.choices[0].message.content)
        axioms = proposal.get("axioms", [])
        if not axioms:
            return None
        return proposal
    except Exception as e:
        print(f"Error con Groq: {e}")
        return None

from SPARQLWrapper import SPARQLWrapper, JSON

def existe_en_wikidata(id_recurso):
    """Consulta si un ID (ej: Q42, P31) existe en Wikidata."""
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
    
        dbpedia_resource = result['dbpedia_uri'].split('/')[-1] if result['dbpedia_uri'] else None
        if existe_en_dbpedia(dbpedia_resource) and existe_en_wikidata(result['wikidata_qid']):
            return DBO[dbpedia_resource]
        else:
            return None
    else:
        return URIRef(result)

import torch
from owlready2 import *
from sentence_transformers import SentenceTransformer, util

class VectorialOntologyMatcher:
    def __init__(self, owl_paths, index_cache="onto_index.pt", model=None):
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

        torch.save({
            'embeddings': self.ontology_embeddings,
            'uris': self.entity_uris,
            'metadata': self.entity_metadata
        }, self.cache_path)
    
    def _load_index(self):
        print("Cargando índice desde cache...")
        data = torch.load(self.cache_path, weights_only=False) 
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
        search_description = preprocess_local_search_text(description)
        query_text = f"{search_name}: {search_description}"
        query_embedding = self.model.encode(query_text, convert_to_tensor=True)

        hits = util.semantic_search(query_embedding, self.ontology_embeddings, top_k=top_k)[0]
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
