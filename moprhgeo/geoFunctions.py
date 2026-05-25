from rdflib.plugins.sparql.operators import register_custom_function
from rdflib import URIRef, Literal
from shapely import wkt
from shapely.geometry import shape
from geopy.distance import geodesic
from pyproj import CRS, Geod

GEOF_SFCONTAINS = URIRef(
    "http://www.opengis.net/def/function/geosparql/sfContains"
)
GEOF_DISTANCE = URIRef("http://www.opengis.net/def/function/geosparql/sfDistance")
GEOF_WITHIN = URIRef("http://www.opengis.net/def/function/geosparql/sfWithin")
GEOF_INTESECT = URIRef("http://www.opengis.net/def/function/geosparql/sfIntersects")
GEOF_OVERLAPS = URIRef("http://www.opengis.net/def/function/geosparql/sfOverlaps")
GEOF_CROSSES = URIRef("http://www.opengis.net/def/function/geosparql/sfCrosses")

import json
from shapely.geometry import shape
from shapely import wkt
from rdflib import Literal
    
"""
PyRCC8 1.2.2
"""

def geof_distance(geom1, geom2):
    g1 = parse_geom(geom1)
    g2 = parse_geom(geom2)
    
    p1 = g1.centroid
    p2 = g2.centroid
    

    coord1 = (p1.y, p1.x)
    coord2 = (p2.y, p2.x)
    
    distancia = geodesic(coord1, coord2).meters
    
    return Literal(distancia)

def getBbox(geoms: list):
    if not geoms:
        return None
    fgeom = geoms[0]
    minx, miny, maxx, maxy = get_offset_bounds(fgeom)

    for g in geoms[1:]:
        g_minx, g_miny, g_maxx, g_maxy = get_offset_bounds(g)

        minx = max(minx, g_minx)
        miny = max(miny, g_miny)
        maxx = min(maxx, g_maxx)
        maxy = min(maxy, g_maxy)

        if minx > maxx or miny > maxy:
            return None  # o "" si prefieres string vacío

    return f"{minx},{miny},{maxx},{maxy}"

def parse_geom(g):
    geom, _ = parse_geom_and_crs(g)
    return geom


def parse_geom_and_crs(g):
    g = g.toPython() if type(g) is not str else g
    crs = None

    if isinstance(g, dict):   # GeoJSON dict
        crs = _extract_geojson_crs(g)
        return shape(g), crs

    if isinstance(g, str):

        g = g.strip()

        if g.upper().startswith("SRID="):
            srid, g = g.split(";", 1)
            crs = _parse_crs_value(srid[5:])

        if g.startswith("{"):   # GeoJSON string
            geojson = json.loads(g)
            crs = _extract_geojson_crs(geojson) or crs
            return shape(geojson), crs

        else:                   # WKT
            return wkt.loads(g), crs

    raise ValueError("Unknown geometry format")


def _extract_geojson_crs(geojson):
    crs_obj = geojson.get("crs")
    if not isinstance(crs_obj, dict):
        return None

    if crs_obj.get("type") == "name":
        return _parse_crs_value(crs_obj.get("properties", {}).get("name"))

    return None


def _parse_crs_value(value):
    if not value:
        return None

    try:
        return CRS.from_user_input(value)
    except Exception:
        return None


def geof_sfContains(geom1, geom2):

    g1 = parse_geom(geom1)
    g2 = parse_geom(geom2)

    return Literal(g1.contains(g2))

def geof_within(geom1, geom2):

    g1 = parse_geom(geom1)
    g2 = parse_geom(geom2)

    return Literal(g1.within(g2))   

def geof_intersects(geom1, geom2):

    g1 = parse_geom(geom1)
    g2 = parse_geom(geom2)

    return Literal(g1.intersects(g2))

def geof_overlaps(geom1, geom2):

    g1 = parse_geom(geom1)
    g2 = parse_geom(geom2)

    return Literal(g1.overlaps(g2))

def geof_crosses(geom1, geom2):

    g1 = parse_geom(geom1)
    g2 = parse_geom(geom2)

    return Literal(g1.crosses(g2))

_DEFAULT_GEOD = Geod(ellps="WGS84")

