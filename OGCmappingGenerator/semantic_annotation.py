import argparse
import hashlib
import json
import os
import shlex
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

import rdflib
from rdflib import BNode, Literal, Namespace, URIRef

from OGCmappingGenerator import (
    GEO,
    OGC,
    OWL,
    RDF,
    RDFS,
    RML,
    XSD,
    namespaces,
)
from ontology_searh import (
    VectorialOntologyMatcher,
    llm_propose,
    llm_propose_axiom,
    llm_propose_property,
    searchNotLocal,
)


OWL_CLASS_LOWER = OWL["class"]
namespaces = {
    **namespaces,
    "schema": Namespace("http://schema.org/"),
    "rr": Namespace("http://www.w3.org/ns/r2rml#"),
    "wgs84_pos": Namespace("http://www.w3.org/2003/01/geo/wgs84_pos#"),
    "skos": Namespace("http://www.w3.org/2004/02/skos/core#"),
    "foaf": Namespace("http://xmlns.com/foaf/0.1/"),
    "org": Namespace("http://www.w3.org/ns/org#"),
    "geolinkeddata": Namespace("http://geo.linkeddata.es/ontology/"),
    "dbo": Namespace("http://dbpedia.org/ontology/"),
}


class GenerationStats:
    def __init__(self):
        self.entity_totals = defaultdict(int)
        self.alignment_totals = defaultdict(lambda: defaultdict(int))
        self.axiom_proposals = 0
        self.axiom_accepted_proposals = 0
        self.axiom_denied_proposals = 0
        self.axiom_accepted_triples = 0
        self.axiom_skipped_triples = 0

    def count_entity(self, entity_type):
        self.entity_totals[entity_type] += 1

    def count_alignment(self, entity_type, source):
        self.alignment_totals[entity_type][source] += 1

    def aligned_total(self, entity_type):
        return sum(self.alignment_totals[entity_type].values())

    def print_summary(self):
        print("\nAnnotation statistics")
        labels = {
            "class": "Classes",
            "property": "Properties",
        }
        for entity_type in ("class", "property"):
            total = self.entity_totals[entity_type]
            aligned = self.aligned_total(entity_type)
            print(f"  {labels[entity_type]}: {aligned}/{total} aligned")
            for source in ("baseline", "local", "notlocal", "proposal"):
                count = self.alignment_totals[entity_type][source]
                print(f"    {source}: {count}")
            print(f"    unaligned: {total - aligned}")
        print("  LLM axiom review:")
        print(f"    proposals reviewed: {self.axiom_proposals}")
        print(f"    proposals accepted: {self.axiom_accepted_proposals}")
        print(f"    proposals denied: {self.axiom_denied_proposals}")
        print(f"    triples accepted: {self.axiom_accepted_triples}")
        print(f"    triples skipped: {self.axiom_skipped_triples}")


class AlignmentReviewer:
    def __init__(self, interactive=True, local_top_k=5, stats=None):
        self.interactive = interactive
        self.local_top_k = local_top_k
        self.stats = stats
        self.local_reviews = []

    def _ask_yes_no(self, prompt, default=False):
        if not self.interactive:
            return default
        suffix = " [Y/n]: " if default else " [y/N]: "
        while True:
            try:
                answer = input(prompt + suffix).strip().lower()
            except EOFError:
                return default
            if not answer:
                return default
            if answer in {"y", "yes", "s", "si", "sí"}:
                return True
            if answer in {"n", "no"}:
                return False
            print("Please answer yes or no.")

    def confirm_external(self, term, entity_type, iri):
        print(f"\nExternal match found for {entity_type} '{term}':")
        print(f"  {iri}")
        if self._ask_yes_no("Accept this external alignment?"):
            return URIRef(iri)
        return None

    def choose_local(self, term, description, entity_type, oe):
        if not oe:
            return None
        matches = oe.search_top(
            term,
            description or "",
            top_k=self.local_top_k * 3,
            threshold=None,
        )
        if entity_type == "property":
            matches = [
                match for match in matches
                if "Propiedad" in match["type"]
            ]
        elif entity_type == "class":
            matches = [
                match for match in matches
                if match["type"] == "Clase"
            ]
        matches = matches[:self.local_top_k]

        review = {
            "term": term,
            "description": description or "",
            "entity_type": entity_type,
            "query_text": matches[0].get("query_text") if matches else None,
            "candidates": [
                {
                    "rank": index,
                    "iri": match["iri"],
                    "name": match["name"],
                    "type": match["type"],
                    "confidence": match["confidence"],
                }
                for index, match in enumerate(matches, start=1)
            ],
            "selected_rank": None,
            "selected_iri": None,
        }
        self.local_reviews.append(review)

        if not matches:
            return None
        print(f"\nLocal ontology matches for {entity_type} '{term}':")
        if matches[0].get("query_text"):
            print(f"  Search text: {matches[0]['query_text']}")
        for index, match in enumerate(matches, start=1):
            print(
                f"  {index}. {match['name']} ({match['type']}) "
                f"confidence={match['confidence']} iri={match['iri']}"
            )
        if not self.interactive:
            return None
        while True:
            try:
                answer = input(
                    "Choose a match number to accept, "
                    "or press Enter/0 to skip: "
                ).strip()
            except EOFError:
                return None
            if not answer or answer == "0":
                return None
            if answer.isdigit() and 1 <= int(answer) <= len(matches):
                selected_rank = int(answer)
                selected_iri = matches[selected_rank - 1]["iri"]
                review["selected_rank"] = selected_rank
                review["selected_iri"] = selected_iri
                return URIRef(selected_iri)
            print(
                f"Please enter a number between 1 and {len(matches)}, "
                "or 0 to skip."
            )


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


