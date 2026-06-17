import type { FeatureCollection } from "geojson";
import { Layer, Source, type LayerProps } from "react-map-gl/maplibre";
import type { RasterOverlayData } from "@/types/map";

const vectorFillLayer: LayerProps = {
  id: "vector-fill",
  type: "fill",
  paint: {
    "fill-color": ["get", "fvkgJsonColor"],
    "fill-opacity": 0.22,
  },
};

const vectorLineLayer: LayerProps = {
  id: "vector-line",
  type: "line",
  paint: {
    "line-color": ["get", "fvkgJsonColor"],
    "line-width": 2.5,
    "line-opacity": 0.95,
  },
};

const vectorCircleLayer: LayerProps = {
  id: "vector-circle",
  type: "circle",
  filter: [
    "any",
    ["==", ["geometry-type"], "Point"],
    ["==", ["geometry-type"], "MultiPoint"],
  ],
  paint: {
    "circle-color": ["get", "fvkgJsonColor"],
    "circle-radius": 6,
    "circle-stroke-color": "#e2e8f0",
    "circle-stroke-width": 1.5,
  },
};

const vectorLabelLayer: LayerProps = {
  id: "vector-label",
  type: "symbol",
  layout: {
    "text-field": ["get", "fvkgJsonLabel"],
    "text-font": ["Open Sans Regular"],
    "text-size": 11,
    "text-offset": [0, 1.2],
    "text-anchor": "top",
  },
  paint: {
    "text-color": "#e2e8f0",
    "text-halo-color": "#071015",
    "text-halo-width": 1.5,
  },
};

interface VectorLayerProps {
  data: FeatureCollection;
  visible?: boolean;
}

export function VectorLayer({ data, visible = true }: VectorLayerProps) {
  if (!visible) return null;

  return (
    <Source data={data} id="vector-data" type="geojson">
      <Layer {...vectorFillLayer} />
      <Layer {...vectorLineLayer} />
      <Layer {...vectorCircleLayer} />
      <Layer {...vectorLabelLayer} />
    </Source>
  );
}

interface RasterOverlayProps {
  data: RasterOverlayData;
  visible?: boolean;
}

export function RasterOverlay({ data, visible = true }: RasterOverlayProps) {
  if (!visible) return null;

  return (
    <Source
      coordinates={data.coordinates}
      id="raster-data"
      type="image"
      url={data.url}
    >
      <Layer
        id="raster-layer"
        paint={{
          "raster-opacity": 0.8,
          "raster-fade-duration": 0,
        }}
        type="raster"
      />
    </Source>
  );
}
