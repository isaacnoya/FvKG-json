import type { FeatureCollection, GeoJsonProperties } from "geojson";

export type MapBounds = [[number, number], [number, number]];

const FEATURE_COLORS = [
  "#22d3ee",
  "#a78bfa",
  "#fb7185",
  "#fbbf24",
  "#34d399",
  "#60a5fa",
  "#f97316",
  "#e879f9",
];

export interface FeatureClass {
  id: string;
  label: string;
  color: string;
  count: number;
}

function stringProperty(
  properties: GeoJsonProperties,
  name: string,
  fallback: string,
) {
  const value = properties?.[name];
  return typeof value === "string" && value ? value : fallback;
}

export function styleFeatureCollection(
  featureCollection: FeatureCollection,
): {
  data: FeatureCollection;
  classes: FeatureClass[];
} {
  const counts = new Map<string, { label: string; count: number }>();

  featureCollection.features.forEach((feature) => {
    const classId = stringProperty(
      feature.properties,
      "morphgeoClass",
      "unclassified",
    );
    const classLabel = stringProperty(
      feature.properties,
      "morphgeoClassLabel",
      "Unclassified",
    );
    const current = counts.get(classId);
    counts.set(classId, {
      label: classLabel,
      count: (current?.count ?? 0) + 1,
    });
  });

  const classes = Array.from(counts, ([id, value]) => ({
    id,
    label: value.label,
    count: value.count,
    color: "",
  }))
    .sort((left, right) => left.label.localeCompare(right.label))
    .map((featureClass, index) => ({
      ...featureClass,
      color: FEATURE_COLORS[index % FEATURE_COLORS.length],
    }));
  const colors = new Map(classes.map(({ id, color }) => [id, color]));

  return {
    classes,
    data: {
      ...featureCollection,
      features: featureCollection.features.map((feature) => {
        const classId = stringProperty(
          feature.properties,
          "morphgeoClass",
          "unclassified",
        );

        return {
          ...feature,
          properties: {
            ...feature.properties,
            morphgeoColor: colors.get(classId) ?? FEATURE_COLORS[0],
          },
        };
      }),
    },
  };
}

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
