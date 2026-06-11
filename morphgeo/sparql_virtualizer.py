from collections import defaultdict
from pathlib import Path
import random
from typing import Generator

import rdflib
from rdflib import Variable
from rdflib.plugins.sparql import CUSTOM_EVALS
from rdflib.plugins.sparql.evalutils import _ebv
from rdflib.plugins.sparql.evaluate import evalPart
from rdflib.plugins.sparql.operators import register_custom_function
from rdflib.plugins.sparql.sparql import FrozenBindings, QueryContext

try:
    from .virtual import (
        evalVirtualBGP,
        evalVirtualBGPWithoutBindings,
        getMappingGroups,
        getMappingsFromBGP,
        getMappingsFromBGPWithoutBindings,
        orderTriplesStatic,
    )
    from .mappings import getMappingsFromFolder
    from .classes import TriplePattern, MappingContext, geoBindings
    from .geoFunctions import GEOF_SFCONTAINS, geof_sfContains, GEOF_DISTANCE, geof_distance, GEOF_WITHIN, geof_within, GEOF_INTESECT, geof_intersects, GEOF_OVERLAPS, geof_overlaps, GEOF_CROSSES, geof_crosses
except ImportError:
    from virtual import (
        evalVirtualBGP,
        evalVirtualBGPWithoutBindings,
        getMappingGroups,
        getMappingsFromBGP,
        getMappingsFromBGPWithoutBindings,
        orderTriplesStatic,
    )
    from mappings import getMappingsFromFolder
    from classes import TriplePattern, MappingContext, geoBindings
    from geoFunctions import GEOF_SFCONTAINS, geof_sfContains, GEOF_DISTANCE, geof_distance, GEOF_WITHIN, geof_within, GEOF_INTESECT, geof_intersects, GEOF_OVERLAPS, geof_overlaps, GEOF_CROSSES, geof_crosses

PROJECT_ROOT = Path(__file__).resolve().parent.parent
mappings = getMappingsFromFolder(
    PROJECT_ROOT / "eval" / "initialMappingTemplates" / "mappings"
)
"""
#TODO:  
    -PRUEBAS:
        0. Comparación de la selección de mappings
        -FIXEAR que mi getMappings no pilla bien los parentTripleMaps de GFTS-Madrid

#POSIBLES MEJORAS:
    -Hacer un selectNextSubQuery dinamico o
    -Mejorar el order. Si una geometria depende de otra que tiene mucho score, se deberia de subir mas el score que si depende de una con menos score.
    -Mejorar compatibleMapping como en Query-Specific Pruning of RML Mappings ?
    -Paralelizar sub-consultas independientes.
    -El order tiene que ponderar el numero de elementos de la coleccion ?
    -Se podra paralelizar la unificacion?
    -Pushdown de los filter sobre valores literales para que ya ni se metan en el triple store.
    -Usar caches


+++ Query-Specific Pruning of RML Mappings:
    -Puedo implementar el prunning al principio? ns si servira de algo, porque despues ya hago el select mapping
    -En todo caso, la definición de incompatibilidad me la quedo

+++ hacer un selectNextTriplePattern? para evaluar dinamicamente la tripleta a evaluar?
+++ Solucionar termCompatibility, sobre todo para diferenciar templates de sujeto(deberian de ser subclase de URIRef) y referencias de objeto

Optimizaciones implementadas (para acordarme):
    -El select de mappings es flow unification, creo q es mejor q el estado del arte. SPOILER: no lo es, pero igual esta bien ponerlo, tambien las pruebas que hice
    -Binding restricted star shaped subqueries (tambien flow recursive unification)
    -Ordenacion de tripletas
    -Bindings geo con void:bbox
    -Objetos literales + void:filter
    -queriesMade teniendo en cuenta el bbox (si se ha hecho la misma consulta pero con un bbox que contenga plenamente al bbox a consultar, no hace falta hacer la consulta).
    -Lo de los triggers.
Assumptions:
    -El join de los parentTriplesMap no se hace, sencillamente se evalua el subject template del padre en el child.
"""

_random_triple_rng = random.Random()
_random_triple_orders = []


def configure_random_triple_order(seed=None):
    """Reset the RNG and trace used by the randomized evaluator."""
    _random_triple_rng.seed(seed)
    _random_triple_orders.clear()


def get_random_triple_orders():
    return [
        [tuple(triple) for triple in bgp_order]
        for bgp_order in _random_triple_orders
    ]


