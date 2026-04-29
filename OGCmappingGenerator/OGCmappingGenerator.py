import argparse
import requests
from jsonpath import JSONPath
import rdflib
from rdflib import Namespace, Literal, BNode, URIRef
import os
import tqdm
from ontology_searh import VectorialOntologyMatcher, searchNotLocal

EX = Namespace("http://example.com/")
HTV = Namespace("http://www.w3.org/2011/http#")
GEO = Namespace("http://www.opengis.net/ont/geosparql#")
OGC = Namespace("http://www.ogc.org/")
SCHEMA = Namespace("http://schema.org/")
RR = Namespace("http://www.w3.org/ns/r2rml#")
RML = Namespace("http://w3id.org/rml/")
XSD = Namespace("http://www.w3.org/2001/XMLSchema#")
WGS84_POS = Namespace("http://www.w3.org/2003/01/geo/wgs84_pos#")
RDF = Namespace("http://www.w3.org/1999/02/22-rdf-syntax-ns#")
RDFS = Namespace("http://www.w3.org/2000/01/rdf-schema#")
OWL = Namespace("http://www.w3.org/2002/07/owl#")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
FOAF = Namespace("http://xmlns.com/foaf/0.1/")
ORG = Namespace("http://www.w3.org/ns/org#")
VOID = Namespace("http://rdfs.org/ns/void#")
GEOLINKEDDATA = Namespace("http://geo.linkeddata.es/ontology/")
DBO = Namespace("http://dbpedia.org/ontology/")
namespaces = {
    "": EX, "schema": SCHEMA, "rr": RR, "rml": RML, "xsd": XSD,
    "wgs84_pos": WGS84_POS, "rdf": RDF, "rdfs": RDFS, "owl": OWL, "skos": SKOS,"foaf": FOAF, "org": ORG, 
    "geo": GEO, "ogc": OGC, "htv": HTV, "void": VOID, "geolinkeddata": GEOLINKEDDATA, "dbo": DBO
}

class Collection:
    def __init__(self, id, title, description, spatial, url, oe: VectorialOntologyMatcher, search_not_local=False):
        self.id = id
        self.title = title
        self.description = description
        self.bbox = spatial["bbox"] if spatial and "bbox" in spatial else None
        self.crs = spatial["crs"] if spatial and "crs" in spatial else None
        self.url = url
        self.oe = oe
        self.search_not_local = search_not_local
        self.properties = self._set_properties()
        self.sameAs = self.sameAsF()

    def _set_properties(self): 
        r = requests.get(self.url+ "/queryables" + "?f=json").json()
        ret = JSONPath("$.properties").parse(r)
        ret = ret[0] if ret else {}
        l = []
        for i, v in ret.items():
            sameAs = self.oe.search(i, "", threshold=0.7) if self.oe else None
            """
            if not sameAs and self.search_not_local: # demasiado costoso hacer la busqueda de cada propiedad.
                sameAs = searchNotLocal(i, "", "property")
            """
            l.append({
                "title": i,
                "type": v.get("type", "string"),  # default to string if type is not provided     
                "sameAs": URIRef(sameAs['iri']) if sameAs else None
            })
        return l
    
    def sameAsF(self):
        resultado = self.oe.search(self.title, self.description, threshold=0.7)
        if resultado:
            return URIRef(resultado['iri'])
        if not resultado and self.search_not_local:
            return searchNotLocal(self.title, self.description, "class")


def add_logical_sources(inputId, urlAPI, ns, g_mappings):
    fuenteAPI = ns["FuenteAPI_" + inputId]
    g_mappings.add((fuenteAPI, HTV["absoluteURI"], Literal(urlAPI)))

    ls_suffix = "LogicalSource_" + inputId
    ls_subject = ns[ls_suffix]
    g_mappings.add((ls_subject, RDF.type, RML.logicalSource))
    g_mappings.add((ls_subject, RML.source, fuenteAPI))
    g_mappings.add((ls_subject, VOID.nextPage, Literal("$.links[?(@.rel==\"next\")].href")))
    g_mappings.add((ls_subject, RML.iterator, Literal("$.features.*")))
    g_mappings.add((ls_subject, RML.referenceFormulation, RML.HTTPAPI))

def add_pom_obj(triples_map, pred, obj, g_mappings, lang=None):
    pom_bnode = BNode()
    g_mappings.add((triples_map, RML.predicateObjectMap, pom_bnode))
    g_mappings.add((pom_bnode, RML.predicate, pred))
    if lang:
        g_mappings.add((pom_bnode, RML.object, Literal(obj, lang=lang)))
    else:
        g_mappings.add((pom_bnode, RML.object, obj if isinstance(obj, URIRef) else Literal(obj)))

