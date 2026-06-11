import type { FeatureCollection } from "geojson";
import type { RasterOverlayData } from "@/types/map";

export interface SparqlBinding {
  type: "uri" | "literal" | "bnode";
  value: string | number | boolean | null;
  datatype?: string | null;
  language?: string | null;
}

export interface SparqlResults {
  variables: string[];
  rows: Record<string, SparqlBinding>[];
}

export interface ApiResponse {
  status: string;
  logs: string[];
  data: {
    vector?: FeatureCollection;
    raster?: {
      url: string;
      coordinates: number[][];
    };
    results: SparqlResults;
  };
}

export interface MapData {
  vector?: FeatureCollection;
  raster?: RasterOverlayData;
  results: SparqlResults;
}
