import argparse
import requests
from jsonpath import JSONPath
import rdflib
from rdflib import Namespace, Literal, BNode, URIRef
import os
import tqdm
from collections import defaultdict
from ontology_searh import VectorialOntologyMatcher, searchNotLocal, llm_propose, llm_propose_axiom, llm_propose_property

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

class GenerationStats:
    def __init__(self):
        self.entity_totals = defaultdict(int)
        self.alignment_totals = defaultdict(lambda: defaultdict(int))
        self.axiom_proposals = 0
        self.axiom_accepted_proposals = 0
        self.axiom_denied_proposals = 0
        self.axiom_accepted_triples = 0
        self.axiom_skipped_triples = 0
        self.mappings_generated = 0

    def count_entity(self, entity_type):
        self.entity_totals[entity_type] += 1

    def count_alignment(self, entity_type, source):
        self.alignment_totals[entity_type][source] += 1

    def aligned_total(self, entity_type):
        return sum(self.alignment_totals[entity_type].values())

    def print_summary(self):
        print("\nGeneration statistics")
        for entity_type in ("class", "property"):
            total = self.entity_totals[entity_type]
            aligned = self.aligned_total(entity_type)
            print(f"  {entity_type.title()}s: {aligned}/{total} aligned")
            for source in ("local", "notlocal", "proposal"):
                print(f"    {source}: {self.alignment_totals[entity_type][source]}")
            print(f"    unaligned: {total - aligned}")
        print("  LLM axiom review:")
        print(f"    proposals reviewed: {self.axiom_proposals}")
        print(f"    proposals accepted: {self.axiom_accepted_proposals}")
        print(f"    proposals denied: {self.axiom_denied_proposals}")
        print(f"    triples accepted: {self.axiom_accepted_triples}")
        print(f"    triples skipped: {self.axiom_skipped_triples}")
        print(f"  RML mappings generated: {self.mappings_generated}")


class AlignmentReviewer:
    def __init__(self, interactive=True, local_top_k=5, stats=None):
        self.interactive = interactive
        self.local_top_k = local_top_k
        self.stats = stats

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
        return URIRef(iri) if self._ask_yes_no("Accept this external alignment?") else None

    def choose_local(self, term, description, entity_type, oe):
        if not oe:
            return None
        matches = oe.search_top(term, description or "", top_k=self.local_top_k * 3, threshold=None)
        if entity_type == "property":
            matches = [match for match in matches if "Propiedad" in match["type"]]
        elif entity_type == "class":
            matches = [match for match in matches if match["type"] == "Clase"]
        matches = matches[:self.local_top_k]
        if not matches:
            return None
        print(f"\nLocal ontology matches for {entity_type} '{term}':")
        if matches[0].get("query_text"):
            print(f"  Search text: {matches[0]['query_text']}")
        for idx, match in enumerate(matches, start=1):
            print(
                f"  {idx}. {match['name']} ({match['type']}) "
                f"confidence={match['confidence']} iri={match['iri']}"
            )
        if not self.interactive:
            return None
        while True:
            try:
                answer = input("Choose a match number to accept, or press Enter/0 to skip: ").strip()
            except EOFError:
                return None
            if not answer or answer == "0":
                return None
            if answer.isdigit() and 1 <= int(answer) <= len(matches):
                return URIRef(matches[int(answer) - 1]["iri"])
            print(f"Please enter a number between 1 and {len(matches)}, or 0 to skip.")

    def align(self, term, description, entity_type, oe=None, search_not_local=False, model=None):
        if not self.interactive:
            return None
        
        local = self.choose_local(term, description, entity_type, oe)
        if local:
            if self.stats:
                self.stats.count_alignment(entity_type, "local")
            return local
        
        if search_not_local:
            external = searchNotLocal(term, description or "", entity_type, model=model)
            if external:
                accepted = self.confirm_external(term, entity_type, external)
                if accepted:
                    if self.stats:
                        self.stats.count_alignment(entity_type, "notlocal")
                    return accepted
        return None


