import argparse
import os
from dataclasses import dataclass, field

import rdflib
from rdflib import Literal, URIRef

from OGCmappingGenerator import (
    AlignmentReviewer,
    GEO,
    GenerationStats,
    OGC,
    OWL,
    RDF,
    RDFS,
    RML,
    XSD,
    VectorialOntologyMatcher,
    llm_propose,
    namespaces,
    review_llm_axioms,
    review_property_alignments,
)


OWL_CLASS_LOWER = OWL["class"]


@dataclass
class ExistingCollection:
    id: str
    title: str
    description: str | None
    local_class_uri: URIRef
    oe: VectorialOntologyMatcher | None
    search_not_local: bool
    model: str
    reviewer: AlignmentReviewer
    equivalentClass: URIRef | None = None
    flag_not_align: bool = False
    properties: list[dict] = field(default_factory=list)


def bind_common_namespaces(graph):
    for prefix, namespace in namespaces.items():
        graph.bind(prefix, namespace)


def load_graph(path):
    graph = rdflib.Graph()
    graph.parse(path)
    bind_common_namespaces(graph)
    return graph


def ontology_files(path):
    if not path:
        return []
    if os.path.isfile(path):
        return [path]

    ret = []
    for file_name in os.listdir(path):
        if file_name.endswith((".owl", ".ttl", ".rdf")):
            ret.append(os.path.join(path, file_name))
    return sorted(ret)


def mapping_files(path):
    ret = []
    for file_name in os.listdir(path):
        if file_name.endswith((".ttl", ".rml", ".rdf")):
            ret.append(os.path.join(path, file_name))
    return sorted(ret)


def local_name(uri, namespace=OGC):
    uri_text = str(uri)
    namespace_text = str(namespace)
    if uri_text.startswith(namespace_text):
        return uri_text[len(namespace_text):]
    return uri_text.rstrip("/#").replace("#", "/").split("/")[-1]


def first_literal_text(graph, subject, predicate):
    value = graph.value(subject, predicate)
    return str(value) if value else None


def property_type_from_range(datatype):
    if not datatype:
        return "string"
    if datatype == XSD.float:
        return "number"
    datatype_text = str(datatype)
    xsd_text = str(XSD)
    if datatype_text.startswith(xsd_text):
        return datatype_text[len(xsd_text):]
    return "string"


def is_local_ogc_uri(uri):
    return isinstance(uri, URIRef) and str(uri).startswith(str(OGC))


def find_existing_collections(ontology, oe, search_not_local, model, reviewer):
    class_uris = set(ontology.subjects(RDFS.subClassOf, GEO.Feature))
    class_uris.update(ontology.subjects(RDF.type, OWL_CLASS_LOWER))

    collections = []
    for class_uri in sorted(class_uris, key=str):
        if not is_local_ogc_uri(class_uri):
            continue
        if str(class_uri).endswith("_collection"):
            continue

        collection = ExistingCollection(
            id=local_name(class_uri),
            title=first_literal_text(ontology, class_uri, RDFS.label) or local_name(class_uri),
            description=first_literal_text(ontology, class_uri, RDFS.comment),
            local_class_uri=class_uri,
            oe=oe,
            search_not_local=search_not_local,
            model=model,
            reviewer=reviewer,
            equivalentClass=ontology.value(class_uri, OWL.equivalentClass),
        )
        collection.properties = find_collection_properties(ontology, class_uri)
        collections.append(collection)

    return collections


def find_collection_properties(ontology, class_uri):
    properties = []
    for property_uri in sorted(ontology.subjects(RDFS.domain, class_uri), key=str):
        if not is_local_ogc_uri(property_uri):
            continue
        if (property_uri, RDF.type, RDF.Property) not in ontology:
            continue

        datatype = ontology.value(property_uri, RDFS.range)
        properties.append({
            "title": local_name(property_uri),
            "type": property_type_from_range(datatype),
            "equivalentClass": ontology.value(property_uri, OWL.equivalentProperty),
        })
    return properties


