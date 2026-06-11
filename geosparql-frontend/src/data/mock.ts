export const DEFAULT_SPARQL = `PREFIX ogc: <http://www.ogc.org/>
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

SELECT ?y ?t WHERE {
    ?y a <http://example.org/ontology/AU_UnidadesAdministrativas> ;
        ogc:nameunit "Santiago de Compostela" ;
        ogc:country "ES" ;
        geo:hasGeometry ?gy .
    ?t a ogc:copernicus_wcs ;
        ogc:coverage "NATURAL-COLOR" ;
        geo:hasGeometry ?gt .
    FILTER(geof:sfContains(?gt, ?gy))
}`;

export const DEFAULT_RML = String.raw`@prefix geo: <http://www.opengis.net/ont/geosparql#> .
@prefix htv: <http://www.w3.org/2011/http#> .
@prefix ogc: <http://www.ogc.org/> .
@prefix rml: <http://w3id.org/rml/> .
@prefix void: <http://rdfs.org/ns/void#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

ogc:administrativeunitTriplesMap2 a rml:TriplesMap ;
    rml:logicalSource ogc:LogicalSource_administrativeunit ;
    rml:predicateObjectMap [ rml:objectMap [ rml:parentTriplesMap ogc:administrativeunitTriplesMap ] ;
            rml:predicate geo:member ] ;
    rml:subjectMap [ rml:class geo:FeatureCollection ;
            rml:constant ogc:administrativeunit_collection ] .

ogc:FuenteAPI_administrativeunit htv:absoluteURI "https://api-features.ign.es/collections/administrativeunit/items?f=json&limit=10000" .

ogc:administrativeunitTriplesMap a rml:TriplesMap ;
    rml:logicalSource ogc:LogicalSource_administrativeunit ;
    rml:predicateObjectMap [ rml:objectMap [ void:filterx "nationallevel=@{1}" ;
                    rml:datatype xsd:string ;
                    rml:reference "properties.nationallevel" ] ;
            rml:predicate ogc:nationallevel ],
        [ rml:objectMap [ void:filterx "codnut2=@{1}" ;
                    rml:datatype xsd:string ;
                    rml:reference "properties.codnut2" ] ;
            rml:predicate ogc:codnut2 ],
        [ rml:objectMap [ void:filterx "nameunit=@{1}" ;
                    rml:datatype xsd:string ;
                    rml:reference "properties.nameunit" ] ;
            rml:predicate ogc:nameunit ],
        [ rml:objectMap [ void:filterx "bbox=@{1}" ;
                    rml:datatype geo:geoJSONLiteral ;
                    rml:reference "geometry" ] ;
            rml:predicate geo:hasGeometry ],
        [ rml:objectMap [ void:filterx "codnut1=@{1}" ;
                    rml:datatype xsd:string ;
                    rml:reference "properties.codnut1" ] ;
            rml:predicate ogc:codnut1 ],
        [ rml:objectMap [ void:filterx "gid=@{1}" ;
                    rml:datatype xsd:integer ;
                    rml:reference "properties.gid" ] ;
            rml:predicate ogc:gid ],
        [ rml:objectMap [ rml:datatype xsd:string ;
                    rml:reference "geometry_name" ] ;
            rml:predicate ogc:geometryName ],
        [ rml:objectMap [ void:filterx "country=@{1}" ;
                    rml:datatype xsd:string ;
                    rml:reference "properties.country" ] ;
            rml:predicate ogc:country ],
        [ rml:objectMap [ void:filterx "nationalcode=@{1}" ;
                    rml:datatype xsd:string ;
                    rml:reference "properties.nationalcode" ] ;
            rml:predicate ogc:nationalcode ],
        [ rml:objectMap [ void:filterx "geometry=@{1}" ;
                    rml:datatype xsd:string ;
                    rml:reference "properties.geometry" ] ;
            rml:predicate <http://geo.linkeddata.es/ontology/hydro-ontology.owl#geometría> ],
        [ rml:objectMap [ void:filterx "nationallevelname=@{1}" ;
                    rml:datatype xsd:string ;
                    rml:reference "properties.nationallevelname" ] ;
            rml:predicate ogc:nationallevelname ],
        [ rml:objectMap [ void:filterx "codnut3=@{1}" ;
                    rml:datatype xsd:string ;
                    rml:reference "properties.codnut3" ] ;
            rml:predicate ogc:codnut3 ] ;
    rml:subjectMap [ rml:class <http://example.org/ontology/AU_UnidadesAdministrativas> ;
            rml:template "https://api-features.ign.es/collections/administrativeunit/items/{id}" ] .

ogc:LogicalSource_administrativeunit a rml:logicalSource ;
    void:nextPage "$.links[?(@.rel==\"next\")].href" ;
    rml:iterator "$.features.*" ;
    rml:referenceFormulation rml:HTTPAPI ;
    rml:source ogc:FuenteAPI_administrativeunit .

@prefix geo: <http://www.opengis.net/ont/geosparql#> .
@prefix htv: <http://www.w3.org/2011/http#> .
@prefix ogc: <http://www.ogc.org/> .
@prefix rml: <http://w3id.org/rml/> .
@prefix void: <http://rdfs.org/ns/void#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

ogc:FuenteAPI_copernicus_wcs htv:absoluteURI "https://sh.dataspace.copernicus.eu/ogc/wcs/9629bdae-70c4-4863-af1b-d007dd102174?SERVICE=WCS&REQUEST=GetCoverage&MAXCC=20&WIDTH=2500&HEIGHT=2500&FORMAT=image/jpeg&SHOWLOGO=false&CRS=EPSG:4326" .

ogc:copernicusWcsTriplesMap a rml:TriplesMap ;
    rml:logicalSource ogc:LogicalSourceCopernicusWcs ;
    rml:predicateObjectMap
        [ rml:objectMap [ void:filterx "BBOX=@{1}" ;
                    rml:datatype geo:geoJSONLiteral ;
                    rml:constant "Cannot be unbounded" ] ;
            rml:predicate geo:hasBoundingBox ],
        [ rml:objectMap [ void:filterx "BBOX=@{1}" ;
                    rml:datatype geo:geoJSONLiteral ;
                    rml:constant "Cannot be unbounded" ] ;
            rml:predicate geo:hasGeometry ],
        [ rml:objectMap [ void:filterx "COVERAGE=@{1}" ;
                    rml:datatype xsd:string ;
                    rml:constant "Cannot be unbounded" ] ;
            rml:predicate ogc:coverage ],
        [ rml:objectMap [ void:filterx "TIME=@{1}" ;
                    rml:datatype xsd:string ;
                    rml:constant "Cannot be unbounded" ] ;
            rml:predicate ogc:time ] ;
    rml:subjectMap [ rml:class ogc:copernicus_wcs ;
            rml:template "https://sh.dataspace.copernicus.eu/ogc/wcs/9629bdae-70c4-4863-af1b-d007dd102174?SERVICE=WCS&REQUEST=GetCoverage&MAXCC=20&WIDTH=2500&HEIGHT=2500&FORMAT=image/jpeg&SHOWLOGO=false" ] .

ogc:LogicalSourceCopernicusWcs a rml:logicalSource ;
    rml:referenceFormulation rml:CoverageForm ;
    rml:source ogc:FuenteAPI_copernicus_wcs .
`;
