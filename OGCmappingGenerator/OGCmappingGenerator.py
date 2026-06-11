import argparse
import os

import rdflib
import requests
import tqdm
from jsonpath import JSONPath
from rdflib import BNode, Literal, Namespace


EX = Namespace("http://example.com/")
HTV = Namespace("http://www.w3.org/2011/http#")
GEO = Namespace("http://www.opengis.net/ont/geosparql#")
OGC = Namespace("http://www.ogc.org/")
RML = Namespace("http://w3id.org/rml/")
XSD = Namespace("http://www.w3.org/2001/XMLSchema#")
RDF = Namespace("http://www.w3.org/1999/02/22-rdf-syntax-ns#")
RDFS = Namespace("http://www.w3.org/2000/01/rdf-schema#")
OWL = Namespace("http://www.w3.org/2002/07/owl#")
VOID = Namespace("http://rdfs.org/ns/void#")

namespaces = {
    "": EX,
    "rml": RML,
    "xsd": XSD,
    "rdf": RDF,
    "rdfs": RDFS,
    "owl": OWL,
    "geo": GEO,
    "ogc": OGC,
    "htv": HTV,
    "void": VOID,
}


class Collection:
    def __init__(self, identifier, title, description, spatial, url):
        self.id = identifier
        self.title = title
        self.description = description
        self.bbox = spatial.get("bbox") if spatial else None
        self.crs = spatial.get("crs") if spatial else None
        self.url = url
        self.properties = self._get_properties()

    def _get_properties(self):
        response = requests.get(
            f"{self.url}/collections/{self.id}/queryables?f=json"
        )
        response.raise_for_status()
        queryables = JSONPath("$.properties").parse(response.json())
        properties = queryables[0] if queryables else {}
        return [
            {
                "title": name,
                "type": definition.get("type", "string"),
            }
            for name, definition in properties.items()
        ]


def bind_namespaces(graph):
    for prefix, namespace in namespaces.items():
        graph.bind(prefix, namespace)


def add_logical_source(collection, graph):
    source = OGC[f"FuenteAPI_{collection.id}"]
    logical_source = OGC[f"LogicalSource_{collection.id}"]
    items_url = (
        f"{collection.url}/collections/{collection.id}/items"
        "?f=json&limit=10000"
    )

    graph.add((source, HTV.absoluteURI, Literal(items_url)))
    graph.add((logical_source, RDF.type, RML.logicalSource))
    graph.add((logical_source, RML.source, source))
    graph.add((
        logical_source,
        VOID.nextPage,
        Literal('$.links[?(@.rel=="next")].href'),
    ))
    graph.add((
        logical_source,
        RML.iterator,
        Literal("$.features.*"),
    ))
    graph.add((
        logical_source,
        RML.referenceFormulation,
        RML.HTTPAPI,
    ))


def add_reference_mapping(
    triples_map,
    predicate,
    reference,
    graph,
    datatype=None,
    filter_expression=None,
):
    predicate_object_map = BNode()
    object_map = BNode()
    graph.add((
        triples_map,
        RML.predicateObjectMap,
        predicate_object_map,
    ))
    graph.add((
        predicate_object_map,
        RML.predicate,
        predicate,
    ))
    graph.add((
        predicate_object_map,
        RML.objectMap,
        object_map,
    ))
    graph.add((object_map, RML.reference, Literal(reference)))
    if filter_expression:
        graph.add((
            object_map,
            VOID.filterx,
            Literal(filter_expression),
        ))
    if datatype:
        graph.add((object_map, RML.datatype, datatype))


def add_parent_mapping(triples_map, predicate, parent_triples_map, graph):
    predicate_object_map = BNode()
    object_map = BNode()
    graph.add((
        triples_map,
        RML.predicateObjectMap,
        predicate_object_map,
    ))
    graph.add((
        predicate_object_map,
        RML.predicate,
        predicate,
    ))
    graph.add((
        predicate_object_map,
        RML.objectMap,
        object_map,
    ))
    graph.add((
        object_map,
        RML.parentTriplesMap,
        parent_triples_map,
    ))


def add_subject_map(
    triples_map,
    class_uri,
    graph,
    template=None,
    constant_uri=None,
):
    subject_map = BNode()
    graph.add((triples_map, RML.subjectMap, subject_map))
    graph.add((subject_map, RML["class"], class_uri))
    if template:
        graph.add((subject_map, RML.template, Literal(template)))
    if constant_uri:
        graph.add((subject_map, RML.constant, constant_uri))


def _collection_from_json(collection_data, url_base):
    extent = collection_data.get("extent", {})
    return Collection(
        identifier=collection_data["id"],
        title=collection_data.get("title", collection_data["id"]),
        description=collection_data.get("description"),
        spatial=extent.get("spatial"),
        url=url_base,
    )


def get_collections(url_base, selected_ids=None):
    try:
        response = requests.get(f"{url_base}/collections?f=json")
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        print(f"Error fetching collections from {url_base}: {exc}")
        return []

    selected_ids = set(selected_ids or [])
    collections_json = JSONPath("$.collections.*").parse(response.json())
    collections = []
    for collection_data in tqdm.tqdm(
        collections_json,
        desc="Processing collections",
        unit="collection",
    ):
        if selected_ids and collection_data["id"] not in selected_ids:
            continue
        collections.append(
            _collection_from_json(collection_data, url_base)
        )
    return collections


def property_datatype(property_type):
    if property_type == "number":
        return XSD.float
    return XSD[property_type]