def add_pom_ref(triples_map, pred, ref, g_mappings, datatype=None, filter=None):
    pom_bnode = BNode()
    g_mappings.add((triples_map, RML.predicateObjectMap, pom_bnode))
    g_mappings.add((pom_bnode, RML.predicate, pred))
    object_map_bnode = BNode()
    g_mappings.add((pom_bnode, RML.objectMap, object_map_bnode))
    g_mappings.add((object_map_bnode, RML.reference, Literal(ref)))
    if filter:
        g_mappings.add((object_map_bnode, VOID.filterx, Literal(filter)))
    if datatype:
        g_mappings.add((object_map_bnode, RML.datatype, datatype))

def add_pom_parenttpm(triples_map, pred, parent_triples_map, join_condition_child, join_condition_parent, g_mappings):
    pom_bnode = BNode()
    g_mappings.add((triples_map, RML.predicateObjectMap, pom_bnode))
    g_mappings.add((pom_bnode, RML.predicate, pred))
    object_map_bnode = BNode()
    g_mappings.add((pom_bnode, RML.objectMap, object_map_bnode))
    g_mappings.add((object_map_bnode, RML.parentTriplesMap, parent_triples_map))
    if join_condition_child and join_condition_parent:
        join_condition_bnode = BNode()
        g_mappings.add((object_map_bnode, RML.joinCondition, join_condition_bnode))
        g_mappings.add((join_condition_bnode, RML.child, Literal(join_condition_child)))
        g_mappings.add((join_condition_bnode, RML.parent, Literal(join_condition_parent)))

def add_subject_map(triples_map, class_uri, g_mappings, template=None, constant_uri=None):
    subject_map_bnode = BNode()
    g_mappings.add((triples_map, RML.subjectMap, subject_map_bnode))
    if constant_uri:
        g_mappings.add((subject_map_bnode, RML.constant, constant_uri))
    g_mappings.add((subject_map_bnode, RML["class"], class_uri))
    if template:
        g_mappings.add((subject_map_bnode, RML.template, Literal(template)))
    return subject_map_bnode

def add_subject_map_BN(triples_map, g_mappings):
    subject_map_bnode = BNode()
    g_mappings.add((triples_map, RML.subjectMap, subject_map_bnode))

    g_mappings.add((subject_map_bnode, RML.constant, BNode()))
    g_mappings.add((subject_map_bnode, RML["termType"], RML["BlankNode"]))



def get_collections(urlBase, oe: VectorialOntologyMatcher, search_not_local=False):
    try:
        response = requests.get(urlBase+"/collections?f=json")
    except requests.exceptions.RequestException as e:
        print(f"Error fetching collections: {e}")
        return []
    collections_json = JSONPath("$.collections.*").parse(response.json())
    collections = []
    for c in tqdm.tqdm(collections_json, desc="Processing collections", unit="collection"):
        collections.append(Collection(
            id=c["id"],
            title=c["title"],
            description=c["description"] if "description" in c else None,
            spatial=c["extent"]["spatial"] if "extent" in c and "spatial" in c["extent"] else None,
            url=urlBase+"/collections/"+c["id"],
            oe=oe,
            search_not_local=search_not_local
        ))
    return collections


def generate_ontology(collections: list[Collection], output_ontology):
    ontology = rdflib.Graph()
    # bindear geosparql y geo al grafo
    ontology.bind("geo", GEO)
    ontology.bind("ogc", OGC)

    for c in collections:
        collection_uri = OGC[c.id+"_collection"]
        class_uri = OGC[c.id] 
        ontology.add((class_uri, RDF.type, OWL["class"]))
        ontology.add((class_uri, RDFS.subClassOf, GEO.Feature))
        ontology.add((collection_uri, RDF.type, GEO.FeatureCollection)) 
        ontology.add((class_uri, RDFS.label, Literal(c.title))) 
        ontology.add((collection_uri, RDFS.label, Literal(c.title))) 

        if c.sameAs:
            ontology.add((class_uri, OWL.sameAs, URIRef(c.sameAs)))

        if c.description: 
            ontology.add((class_uri, RDFS.comment, Literal(c.description))) 
        if c.bbox and c.crs: 
            bbox_blank_node = rdflib.BNode()
            ontology.add((collection_uri, GEO.hasBoundingBox, bbox_blank_node))
            wkt_literal = Literal(f"<{c.crs}> POLYGON((" + ",".join(map(str, c.bbox[0])) + "))", datatype=GEO.wktLiteral)
            ontology.add((bbox_blank_node, GEO.asWKT, wkt_literal))
        for prop in c.properties: 
            property_uri = OGC[prop["title"]] if not prop["sameAs"] else prop["sameAs"]
            ontology.add((property_uri, RDF.type, RDF.Property)) 
            ontology.add((property_uri, RDFS.label, Literal(prop["title"]))) 
            ontology.add((property_uri, RDFS.range, XSD[prop["type"]])) if prop["type"]!="number" else ontology.add((property_uri, RDFS.range, XSD["float"]))
            ontology.add((property_uri, RDFS.domain, class_uri))
    
    ontology.serialize(destination=output_ontology, format="turtle")

