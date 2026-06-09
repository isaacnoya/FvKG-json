import argparse
import hashlib
import json
import os
import shlex
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

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
    searchNotLocal,
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
    annotation_source: str | None = None
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


def default_embedding_cache_path(output_ontology, vectorial_model):
    model_name = vectorial_model.rstrip("/").split("/")[-1]
    model_slug = "".join(
        char.lower() if char.isalnum() else "-"
        for char in model_name
    ).strip("-")
    model_hash = hashlib.sha256(vectorial_model.encode("utf-8")).hexdigest()[:8]
    cache_folder = os.path.join(
        os.path.dirname(os.path.abspath(output_ontology)),
        ".embedding_cache",
    )
    return os.path.join(cache_folder, f"{model_slug}-{model_hash}.pt")


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
            annotation_source=(
                "baseline"
                if ontology.value(class_uri, OWL.equivalentClass)
                else None
            ),
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
            "annotation_source": (
                "baseline"
                if ontology.value(property_uri, OWL.equivalentProperty)
                else None
            ),
        })
    return properties


def annotate_classes(
    collections,
    ontology,
    reviewer,
    model,
    stats=None,
    use_local=True,
    use_external=True,
):
    for collection in collections:
        if stats:
            stats.count_entity("class")
        if collection.equivalentClass:
            continue
        if not reviewer.interactive:
            continue

        aligned_uri = None
        annotation_source = None
        if use_local:
            aligned_uri = reviewer.choose_local(
                collection.title,
                collection.description,
                "class",
                collection.oe,
            )
            if aligned_uri:
                annotation_source = "local"
                if stats:
                    stats.count_alignment("class", "local")

        if not aligned_uri and use_external:
            external = searchNotLocal(
                collection.title,
                collection.description or "",
                "class",
                model=model,
            )
            if external:
                aligned_uri = reviewer.confirm_external(
                    collection.title,
                    "class",
                    external,
                )
                if aligned_uri:
                    annotation_source = "notlocal"
                    if stats:
                        stats.count_alignment("class", "notlocal")

        if not aligned_uri:
            continue

        ontology.add((collection.local_class_uri, OWL.equivalentClass, URIRef(aligned_uri)))
        collection.equivalentClass = URIRef(aligned_uri)
        collection.annotation_source = annotation_source


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
        collection.annotation_source = "proposal"
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


def remove_equivalent_properties(ontology):
    removed = property_equivalences(ontology)
    for local_property, equivalent_property in removed.items():
        ontology.remove((local_property, OWL.equivalentProperty, equivalent_property))
    return removed


def load_annotation_report(path):
    with open(path, "r", encoding="utf-8") as annotations_file:
        report = json.load(annotations_file)

    if not isinstance(report, dict):
        raise ValueError("The annotations file must contain a JSON object.")
    if not isinstance(report.get("class_annotations", []), list):
        raise ValueError("class_annotations must be a JSON list.")
    if not isinstance(report.get("property_annotations", []), list):
        raise ValueError("property_annotations must be a JSON list.")
    return report


def apply_annotation_report(ontology, report):
    imported_classes = 0
    imported_properties = 0

    for annotation in report.get("class_annotations", []):
        concept_uri = annotation.get("concept_uri")
        annotated_uri = annotation.get("annotated_class_uri")
        if not concept_uri or not annotated_uri:
            continue
        concept = URIRef(concept_uri)
        if not is_local_ogc_uri(concept):
            continue
        ontology.set((concept, OWL.equivalentClass, URIRef(annotated_uri)))
        imported_classes += 1

    for annotation in report.get("property_annotations", []):
        concept_uri = annotation.get("concept_uri")
        annotated_uri = annotation.get("annotated_property_uri")
        if not concept_uri or not annotated_uri:
            continue
        concept = URIRef(concept_uri)
        if not is_local_ogc_uri(concept):
            continue
        ontology.set((concept, OWL.equivalentProperty, URIRef(annotated_uri)))
        imported_properties += 1

    return imported_classes, imported_properties


