import rdflib
import re
from classes import *

from rdflib.plugins.sparql.sparql import AlreadyBound
  

def rdf_class_to_pom(mapping_graph):
    """
    Replace rr:class definitions by predicate object maps.
    """
    query = 'SELECT ?tm ?c WHERE { ' \
            f'?tm <{RML_SUBJECT_MAP}> ?sm . ' \
            f'?sm <{RML_CLASS}> ?c . }}'
    for tm, c in mapping_graph.query(query):
        blanknode = rdflib.BNode()
        mapping_graph.add((tm, rdflib.term.URIRef(RML_PREDICATE_OBJECT_MAP), blanknode))
        mapping_graph.add((blanknode, rdflib.term.URIRef(RML_PREDICATE_SHORTCUT), rdflib.RDF.type))
        mapping_graph.add((blanknode, rdflib.term.URIRef(RML_OBJECT_SHORTCUT), c))

    mapping_graph.remove((None, rdflib.term.URIRef(RML_CLASS), None))

    return mapping_graph

def completeParentTriplesMap(mapping_graph):
    # complete referencing object maps with the termtype coming from the subject of the parent
    query = 'SELECT DISTINCT ?term_map ?termtype WHERE { ' \
            f'?term_map <{RML_PARENT_TRIPLES_MAP}> ?parent_tm . ' \
            f'?parent_tm <{RML_SUBJECT_MAP}> ?parent_subject_map . ' \
            f'?parent_subject_map <{RML_TERM_TYPE}> ?termtype . }}'
    for term_map, termtype in mapping_graph.query(query):
        mapping_graph.add((term_map, rdflib.term.URIRef(RML_TERM_TYPE), rdflib.term.URIRef(termtype)))



def get_invariant(mapping_template):
    """
    Extrae el invariante: la subcadena inicial común compartida por todos 
    los triples en el rango del mapeo.
    """
    template_str = str(mapping_template)
    # Buscamos la posición del primer '{' para obtener la parte estática
    match = re.split(r'\{', template_str)
    return match[0]


def termMapCompatibility(t1, t2, pos=None):
    #TODO: Arreglar esto que rompe por todos lados y no es nada claro
    i1 = get_invariant(t1)
    i2 = get_invariant(t2)

    if pos == 'object' and isinstance(t1, Reference) and isinstance(t2, Reference):
        return True # References on object, always compatible

    if isinstance(t1, rdflib.term.Variable) or isinstance(t2, rdflib.term.Variable) or t1==None or t2==None:
        return True
    if (type(t1) is Reference and type(t2) is rdflib.term.Literal ) or (type(t2) is Reference and type(t1) is rdflib.term.Literal ) :
        return True
    if (i1.startswith(i2) or i2.startswith(i1)) and (isinstance(t1, rdflib.term.URIRef) or isinstance(t2, rdflib.term.URIRef)) and (isinstance(t1, Reference) or isinstance(t2, Reference)):
        return True
    #if not isinstance(t1, type(t2)) and not isinstance(t2, type(t1)):
    #    return False
    if ( i1 != i2 or not i1.startswith(i2) or not i2.startswith(i1)) :
        return False

    return True


def is_compatible(pattern, mapping):
    p_s, p_p, p_o = pattern.s, pattern.p, pattern.o
    m_s, m_p, m_o = mapping.s, mapping.p, mapping.o

    if termMapCompatibility(p_s, m_s) and termMapCompatibility(p_p, m_p) and termMapCompatibility(p_o, m_o, pos='object'):
        return True
    return False


from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from collections import defaultdict

def merge_urls(urls):
    if not urls:
        return None

    base = None
    merged_params = defaultdict(set)

    for url in urls:
        parsed = urlparse(url)

        # construir base sin query
        current_base = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            '', '', ''
        ))

        if base is None:
            base = current_base
        elif base != current_base:
            raise ValueError("Las URLs no comparten la misma base")

        params = parse_qs(parsed.query)

        for key, values in params.items():
            for v in values:
                merged_params[key].add(v)

    # convertir sets a listas
    merged_params = {k: list(v) for k, v in merged_params.items()}

    # construir query final
    query = urlencode(merged_params, doseq=True)

    return f"{base}?{query}"

def getBaseURL(url):
    parsed = urlparse(url)
    
    # Nos quedamos con esquema + netloc + path (sin params, query, fragment)
    base_url = urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        '',  # params
        '',  # query
        ''   # fragment
    ))
    
    return base_url   

from itertools import product
def normalize_hierarchical_data(data):
    """
    This is taken from
    https://stackoverflow.com/questions/36731480/flatten-nested-json-dict-list-into-list-to-prepare-to-write-into-db#answer-43173998
    """
    if isinstance(data, dict):
        keys = data.keys()
        values = (normalize_hierarchical_data(i) for i in data.values())
        for i in product(*values):
            yield (dict(zip(keys, i)))
    elif isinstance(data, list):
        for i in data:
            yield from normalize_hierarchical_data(i)
    else:
        yield data