def annotate_classes(collections, ontology, reviewer, model, stats=None):
    for collection in collections:
        if stats:
            stats.count_entity("class")
        if collection.equivalentClass:
            continue

        aligned_uri = reviewer.align(
            collection.title,
            collection.description,
            "class",
            oe=collection.oe,
            search_not_local=True,
            model=model,
        )
        if not aligned_uri:
            continue

        ontology.add((collection.local_class_uri, OWL.equivalentClass, URIRef(aligned_uri)))
        collection.equivalentClass = URIRef(aligned_uri)


def propose_class_extensions(collections, ontology, reference_ontology, model, interactive, stats=None):
    if not interactive or not reference_ontology:
        return

    for collection in collections:
        if collection.equivalentClass or not collection.search_not_local:
            continue

        proposal = llm_propose(
            reference_ontology,
            collection.title,
            type="class",
            description=collection.description or "",
            model=model,
            prefix=str(OGC),
            interactive=interactive,
        )
        if not proposal:
            continue

        proposed_uri = URIRef(proposal["iri"])
        parent_uri = URIRef(proposal["parent_iri"])
        ontology.add((proposed_uri, RDF.type, OWL.Class))
        ontology.add((proposed_uri, RDFS.subClassOf, parent_uri))
        ontology.add((proposed_uri, RDFS.label, Literal(proposal.get("label", collection.title))))
        if proposal.get("comment"):
            ontology.add((proposed_uri, RDFS.comment, Literal(proposal["comment"])))
        ontology.add((collection.local_class_uri, OWL.equivalentClass, proposed_uri))
        collection.equivalentClass = proposed_uri
        if stats:
            stats.count_alignment("class", "proposal")


def class_equivalences(ontology):
    return {
        URIRef(class_uri): URIRef(equivalent_uri)
        for class_uri, equivalent_uri in ontology.subject_objects(OWL.equivalentClass)
        if is_local_ogc_uri(class_uri) and isinstance(equivalent_uri, URIRef)
    }


def remove_equivalent_classes(ontology):
    removed = class_equivalences(ontology)
    for local_class, equivalent_class in removed.items():
        ontology.remove((local_class, OWL.equivalentClass, equivalent_class))
    return removed


def property_equivalences(ontology):
    return {
        URIRef(property_uri): URIRef(equivalent_uri)
        for property_uri, equivalent_uri in ontology.subject_objects(OWL.equivalentProperty)
        if is_local_ogc_uri(property_uri) and isinstance(equivalent_uri, URIRef)
    }


def replace_object(graph, subject, predicate, old_object, new_object):
    if old_object == new_object:
        return False
    graph.remove((subject, predicate, old_object))
    graph.add((subject, predicate, new_object))
    return True


def annotate_mapping(mapping_path, output_path, class_map, property_map, reset_class_map=None):
    mapping = load_graph(mapping_path)
    changed = False

    for local_class, old_equivalent_class in (reset_class_map or {}).items():
        for subject_map in list(mapping.subjects(RML["class"], old_equivalent_class)):
            changed = replace_object(
                mapping,
                subject_map,
                RML["class"],
                old_equivalent_class,
                local_class,
            ) or changed

    for old_class, new_class in class_map.items():
        for subject_map in list(mapping.subjects(RML["class"], old_class)):
            changed = replace_object(mapping, subject_map, RML["class"], old_class, new_class) or changed

    for old_property, new_property in property_map.items():
        for predicate_object_map in list(mapping.subjects(RML.predicate, old_property)):
            changed = replace_object(
                mapping,
                predicate_object_map,
                RML.predicate,
                old_property,
                new_property,
            ) or changed

    if changed or mapping_path != output_path:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        mapping.serialize(destination=output_path, format="turtle")

    return changed


def annotate_mappings(mappings_folder, output_mappings_folder, ontology, reset_class_map=None):
    class_map = class_equivalences(ontology)
    property_map = property_equivalences(ontology)
    changed_count = 0
    processed_count = 0

    for mapping_path in mapping_files(mappings_folder):
        processed_count += 1
        output_path = os.path.join(output_mappings_folder, os.path.basename(mapping_path))
        if annotate_mapping(mapping_path, output_path, class_map, property_map, reset_class_map):
            changed_count += 1

    return processed_count, changed_count