def generate_mapping(collection, output_mappings_folder, urlBase):
    g_mappings = rdflib.Graph()
    for b in namespaces:
        g_mappings.bind(b, namespaces[b])
    add_logical_sources(collection.id, collection.url + "/items?f=json&limit=10000", OGC, g_mappings)
    triples_map = OGC[collection.id + "TriplesMap"]
    g_mappings.add((triples_map, RDF.type, RML.TriplesMap))

    g_mappings.add((triples_map, RML.logicalSource, OGC["LogicalSource_" + collection.id]))
    if not collection.sameAs:
        add_subject_map(triples_map, OGC[collection.id], g_mappings, template=ogc_api_url+f"/collections/{collection.id}" + "/items/{id}")
    else:
        add_subject_map(triples_map, collection.sameAs, g_mappings, template=ogc_api_url+f"/collections/{collection.id}" + "/items/{id}")

    for prop in collection.properties: 
        if prop["sameAs"]:
            add_pom_ref(triples_map, URIRef(prop["sameAs"]), f"properties.{prop['title']}", g_mappings, datatype=XSD[prop["type"]], filter=f"{prop['title']}"+"=@{1}") if prop["type"]!="number" else add_pom_ref(triples_map, URIRef(prop["sameAs"]), f"properties.{prop['title']}", g_mappings, datatype=XSD["float"], filter=f"{prop['title']}"+"=@{1}")
        else:
            add_pom_ref(triples_map, OGC[prop["title"]], f"properties.{prop['title']}", g_mappings, datatype=XSD[prop["type"]], filter=f"{prop['title']}"+"=@{1}") if prop["type"]!="number" else add_pom_ref(triples_map, OGC[prop["title"]], f"properties.{prop['title']}", g_mappings, datatype=XSD["float"], filter=f"{prop['title']}"+"=@{1}")
    add_pom_ref(triples_map, GEO.hasGeometry, "geometry", g_mappings,  filter="bbox=@{1}", datatype=GEO.geoJSONLiteral)
    add_pom_ref(triples_map, OGC.geometryName, "geometry_name", g_mappings, datatype=XSD.string)

    tp_collecion = OGC[collection.id + "TriplesMap2"]
    g_mappings.add((tp_collecion, RDF.type, RML.TriplesMap))
    add_subject_map(tp_collecion, GEO.FeatureCollection, g_mappings, constant_uri=OGC[collection.id+"_collection"])
    g_mappings.add((tp_collecion, RML.logicalSource, OGC["LogicalSource_" + collection.id]))
    add_pom_parenttpm(tp_collecion, GEO.member, triples_map, None, None, g_mappings)

    g_mappings.serialize(destination=output_mappings_folder + "/" + collection.id + "_mapping.ttl", format="turtle")




if __name__ == "__main__":
    argparser = argparse.ArgumentParser(description="OGC Mapping Generator")
    argparser.add_argument("OGC_API_URL", help="URL of the Features OGC root endpoint")
    argparser.add_argument("--output_folder", "-o", default="output", help="Output folder name (default: output)")
    argparser.add_argument("-n", default=False, help="Search in not local ontologies (Wikidata, DBpedia) if no match is found in the local vectorial search. WARNING: can be very slow!")
    argparser.add_argument("-r", "--rontologias", nargs="+", help="Rutas a los archivos .owl")

    args = argparser.parse_args()
    ogc_api_url = args.OGC_API_URL
    os.makedirs(args.output_folder, exist_ok=True)
    output_ontology = args.output_folder + "/ontology.ttl"

    oe = VectorialOntologyMatcher(args.rontologias)

    print(f"Fetching collections from OGC API at {ogc_api_url}...")
    collections = get_collections(ogc_api_url, oe, args.n)

    print(f"Generating ontology for {len(collections)} collections...")
    generate_ontology(collections, output_ontology)

    output_mappings_folder = args.output_folder + "/mappings"
    os.makedirs(output_mappings_folder, exist_ok=True) 
    

    print("Generating RML mappings...")
    for collection in collections:
        generate_mapping(collection, output_mappings_folder, ogc_api_url)
    print("All done!")
    



