import rdflib
import re
from rdflib.plugins.sparql.sparql import QueryContext

RML_NAMESPACE = 'http://w3id.org/rml/'
RML_SUBJECT_MAP = f'{RML_NAMESPACE}subjectMap'
RML_PREDICATE_MAP = f'{RML_NAMESPACE}predicateMap'
RML_OBJECT_MAP = f'{RML_NAMESPACE}objectMap'
RML_SUBJECT_SHORTCUT = f'{RML_NAMESPACE}subject'
RML_PREDICATE_SHORTCUT = f'{RML_NAMESPACE}predicate'
RML_OBJECT_SHORTCUT = f'{RML_NAMESPACE}object'
RML_PREDICATE_OBJECT_MAP = f'{RML_NAMESPACE}predicateObjectMap'
RML_CLASS = f'{RML_NAMESPACE}class'
RML_PARENT_TRIPLES_MAP = f'{RML_NAMESPACE}parentTriplesMap'
RML_TERM_TYPE = f'{RML_NAMESPACE}termType'
RML_IRI = f'{RML_NAMESPACE}IRI'
RML_LITERAL = f'{RML_NAMESPACE}Literal'
RML_BLANK_NODE = f'{RML_NAMESPACE}BlankNode'

from collections import defaultdict
geoBindings = defaultdict(list)



class Reference(rdflib.term.Literal):
    def __init__(self, value, *args, **kwargs):
            super().__init__()    

class Template(rdflib.term.Literal):
    def __init__(self, value, *args, **kwargs):
            super().__init__()    

from urllib.parse import urlparse
class VirtualMapping:
    def __init__(
        self,
        subject=None,
        predicate=None,
        objec=None,
        reference=None,
        source=None,
        iterator=None,
        nextPage=None,
        filterx=None,
        projectx=None,
        limit=None,
        nElements=None,
        datatype=None,
        language=None,
        term_type=None,
        coverage=False,
    ):
        if subject != None:
            self.s = Reference(subject) if isinstance(subject, rdflib.term.Literal) else subject
        if predicate != None:
            self.p = predicate
        if objec != None and reference == None:
            self.o = objec
        elif reference != None and objec == None:
            self.o = Reference(reference) 
        else:
            self.o = None

        self.source = source
        self.coverage = coverage   
        
        self.iterator = iterator
        self.nextPage = nextPage
        self.filterx = filterx
        self.projectx = projectx
        self.limit = limit
        self.nElements = nElements
        self.datatype = datatype or getattr(objec, "datatype", None)
        self.language = language or getattr(objec, "language", None)
        self.term_type = term_type


    def setParentTriplesMapInfo(self, childJoinCond=None, parentJoinCond=None, parentURL=None, parentIterator=None):
        if parentURL != self.source:
            return 
        self.o = Reference(self.o)
        self.childJoinCond = childJoinCond
        self.parentJoinCond = parentJoinCond
        self.parentIterator = parentIterator

    def setBindingVariables(self, bs, bp, bo):
        bs = bs 
        bp = bp 
        bo = bo 
        self.bindingVariables = (bs, bp, bo)
    
    def safeUnifySourceMapping(self, vm):
        def obtener_url_base(url):
            parsed_url = urlparse(url)
            # Reconstruimos solo con el esquema (http/https) y el netloc (dominio + puerto)
            return f"{parsed_url.scheme}://{parsed_url.netloc}"
        if obtener_url_base(self.source) != obtener_url_base(vm.source):
            return False

        
        if self.bindingVariables[0] != vm.bindingVariables[0]:  #Acting over the same subject variable
            return False
        return True

    def saturateLiteral(self, literal, iterator):
        """
        reciba un literal flow "https://api-features.idee.es/collections/railwaystationnode/items/{id}" y un iterator flow "$.features.*" y me devuelva "https://api-features.idee.es/collections/railwaystationnode/items/{$.features.*.id}"
        """
        literal = str(literal.toPython()) if hasattr(literal, 'toPython') else str(literal)
        if "{" in literal:
            patron = r'\{([^}]+)\}'
        
            def reemplazo(match):
                variable_original = match.group(1) 
                return f"{{{iterator}.{variable_original}}}"
                
            resultado = re.sub(patron, reemplazo, literal)
            return rdflib.term.Literal(resultado)
        else:
            return rdflib.term.Literal(f"{iterator}.{literal}")
    def __hash__(self):
        return hash((
            self.s,
            self.p,
            self.o,
            getattr(self, "source", None),
            getattr(self, "datatype", None),
            getattr(self, "language", None),
            getattr(self, "term_type", None),
            ))
    def __eq__(self, other):
        if not isinstance(other, VirtualMapping):
            return False
        return (
            getattr(self, "s", None) == getattr(other, "s", None) and
            getattr(self, "p", None) == getattr(other, "p", None) and
            getattr(self, "o", None) == getattr(other, "o", None) and
            getattr(self, "source", None) == getattr(other, "source", None) and
            getattr(self, "datatype", None) == getattr(other, "datatype", None) and
            getattr(self, "language", None) == getattr(other, "language", None) and
            getattr(self, "term_type", None) == getattr(other, "term_type", None)
            #and getattr(self, "bindingVariables", None) == getattr(other, "bindingVariables", None)
        )
        
class TriplePattern:
    def __init__(self, s, p, o):
        self.s=s 
        self.p=p
        self.o=o


class MappingContext(QueryContext):
    def __init__(self, *args, mappings=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.mappings = mappings or []

    def clone(self, bindings=None):
        r = MappingContext(
            self._dataset if self._dataset is not None else self.graph,
            bindings or self.bindings,
            initBindings=self.initBindings,
            mappings=list(self.mappings),  
        )
        r.prologue = self.prologue
        r.graph = self.graph
        r.bnodes = self.bnodes
        return r


    