def parse_args():
    parser = argparse.ArgumentParser(
        description="Annotate an already-created OGC ontology and RML mappings."
    )
    parser.add_argument("--ontology", required=True, help="Path to the existing ontology TTL/RDF/OWL file")
    parser.add_argument("--mappings_folder", required=True, help="Folder with existing mapping TTL/RML files")
    parser.add_argument("--output_ontology", default=None, help="Annotated ontology output path. Defaults to overwriting --ontology")
    parser.add_argument("--output_mappings_folder", default=None, help="Annotated mappings output folder. Defaults to overwriting --mappings_folder")
    parser.add_argument("-r", "--rontologias", default=None, help="Reference ontology file or folder for local vector search and class extension proposals")
    parser.add_argument("-l", "--llm_model", default="openai/gpt-oss-120b", help="LLM model to use for ontology search")
    parser.add_argument("-v", "--vectorial_model", default="paraphrase-multilingual-MiniLM-L12-v2", help="Sentence Transformer model for local ontology alignment")
    parser.add_argument("-n", action="store_true", help="Enable the same class-extension proposal step used by OGCmappingGenerator.py")
    parser.add_argument("--no-interactive", action="store_true", help="Disable human confirmation prompts and skip new alignments")
    parser.add_argument("--local-top-k", type=int, default=5, help="Number of local ontology candidates to show")
    parser.add_argument(
        "--reset-equivalent-classes",
        action="store_true",
        help="Remove existing local owl:equivalentClass triples before annotation and reset old RML subject classes back to the local OGC class first",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    output_ontology = args.output_ontology or args.ontology
    output_mappings_folder = args.output_mappings_folder or args.mappings_folder
    interactive = not args.no_interactive

    reference_ontologies = ontology_files(args.rontologias)
    stats = GenerationStats()
    oe = (
        VectorialOntologyMatcher(reference_ontologies, model=args.vectorial_model)
        if reference_ontologies
        else None
    )
    reviewer = AlignmentReviewer(
        interactive=interactive,
        local_top_k=args.local_top_k,
        stats=stats,
    )

    print(f"Loading existing ontology: {args.ontology}")
    ontology = load_graph(args.ontology)
    reset_class_map = {}
    if args.reset_equivalent_classes:
        reset_class_map = remove_equivalent_classes(ontology)
        print(f"Removed {len(reset_class_map)} existing equivalent class annotation(s).")

    collections = find_existing_collections(
        ontology,
        oe=oe,
        search_not_local=args.n,
        model=args.llm_model,
        reviewer=reviewer,
    )
    print(f"Found {len(collections)} existing OGC collection class(es) to annotate.")

    annotate_classes(collections, ontology, reviewer, args.llm_model, stats=stats)
    propose_class_extensions(
        collections,
        ontology,
        reference_ontologies[0] if reference_ontologies else None,
        args.llm_model,
        interactive,
        stats=stats,
    )

    stats.entity_totals["property"] = len({
        URIRef(OGC[prop["title"]])
        for collection in collections
        for prop in collection.properties
    })
    review_property_alignments(collections, ontology, interactive=interactive, stats=stats)
    review_llm_axioms(ontology, model=args.llm_model, interactive=interactive, stats=stats)

    os.makedirs(os.path.dirname(output_ontology) or ".", exist_ok=True)
    ontology.serialize(destination=output_ontology, format="turtle")
    print(f"Annotated ontology written to: {output_ontology}")

    processed_mappings, changed_mappings = annotate_mappings(
        args.mappings_folder,
        output_mappings_folder,
        ontology,
        reset_class_map=reset_class_map,
    )
    print(f"Annotated {changed_mappings}/{processed_mappings} mapping file(s).")
    stats.print_summary()
    print("All done!")


if __name__ == "__main__":
    main()