def replace_object(graph, subject, predicate, old_object, new_object):
    if old_object == new_object:
        return False
    graph.remove((subject, predicate, old_object))
    graph.add((subject, predicate, new_object))
    return True


def annotate_mapping(
    mapping_path,
    output_path,
    class_map,
    property_map,
    reset_class_map=None,
    reset_property_map=None,
):
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

    for local_property, old_equivalent_property in (reset_property_map or {}).items():
        for predicate_object_map in list(mapping.subjects(RML.predicate, old_equivalent_property)):
            changed = replace_object(
                mapping,
                predicate_object_map,
                RML.predicate,
                old_equivalent_property,
                local_property,
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


def annotate_mappings(
    mappings_folder,
    output_mappings_folder,
    ontology,
    reset_class_map=None,
    reset_property_map=None,
):
    class_map = class_equivalences(ontology)
    property_map = property_equivalences(ontology)
    changed_count = 0
    processed_count = 0

    for mapping_path in mapping_files(mappings_folder):
        processed_count += 1
        output_path = os.path.join(output_mappings_folder, os.path.basename(mapping_path))
        if annotate_mapping(
            mapping_path,
            output_path,
            class_map,
            property_map,
            reset_class_map,
            reset_property_map,
        ):
            changed_count += 1

    return processed_count, changed_count


def stats_to_dict(stats):
    entity_stats = {}
    for entity_type in ("class", "property"):
        total = stats.entity_totals[entity_type]
        alignments = {
            source: stats.alignment_totals[entity_type][source]
            for source in ("baseline", "local", "notlocal", "proposal")
        }
        aligned = sum(alignments.values())
        entity_stats[entity_type] = {
            "total": total,
            "aligned": aligned,
            "unaligned": total - aligned,
            "by_source": alignments,
        }

    return {
        "entities": entity_stats,
        "llm_axiom_review": {
            "proposals_reviewed": stats.axiom_proposals,
            "proposals_accepted": stats.axiom_accepted_proposals,
            "proposals_denied": stats.axiom_denied_proposals,
            "triples_accepted": stats.axiom_accepted_triples,
            "triples_skipped": stats.axiom_skipped_triples,
        },
    }


def class_annotation_records(collections):
    return [
        {
            "concept_id": collection.id,
            "concept_uri": str(collection.local_class_uri),
            "title": collection.title,
            "description": collection.description,
            "annotated_class_uri": (
                str(collection.equivalentClass)
                if collection.equivalentClass
                else None
            ),
            "status": "annotated" if collection.equivalentClass else "unaligned",
            "annotation_source": collection.annotation_source,
        }
        for collection in sorted(collections, key=lambda item: item.id)
    ]


def property_annotation_records(collections, ontology):
    records_by_uri = {}
    for collection in sorted(collections, key=lambda item: item.id):
        for prop in sorted(collection.properties, key=lambda item: item["title"]):
            local_property_uri = URIRef(OGC[prop["title"]])
            uri_text = str(local_property_uri)
            record = records_by_uri.setdefault(uri_text, {
                "concept": prop["title"],
                "concept_uri": uri_text,
                "datatypes": set(),
                "collections": [],
                "annotation_sources": set(),
            })
            record["datatypes"].add(prop["type"])
            if prop.get("annotation_source"):
                record["annotation_sources"].add(prop["annotation_source"])
            record["collections"].append({
                "id": collection.id,
                "title": collection.title,
            })

    records = []
    for uri_text, record in sorted(records_by_uri.items()):
        equivalent_property = ontology.value(
            URIRef(uri_text),
            OWL.equivalentProperty,
        )
        records.append({
            **record,
            "datatypes": sorted(record["datatypes"]),
            "annotation_sources": sorted(record["annotation_sources"]),
            "annotated_property_uri": (
                str(equivalent_property)
                if equivalent_property
                else None
            ),
            "status": "annotated" if equivalent_property else "unaligned",
        })
    return records


def write_evaluation_results(
    path,
    args,
    collections,
    ontology,
    stats,
    reference_ontologies,
    embedding_cache,
    output_ontology,
    output_mappings_folder,
    processed_mappings,
    changed_mappings,
    started_at,
    duration_seconds,
    reviewer,
    annotation_report=None,
):
    use_embeddings = args.mode in {"full", "embeddings"}
    use_llm = args.mode in {"full", "llm"}
    baseline_embedding = (
        (annotation_report or {}).get("models", {}).get("embedding")
        if args.annotations_file
        else None
    )
    report = {
        "run_name": args.run_name,
        "started_at": started_at.isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(duration_seconds, 3),
        "command": shlex.join(sys.argv),
        "models": {
            "embedding": args.vectorial_model if use_embeddings else baseline_embedding,
            "llm": args.llm_model if use_llm else None,
        },
        "configuration": {
            "mode": args.mode,
            "interactive": not args.no_interactive,
            "local_top_k": args.local_top_k,
            "class_extension_proposals": args.n,
            "reset_equivalent_classes": args.reset_equivalent_classes,
            "reset_equivalent_properties": args.reset_equivalent_properties,
            "embedding_cache": os.path.abspath(embedding_cache) if embedding_cache else None,
        },
        "inputs": {
            "ontology": os.path.abspath(args.ontology),
            "mappings_folder": os.path.abspath(args.mappings_folder),
            "reference_ontologies": [
                os.path.abspath(path)
                for path in reference_ontologies
            ],
            "annotations_file": (
                os.path.abspath(args.annotations_file)
                if args.annotations_file
                else None
            ),
        },
        "outputs": {
            "ontology": os.path.abspath(output_ontology),
            "mappings_folder": os.path.abspath(output_mappings_folder),
        },
        "statistics": stats_to_dict(stats),
        "mappings": {
            "processed": processed_mappings,
            "changed": changed_mappings,
        },
        "embedding_reviews": reviewer.local_reviews,
        "class_annotations": class_annotation_records(collections),
        "property_annotations": property_annotation_records(collections, ontology),
    }

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as results_file:
        json.dump(report, results_file, ensure_ascii=False, indent=2)
        results_file.write("\n")


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
    parser.add_argument(
        "--mode",
        choices=("full", "embeddings", "llm"),
        default="full",
        help="Pipeline phase to run: full hierarchy, local embeddings only, or LLM fallbacks using frozen annotations",
    )
    parser.add_argument(
        "--annotations_file",
        "--annotations-file",
        default=None,
        help="Results JSON whose accepted class/property annotations are loaded as a frozen baseline",
    )
    parser.add_argument("--no-interactive", action="store_true", help="Disable human confirmation prompts and skip new alignments")
    parser.add_argument("--local-top-k", type=int, default=5, help="Number of local ontology candidates to show")
    parser.add_argument("--run_name", "--run-name", default=None, help="Optional experiment name stored in the results file")
    parser.add_argument("--results_file", "--results-file", default=None, help="Write experiment metadata, statistics, and concept annotations to this JSON file")
    parser.add_argument(
        "--embedding_cache",
        "--embedding-cache",
        default=None,
        help="Embedding index cache path. Defaults to a model-specific cache beside the output ontology",
    )
    parser.add_argument(
        "--reset-equivalent-classes",
        action="store_true",
        help="Remove existing local owl:equivalentClass triples before annotation and reset old RML subject classes back to the local OGC class first",
    )
    parser.add_argument(
        "--reset-equivalent-properties",
        action="store_true",
        help="Remove existing local owl:equivalentProperty triples before annotation and reset old RML predicates back to local OGC properties",
    )
    args = parser.parse_args()
    if args.mode == "embeddings" and not args.rontologias:
        parser.error("--mode embeddings requires --rontologias.")
    if args.mode == "embeddings" and args.annotations_file:
        parser.error("--mode embeddings cannot be combined with --annotations_file.")
    return args


def main():
    args = parse_args()
    started_at = datetime.now(timezone.utc)
    start_time = time.perf_counter()
    output_ontology = args.output_ontology or args.ontology
    output_mappings_folder = args.output_mappings_folder or args.mappings_folder
    interactive = not args.no_interactive
    use_embeddings = args.mode in {"full", "embeddings"}
    use_llm = args.mode in {"full", "llm"}

    reference_ontologies = ontology_files(args.rontologias)
    stats = GenerationStats()
    embedding_cache = None
    if reference_ontologies and use_embeddings:
        embedding_cache = args.embedding_cache or default_embedding_cache_path(
            output_ontology,
            args.vectorial_model,
        )
        os.makedirs(os.path.dirname(os.path.abspath(embedding_cache)), exist_ok=True)
    oe = (
        VectorialOntologyMatcher(
            reference_ontologies,
            index_cache=embedding_cache,
            model=args.vectorial_model,
        )
        if reference_ontologies and use_embeddings
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
    reset_property_map = {}
    if args.reset_equivalent_classes:
        reset_class_map = remove_equivalent_classes(ontology)
        print(f"Removed {len(reset_class_map)} existing equivalent class annotation(s).")
    if args.reset_equivalent_properties:
        reset_property_map = remove_equivalent_properties(ontology)
        print(f"Removed {len(reset_property_map)} existing equivalent property annotation(s).")

    annotation_report = None
    if args.annotations_file:
        annotation_report = load_annotation_report(args.annotations_file)
        imported_classes, imported_properties = apply_annotation_report(
            ontology,
            annotation_report,
        )
        print(
            f"Loaded {imported_classes} class and {imported_properties} property "
            f"annotation(s) from: {args.annotations_file}"
        )

    collections = find_existing_collections(
        ontology,
        oe=oe,
        search_not_local=args.n,
        model=args.llm_model,
        reviewer=reviewer,
    )
    print(f"Found {len(collections)} existing OGC collection class(es) to annotate.")

    stats.alignment_totals["class"]["baseline"] = sum(
        bool(collection.equivalentClass)
        for collection in collections
    )

    annotate_classes(
        collections,
        ontology,
        reviewer,
        args.llm_model,
        stats=stats,
        use_local=use_embeddings,
        use_external=use_llm,
    )
    if use_llm:
        propose_class_extensions(
            collections,
            ontology,
            reference_ontologies[0] if reference_ontologies else None,
            args.llm_model,
            interactive and args.n,
            stats=stats,
        )

    stats.entity_totals["property"] = len({
        URIRef(OGC[prop["title"]])
        for collection in collections
        for prop in collection.properties
    })
    stats.alignment_totals["property"]["baseline"] = len({
        URIRef(OGC[prop["title"]])
        for collection in collections
        for prop in collection.properties
        if prop["equivalentClass"]
    })
    review_property_alignments(
        collections,
        ontology,
        interactive=interactive,
        stats=stats,
        use_local=use_embeddings,
        use_external=use_llm,
        use_proposals=use_llm,
    )
    if use_llm:
        review_llm_axioms(
            ontology,
            model=args.llm_model,
            interactive=interactive,
            stats=stats,
        )

    os.makedirs(os.path.dirname(output_ontology) or ".", exist_ok=True)
    ontology.serialize(destination=output_ontology, format="turtle")
    print(f"Annotated ontology written to: {output_ontology}")

    processed_mappings, changed_mappings = annotate_mappings(
        args.mappings_folder,
        output_mappings_folder,
        ontology,
        reset_class_map=reset_class_map,
        reset_property_map=reset_property_map,
    )
    print(f"Annotated {changed_mappings}/{processed_mappings} mapping file(s).")
    stats.print_summary()
    if args.results_file:
        write_evaluation_results(
            args.results_file,
            args,
            collections,
            ontology,
            stats,
            reference_ontologies,
            embedding_cache,
            output_ontology,
            output_mappings_folder,
            processed_mappings,
            changed_mappings,
            started_at,
            time.perf_counter() - start_time,
            reviewer,
            annotation_report=annotation_report,
        )
        print(f"Evaluation results written to: {args.results_file}")
    print("All done!")


if __name__ == "__main__":
    main()