def _format_axiom_proposal(proposal):
    print("\nLLM proposed ontology restriction:")
    if proposal.get("rationale"):
        print(f"  Rationale: {proposal['rationale']}")
    for index, restriction in enumerate(
        proposal.get("restrictions", []),
        start=1,
    ):
        quantifier = restriction.get("quantifier")
        value = (
            restriction.get("value_iri")
            or restriction.get("cardinality")
        )
        print(
            f"  {index}. {restriction.get('class_iri')} "
            "rdfs:subClassOf "
            "[ a owl:Restriction ; "
            f"owl:onProperty {restriction.get('property_iri')} ; "
            f"owl:{quantifier} {value} ]"
        )
    for index, axiom in enumerate(proposal.get("axioms", []), start=1):
        print(
            f"  Legacy triple {index}. {axiom.get('subject')} "
            f"{axiom.get('predicate')} {axiom.get('object')}"
        )


def _known_restriction_resources(ontology):
    known_resources = {
        str(GEO.Feature),
        str(GEO.FeatureCollection),
        str(GEO.Geometry),
        str(GEO.hasGeometry),
        str(GEO.asWKT),
        str(GEO.wktLiteral),
        str(GEO.geoJSONLiteral),
        str(XSD.string),
        str(XSD.integer),
        str(XSD.float),
        str(XSD.boolean),
        str(XSD.nonNegativeInteger),
    }
    for subject, predicate, obj in ontology:
        for term in (subject, predicate, obj):
            if isinstance(term, URIRef):
                known_resources.add(str(term))
    return known_resources


def _restriction_predicate(quantifier):
    normalized = (quantifier or "").strip().split(":")[-1]
    predicates = {
        "someValuesFrom": OWL.someValuesFrom,
        "allValuesFrom": OWL.allValuesFrom,
        "cardinality": OWL.cardinality,
        "minCardinality": OWL.minCardinality,
        "maxCardinality": OWL.maxCardinality,
    }
    return predicates.get(normalized) or {
        key.lower(): value
        for key, value in predicates.items()
    }.get(normalized.lower())


def _is_cardinality_restriction(predicate):
    return predicate in {
        OWL.cardinality,
        OWL.minCardinality,
        OWL.maxCardinality,
    }


def _add_restriction_proposal(
    ontology,
    restriction,
    known_resources,
    stats=None,
):
    class_iri = restriction.get("class_iri")
    property_iri = restriction.get("property_iri")
    predicate = _restriction_predicate(restriction.get("quantifier"))

    if not class_iri or not property_iri or not predicate:
        print("Skipping malformed OWL restriction.")
        if stats:
            stats.axiom_skipped_triples += 1
        return []
    if class_iri not in known_resources or property_iri not in known_resources:
        print(
            "Skipping OWL restriction with unknown class "
            "or property IRI."
        )
        if stats:
            stats.axiom_skipped_triples += 1
        return []

    if _is_cardinality_restriction(predicate):
        try:
            cardinality = int(restriction.get("cardinality"))
        except (TypeError, ValueError):
            print("Skipping OWL restriction with invalid cardinality.")
            if stats:
                stats.axiom_skipped_triples += 1
            return []
        if cardinality < 0:
            print("Skipping OWL restriction with negative cardinality.")
            if stats:
                stats.axiom_skipped_triples += 1
            return []
        value = Literal(cardinality, datatype=XSD.nonNegativeInteger)
    else:
        value_iri = restriction.get("value_iri")
        if not value_iri or value_iri not in known_resources:
            print("Skipping OWL restriction with unknown value IRI.")
            if stats:
                stats.axiom_skipped_triples += 1
            return []
        value = URIRef(value_iri)

    restriction_node = BNode()
    triples = [
        (URIRef(class_iri), RDFS.subClassOf, restriction_node),
        (restriction_node, RDF.type, OWL.Restriction),
        (restriction_node, OWL.onProperty, URIRef(property_iri)),
        (restriction_node, predicate, value),
    ]
    for triple in triples:
        ontology.add(triple)
    if stats:
        stats.axiom_accepted_triples += len(triples)
    return triples


