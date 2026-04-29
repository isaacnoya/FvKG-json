import os
import json
from groq import Groq
from dotenv import load_dotenv
import requests
from rdflib import Namespace, Literal, BNode, URIRef

DBO = Namespace("http://dbpedia.org/ontology/")

load_dotenv()
    
def searchLLM(term, type="class",description="", model="openai/gpt-oss-120b"):  
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
        return URIRef(result['iri'])

import torch
from owlready2 import *
from sentence_transformers import SentenceTransformer, util

class VectorialOntologyMatcher:
    def __init__(self, owl_paths, index_cache="onto_index.pt"):
        self.model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
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

