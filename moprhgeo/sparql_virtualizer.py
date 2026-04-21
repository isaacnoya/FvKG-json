from rdflib.plugins.sparql import CUSTOM_EVALS
from rdflib.plugins.sparql.sparql import FrozenBindings, QueryContext
from rdflib.plugins.sparql.evaluate import evalPart
from rdflib.plugins.sparql.operators import register_custom_function
from rdflib import Variable, Namespace
from typing import Generator

from rdflib.plugins.sparql.evalutils import (
    _ebv,
    _eval,
    _fillTemplate,
    _join,
    _minus,
    _val,
)

from virtual import getStarShapedSubqueries, candidateMappingSelection, materializeVirtualMappingGroup, getMappingsFromBGP, evalVirtualBGP, getMappingGroups, orderTriplesStatic
from mappings import getMappingsFromTxT
from classes import TriplePattern, MappingContext, geoBindings
from geoFunctions import GEOF_SFCONTAINS, geof_sfContains, GEOF_DISTANCE, geof_distance, GEOF_WITHIN, geof_within, GEOF_INTESECT, geof_intersects, GEOF_OVERLAPS, geof_overlaps, GEOF_CROSSES, geof_crosses

EX = Namespace("http://example.com/")

mappings = getMappingsFromTxT("/Users/kekojohns/Library/CloudStorage/OneDrive-Personal/muia/oeg/tfm/moprhgeo/mappings.txt")

"""
#TODO:  
    -Buscar caso de uso
    -Solucionar lo de la coordenada de referencia (ns q es), mirar https://pypi.org/project/pyproj/
    -mejorar visualizacion
    -Mejorar compatibleMapping como en Query-Specific Pruning of RML Mappings.


+++ Query-Specific Pruning of RML Mappings:
    -Puedo implementar el prunning al principio? ns si servira de algo, porque despues ya hago el select mapping
    -En todo caso, la definición de incompatibilidad me la quedo

+++ hacer un selectNextTriplePattern? para evaluar dinamicamente la tripleta a evaluar?
+++ Solucionar termCompatibility, sobre todo para diferenciar templates de sujeto(deberian de ser subclase de URIRef) y referencias de objeto

Optimizaciones implementadas (para acordarme):
    -El select de mappings es flow unification, creo q es mejor q el estado del arte
    -Binding restricted star shaped subqueries (tambien flow recursive unification)
    -Ordenacion de tripletas
    -Bindings geo con void:bbox
    -Objetos literales + void:filter
    -queriesMade teniendo en cuenta el bbox (si se ha hecho la misma consulta pero con un bbox que contenga plenamente al bbox a consultar, no hace falta hacer la consulta), si no se overlapean al completo, saca los fragmentos.
Assumptions:
    -El join de los parentTriplesMap no se hace, sencillamente se evalua el subject template del padre en el child.
"""

def virtual_bgp_eval(ctx: QueryContext, part) -> Generator[FrozenBindings, None, None]:
    if part.name != "BGP":
        raise NotImplementedError()
    
    tps = []
    for s, p, o in part.triples:
        tp = TriplePattern(s, p, o)
        tps.append(tp)

    subqueries = getStarShapedSubqueries(tps)

    for suj, tps in subqueries.items():
        mappings_for_subq = candidateMappingSelection(tps, mappings)

        ctx = materializeVirtualMappingGroup(
            mappings_for_subq,
            ctx
        )

    triples = sorted(
        part.triples, key=lambda t: len([n for n in t if ctx[n] is None])
    )
    return rdflib.plugins.sparql.evaluate.evalBGP(ctx, triples)

def virtual_bgp_eval2(ctx: QueryContext, part) -> Generator[FrozenBindings, None, None]:
    if part.name != "BGP":
        raise NotImplementedError()
    
    tps = []
    for s, p, o in part.triples:
        tp = TriplePattern(s, p, o)
        tps.append(tp)

    subqueries = getStarShapedSubqueries(tps)

    for suj, tps in subqueries.items():
        mappings_for_subq = set()
        ctxMapping = MappingContext()
        for m in getMappingsFromBGP(ctxMapping, tps, mappings):
            mappings_for_subq.add(m)
        
        ctx = materializeVirtualMappingGroup(
            mappings_for_subq,
            ctx
        )

    triples = sorted(
        part.triples, key=lambda t: len([n for n in t if ctx[n] is None])
    )
    return rdflib.plugins.sparql.evaluate.evalBGP(ctx, triples)

from collections import defaultdict
def virtual_bgp_eval3(ctx: QueryContext, part) -> Generator[FrozenBindings, None, None]:
    if part.name != "BGP":
        raise NotImplementedError()
    
    tps = []
    """
    triples = sorted(
        part.triples, key=lambda t: len([n for n in t if ctx[n] is None])
    )
    """
    triples = orderTriplesStatic(ctx, part.triples)
    
    for s, p, o in triples:
        tp = TriplePattern(s, p, o)
        tps.append(tp)

    mappingsBGP = set()
    ctxMapping = MappingContext()
    for m in getMappingsFromBGP(ctxMapping, tps, mappings):
        mappingsBGP.add(m)    

    mappingGroups = getMappingGroups(mappingsBGP)
    # TODO: optimizeMappingGroups() -> Si 2 grupos de mappings tienen el mismo merged source, igual hay que unificarlos
    
    trigers = defaultdict(lambda: None)
    queriesMade = set()
    return evalVirtualBGP(ctx, tps, mappingGroups, trigers, queriesMade)


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


CUSTOM_EVALS["virtual_bgp"] = virtual_bgp_eval3
CUSTOM_EVALS["virtualGeofilter"] = virtualGeoFilter
register_custom_function(GEOF_SFCONTAINS, geof_sfContains)
register_custom_function(GEOF_DISTANCE, geof_distance)
register_custom_function(GEOF_WITHIN, geof_within)
register_custom_function(GEOF_INTESECT, geof_intersects)
register_custom_function(GEOF_OVERLAPS, geof_overlaps)
register_custom_function(GEOF_CROSSES, geof_crosses)

import rdflib
if __name__ == "__main__":
    g = rdflib.Graph()


    query = """
    PREFIX ogc: <http://www.ogc.org/>
    PREFIX ine: <http://lod.ine.es/def/vocabulary/>
    PREFIX sdmx-measure: <http://purl.org/linked-data/sdmx/2009/measure#>
    PREFIX sdmx-dimension: <http://purl.org/linked-data/sdmx/2009/dimension#>
    PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
    PREFIX geof: <http://www.opengis.net/def/function/geosparql/>
    PREFIX ex: <http://example.com/>
    PREFIX qb: <http://purl.org/linked-data/cube#>

    SELECT ?w ?t WHERE {
        ?s a ogc:administrativeunit ;
            ogc:nameunit "Galicia" ;
            geo:hasGeometry ?gs .

        ?w a <http://www.ogc.org/agua:Zi_arpsi> ;
            geo:hasGeometry ?gw .

        ?t a ogc:damorweir ;
            geo:hasGeometry ?gt .
        
        FILTER (geof:sfWithin(?gw, ?gs))
        FILTER (geof:sfWithin(?gt, ?gs))
        FILTER (geof:sfDistance(?gw, ?gt) < 5000)
    }
    """

    qres = g.query(query)
    for r in qres:
        print(r)
        pass