def _add_axiom_proposal(ontology, proposal, stats=None):
    added = []
    known_resources = _known_restriction_resources(ontology)

    for restriction in proposal.get("restrictions", []):
        added.extend(
            _add_restriction_proposal(
                ontology,
                restriction,
                known_resources,
                stats=stats,
            )
        )

    for axiom in proposal.get("axioms", []):
        subject = axiom.get("subject")
        predicate = axiom.get("predicate")
        obj = axiom.get("object")
        if not subject or not predicate or not obj:
            print("Skipping malformed axiom.")
            if stats:
                stats.axiom_skipped_triples += 1
            continue
        if predicate in {str(RDFS.domain), str(RDFS.range)}:
            print(
                "Skipping global rdfs:domain/rdfs:range axiom. "
                "Use an OWL class restriction instead."
            )
            if stats:
                stats.axiom_skipped_triples += 1
            continue
        if subject not in known_resources or obj not in known_resources:
            print("Skipping axiom with unknown subject or object IRI.")
            if stats:
                stats.axiom_skipped_triples += 1
            continue
        triple = (URIRef(subject), URIRef(predicate), URIRef(obj))
        ontology.add(triple)
        added.append(triple)
        if stats:
            stats.axiom_accepted_triples += 1
    return added


def review_llm_axioms(ontology, model=None, interactive=True, stats=None):
    if not interactive:
        return

    history = []
    print("\nStarting LLM ontology axiom review loop.")
    print("For each proposal choose: accept, deny, or finish.")

    while True:
        proposal = llm_propose_axiom(
            ontology,
            model=model,
            history=history,
        )
        if not proposal:
            print("No axiom proposal was produced.")
            reviewer = AlignmentReviewer(interactive=True)
            if not reviewer._ask_yes_no("Try again?"):
                break
            continue

        if stats:
            stats.axiom_proposals += 1
        _format_axiom_proposal(proposal)
        while True:
            try:
                answer = input(
                    "Accept, deny, or finish? [a/d/f]: "
                ).strip().lower()
            except EOFError:
                return
            if answer in {"a", "accept", "yes", "y", "s", "si", "sí"}:
                added = _add_axiom_proposal(
                    ontology,
                    proposal,
                    stats=stats,
                )
                history.append({
                    "decision": "accepted",
                    "proposal": proposal,
                })
                if stats:
                    stats.axiom_accepted_proposals += 1
                print(f"Accepted {len(added)} axiom triple(s).")
                break
            if answer in {"d", "deny", "no", "n"}:
                history.append({
                    "decision": "denied",
                    "proposal": proposal,
                })
                if stats:
                    stats.axiom_denied_proposals += 1
                print("Denied. Asking the LLM for another proposal.")
                break
            if answer in {"f", "finish", "q", "quit", "stop"}:
                print("Finished ontology axiom review.")
                return
            print("Please answer accept, deny, or finish.")


def _property_description(occurrences):
    first_collection, first_property = occurrences[0]
    collection_titles = ", ".join(
        collection.title
        for collection, _ in occurrences[:5]
    )
    parts = [
        f"Property used by collection(s): {collection_titles}."
    ]
    if len(occurrences) > 5:
        parts.append(f"And {len(occurrences) - 5} more collection(s).")
    if first_collection.description:
        parts.append(first_collection.description)
    parts.append(f"Datatype: {first_property['type']}.")
    return " ".join(parts)


def _property_title_from_ontology(ontology, property_uri):
    label = ontology.value(property_uri, RDFS.label)
    if label:
        return str(label)
    return str(property_uri).rstrip("/#").split("/")[-1].split("#")[-1]


def _collection_properties_by_ontology_uri(collections):
    properties_by_uri = defaultdict(list)
    for collection in collections:
        for prop in collection.properties:
            property_uri = URIRef(OGC[prop["title"]])
            properties_by_uri[property_uri].append((collection, prop))
    return properties_by_uri


def _datatype_uri(property_type):
    if property_type == "number":
        return XSD.float
    return XSD[property_type]