class Collection:
    def __init__(self, id, title, description, spatial, url, oe: VectorialOntologyMatcher, search_not_local=False, model=None, flag_not_align=False, reviewer=None, stats=None):
        self.id = id
        self.title = title
        self.description = description
        self.bbox = spatial["bbox"] if spatial and "bbox" in spatial else None
        self.crs = spatial["crs"] if spatial and "crs" in spatial else None
        self.url = url
        self.oe = oe
        self.search_not_local = search_not_local
        self.model = model
        self.flag_not_align = flag_not_align
        self.reviewer = reviewer or AlignmentReviewer(interactive=False)
        self.stats = stats
        self.equivalentClass = self.equivalentClassF()
        self.properties = self._set_properties()
    def _set_properties(self): 
        r = requests.get(self.url + "/collections/" + self.id + "/queryables" + "?f=json").json()
        ret = JSONPath("$.properties").parse(r)
        ret = ret[0] if ret else {}
        l = []
        for i, v in ret.items():
            l.append({
                "title": i,
                "type": v.get("type", "string"),   
                "equivalentClass": None
            })
        return l
    
    def equivalentClassF(self):
        if self.stats:
            self.stats.count_entity("class")
        if self.flag_not_align:
            return None
        return self.reviewer.align(
            self.title,
            self.description,
            "class",
            oe=self.oe,
            search_not_local=True,
            model=self.model
        )


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



def get_collections(urlBase, oe: VectorialOntologyMatcher, search_not_local=False, model=None, flag_not_align=False, reviewer=None, stats=None):
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
            url=urlBase,
            oe=oe,
            search_not_local=search_not_local,
            model=model,
            flag_not_align=flag_not_align,
            reviewer=reviewer,
            stats=stats
        ))
    return collections

def get_collections_filtered(urlBase, oe: VectorialOntologyMatcher, collectionsFiltered, search_not_local=False, model=None, flag_not_align=False, reviewer=None, stats=None):
    try:
        response = requests.get(urlBase+"/collections?f=json")
    except requests.exceptions.RequestException as e:
        print(f"Error fetching collections: {e}")
        return []
    collections_json = JSONPath("$.collections.*").parse(response.json())
    collections = []
    for c in tqdm.tqdm(collections_json, desc="Processing collections", unit="collection"):
        if c["id"] in collectionsFiltered:
            collections.append(Collection(
                id=c["id"],
                title=c["title"],
                description=c["description"] if "description" in c else None,
                spatial=c["extent"]["spatial"] if "extent" in c and "spatial" in c["extent"] else None,
                url=urlBase,
                oe=oe,
                search_not_local=search_not_local,
                model=model,
                flag_not_align=flag_not_align,
                reviewer=reviewer,
                stats=stats
            ))
    return collections

def _format_axiom_proposal(proposal):
    print("\nLLM proposed ontology axiom:")
    if proposal.get("rationale"):
        print(f"  Rationale: {proposal['rationale']}")
    for idx, axiom in enumerate(proposal.get("axioms", []), start=1):
        print(f"  {idx}. {axiom.get('subject')} {axiom.get('predicate')} {axiom.get('object')}")


def _add_axiom_proposal(ontology, proposal, stats=None):
    added = []
    known_resources = set()
    for s, p, o in ontology.triples((None, None, None)):
        if isinstance(s, URIRef):
            known_resources.add(str(s))
        if isinstance(o, URIRef):
            known_resources.add(str(o))

    for axiom in proposal.get("axioms", []):
        subject = axiom.get("subject")
        predicate = axiom.get("predicate")
        obj = axiom.get("object")
        if not subject or not predicate or not obj:
            print("Skipping malformed axiom.")
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
        proposal = llm_propose_axiom(ontology, model=model, history=history)
        if not proposal:
            print("No axiom proposal was produced.")
            if not AlignmentReviewer(interactive=True)._ask_yes_no("Try again?"):
                break
            continue

        if stats:
            stats.axiom_proposals += 1
        _format_axiom_proposal(proposal)
        while True:
            try:
                answer = input("Accept, deny, or finish? [a/d/f]: ").strip().lower()
            except EOFError:
                return
            if answer in {"a", "accept", "yes", "y", "s", "si", "sí"}:
                added = _add_axiom_proposal(ontology, proposal, stats=stats)
                history.append({"decision": "accepted", "proposal": proposal})
                if stats:
                    stats.axiom_accepted_proposals += 1
                print(f"Accepted {len(added)} axiom triple(s).")
                break
            if answer in {"d", "deny", "no", "n"}:
                history.append({"decision": "denied", "proposal": proposal})
                if stats:
                    stats.axiom_denied_proposals += 1
                print("Denied. Asking the LLM for another proposal.")
                break
            if answer in {"f", "finish", "q", "quit", "stop"}:
                print("Finished ontology axiom review.")
                return
            print("Please answer accept, deny, or finish.")


