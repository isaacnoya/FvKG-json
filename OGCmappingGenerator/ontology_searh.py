import os
import json
from groq import Groq
from dotenv import load_dotenv
import requests
from rdflib import Graph, Namespace, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS

DBO = Namespace("http://dbpedia.org/ontology/")

load_dotenv()
    
def searchLLM(term, type="class",description="", model=None):  
    #return None
    api_key = os.getenv("GROQ_API_KEY")

    client = Groq(api_key=api_key)
    
    prompt_sistema = """
    You are an expert in Semantic Web and Linked Data.
    Your task is to map user {type} to Wikidata and DBpedia.
    Respond ONLY in JSON format with the following structure:
    {
    "{type}": "...",
    "wikidata_qid": "Q...",
    "dbpedia_uri": "http://dbpedia.org/ontology/..."
    }
    If you are not sure, set a low confidence value.
    """
    
    prompt_usuario = f"Find the equivalent Wikidata ID and DBpedia {type} URI for the {type}: '{term}'" if not description else f"Find the equivalent Wikidata QID and DBpedia {type} URI for the {type}: '{term}' with the following description: '{description}'"

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

        # Parsear la respuesta
        respuesta_json = json.loads(chat_completion.choices[0].message.content)
        return respuesta_json

    except Exception as e:
        print(f"Error con Groq: {e}")
        return None
    

def _compact_ontology_classes(ontology, max_classes=80):
    """Build a compact class list so the LLM can choose a valid parent."""
    class_uris = set(ontology.subjects(RDF.type, OWL.Class))
    class_uris.update(ontology.subjects(RDF.type, RDFS.Class))
    class_uris.update(ontology.subjects(RDFS.subClassOf, None))
    class_uris.update(ontology.objects(None, RDFS.subClassOf))

    classes = []
    for class_uri in sorted(class_uris, key=str):
        label = ontology.value(class_uri, RDFS.label)
        comment = ontology.value(class_uri, RDFS.comment)
        classes.append({
            "iri": str(class_uri),
            "label": str(label) if label else "",
            "comment": str(comment) if comment else ""
        })
        if len(classes) >= max_classes:
            break
    return classes


def _safe_fragment(term):
    fragment = "".join(char if char.isalnum() else "_" for char in term.strip())
    fragment = "_".join(part for part in fragment.split("_") if part)
    return fragment or "NewClass"


def llm_propose(ontology, term, type="class", description="", model=None, prefix="http://example.org/ontology#"):
    api_key = os.getenv("GROQ_API_KEY")
    client = Groq(api_key=api_key)
    existing_classes = _compact_ontology_classes(ontology) if isinstance(ontology, Graph) else []
    default_iri = f"{prefix}{_safe_fragment(term)}"
    prompt_sistema = f"""
    You are an expert in Semantic Web and Linked Data.
    Your task is to propose an extension of the ontology to include the following {type}: '{term}' with the following description: '{description}'.
    Choose the most specific parent class from the ontology classes provided by the user.
    Respond ONLY in JSON format with the following structure:
    {{
        "iri": "{default_iri}",
        "parent_iri": "existing ontology class IRI",
        "label": "{term}",
        "comment": "{description}"
    }}
    The parent_iri value MUST be one of the existing ontology class IRIs provided by the user.
    """
    prompt_usuario = json.dumps({
        "task": f"Propose where to attach the {type} in the ontology.",
        "term": term,
        "description": description,
        "default_iri": default_iri,
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
            return None
        
        # Manual validation by the user
        proposed_iri = respuesta_json.get("iri", "")
        print(f"Proposed IRI: {proposed_iri}")
        print(f"Proposed parent: {parent_iri}")
        print(f"Proposed label: {respuesta_json.get('label', '')}")
        user_input = input("Do you want to add this extension to the ontology? (yes/no): ").strip().lower()
        if user_input == "yes":
            return respuesta_json
        else:
            return None

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
        query_text = f"{name}: {description}"
        query_embedding = self.model.encode(query_text, convert_to_tensor=True)

        hits = util.semantic_search(query_embedding, self.ontology_embeddings, top_k=top_k)[0]

        if hits[0]['score'] > threshold:  # Umbral de confianza
            idx = hits[0]['corpus_id']

            return {
                "iri": self.entity_uris[idx],
                "type": self.entity_metadata[idx]['type'],
                "name": self.entity_metadata[idx]['name'],
                "confidence": round(hits[0]['score'], 4)
            }
        else:
            return None
    
if __name__ == "__main__":
    oe = VectorialOntologyMatcher(["/Users/kekojohns/Library/CloudStorage/OneDrive-Personal/muia/oeg/tfm/ontologiasReferencia/hydrOntology_GeoLinkedData.owl"])
    title = "HY-P Cruce"
    description = "Objeto artificial que permite el paso del agua por encima o por debajo de un obstáculo. Puede ser de tipo acueducto, puente, alcantarilla o sifón."
    resultado = oe.search(title, description, threshold=0.7)
    if resultado:
        sameAs = resultado['iri']
    if not resultado:
        sameAs = searchNotLocal(title, description, "class")

    print(f"Resultado de búsqueda: {sameAs}")
    pass
