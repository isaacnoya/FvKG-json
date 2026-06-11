import copy
import re
from collections import defaultdict
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import pandas as pd
import rdflib
import requests
from jsonpath import JSONPath
from rdflib import Literal, URIRef, Variable
from rdflib.plugins.sparql.sparql import (
    AlreadyBound,
    QueryContext,
)

try:
    from .classes import *
    from .geoFunctions import getBbox, bbox_contains, bboxToGeometry
    from .mappings import get_compatible_mappings
    from .utils import (
        getBaseURL,
        merge_urls,
        normalize_hierarchical_data,
    )
except ImportError:
    from classes import *
    from geoFunctions import getBbox, bbox_contains, bboxToGeometry
    from mappings import get_compatible_mappings
    from utils import (
        getBaseURL,
        merge_urls,
        normalize_hierarchical_data,
    )

def yield_flatten(items):
    for item in items:
        if isinstance(item, set):
            yield from yield_flatten(item)
        else:
            yield item

def getMappingsFromBGP(ctx: MappingContext, tps: list[TriplePattern], mappings: list[VirtualMapping]):
    if not tps:
        yield from yield_flatten(ctx.mappings)
        #yield ctx.mappings
        return

    tp = tps[0]
    s, p, o = tp.s, tp.p, tp.o
    _s = ctx[s] 
    _p = ctx[p] 
    _o = ctx[o] 

    _tp = TriplePattern(_s, _p, _o) 
    c_mappings = get_compatible_mappings(_tp, mappings) 
    for m in c_mappings:
        m = copy.copy(m)
        ss = m.s
        sp = m.p
        so = m.o
    
        if None in (_s, _p, _o):
            c = ctx.push()
        else:
            c = ctx

        try:
            if _p is None:
                c[p] = sp
        except AlreadyBound:
            continue
    
        try:
            if _o is None:
                c[o] = so
        except AlreadyBound:
            continue
        
        if _s is None:
            c[s] = ss 

        m.setBindingVariables(s, p , o)
        params = {}

        # !!!! esto igual lo podria hacer al parsear los mappings y queda mas limpio !!!!
        if (type(_tp.o) is Literal or type(tp.o) is Variable) and m.filterx is not None and _p is not None:
            param = m.filterx.replace("@{1}", str(tp.o)) if type(_tp.o) is Literal else m.filterx.replace("@{1}", "variable("+str(tp.o)+")")
            key, value = param.split('=')
            params = params | {key: value}
            req = requests.Request('GET', m.source, params=params).prepare()
            m.source=req.url


        """
        for vm in ctx.mappings:
            if m.safeUnifySourceMapping(vm):
                req = requests.Request('GET', vm.source, params=params).prepare()
                vm.source=req.url
        """
        c.mappings.append(m) 

        for res in getMappingsFromBGP(c, tps[1:], mappings):
            yield res

    return None


def getMappingsFromBGPWithoutBindings(
    ctx: MappingContext,
    tps: list[TriplePattern],
    mappings: list[VirtualMapping],
):
    """Select compatible mappings without adding query bindings to their URLs."""
    if not tps:
        yield from yield_flatten(ctx.mappings)
        return

    tp = tps[0]
    s, p, o = tp.s, tp.p, tp.o
    _s = ctx[s]
    _p = ctx[p]
    _o = ctx[o]

    compatible_mappings = get_compatible_mappings(
        TriplePattern(_s, _p, _o),
        mappings,
    )
    for mapping in compatible_mappings:
        mapping = copy.copy(mapping)

        child_ctx = ctx.push() if None in (_s, _p, _o) else ctx

        try:
            if _p is None:
                child_ctx[p] = mapping.p
        except AlreadyBound:
            continue

        try:
            if _o is None:
                child_ctx[o] = mapping.o
        except AlreadyBound:
            continue

        if _s is None:
            child_ctx[s] = mapping.s

        mapping.setBindingVariables(s, p, o)
        child_ctx.mappings.append(mapping)

        yield from getMappingsFromBGPWithoutBindings(
            child_ctx,
            tps[1:],
            mappings,
        )


