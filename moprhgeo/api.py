from __future__ import annotations

import io
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import parse_qs, urlparse

import rdflib
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from rdflib import BNode, Literal, URIRef
from shapely.geometry import mapping as geometry_mapping

from . import sparql_virtualizer
from .classes import geoBindings
from .geoFunctions import parse_geom
from .mappings import getMappings

GEO_HAS_GEOMETRY = URIRef("http://www.opengis.net/ont/geosparql#hasGeometry")
EXECUTION_LOCK = Lock()


class ExecuteRequest(BaseModel):
    sparql_query: str = Field(min_length=1)
    rml_mapping: str = Field(min_length=1)


class RasterResult(BaseModel):
    url: str
    coordinates: list[list[float]]


class SpatialData(BaseModel):
    vector: dict[str, Any] | None = None
    raster: RasterResult | None = None


class ExecuteResponse(BaseModel):
    status: str
    logs: list[str]
    data: SpatialData


app = FastAPI(
    title="MorphGEO",
    description="GeoSPARQL virtualization endpoint by Isaac Noya Vázquez.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _load_uploaded_mappings(mapping_text: str):
    mapping_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".ttl",
            encoding="utf-8",
            delete=False,
        ) as mapping_file:
            mapping_file.write(mapping_text)
            mapping_path = Path(mapping_file.name)

        mappings = getMappings(mapping_path)
        if not mappings:
            raise ValueError("The uploaded RML text contains no usable mappings.")
        return mappings
    finally:
        if mapping_path is not None:
            mapping_path.unlink(missing_ok=True)


def _term_value(term: rdflib.term.Node) -> Any:
    if isinstance(term, Literal):
        value = term.toPython()
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)
    return str(term)


def _property_name(predicate: rdflib.term.Node) -> str:
    value = str(predicate)
    return value.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def _is_wcs_url(value: str) -> bool:
    parsed = urlparse(value)
    params = {key.lower(): values for key, values in parse_qs(parsed.query).items()}
    service = params.get("service", [""])[0].lower()
    request = params.get("request", [""])[0].lower()
    return service == "wcs" or request == "getcoverage"


def _raster_from_subject(
    graph: rdflib.Graph,
    subject: rdflib.term.Node,
) -> RasterResult | None:
    url = str(subject)
    if not _is_wcs_url(url):
        return None

    geometry_value = graph.value(subject, GEO_HAS_GEOMETRY)
    if geometry_value is None:
        return None

    geometry = parse_geom(geometry_value)
    min_x, min_y, max_x, max_y = geometry.bounds
    return RasterResult(
        url=url,
        coordinates=[
            [min_x, max_y],
            [max_x, max_y],
            [max_x, min_y],
            [min_x, min_y],
        ],
    )


def _feature_from_subject(
    graph: rdflib.Graph,
    subject: rdflib.term.Node,
) -> dict[str, Any] | None:
    geometry_value = graph.value(subject, GEO_HAS_GEOMETRY)
    if geometry_value is None:
        return None

    geometry = parse_geom(geometry_value)
    properties: dict[str, Any] = {"id": str(subject)}
    for predicate, obj in graph.predicate_objects(subject):
        if predicate == GEO_HAS_GEOMETRY:
            continue
        key = _property_name(predicate)
        value = _term_value(obj)
        if key in properties:
            current = properties[key]
            properties[key] = current + [value] if isinstance(current, list) else [current, value]
        else:
            properties[key] = value

    return {
        "type": "Feature",
        "id": str(subject),
        "properties": properties,
        "geometry": geometry_mapping(geometry),
    }


def _spatial_data(
    graph: rdflib.Graph,
    rows: list[dict[str, rdflib.term.Node]],
) -> SpatialData:
    selected_subjects = {
        value
        for row in rows
        for value in row.values()
        if isinstance(value, (URIRef, BNode))
    }
    geometry_subjects = set(graph.subjects(GEO_HAS_GEOMETRY, None))
    candidate_subjects = selected_subjects & geometry_subjects
    if not candidate_subjects:
        candidate_subjects = geometry_subjects

    features: list[dict[str, Any]] = []
    raster: RasterResult | None = None

    for subject in candidate_subjects:
        subject_raster = _raster_from_subject(graph, subject)
        if subject_raster is not None:
            raster = raster or subject_raster
            continue

        feature = _feature_from_subject(graph, subject)
        if feature is not None:
            features.append(feature)

    vector = (
        {
            "type": "FeatureCollection",
            "features": features,
        }
        if features
        else None
    )
    return SpatialData(vector=vector, raster=raster)


def _execute(request: ExecuteRequest) -> ExecuteResponse:
    logs = [
        "[INFO] Parsing uploaded RML mappings.",
        "[INFO] Executing the GeoSPARQL query.",
    ]
    uploaded_mappings = _load_uploaded_mappings(request.rml_mapping)
    graph = rdflib.Graph()
    output = io.StringIO()

    with EXECUTION_LOCK:
        previous_mappings = sparql_virtualizer.mappings
        sparql_virtualizer.mappings = uploaded_mappings
        geoBindings.clear()
        try:
            with redirect_stdout(output):
                result = graph.query(request.sparql_query)
                rows = [dict(row.asdict()) for row in result]
        finally:
            sparql_virtualizer.mappings = previous_mappings
            geoBindings.clear()

    engine_logs = [
        f"[INFO] Source request: {line}"
        for line in output.getvalue().splitlines()
        if line.strip()
    ]
    logs.extend(engine_logs)
    logs.append(f"[SUCCESS] Query returned {len(rows)} result row(s).")

    return ExecuteResponse(
        status="success",
        logs=logs,
        data=_spatial_data(graph, rows),
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/execute", response_model=ExecuteResponse)
def execute(request: ExecuteRequest) -> ExecuteResponse:
    try:
        return _execute(request)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