def _property_description(occurrences):
    first_collection, first_prop = occurrences[0]
    collection_titles = ", ".join(c.title for c, _ in occurrences[:5])
    parts = [f"Property used by collection(s): {collection_titles}."]
    if len(occurrences) > 5:
        parts.append(f"And {len(occurrences) - 5} more collection(s).")
    if first_collection.description:
        parts.append(first_collection.description)
    parts.append(f"Datatype: {first_prop['type']}.")
    return " ".join(parts)


def _property_title_from_ontology(ontology, property_uri):
    label = ontology.value(property_uri, RDFS.label)
    if label:
        return str(label)
    return str(property_uri).rstrip("/#").split("/")[-1].split("#")[-1]


def _collection_properties_by_ontology_uri(collections):
    properties_by_uri = defaultdict(list)
    for c in collections:
        if c.flag_not_align:
            continue
        for prop in c.properties:
            properties_by_uri[URIRef(OGC[prop["title"]])].append((c, prop))
    return properties_by_uri


def _datatype_uri(prop_type):
    return XSD["float"] if prop_type == "number" else XSD[prop_type]


def _add_property_alignment(ontology, collection, prop, aligned_uri, stats=None, source=None):
    local_property_uri = OGC[prop["title"]]
    aligned_uri = URIRef(aligned_uri)
    class_uri = OGC[collection.id]

    ontology.add((local_property_uri, OWL.equivalentProperty, aligned_uri))
    ontology.add((aligned_uri, RDF.type, RDF.Property))
    ontology.add((aligned_uri, RDFS.label, Literal(prop["title"])))
    ontology.add((aligned_uri, RDFS.range, _datatype_uri(prop["type"])))
    ontology.add((aligned_uri, RDFS.domain, class_uri))
    prop["equivalentClass"] = aligned_uri
    if stats and source:
        stats.count_alignment("property", source)


def _add_property_extension(ontology, collection, prop, proposal, stats=None):
    proposed_uri = URIRef(proposal["iri"])
    class_uri = OGC[collection.id]

    ontology.add((proposed_uri, RDF.type, RDF.Property))
    ontology.add((proposed_uri, RDFS.label, Literal(proposal.get("label", prop["title"]))))
    ontology.add((proposed_uri, RDFS.range, _datatype_uri(prop["type"])))
    ontology.add((proposed_uri, RDFS.domain, class_uri))
    if proposal.get("comment"):
        ontology.add((proposed_uri, RDFS.comment, Literal(proposal["comment"])))
    if proposal.get("parent_iri"):
        ontology.add((proposed_uri, RDFS.subPropertyOf, URIRef(proposal["parent_iri"])))

    local_property_uri = OGC[prop["title"]]
    ontology.add((local_property_uri, OWL.equivalentProperty, proposed_uri))
    prop["equivalentClass"] = proposed_uri
    if stats:
        stats.count_alignment("property", "proposal")


def review_property_alignments(collections, ontology, interactive=True, stats=None):
    if not interactive:
        return

    print("\nStarting property alignment review after first ontology draft.")
    collection_properties = _collection_properties_by_ontology_uri(collections)
    ontology_properties = sorted(set(ontology.subjects(RDF.type, RDF.Property)), key=str)

    for property_uri in ontology_properties:
        occurrences = collection_properties.get(property_uri)
        if not occurrences or all(prop["equivalentClass"] for _, prop in occurrences):
            continue

        representative_collection, representative_prop = occurrences[0]
        property_title = _property_title_from_ontology(ontology, property_uri)
        description = _property_description(occurrences)
        print(f"\nReviewing property '{property_title}' used in {len(occurrences)} collection(s)")

        review_flag = input("Do you want to review this property for possible alignment or extension? [Y/n]: ").strip().lower()
        if review_flag in {"n", "no"}:
            print("Skipping review for this property.")
            continue

        external = searchNotLocal(property_title, description, "property", model=representative_collection.model)
        if external:
            accepted = representative_collection.reviewer.confirm_external(property_title, "property", external)
            if accepted:
                for index, (c, prop) in enumerate(occurrences):
                    _add_property_alignment(
                        ontology,
                        c,
                        prop,
                        accepted,
                        stats=stats if index == 0 else None,
                        source="notlocal"
                    )
                continue        
        local = representative_collection.reviewer.choose_local(property_title, description, "property", representative_collection.oe)
        if local:
            for c, prop in occurrences:
                _add_property_alignment(ontology, c, prop, local, stats=stats, source="local")
            continue
        
        proposal = llm_propose_property(
            ontology,
            property_title,
            description=description,
            datatype=representative_prop["type"],
            domain_iri=str(OGC[representative_collection.id]),
            model=representative_collection.model,
            prefix=f"{str(OGC)}extension/",
            interactive=interactive
        )
        if proposal:
            for index, (c, prop) in enumerate(occurrences):
                _add_property_extension(ontology, c, prop, proposal, stats=stats if index == 0 else None)


