import type { FeatureCollection } from "geojson";
import { Layer, Source, type LayerProps } from "react-map-gl/maplibre";
import type { RasterOverlayData } from "@/types/map";

const vectorFillLayer: LayerProps = {
  id: "vector-fill",
  type: "fill",
  paint: {
    "fill-color": "#22d3ee",
    "fill-opacity": 0.16,
  },
};

const vectorLineLayer: LayerProps = {
  id: "vector-line",
  type: "line",
  paint: {
    "line-color": "#67e8f9",
    "line-width": 2.5,
    "line-opacity": 0.95,
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