def evalVirtualBGP(ctx: QueryContext, bgp: list[TriplePattern],  mappingGroups: dict, triggers, queriesMade):
    if not bgp:
        yield ctx.solution()
        return
    
    tp = bgp[0]
    s, p, o = tp.s, tp.p, tp.o

    _s = ctx[s] 
    _p = ctx[p] 
    _o = ctx[o] 

    materializeCompatibleMappingGroup(ctx, tp, mappingGroups, triggers, queriesMade)    
    for ss, sp, so in ctx.graph.triples((_s, _p, _o)):  # type: ignore[union-attr, arg-type]
        if None in (_s, _p, _o):
            c = ctx.push()  
        else:
            c = ctx

        if _s is None:
            # type error: Incompatible types in assignment (expression has type "Union[Node, Any]", target has type "Identifier")
            c[s] = ss  # type: ignore[assignment]

        try:
            if _p is None:
                # type error: Incompatible types in assignment (expression has type "Union[Node, Any]", target has type "Identifier")
                c[p] = sp  # type: ignore[assignment]
        except AlreadyBound:
            continue

        try:
            if _o is None:
                # type error: Incompatible types in assignment (expression has type "Union[Node, Any]", target has type "Identifier")
                c[o] = so  # type: ignore[assignment]
        except AlreadyBound:
            continue

        for x in evalVirtualBGP(c, bgp[1:], mappingGroups, triggers, queriesMade):
            yield x

    return None


def evalVirtualBGPWithoutBindings(
    ctx: QueryContext,
    bgp: list[TriplePattern],
    mappingGroups: dict,
    triggers,
    queriesMade,
):
    """Evaluate a BGP using the materializer that never injects URL bindings."""
    if not bgp:
        yield ctx.solution()
        return

    tp = bgp[0]
    s, p, o = tp.s, tp.p, tp.o
    _s = ctx[s]
    _p = ctx[p]
    _o = ctx[o]

    materializeCompatibleMappingGroupWithoutBindings(
        ctx,
        tp,
        mappingGroups,
        triggers,
        queriesMade,
    )
    for ss, sp, so in ctx.graph.triples((_s, _p, _o)):
        child_ctx = ctx.push() if None in (_s, _p, _o) else ctx

        if _s is None:
            child_ctx[s] = ss

        try:
            if _p is None:
                child_ctx[p] = sp
        except AlreadyBound:
            continue

        try:
            if _o is None:
                child_ctx[o] = so
        except AlreadyBound:
            continue

        yield from evalVirtualBGPWithoutBindings(
            child_ctx,
            bgp[1:],
            mappingGroups,
            triggers,
            queriesMade,
        )


def isCompatibleMappingGroup(tp, mappings):
    for m in mappings:
        ms, mp, mo = m.bindingVariables
        if tp.s == ms and tp.p == mp and tp.o == mo:
            return True
    return False

try:
    from .classes import geoBindings
except ImportError:
    from classes import geoBindings

def injectBindings(ctx, url):
    url_parts = list(urlparse(url))
    query_params = parse_qsl(url_parts[4]) 
    
    nuevos_params = []
    
    for key, value in query_params:
        match = re.search(r'variable\((\w+)\)', value)        
        if match:
            var_name = match.group(1)
            valor_ctx = ctx[Variable(var_name)]
            geoBindings_value = []
            for i in geoBindings.get(Variable(var_name), []):
                if isinstance(i, Variable):
                    v, _, distance = i.partition(":-:") if ":-:" in i else (i, None, 0)
                    geoBindings_value.append((ctx[Variable(v)], distance)) if ctx[Variable(v)] is not None else None
                elif isinstance(i, rdflib.term.Literal):
                    geoBindings_value.append((i, 0))
            
            if valor_ctx is not None:
                nuevo_valor = value.replace(match.group(0), str(valor_ctx)) 
                nuevos_params.append((key, nuevo_valor))
            elif len(geoBindings_value) and all(v[0] is not None for v in geoBindings_value):
                newbbox = getBbox(geoBindings_value)
                if newbbox is None: # bbox intersection was empty, no need to query as it will not return any result
                    return None
                nuevo_valor = value.replace(match.group(0), str(newbbox)) 
                nuevos_params.append((key, nuevo_valor))
        else:
            nuevos_params.append((key, value))

    url_parts[4] = urlencode(nuevos_params)
    return urlunparse(url_parts)

def has_filter(ref: str) -> bool:
        return '[?(' in ref

