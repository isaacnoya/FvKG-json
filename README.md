# FvKG-json

FvKG-json is a research prototype for just-in-time GeoSPARQL virtualization over
JSON-based geospatial web APIs. It combines RML mappings, GeoSPARQL query
evaluation, OGC API Features metadata extraction, semantic annotation utilities,
benchmarking scripts, and a WebGIS frontend for interactive query execution and
map visualization.

The project was developed as part of Isaac Noya Vazquez's master's thesis work
on virtual knowledge graphs for geospatial JSON services.

## Features

- Just-in-time GeoSPARQL query execution over RML mappings.
- Support for vector features and georeferenced raster/WCS results.
- FastAPI backend exposing an execution endpoint for SPARQL and RML input.
- React, Vite, MapLibre frontend for query editing and spatial visualization.
- OGC API Features ontology and RML mapping generation utilities.
- Semantic annotation pipeline for aligning generated ontologies and mappings.
- Benchmarking and plotting scripts for VKG and semantic annotation evaluation.
- Lean proof artifacts for selected formal properties.

## Repository Layout

```text
fvkg_json/              Core Python virtualizer and FastAPI backend
geosparql-frontend/     React/MapLibre WebGIS frontend
OGCmappingGenerator/    OGC API Features ontology, mapping, and annotation tools
eval/                   Evaluation data, queries, mappings, results, and figures
leanProofs/             Lean formalization artifacts
tests/                  Python tests
requirements.txt        Python runtime dependencies
start-fvkg-json.sh      Helper script to start backend and frontend together
```

## Requirements

- Python 3.10 or newer
- Node.js and npm
- A Python environment with the packages listed in `requirements.txt`
- For the frontend map basemap, network access to the public CARTO MapLibre style

The helper script assumes a Conda environment named `oeg` by default. You can
override it with `CONDA_ENV`.

## Installation

Create and activate a Python environment, then install the backend dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Install the frontend dependencies:

```bash
cd geosparql-frontend
npm install
cd ..
```

If you use Conda instead, create or activate your environment and install the
same Python requirements there. The project script uses `CONDA_ENV=oeg` unless
another environment name is provided.

## Running the Application

Start the backend and frontend together from the repository root:

```bash
./start-fvkg-json.sh
```

By default this starts:

- Backend: `http://127.0.0.1:8000`
- Frontend: `http://127.0.0.1:5173`

To use a different Conda environment:

```bash
CONDA_ENV=my-env ./start-fvkg-json.sh
```

To run the services separately, start the backend:

```bash
uvicorn fvkg_json.api:app --reload --port 8000
```

Then start the frontend:

```bash
cd geosparql-frontend
npm run dev
```

The frontend sends execution requests to:

```text
http://localhost:8000/api/execute
```

Set `VITE_API_URL` to point the frontend to a different backend endpoint.

## API

The backend exposes a FastAPI application at `fvkg_json.api:app`.

Main endpoints:

- `GET /health` checks service availability.
- `POST /api/execute` runs a SPARQL query against uploaded RML mapping text.

The execution endpoint expects:

```json
{
  "sparql_query": "SELECT ...",
  "rml_mapping": "@prefix ..."
}
```

The response contains execution logs, tabular SPARQL bindings, and optional
spatial data as GeoJSON vector features or a raster overlay descriptor.

## OGC API Features Mapping Generation

The `OGCmappingGenerator` tools generate an ontology and RML mappings from OGC
API Features endpoints and their queryables metadata.

Inspect available options with:

```bash
python OGCmappingGenerator/OGCmappingGenerator.py --help
```

Semantic annotation utilities are available in:

```bash
python OGCmappingGenerator/semantic_annotation.py --help
```

Some semantic annotation workflows depend on local embedding models, reference
ontologies, or LLM API configuration.

## Evaluation

Run the VKG benchmark with the provided evaluation queries and mappings:

```bash
python eval/vkg/evaluate_vkg.py \
  --queries-dir eval/vkg/queries \
  --mappings-dir eval/vkg/mappings \
  --output-dir eval/vkg/results \
  --repetitions 3 \
  --timeout-seconds 600
```

To validate inputs without executing API calls:

```bash
python eval/vkg/evaluate_vkg.py --validate-only
```

Generate evaluation graphics from existing semantic annotation and VKG results:

```bash
python eval/generate_evaluation_graphics.py
```

The generated figures are written under `eval/graphics/`.

## Tests

Run the Python test suite with:

```bash
pytest
```

Build the frontend with:

```bash
cd geosparql-frontend
npm run build
```

## License

This project is licensed under the Apache License 2.0. See `LICENSE` for
details.