def _record_random_triple_order(triples):
    _random_triple_orders.append([
        tuple(
            term.n3() if isinstance(term, rdflib.term.Node) else str(term)
            for term in triple
        )
        for triple in triples
    ])


def virtual_bgp_evalBaseline(
    ctx: QueryContext,
    part,
) -> Generator[FrozenBindings, None, None]:
    """Evaluate in query order without literal or geospatial URL bindings."""
    if part.name != "BGP":
        raise NotImplementedError()

    triple_patterns = [
        TriplePattern(s, p, o)
        for s, p, o in part.triples
    ]
    selected_mappings = set()
    mapping_ctx = MappingContext()
    for mapping in getMappingsFromBGPWithoutBindings(
        mapping_ctx,
        triple_patterns,
        mappings,
    ):
        selected_mappings.add(mapping)

    mapping_groups = getMappingGroups(selected_mappings)
    triggers = defaultdict(lambda: None)
    queries_made = set()
    return evalVirtualBGPWithoutBindings(
        ctx,
        triple_patterns,
        mapping_groups,
        triggers,
        queries_made,
    )


def virtual_bgp_evalBindingInjectionRandom(
    ctx: QueryContext,
    part,
) -> Generator[FrozenBindings, None, None]:
    """Evaluate with URL binding injection and randomized triple order."""
    if part.name != "BGP":
        raise NotImplementedError()

    triples = list(part.triples)
    _random_triple_rng.shuffle(triples)
    _record_random_triple_order(triples)
    triple_patterns = [
        TriplePattern(s, p, o)
        for s, p, o in triples
    ]

    selected_mappings = set()
    mapping_ctx = MappingContext()
    for mapping in getMappingsFromBGP(
        mapping_ctx,
        triple_patterns,
        mappings,
    ):
        selected_mappings.add(mapping)

    mapping_groups = getMappingGroups(selected_mappings)
    triggers = defaultdict(lambda: None)
    queries_made = set()
    return evalVirtualBGP(
        ctx,
        triple_patterns,
        mapping_groups,
        triggers,
        queries_made,
    )


def virtual_bgp_evalFinal(ctx: QueryContext, part) -> Generator[FrozenBindings, None, None]:
    if part.name != "BGP":
        raise NotImplementedError()
    
    tps = []
    triples, _ = orderTriplesStatic(ctx, part.triples)
    
    for s, p, o in triples:
        tp = TriplePattern(s, p, o)
        tps.append(tp)

    mappingsBGP = set()
    ctxMapping = MappingContext()
    for m in getMappingsFromBGP(ctxMapping, tps, mappings):
        mappingsBGP.add(m)    

    mappingGroups = getMappingGroups(mappingsBGP)
    # TO-DO: optimizeMappingGroups() -> Si 2 grupos de mappings tienen el mismo merged source, igual hay que unificarlos
    
    triggers = defaultdict(lambda: None)
    queriesMade = set()
    return evalVirtualBGP(ctx, tps, mappingGroups, triggers, queriesMade)


