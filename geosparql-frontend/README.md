# MorphGEO Frontend

Dark WebGIS dashboard for authoring SPARQL queries and RML mappings, executing
a just-in-time virtualization pipeline, and visualizing vector and raster
results with MapLibre.

Developed by Isaac Noya Vázquez.

## Run locally

Start the backend and frontend together from the repository root:

```bash
./start-morphgeo.sh
```

Press `Ctrl+C` to stop both services.

To start each service separately, use the commands below.

From the repository root, start the FastAPI backend:

```bash
source /opt/miniconda3/etc/profile.d/conda.sh
conda activate oeg
uvicorn morphgeo.api:app --reload --port 8000
```

In a second terminal, start the frontend:

```bash
cd geosparql-frontend
npm install
npm run dev
```

Create a production build with:

```bash
npm run build
```

## Backend integration

`Execute MorphGEO Query` posts the current editor contents to:

```text
http://localhost:8000/api/execute
```

Set `VITE_API_URL` to override the complete execution endpoint URL. The backend
must allow the frontend origin through CORS when they run on different ports.

The response is rendered as:

- GeoJSON `FeatureCollection` data using fill and line layers
- Georeferenced WCS images using a MapLibre image source

The basemap uses the public CARTO Dark Matter MapLibre style and therefore needs
network access while the app is running.