def generate_ontology(collections, output_ontology):
    ontology = rdflib.Graph()
    bind_namespaces(ontology)

    for collection in collections:
        class_uri = OGC[collection.id]
        collection_uri = OGC[f"{collection.id}_collection"]

        ontology.add((class_uri, RDF.type, OWL["class"]))
        ontology.add((class_uri, RDFS.subClassOf, GEO.Feature))
        ontology.add((class_uri, RDFS.label, Literal(collection.title)))
        ontology.add((
            collection_uri,
            RDF.type,
            GEO.FeatureCollection,
        ))
        ontology.add((
            collection_uri,
            RDFS.label,
            Literal(collection.title),
        ))

        if collection.description:
            ontology.add((
                class_uri,
                RDFS.comment,
                Literal(collection.description),
            ))
        if collection.bbox and collection.crs:
            bounding_box = BNode()
            coordinates = ",".join(map(str, collection.bbox[0]))
            geometry = Literal(
                f"<{collection.crs}> POLYGON(({coordinates}))",
                datatype=GEO.wktLiteral,
            )
            ontology.add((
                collection_uri,
                GEO.hasBoundingBox,
                bounding_box,
            ))
            ontology.add((bounding_box, GEO.asWKT, geometry))

        for prop in collection.properties:
            property_uri = OGC[prop["title"]]
            ontology.add((property_uri, RDF.type, RDF.Property))
            ontology.add((
                property_uri,
                RDFS.label,
                Literal(prop["title"]),
            ))
            ontology.add((
                property_uri,
                RDFS.range,
                property_datatype(prop["type"]),
            ))
            ontology.add((property_uri, RDFS.domain, class_uri))

    ontology.serialize(destination=output_ontology, format="turtle")


def generate_mapping(collection, output_mappings_folder):
    graph = rdflib.Graph()
    bind_namespaces(graph)
    add_logical_source(collection, graph)

    triples_map = OGC[f"{collection.id}TriplesMap"]
    logical_source = OGC[f"LogicalSource_{collection.id}"]
    graph.add((triples_map, RDF.type, RML.TriplesMap))
    graph.add((triples_map, RML.logicalSource, logical_source))
    add_subject_map(
        triples_map,
        OGC[collection.id],
        graph,
        template=(
            f"{collection.url}/collections/{collection.id}/items/{{id}}"
        ),
    )

    for prop in collection.properties:
        add_reference_mapping(
            triples_map,
            OGC[prop["title"]],
            f"properties.{prop['title']}",
            graph,
            datatype=property_datatype(prop["type"]),
            filter_expression=f"{prop['title']}=@{{1}}",
        )
    add_reference_mapping(
        triples_map,
        GEO.hasGeometry,
        "geometry",
        graph,
        datatype=GEO.geoJSONLiteral,
        filter_expression="bbox=@{1}",
    )
    add_reference_mapping(
        triples_map,
        OGC.geometryName,
        "geometry_name",
        graph,
        datatype=XSD.string,
    )

    collection_triples_map = OGC[f"{collection.id}TriplesMap2"]
    graph.add((
        collection_triples_map,
        RDF.type,
        RML.TriplesMap,
    ))
    graph.add((
        collection_triples_map,
        RML.logicalSource,
        logical_source,
    ))
    add_subject_map(
        collection_triples_map,
        GEO.FeatureCollection,
        graph,
        constant_uri=OGC[f"{collection.id}_collection"],
    )
    add_parent_mapping(
        collection_triples_map,
        GEO.member,
        triples_map,
        graph,
    )

    output_path = os.path.join(
        output_mappings_folder,
        f"{collection.id}_mapping.ttl",
    )
    graph.serialize(destination=output_path, format="turtle")


def read_lines(path):
    with open(path, "r", encoding="utf-8") as input_file:
        return [line.strip() for line in input_file if line.strip()]


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Generate a local OGC ontology and RML mappings "
            "from OGC API Features endpoints."
        )
    )
    parser.add_argument(
        "-u",
        "--ogc_api_url",
        required=True,
        help=(
            "OGC API Features root endpoint or a text file "
            "containing one endpoint per line."
        ),
    )
    parser.add_argument(
        "-o",
        "--output_folder",
        default="output",
        help="Output folder. Defaults to output.",
    )
    parser.add_argument(
        "-c",
        "--collections",
        default=None,
        help="Optional file containing collection IDs to process.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if os.path.isfile(args.ogc_api_url):
        api_urls = read_lines(args.ogc_api_url)
    else:
        api_urls = [args.ogc_api_url]
    selected_ids = read_lines(args.collections) if args.collections else None

    print("Fetching collections from OGC API(s)...")
    collections = []
    for api_url in api_urls:
        print(f"Processing OGC API: {api_url}")
        collections.extend(get_collections(api_url, selected_ids))

    os.makedirs(args.output_folder, exist_ok=True)
    output_ontology = os.path.join(args.output_folder, "ontology.ttl")
    print(f"Generating ontology for {len(collections)} collections...")
    generate_ontology(collections, output_ontology)

    output_mappings_folder = os.path.join(
        args.output_folder,
        "mappings",
    )
    os.makedirs(output_mappings_folder, exist_ok=True)
    print("Generating RML mappings...")
    for collection in collections:
        generate_mapping(collection, output_mappings_folder)

    print(f"Generated {len(collections)} RML mapping file(s).")
    print("All done!")


if __name__ == "__main__":
    main()
