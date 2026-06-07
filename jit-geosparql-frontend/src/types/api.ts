import type { FeatureCollection } from "geojson";
import type { RasterOverlayData } from "@/types/map";

export interface ApiResponse {
  status: string;
  logs: string[];
  data: {
    vector?: FeatureCollection;
    raster?: {
      url: string;
      coordinates: number[][];
    };
  };
}

export interface MapData {
  vector?: FeatureCollection;
  raster?: RasterOverlayData;
}