def _split_bbox_url(url):
    url_parts = list(urlparse(url))
    query_params = parse_qsl(url_parts[4], keep_blank_values=True)
    bbox = None
    filtered_params = []

    for key, value in query_params:
        if key == "bbox" and bbox is None:
            try:
                bbox = tuple(map(float, value.split(",")))
            except (TypeError, ValueError):
                bbox = None
            continue
        filtered_params.append((key, value))

    url_parts[4] = urlencode(filtered_params)
    return urlunparse(url_parts), bbox

def querieMade(queriesMade, url_next, suj):
    normalized_url, bbox = _split_bbox_url(url_next)

    for url, previous_bbox, sujeto in queriesMade:
        if url == normalized_url and sujeto == suj and bbox_contains(previous_bbox, bbox):
            return True
    
    queriesMade.add((normalized_url, bbox, suj))
    return False

def ogcCoverageMaterializer(ctx, mappings, url_next):
    url_parts = list(urlparse(url_next))
    query_params = parse_qsl(url_parts[4], keep_blank_values=True)
    updated_params = []
    bbox_values = None
    for key, value in query_params:
        if key.lower() == "bbox":
            bbox_values = value.split(",")
            if len(bbox_values) == 4:
                try:
                    min_x, min_y, max_x, max_y = map(float, bbox_values)
                    if min_x == max_x and min_y == max_y:
                        offset = 0.01
                        bbox_values = [
                            str(min_x - offset),
                            str(min_y - offset),
                            str(max_x + offset),
                            str(max_y + offset),
                        ]
                except ValueError:
                    pass
                value = ",".join((bbox_values[1], bbox_values[0], bbox_values[3], bbox_values[2]))
        updated_params.append((key, value))

    url_parts[4] = urlencode(updated_params)
    url_next = urlunparse(url_parts)

    for m in mappings:
        #print(url_next)
        if m.p == URIRef("http://www.opengis.net/ont/geosparql#hasGeometry") and isinstance(m.bindingVariables[2], Variable):
            ctx.graph.add((URIRef(url_next), URIRef(m.p), bboxToGeometry(bbox_values))) if bbox_values else None
        else:
            ctx.graph.add((URIRef(url_next), URIRef(m.p), m.bindingVariables[2])) 
    return ctx

def materializeGroup(ctx, mappings, suj, queriesMade):
    url_next = merge_urls([m.source for m in mappings])
    url_next = injectBindings(ctx, url_next)
    
    if url_next is None or querieMade(queriesMade, url_next, suj):
        return ctx

    if mappings[0].coverage: 
        return ogcCoverageMaterializer(ctx, mappings, url_next)

    while url_next:
        try:
            print(url_next)
            r = requests.get(url_next).json()
        except:
            r = {} 
        #Podemos usar mappings[0] porque todos los mappings comparten sujeto?
        next = JSONPath(mappings[0].nextPage).parse(r) if mappings[0].nextPage != None else []

        url_next = next[0] if len(next) else False
                
        if isinstance(mappings[0].s, Reference):
            template = mappings[0].s
            refs = re.findall(r"\{(.*?)\}", template)
            values_per_ref = [JSONPath(mappings[0].iterator + "." + ref).parse(r) for ref in refs]
            r_subj = []
            for vals in zip(*values_per_ref):  # empareja 1 a 1
                result = template
                for ref, val in zip(refs, vals):
                    result = result.replace(f"{{{ref}}}", str(val))
                r_subj.append(result)
        else:
            r_subj=mappings[0].s
            refs = []

        for m in mappings: 
            if isinstance(m.o, Reference) and not has_filter(m.o) and not getattr(m, "parentIterator", None):
                r_obj = JSONPath(m.iterator + "." + m.o).parse(r) 
                r_subj = [mappings[0].s for _ in r_obj] if isinstance(mappings[0].s, URIRef) else r_subj # In case subject is a constant, r_subj and r_obj must be same size in order to zip correctly
                for sujeto, objeto in zip(r_subj, r_obj):
                    ctx.graph.add((URIRef(sujeto), URIRef(m.p), Literal(objeto)))
            elif isinstance(m.o, Reference) and has_filter(m.o) and not getattr(m, "parentIterator", None):    
                join_key = refs[0]
                entries = JSONPath(m.iterator).parse(r)
                lookup_data = {item.get(join_key): item for item in entries if item.get(join_key)}
                column_value = []
                for key_value in values_per_ref[0]:
                    match = lookup_data.get(key_value)
                    if match:
                        res = JSONPath(f"$.{m.o}").parse(match)
                        ctx.graph.add((URIRef(template.replace(f"{{{refs[0]}}}", str(key_value))), URIRef(m.p), Literal(res[0]))) if res else None
                    else:
                        column_value.append(None)
            elif isinstance(m.o, Reference) and getattr(m, "parentIterator", None): #parentTripleMaps logic adhoc to use case
                # if subject is a constant it might not work
                refObj = re.findall(r"\{(.*?)\}", m.o)[0]
                references = refs + [refObj]

                jsonpath_expression = m.iterator + '.('
                for reference in references: 
                    jsonpath_expression += reference.split('.')[0] + ','
                jsonpath_expression = jsonpath_expression[:-1] + ')'

                jsonpath_result = JSONPath(jsonpath_expression).parse(r)
                json_df = pd.json_normalize([json_object for json_object in normalize_hierarchical_data(jsonpath_result) if
                                 None not in json_object.values()])

                json_df = json_df[[c.replace('*.', '') for c in references if c.replace('*.', '') in json_df.columns]]

                for index, row in json_df.iterrows():
                    subj = m.s
                    for reference in refs:
                        subj = subj.replace(f"{{{reference}}}", str(row[reference.replace('*.', '')]))
                    ctx.graph.add((URIRef(subj), URIRef(m.p), URIRef(m.o.replace(f"{{{refObj}}}", str(row[refObj.replace('*.', '')])))))            
            elif isinstance(m.o, URIRef): # Object is a constant URI, not a Reference
                if isinstance(mappings[0].s, Reference):
                    for sujeto in r_subj:
                        ctx.graph.add((URIRef(sujeto), URIRef(m.p), URIRef(m.o)))
                else: 
                    ctx.graph.add((URIRef(r_subj), URIRef(m.p), URIRef(m.o)))
    return ctx


