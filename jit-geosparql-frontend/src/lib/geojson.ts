import type { FeatureCollection } from "geojson";

export type MapBounds = [[number, number], [number, number]];

export function getGeoJsonBounds(
  featureCollection: FeatureCollection,
): MapBounds | null {
  let west = Number.POSITIVE_INFINITY;
  let south = Number.POSITIVE_INFINITY;
  let east = Number.NEGATIVE_INFINITY;
  let north = Number.NEGATIVE_INFINITY;

  const visitCoordinates = (value: unknown) => {
    if (!Array.isArray(value)) return;

    if (
      value.length >= 2 &&
      typeof value[0] === "number" &&
      typeof value[1] === "number"
    ) {
      west = Math.min(west, value[0]);
      south = Math.min(south, value[1]);
      east = Math.max(east, value[0]);
      north = Math.max(north, value[1]);
      return;
    }

    value.forEach(visitCoordinates);
  };

  featureCollection.features.forEach((feature) => {
    if (feature.geometry && "coordinates" in feature.geometry) {
      visitCoordinates(feature.geometry.coordinates);
    }
  });

  if (![west, south, east, north].every(Number.isFinite)) return null;
  return [
    [west, south],
    [east, north],
  ];
}
