import re
from pathlib import Path
from typing import List, Tuple, Set
from rdflib import URIRef, Namespace, Variable
import rdflib
import pandas as pd
from rdflib.plugins.sparql import prepareQuery

from classes import *
from utils import get_invariant
from virtual import getMappingsFromBGP
from mappings import getMappingsFromFolder, getMappings


def mappingCandidateSelectionITT(mappings: List[VirtualMapping], triple_patterns) -> List[VirtualMapping]:
    def term_to_df_value(term):
        if isinstance(term, rdflib.term.Variable):
            return f"?{term}"
        return str(term)

    def mappings_to_df(virtual_mappings):
        return pd.DataFrame.from_records(
            (
                {
                    "__mapping_idx": i,
                    "subject_invariant": get_invariant(vm.s),
                    "predicate_map_value": str(vm.p),
                    "object_map_value": str(vm.o),
                }
                for i, vm in enumerate(virtual_mappings)
            )
        )

    def triple_patterns_to_df(patterns):
        if isinstance(patterns, pd.DataFrame):
            return patterns.copy()
        if hasattr(patterns, "algebra"):
            patterns = triples_from_algebra(patterns.algebra)
        elif not isinstance(patterns, (list, tuple, set)):
            patterns = triples_from_algebra(patterns)
        return pd.DataFrame.from_records(
            (
                {
                    "s": term_to_df_value(tp.s),
                    "p": term_to_df_value(tp.p),
                    "o": term_to_df_value(tp.o),
                }
                for tp in patterns
            ),
            columns=["s", "p", "o"],
        )

    asserted_mapping_df = mappings_to_df(mappings)
    if asserted_mapping_df.empty:
        return []

    triple_patterns_df = triple_patterns_to_df(triple_patterns)
    if triple_patterns_df.empty:
        return []


    simplified_df = asserted_mapping_df
    simplified_df['is_used'] = False

    ###############################################################################
    ######################## UNBOUNDED SUBJECTS ###################################
    ###############################################################################

    subject_groups_df = [group for _, group in asserted_mapping_df.groupby(by='subject_invariant')]

    # structure for subject groups
    sgs = []
    for i, subject_group_df in enumerate(subject_groups_df):
        sg = dict()
        sg['subject_invariant'] = subject_group_df.iloc[0]['subject_invariant']
        sg['predicates'] = set(subject_group_df['predicate_map_value'])
        aux_df = subject_group_df[subject_group_df['predicate_map_value'] == 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type']
        sg['classes'] = set(aux_df['object_map_value'])
        sgs.append(sg)


    star_triple_patterns_df = triple_patterns_df[triple_patterns_df['s'].str.startswith('?')]
    star_triple_patterns_df = [group for _, group in star_triple_patterns_df.groupby(by='s')]

    for star_triple_pattern_df in star_triple_patterns_df:
        all_preds_bound = True
        for pred in star_triple_pattern_df['p']:
            if pred.startswith('?'):
                all_preds_bound = False

        if all_preds_bound:
            for sg in sgs:
                stp_sg_predicate_intersection = set(star_triple_pattern_df['p']).intersection(sg['predicates'])

                # if star pattern is typed and triples map is typed check if they overlap
                if 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type' in list(star_triple_pattern_df['p']):
                    if len(set(star_triple_pattern_df['o']).intersection(sg['classes'])) > 0:
                        for i, row in simplified_df.iterrows():
                            if row['subject_invariant'] == sg['subject_invariant'] and row['predicate_map_value'] in stp_sg_predicate_intersection:
                                # set to used the rules in the triples maps based on the predicates
                                simplified_df.at[i, 'is_used'] = True
                else:
                    for i, row in simplified_df.iterrows():
                        if row['subject_invariant'] == sg['subject_invariant'] and row['predicate_map_value'] in stp_sg_predicate_intersection:
                            # set to used the rules in the triples maps based on the predicates
                            simplified_df.at[i, 'is_used'] = True

        else:   # unbound predicates
            for sg in sgs:
                if 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type' in list(star_triple_pattern_df['p']):
                    if len(set(star_triple_pattern_df['o']).intersection(sg['classes'])) > 0:
                        for i, row in simplified_df.iterrows():
                            if row['subject_invariant'] == sg['subject_invariant']:
                                # set to used the rules in the triples maps based on the predicates
                                simplified_df.at[i, 'is_used'] = True
                else:
                    # it is not possible to simplify mappings
                    simplified_df['is_used'] = True



    ###############################################################################
    ######################## BOUNDED SUBJECTS #####################################
    ###############################################################################

    bounded_triple_patterns_df = triple_patterns_df[~triple_patterns_df['s'].str.startswith('?')]
    for i, rule in simplified_df.iterrows():
        for j, triple_pattern in bounded_triple_patterns_df.iterrows():
            if triple_pattern['s'].startswith(rule['subject_invariant']):
                if triple_pattern['p'].startswith('?'):
                    simplified_df.at[i, 'is_used'] = True
                else:
                    if triple_pattern['p'] == rule['predicate_map_value']:
                        simplified_df.at[i, 'is_used'] = True


    simplified_df = simplified_df[simplified_df.is_used == True]

    return [mappings[i] for i in simplified_df['__mapping_idx'].to_numpy()]



def template_to_regex(template: str):
    return re.escape(template).replace(r"\{", "{").replace(r"\}", "}") \
        .replace("{", "").replace("}", ".+")

def matches(pattern: str, value: str) -> bool:
    """Comprueba si un valor encaja con un patrón (regex simple)."""
    try:
        return re.fullmatch(template_to_regex(pattern), value) is not None
    except:
        return pattern == value

def is_variable(x) -> bool:
    return isinstance(x, rdflib.term.Variable) 



def is_incompatible(tp: TriplePattern, mtm: VirtualMapping) -> bool:
    s, p, o = tp.s, tp.p, tp.o

    # SUBJECT
    if not is_variable(s):
        if not matches(mtm.s, s):
            return True

    # PREDICATE
    if not is_variable(p):
        if not matches(mtm.p, p):
            return True

    # OBJECT
    if not is_variable(o):
        if not matches(mtm.o, o):
            return True

    return False  # si no encontramos incompatibilidad

def prune_mappings_olaf(P: List[TriplePattern], M: List[VirtualMapping]) -> List[VirtualMapping]:
    result = set()

    for mtm in M:
        for tp in P:
            if not is_incompatible(tp, mtm):
                result.add(mtm)
                break  # equivalente a "continue" del algoritmo

    return result

def triples_from_algebra(algebra) -> List[TriplePattern]:
    tps = []
    seen = set()

    def visit(node):
        node_id = id(node)
        if node_id in seen:
            return
        seen.add(node_id)

        triples = getattr(node, "triples", None)
        if triples:
            tps.extend(TriplePattern(s, p, o) for s, p, o in triples)

        if isinstance(node, dict):
            values = node.values()
        elif isinstance(node, (list, tuple, set)):
            values = node
        else:
            return

        for value in values:
            visit(value)

    visit(algebra)
    return tps

def runEval():
    resources_path = Path("/Users/kekojohns/Desktop/pruningOlaf/resources")
    queries_path = resources_path / "queries"
    mappings = getMappings(str(resources_path / "mapping.rml.ttl"))

    def natural_key(path: Path):
        return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", path.name)]

    rows = []
    for query_path in sorted(queries_path.glob("*.rq"), key=natural_key):
        q = prepareQuery(query_path.read_text(encoding="utf-8"))
        tps = triples_from_algebra(q.algebra)

        rows.append(
            {
                "query": query_path.name,
                "triple_patterns": len(tps),
                "olaf": len(prune_mappings_olaf(tps, mappings)),
                "itt": len(set(mappingCandidateSelectionITT(mappings, tps))),
                "morphgeo": len(set(getMappingsFromBGP(MappingContext(), tps, mappings))),
            }
        )

    print(pd.DataFrame(rows).to_string(index=False))

def aux():
    #mappings = getMappings("/Users/kekojohns/Desktop/pruningOlaf/resources/mapping.rml.ttl")
    mappings = getMappingsFromFolder("/Users/kekojohns/Library/CloudStorage/OneDrive-Personal/muia/oeg/tfm/casoDeUso/mappings")

    #q = prepareQuery(Path("/Users/kekojohns/Desktop/pruningOlaf/resources/queries/q18.rq").read_text(encoding="utf-8"))
    q = prepareQuery(Path("/Users/kekojohns/Library/CloudStorage/OneDrive-Personal/muia/oeg/tfm/casoDeUso/queries/q02.rq").read_text(encoding="utf-8"))
    tps = triples_from_algebra(q.algebra)

    ms_morphgeo = set(getMappingsFromBGP(MappingContext(), tps, mappings))
    ms_itt = mappingCandidateSelectionITT(mappings, tps)

    print(f"Len morphgeo {len(list(ms_morphgeo))}, Len ITT {len(ms_itt)}")

    ms_itt = set(ms_itt)
    print(f"In ms_morphgeo and not in ms_itt: {len(ms_morphgeo - ms_itt)}")
    for m in ms_morphgeo - ms_itt:
        print(m.s, m.p, m.o, m.source)
    print(f"In ms_itt and not in ms_morphgeo: {len(ms_itt - ms_morphgeo)}")
    for m in ms_itt - ms_morphgeo:
        print(m.s, m.p, m.o, m.source)


if __name__ == "__main__":
    #runEval()
    aux()