def _add_property_alignment(
    ontology,
    collection,
    prop,
    aligned_uri,
    stats=None,
    source=None,
):
    local_property_uri = OGC[prop["title"]]
    aligned_uri = URIRef(aligned_uri)
    class_uri = OGC[collection.id]

    ontology.add((
        local_property_uri,
        OWL.equivalentProperty,
        aligned_uri,
    ))
    ontology.add((aligned_uri, RDF.type, RDF.Property))
    ontology.add((aligned_uri, RDFS.label, Literal(prop["title"])))
    ontology.add((
        aligned_uri,
        RDFS.range,
        _datatype_uri(prop["type"]),
    ))
    ontology.add((aligned_uri, RDFS.domain, class_uri))
    prop["equivalentClass"] = aligned_uri
    prop["annotation_source"] = source
    if stats and source:
        stats.count_alignment("property", source)


def _add_property_extension(
    ontology,
    collection,
    prop,
    proposal,
    stats=None,
):
    proposed_uri = URIRef(proposal["iri"])
    class_uri = OGC[collection.id]

    ontology.add((proposed_uri, RDF.type, RDF.Property))
    ontology.add((
        proposed_uri,
        RDFS.label,
        Literal(proposal.get("label", prop["title"])),
    ))
    ontology.add((
        proposed_uri,
        RDFS.range,
        _datatype_uri(prop["type"]),
    ))
    ontology.add((proposed_uri, RDFS.domain, class_uri))
    if proposal.get("comment"):
        ontology.add((
            proposed_uri,
            RDFS.comment,
            Literal(proposal["comment"]),
        ))
    if proposal.get("parent_iri"):
        ontology.add((
            proposed_uri,
            RDFS.subPropertyOf,
            URIRef(proposal["parent_iri"]),
        ))

    local_property_uri = OGC[prop["title"]]
    ontology.add((
        local_property_uri,
        OWL.equivalentProperty,
        proposed_uri,
    ))
    prop["equivalentClass"] = proposed_uri
    prop["annotation_source"] = "proposal"
    if stats:
        stats.count_alignment("property", "proposal")


def review_property_alignments(
    collections,
    ontology,
    interactive=True,
    stats=None,
    use_local=True,
    use_external=True,
    use_proposals=True,
):
    if not interactive:
        return

    print("\nStarting property alignment review after first ontology draft.")
    collection_properties = _collection_properties_by_ontology_uri(
        collections
    )
    ontology_properties = sorted(
        set(ontology.subjects(RDF.type, RDF.Property)),
        key=str,
    )

    for property_uri in ontology_properties:
        occurrences = collection_properties.get(property_uri)
        if not occurrences or all(
            prop["equivalentClass"]
            for _, prop in occurrences
        ):
            continue

        representative_collection, representative_prop = occurrences[0]
        property_title = _property_title_from_ontology(
            ontology,
            property_uri,
        )
        description = _property_description(occurrences)
        print(
            f"\nReviewing property '{property_title}' "
            f"used in {len(occurrences)} collection(s)"
        )

        review_flag = input(
            "Do you want to review this property for possible "
            "alignment or extension? [Y/n]: "
        ).strip().lower()
        if review_flag in {"n", "no"}:
            print("Skipping review for this property.")
            continue

        if use_local:
            local = representative_collection.reviewer.choose_local(
                property_title,
                description,
                "property",
                representative_collection.oe,
            )
            if local:
                for index, (collection, prop) in enumerate(occurrences):
                    _add_property_alignment(
                        ontology,
                        collection,
                        prop,
                        local,
                        stats=stats if index == 0 else None,
                        source="local",
                    )
                continue

        if use_external:
            external = searchNotLocal(
                property_title,
                description,
                "property",
                model=representative_collection.model,
            )
            if external:
                accepted = (
                    representative_collection.reviewer.confirm_external(
                        property_title,
                        "property",
                        external,
                    )
                )
                if accepted:
                    for index, (collection, prop) in enumerate(occurrences):
                        _add_property_alignment(
                            ontology,
                            collection,
                            prop,
                            accepted,
                            stats=stats if index == 0 else None,
                            source="notlocal",
                        )
                    continue

        if not use_proposals:
            continue

        proposal = llm_propose_property(
            ontology,
            property_title,
            description=description,
            datatype=representative_prop["type"],
            domain_iri=str(OGC[representative_collection.id]),
            model=representative_collection.model,
            prefix=f"{str(OGC)}extension/",
            interactive=interactive,
        )
        if proposal:
            for index, (collection, prop) in enumerate(occurrences):
                _add_property_extension(
                    ontology,
                    collection,
                    prop,
                    proposal,
                    stats=stats if index == 0 else None,
                )


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
    parser.add_argument(
        "-n",
        action="store_true",
        help="Enable LLM class-extension proposals.",
    )
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