def meters_to_degrees(dist_meters, lat_reference, geod=None):
    """
    Convierte una distancia en metros a desplazamientos en grados (offset_x, offset_y).
    lat_reference: Latitud en la que se encuentra la geometría (en grados decimales).
    """
    lat_reference = max(min(float(lat_reference), 90.0), -90.0)
    dist_meters = float(dist_meters)

    if dist_meters == 0:
        return 0.0, 0.0

    geod = geod or _DEFAULT_GEOD
    lon_east, _, _ = geod.fwd(0.0, lat_reference, 90.0, dist_meters)
    _, lat_north, _ = geod.fwd(0.0, lat_reference, 0.0, dist_meters)

    offset_x = abs(lon_east)
    offset_y = abs(lat_north - lat_reference)

    return offset_x, offset_y

def get_offset_bounds(g_tuple):
    geom_raw, dist_m = g_tuple
    dist_m = float(dist_m) if dist_m else 0
    # Obtenemos los límites originales en grados
    geom, crs = parse_geom_and_crs(geom_raw)
    b_minx, b_miny, b_maxx, b_maxy = geom.bounds
    
    if dist_m == 0:
        return (b_minx, b_miny, b_maxx, b_maxy)

    if crs is not None and crs.is_projected:
        unit_factor = crs.axis_info[0].unit_conversion_factor or 1.0
        delta = dist_m / unit_factor
        return (b_minx - delta, b_miny - delta, b_maxx + delta, b_maxy + delta)

    lat_media = (b_miny + b_maxy) / 2
    geod = crs.get_geod() if crs is not None and crs.is_geographic else _DEFAULT_GEOD
    dx, dy = meters_to_degrees(dist_m, lat_media, geod)

    # Aplicamos el margen (Buffer)
    return (b_minx - dx, b_miny - dy, b_maxx + dx, b_maxy + dy)

from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

def bbox_intersection(a, b):
    min_x = max(a[0], b[0])
    min_y = max(a[1], b[1])
    max_x = min(a[2], b[2])
    max_y = min(a[3], b[3])
    if min_x >= max_x or min_y >= max_y:
        return None
    return (min_x, min_y, max_x, max_y)

def subtract_bbox(bbox, covered):
    overlap = bbox_intersection(bbox, covered)
    if overlap is None:
        return [bbox]

    bx1, by1, bx2, by2 = bbox
    ox1, oy1, ox2, oy2 = overlap
    fragments = []

    if bx1 < ox1:
        fragments.append((bx1, by1, ox1, by2))
    if ox2 < bx2:
        fragments.append((ox2, by1, bx2, by2))
    if by1 < oy1:
        fragments.append((ox1, by1, ox2, oy1))
    if oy2 < by2:
        fragments.append((ox1, oy2, ox2, by2))

    return fragments

def replace_bbox(url, bbox):
    parsed = urlparse(url)
    params = parse_qsl(parsed.query, keep_blank_values=True)
    bbox_value = ",".join(f"{coord:g}" for coord in bbox)
    updated = []
    replaced = False

    for key, value in params:
        if key == "bbox" and not replaced:
            updated.append((key, bbox_value))
            replaced = True
        elif key != "bbox":
            updated.append((key, value))

    if not replaced:
        updated.append(("bbox", bbox_value))

    return urlunparse(parsed._replace(query=urlencode(updated)))

def bbox_contains(container, contained):
    if container is None:
        return True
    if contained is None or len(container) != 4 or len(contained) != 4:
        return False
    return (
        container[0] <= contained[0]
        and container[1] <= contained[1]
        and container[2] >= contained[2]
        and container[3] >= contained[3]
    )

def parse_bbox(value):
    try:
        min_x, min_y, max_x, max_y = (float(part) for part in value.split(','))
    except (TypeError, ValueError):
        return None
    if min_x >= max_x or min_y >= max_y:
        return None
    return (min_x, min_y, max_x, max_y)


def bboxToGeometry(bbox):
    if bbox is None:
        return None
    min_x, min_y, max_x, max_y = bbox
    return Literal(f"POLYGON(({min_x} {min_y}, {min_x} {max_y}, {max_x} {max_y}, {max_x} {min_y}, {min_x} {min_y}))")
