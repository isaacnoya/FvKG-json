from classes import Reference, VirtualMapping
import rdflib
from utils import is_compatible, rdf_class_to_pom
from rdflib.plugins.sparql import prepareQuery


def get_compatible_mappings(pattern, mappings):
    """
    Devuelve la lista de mapeos compatibles con el patrón dado.
    """
    compatible_mappings = []
    for mapping in mappings:
        if is_compatible(pattern, mapping):
            compatible_mappings.append(mapping) 
    return compatible_mappings


def getMappings(mapping_file):
    mappings = rdflib.Graph()
    mappings = rdf_class_to_pom(mappings.parse(mapping_file, format="turtle"))

    # select all mapping rules with the form (subject, predicate, object/reference).
    # Source-related fields are optional because some RML files only need the
    # term maps for mapping selection.
    mappingRuleQuery = prepareQuery("""
    PREFIX rml: <http://w3id.org/rml/>
    PREFIX htv: <http://www.w3.org/2011/http#>
    PREFIX void: <http://rdfs.org/ns/void#> 

    SELECT ?subject ?predicate ?object ?reference ?url ?iterator ?nextPage ?filterx ?projectx ?limit ?nElements WHERE {
        ?tm a rml:TriplesMap ;
            rml:predicateObjectMap ?pom .
        OPTIONAL {
            ?tm rml:logicalSource ?ls .
            OPTIONAL {
                ?ls rml:source ?source .
                OPTIONAL { ?source htv:absoluteURI ?url . }
            }
            OPTIONAL { ?ls rml:iterator ?iterator . }
            OPTIONAL { ?ls void:nextPage ?nextPage . }
            OPTIONAL {
                ?ls void:limit ?limit .
                ?ls void:nElements ?nElements .
            }
        } .
        {
            ?pom rml:predicate ?predicate .
        } UNION {
            ?pom rml:predicateMap ?pm .
            ?pm rml:constant ?predicate .
        }
        ?tm rml:subjectMap ?sm .
        OPTIONAL {
            ?sm rml:template ?subject .
        } .
        OPTIONAL {
            ?sm rml:constant ?subject .
        } .
        OPTIONAL { ?pom rml:objectMap ?om .        
                    ?om void:filterx ?filterx 
        } .
        OPTIONAL {?pom rml:objectMap ?om .        
                    ?om void:projectx ?projectx 
        } .
        OPTIONAL {
            { ?pom rml:object ?object }
            UNION {
                ?pom rml:objectMap ?omObject .
                ?omObject rml:constant ?object .
            }
            UNION {
                ?pom rml:objectMap ?omObject .
                ?omObject rml:template ?object .
            }
        } .
        OPTIONAL { 
                ?pom rml:objectMap ?om .                    
                ?om rml:reference ?reference .
        } .
    }
    """)
    mrules = []
    for m in mappings.query(mappingRuleQuery):
        vb = VirtualMapping(*m)
        mrules.append(vb) if vb.o is not None else None

    mappingsParentTPQuery = prepareQuery("""
    PREFIX rml: <http://w3id.org/rml/>
    PREFIX htv: <http://www.w3.org/2011/http#>
    PREFIX void: <http://rdfs.org/ns/void#> 

    SELECT ?subject ?predicate ?object ?reference ?url ?iterator ?nextPage ?childJoinCond ?parentJoinCond ?parentURL ?parentIterator WHERE {
        ?tm a rml:TriplesMap ;
            rml:predicateObjectMap ?pom .
        OPTIONAL {
            ?tm rml:logicalSource ?ls .
            OPTIONAL {
                ?ls rml:source ?source .
                OPTIONAL { ?source htv:absoluteURI ?url . }
            }
            OPTIONAL { ?ls rml:iterator ?iterator . }
            OPTIONAL { ?ls void:nextPage ?nextPage . }
        } .
        {
            ?pom rml:predicate ?predicate .
        } UNION {
            ?pom rml:predicateMap ?pm .
            ?pm rml:constant ?predicate .
        }
                                         
        ?tm rml:subjectMap ?sm .
        OPTIONAL {
            ?sm rml:template ?subject .
        } .
        OPTIONAL {
            ?sm rml:constant ?subject .
        } .
        ?pom rml:objectMap ?om .
        ?om rml:joinCondition ?joinCondition .
        OPTIONAL {
        ?joinCondition rml:child ?childJoinCond .
        ?joinCondition rml:parent ?parentJoinCond .
        } .
                                         
        ?om rml:parentTriplesMap ?parentTM .
        ?parentTM rml:subjectMap ?parentSM .
        OPTIONAL {
            ?parentSM rml:template ?object .
        } .
        OPTIONAL {
            ?parentSM rml:constant ?object .
        } .
        OPTIONAL {
            ?parentTM rml:logicalSource ?parentLS .
            OPTIONAL {
                ?parentLS rml:source ?parentSource .
                OPTIONAL { ?parentSource htv:absoluteURI ?parentURL . }
            }
            OPTIONAL { ?parentLS rml:iterator ?parentIterator . }
        } .
    }
    """)
    for m in mappings.query(mappingsParentTPQuery):
        s, p, o, ref, url, iterator, nextPage, childJoinCond, parentJoinCond, parentURL, parentIterator = m
        vb = VirtualMapping(s, p, o, ref, url, iterator, nextPage)
        if parentURL is not None:
            vb.setParentTriplesMapInfo(childJoinCond, parentJoinCond, parentURL, parentIterator)
        mrules.append(vb) if vb.o is not None else None
                                         
    return mrules

def getMappingsFromTxT(file_name):
    all_rules = []
    try:
        with open(file_name, 'r', encoding='utf-8') as f:
            for line in f:
                mapping_file = line.strip()                
                if mapping_file:
                    rules = getMappings(mapping_file)
                    all_rules.extend(rules)                    
    except FileNotFoundError:
        print(f"Error: No se encontró el archivo de rutas en {mapping_file}")
    except Exception as e:
        print(f"Ocurrió un error inesperado: {e}")
        
    return all_rules

def getMappingsFromFolder(folder_path):
    import os
    all_rules = []
    try:
        for file_name in os.listdir(folder_path):
            if file_name.endswith('.ttl'):
                mapping_file = os.path.join(folder_path, file_name)
                rules = getMappings(mapping_file)
                all_rules.extend(rules)
    except FileNotFoundError:
        print(f"Error: No se encontró el directorio {folder_path}")
    except Exception as e:
        print(f"Ocurrió un error inesperado: {e}")
        
    return all_rules