def materializeGroupWithoutBindings(ctx, mappings, suj, queriesMade):
    """Materialize a mapping group without modifying its URL from query bindings."""
    url_next = merge_urls([mapping.source for mapping in mappings])

    if url_next is None or querieMade(queriesMade, url_next, suj):
        return ctx

    if mappings[0].coverage:
        return ogcCoverageMaterializer(ctx, mappings, url_next)

    while url_next:
        try:
            print(url_next)
            response = requests.get(url_next).json()
        except Exception:
            response = {}

        next_pages = (
            JSONPath(mappings[0].nextPage).parse(response)
            if mappings[0].nextPage is not None
            else []
        )
        url_next = next_pages[0] if next_pages else False

        if isinstance(mappings[0].s, Reference):
            template = mappings[0].s
            refs = re.findall(r"\{(.*?)\}", template)
            values_per_ref = [
                JSONPath(mappings[0].iterator + "." + ref).parse(response)
                for ref in refs
            ]
            response_subjects = []
            for values in zip(*values_per_ref):
                subject = template
                for ref, value in zip(refs, values):
                    subject = subject.replace(f"{{{ref}}}", str(value))
                response_subjects.append(subject)
        else:
            response_subjects = mappings[0].s
            refs = []

        for mapping in mappings:
            if (
                isinstance(mapping.o, Reference)
                and not has_filter(mapping.o)
                and not getattr(mapping, "parentIterator", None)
            ):
                response_objects = JSONPath(
                    mapping.iterator + "." + mapping.o
                ).parse(response)
                if isinstance(mappings[0].s, URIRef):
                    response_subjects = [
                        mappings[0].s
                        for _ in response_objects
                    ]
                for subject, obj in zip(response_subjects, response_objects):
                    ctx.graph.add((
                        URIRef(subject),
                        URIRef(mapping.p),
                        Literal(obj),
                    ))
            elif (
                isinstance(mapping.o, Reference)
                and has_filter(mapping.o)
                and not getattr(mapping, "parentIterator", None)
            ):
                join_key = refs[0]
                entries = JSONPath(mapping.iterator).parse(response)
                lookup_data = {
                    item.get(join_key): item
                    for item in entries
                    if item.get(join_key)
                }
                for key_value in values_per_ref[0]:
                    match = lookup_data.get(key_value)
                    if not match:
                        continue
                    result = JSONPath(f"$.{mapping.o}").parse(match)
                    if result:
                        ctx.graph.add((
                            URIRef(
                                template.replace(
                                    f"{{{refs[0]}}}",
                                    str(key_value),
                                )
                            ),
                            URIRef(mapping.p),
                            Literal(result[0]),
                        ))
            elif (
                isinstance(mapping.o, Reference)
                and getattr(mapping, "parentIterator", None)
            ):
                object_ref = re.findall(r"\{(.*?)\}", mapping.o)[0]
                references = refs + [object_ref]
                jsonpath_expression = (
                    mapping.iterator
                    + ".("
                    + ",".join(
                        reference.split(".")[0]
                        for reference in references
                    )
                    + ")"
                )
                jsonpath_result = JSONPath(jsonpath_expression).parse(response)
                json_df = pd.json_normalize([
                    json_object
                    for json_object in normalize_hierarchical_data(
                        jsonpath_result
                    )
                    if None not in json_object.values()
                ])
                columns = [
                    reference.replace("*.", "")
                    for reference in references
                    if reference.replace("*.", "") in json_df.columns
                ]
                json_df = json_df[columns]

                for _, row in json_df.iterrows():
                    subject = mapping.s
                    for reference in refs:
                        column = reference.replace("*.", "")
                        subject = subject.replace(
                            f"{{{reference}}}",
                            str(row[column]),
                        )
                    object_column = object_ref.replace("*.", "")
                    ctx.graph.add((
                        URIRef(subject),
                        URIRef(mapping.p),
                        URIRef(
                            mapping.o.replace(
                                f"{{{object_ref}}}",
                                str(row[object_column]),
                            )
                        ),
                    ))
            elif isinstance(mapping.o, URIRef):
                if isinstance(mappings[0].s, Reference):
                    for subject in response_subjects:
                        ctx.graph.add((
                            URIRef(subject),
                            URIRef(mapping.p),
                            URIRef(mapping.o),
                        ))
                else:
                    ctx.graph.add((
                        URIRef(response_subjects),
                        URIRef(mapping.p),
                        URIRef(mapping.o),
                    ))
    return ctx