def generate_ontology(collections: list[Collection], output_ontology, reference_ontology, interactive=True, model=None, stats=None):
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

        if c.equivalentClass:
            ontology.add((class_uri, OWL.equivalentClass, URIRef(c.equivalentClass)))

        if c.description: 
            ontology.add((class_uri, RDFS.comment, Literal(c.description))) 
        if c.bbox and c.crs: 
            bbox_blank_node = rdflib.BNode()
            ontology.add((collection_uri, GEO.hasBoundingBox, bbox_blank_node))
            wkt_literal = Literal(f"<{c.crs}> POLYGON((" + ",".join(map(str, c.bbox[0])) + "))", datatype=GEO.wktLiteral)
            ontology.add((bbox_blank_node, GEO.asWKT, wkt_literal))
        for prop in c.properties: 
            property_uri = OGC[prop["title"]] if not prop["equivalentClass"] else prop["equivalentClass"]
            ontology.add((property_uri, RDF.type, RDF.Property)) 
            ontology.add((property_uri, RDFS.label, Literal(prop["title"]))) 
            ontology.add((property_uri, RDFS.range, XSD[prop["type"]])) if prop["type"]!="number" else ontology.add((property_uri, RDFS.range, XSD["float"]))
            ontology.add((property_uri, RDFS.domain, class_uri))

    if stats:
        collection_property_uris = _collection_properties_by_ontology_uri(collections)
        stats.entity_totals["property"] = len({
            property_uri
            for property_uri in ontology.subjects(RDF.type, RDF.Property)
            if property_uri in collection_property_uris
        })

    for c in collections:
        if c.equivalentClass or not c.search_not_local or not interactive:
            continue

        proposal = llm_propose(
            reference_ontology,
            c.title,
            type="class",
            description=c.description or "",
            model=c.model,
            prefix=str(OGC),
            interactive=interactive
        ) if reference_ontology else None
        if not proposal:
            continue

        class_uri = OGC[c.id]
        proposed_uri = URIRef(proposal["iri"])
        parent_uri = URIRef(proposal["parent_iri"])
        ontology.add((proposed_uri, RDF.type, OWL.Class))
        ontology.add((proposed_uri, RDFS.subClassOf, parent_uri))
        ontology.add((proposed_uri, RDFS.label, Literal(proposal.get("label", c.title))))
        if proposal.get("comment"):
            ontology.add((proposed_uri, RDFS.comment, Literal(proposal["comment"])))
        ontology.add((class_uri, OWL.equivalentClass, proposed_uri))
        c.equivalentClass = proposed_uri
        if stats:
            stats.count_alignment("class", "proposal")

    review_property_alignments(collections, ontology, interactive=interactive, stats=stats)
    review_llm_axioms(ontology, model=model, interactive=interactive, stats=stats)
    
    ontology.serialize(destination=output_ontology, format="turtle")

