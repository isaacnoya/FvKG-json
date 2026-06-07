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