def materializeCompatibleMappingGroup(ctx, tp, mappingGroups, triggers, queriesMade):
    for key in list(mappingGroups.keys()):
        mappings = mappingGroups[key]

        # Only materialize when tp is the trigger tp for the mappingGroup (the firts tp)
        if isCompatibleMappingGroup(tp, mappings) and (triggers[key] == tp or triggers[key] is None):
            triggers[key] = tp
            ctx = materializeGroup(ctx, mappings, key[1], queriesMade)

    return ctx, mappingGroups


def materializeCompatibleMappingGroupWithoutBindings(
    ctx,
    tp,
    mappingGroups,
    triggers,
    queriesMade,
):
    for key in list(mappingGroups.keys()):
        mappings = mappingGroups[key]
        if (
            isCompatibleMappingGroup(tp, mappings)
            and (triggers[key] == tp or triggers[key] is None)
        ):
            triggers[key] = tp
            ctx = materializeGroupWithoutBindings(
                ctx,
                mappings,
                key[1],
                queriesMade,
            )

    return ctx, mappingGroups


def getMappingGroups(mappings: set[VirtualMapping]) -> dict:
    groups = defaultdict(list)

    for m in mappings:
        key = (
            getBaseURL(m.source),
            m.bindingVariables[0], #variable sujeto
            m.s
        )
        groups[key].append(m)
    
    return groups


def orderTriplesStatic(ctx, triples) -> list:
    grupos = {}
    for t in triples:
        s = t[0]
        grupos.setdefault(s, []).append(t)

    def score_grupo(triples_grupo):
        score = 0
        for t in triples_grupo:
            obj = t[2]
            if type(obj) is rdflib.term.Literal:
                score += 10
            geoBind = geoBindings.get(obj, None)
            if geoBind is not None:
                score += 20
                if any(isinstance(x, rdflib.term.Literal) for x in geoBind):
                    score += 10
        return score

    grupos_con_score = [
        (sujeto, triples_grupo, score_grupo(triples_grupo))
        for sujeto, triples_grupo in grupos.items()
    ]

    grupos_ordenados = sorted(
        grupos_con_score,
        key=lambda item: item[2],
        reverse=True
    )

    resultado = []
    for sujeto, triples_grupo, _ in grupos_ordenados:
        resultado.extend(triples_grupo)

    return resultado, grupos_con_score
