export type RasterCoordinates = [
  [number, number],
  [number, number],
  [number, number],
  [number, number],
];

export interface RasterOverlayData {
  url: string;
  coordinates: RasterCoordinates;
}

export const INTERACTIVE_VECTOR_LAYER_IDS = [
  "vector-fill",
  "vector-line",
  "vector-circle",
  "vector-label",
];