def generate_mapping(collection, output_mappings_folder, urlBase):
    g_mappings = rdflib.Graph()
    for b in namespaces:
        g_mappings.bind(b, namespaces[b])
    add_logical_sources(collection.id, collection.url + f"/collections/{collection.id}" + "/items?f=json&limit=10000", OGC, g_mappings)
    triples_map = OGC[collection.id + "TriplesMap"]
    g_mappings.add((triples_map, RDF.type, RML.TriplesMap))

    g_mappings.add((triples_map, RML.logicalSource, OGC["LogicalSource_" + collection.id]))
    if not collection.equivalentClass:
        add_subject_map(triples_map, OGC[collection.id], g_mappings, template=collection.url + f"/collections/{collection.id}" + "/items/{id}")
    else:
        add_subject_map(triples_map, collection.equivalentClass, g_mappings, template=collection.url + f"/collections/{collection.id}" + "/items/{id}")

    for prop in collection.properties: 
        if prop["equivalentClass"]:
            add_pom_ref(triples_map, URIRef(prop["equivalentClass"]), f"properties.{prop['title']}", g_mappings, datatype=XSD[prop["type"]], filter=f"{prop['title']}"+"=@{1}") if prop["type"]!="number" else add_pom_ref(triples_map, URIRef(prop["equivalentClass"]), f"properties.{prop['title']}", g_mappings, datatype=XSD["float"], filter=f"{prop['title']}"+"=@{1}")
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
    argparser.add_argument("-u", "--ogc_api_url", help="URL of the Features OGC root endpoint OR text file with multiple OGC API endpoints (one per line)")
    argparser.add_argument("--output_folder", "-o", default="output", help="Output folder name (default: output)")
    argparser.add_argument("-n", action="store_true", help="Search Wikidata/DBpedia before local vectorial search. WARNING: can be very slow!")
    argparser.add_argument("-c","--collections", default=None, help="File with urls of the collections to process")
    argparser.add_argument("-r", "--rontologias", default=None, help="Rutas a los archivos .owl")
    argparser.add_argument("-l", "--llm_model", default="openai/gpt-oss-120b", help="LLM model to use for ontology search")
    argparser.add_argument("-v", "--vectorial_model", default="paraphrase-multilingual-MiniLM-L12-v2", help="Sentence Transformer model to use for ontology alignment")
    argparser.add_argument("-f", "--flag-not-align", action="store_true", help="Flag to not perform ontology alignment and just generate mappings with the original collection properties")
    argparser.add_argument("--no-interactive", action="store_true", help="Disable human confirmation prompts and skip automatic alignments")

    args = argparser.parse_args()

    if not args.ogc_api_url and not args.collections:
        print("Error: You must provide either an OGC API URL or a file with collection URLs.")
        exit(1)

    ogc_api_urls = []
    collectionsFiltered = []
    ogc_api_url = args.ogc_api_url if args.ogc_api_url and not os.path.isfile(args.ogc_api_url) else None
    if not ogc_api_url and args.ogc_api_url and os.path.isfile(args.ogc_api_url):
        with open(args.ogc_api_url, "r") as f:
            ogc_api_urls = [line.strip() for line in f if line.strip()]  
    if args.collections:
        with open(args.collections, "r") as f:
            collectionsFiltered = [line.strip() for line in f if line.strip()]
    os.makedirs(args.output_folder, exist_ok=True)
    output_ontology = args.output_folder + "/ontology.ttl"

    ontologies = []
    if args.rontologias:
        if os.path.isfile(args.rontologias):
            ontologies.append(args.rontologias)
        else:
            for file in os.listdir(args.rontologias):
                if file.endswith(".owl") or file.endswith(".ttl") or file.endswith(".rdf"):
                    ontologies.append(os.path.join(args.rontologias, file))

    stats = GenerationStats()
    oe = VectorialOntologyMatcher(ontologies, model=args.vectorial_model) if ontologies and not args.flag_not_align else None
    reviewer = AlignmentReviewer(interactive=not args.no_interactive, stats=stats)

    print(f"Fetching collections from OGC API(s)...")
    if not args.collections:
        if ogc_api_url:
            collections = get_collections(ogc_api_url, oe, args.n, model=args.llm_model, flag_not_align=args.flag_not_align, reviewer=reviewer, stats=stats)
        elif ogc_api_urls:
            collections = []
            for url in ogc_api_urls:
                print(f"Processing OGC API: {url}")
                collections.extend(get_collections(url, oe, args.n, model=args.llm_model, flag_not_align=args.flag_not_align, reviewer=reviewer, stats=stats))
    else:
        if ogc_api_url:
            collections = get_collections_filtered(ogc_api_url, oe, collectionsFiltered, args.n, model=args.llm_model, flag_not_align=args.flag_not_align, reviewer=reviewer, stats=stats)
        elif ogc_api_urls:
            collections = []
            for url in ogc_api_urls:
                print(f"Processing OGC API: {url}")
                collections.extend(get_collections_filtered(url, oe, collectionsFiltered, args.n, model=args.llm_model, flag_not_align=args.flag_not_align, reviewer=reviewer, stats=stats))

    print(f"Generating ontology for {len(collections)} collections...")
    generate_ontology(collections, output_ontology, ontologies[0], interactive=not args.no_interactive, model=args.llm_model, stats=stats) if ontologies and not args.flag_not_align else generate_ontology(collections, output_ontology, None, interactive=not args.no_interactive, model=args.llm_model, stats=stats)

    output_mappings_folder = args.output_folder + "/mappings"
    os.makedirs(output_mappings_folder, exist_ok=True) 

    print("Generating RML mappings...")
    for collection in collections:
        generate_mapping(collection, output_mappings_folder, ogc_api_url)
        stats.mappings_generated += 1
    stats.print_summary()
    print("All done!")
    