def virtualGeoFilter(ctx: QueryContext, part) -> Generator[FrozenBindings, None, None]:
    if part.name != "Filter":
        raise NotImplementedError()

    def _append_contains(container, contained):
        if type(contained) is Variable and type(container) is rdflib.term.Literal:
            geoBindings[contained].append(container)
        if type(contained) is Variable and type(container) is Variable:
            geoBindings[contained].append(container)

    def _append_contains_bi(geom1, geom2):
        if type(geom1) is Variable and type(geom2) is rdflib.term.Literal:
            geoBindings[geom1].append(geom2)
        if type(geom2) is Variable and type(geom1) is rdflib.term.Literal:
            geoBindings[geom2].append(geom1)
        if type(geom2) is Variable and type(geom1) is Variable:
            geoBindings[geom2].append(geom1)
            geoBindings[geom1].append(geom2)

    def _append_distance(geom1, geom2, distance):
        distance = str(distance)
        if type(geom1) is Variable and type(geom2) is rdflib.term.Literal:
            geoBindings[geom1].append(geom2 + ":-:" + distance)
        if type(geom2) is Variable and type(geom1) is rdflib.term.Literal:
            geoBindings[geom2].append(geom1 + ":-:" + distance)
        if type(geom2) is Variable and type(geom1) is Variable:
            geoBindings[geom2].append(geom1 + ":-:" + distance)
            geoBindings[geom1].append(geom2 + ":-:" + distance)

    def _is_distance_upper_bound(op, distance_on_left):
        if distance_on_left:
            return op in ("<", "<=", "=")
        return op in (">", ">=", "=")

    def _handle_geo_expr(expr):
        iri = getattr(expr, "iri", None)
        args = getattr(expr, "expr", None)
        if not isinstance(args, (list, tuple)) or len(args) != 2:
            return

        if iri == GEOF_SFCONTAINS:
            _append_contains_bi(args[0], args[1])
        elif iri == GEOF_WITHIN:
            _append_contains_bi(args[1], args[0])
        elif iri == GEOF_INTESECT or iri == GEOF_OVERLAPS or iri == GEOF_CROSSES:
            _append_contains_bi(args[0], args[1])
        elif iri == GEOF_DISTANCE:
            return

    stack = [part.expr]
    seen = set()
    while stack:
        expr = stack.pop()
        if expr is None:
            continue

        expr_id = id(expr)
        if expr_id in seen:
            continue
        seen.add(expr_id)

        _handle_geo_expr(expr)

        op = getattr(expr, "op", None)
        if op is not None:
            left = getattr(expr, "expr", None)
            right = getattr(expr, "other", None)
            if getattr(left, "iri", None) == GEOF_DISTANCE and _is_distance_upper_bound(op, True):
                args = getattr(left, "expr", None)
                if isinstance(args, (list, tuple)) and len(args) == 2:
                    _append_distance(args[0], args[1], right)
            elif getattr(right, "iri", None) == GEOF_DISTANCE and _is_distance_upper_bound(op, False):
                args = getattr(right, "expr", None)
                if isinstance(args, (list, tuple)) and len(args) == 2:
                    _append_distance(args[0], args[1], left)

        if isinstance(expr, (list, tuple)):
            stack.extend(expr)
            continue
        if isinstance(expr, dict):
            stack.extend(expr.values())
            continue

        values = getattr(expr, "values", None)
        if callable(values):
            try:
                stack.extend(values())
            except TypeError:
                pass


    def _auxGen(ctx, part):
        for c in evalPart(ctx, part.p):
            if _ebv(
                part.expr,
                c.forget(ctx, _except=part._vars) if not part.no_isolated_scope else c,
            ):
                yield c

    return _auxGen(ctx, part)


CUSTOM_EVALS["virtual_bgp"] = virtual_bgp_evalFinal
CUSTOM_EVALS["virtualGeofilter"] = virtualGeoFilter
register_custom_function(GEOF_SFCONTAINS, geof_sfContains)
register_custom_function(GEOF_DISTANCE, geof_distance)
register_custom_function(GEOF_WITHIN, geof_within)
register_custom_function(GEOF_INTESECT, geof_intersects)
register_custom_function(GEOF_OVERLAPS, geof_overlaps)
register_custom_function(GEOF_CROSSES, geof_crosses)

if __name__ == "__main__":
    g = rdflib.Graph()


    query = """
    PREFIX ogc: <http://www.ogc.org/>
    PREFIX geo: <http://www.opengis.net/ont/geosparql#> 
    PREFIX ine: <http://lod.ine.es/def/vocabulary/>
    PREFIX sdmx-measure: <http://purl.org/linked-data/sdmx/2009/measure#>
    PREFIX sdmx-dimension: <http://purl.org/linked-data/sdmx/2009/dimension#>
    PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
    PREFIX geof: <http://www.opengis.net/def/function/geosparql/>
    PREFIX ex: <http://example.com/>
    PREFIX qb: <http://purl.org/linked-data/cube#>
    PREFIX dbo: <http://dbpedia.org/ontology/>
    PREFIX geolinkeddata: <http://geo.linkeddata.es/ontology/> 

    SELECT ?t WHERE {
        ?y a <http://example.org/ontology/AU_UnidadesAdministrativas> ;
            ogc:nameunit "Madrid" ;
            ogc:country "ES" ;
            geo:hasGeometry ?gy .
        ?t a ogc:copernicus_wcs ;
            ogc:coverage "NATURAL-COLOR" ;
            geo:hasGeometry ?gt .
        FILTER(geof:sfContains(?gt, ?gy))
    }

    """

    qres = g.query(query)
    #qres = g.query(Path("/Users/kekojohns/Library/CloudStorage/OneDrive-Personal/muia/oeg/tfm/eval/vkg/queries/q04.rq").read_text(encoding="utf-8"))
    g_out = rdflib.Graph()

    for r in qres:
        #g_out.add(r)
        print(r)
        pass

    #g_out.serialize("output.ttl", format="turtle")
