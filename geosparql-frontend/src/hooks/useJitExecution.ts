import { useCallback, useRef, useState } from "react";
import type { ApiResponse, MapData } from "@/types/api";
import type { RasterCoordinates } from "@/types/map";

const API_ENDPOINT =
  import.meta.env.VITE_API_URL ?? "http://localhost:8000/api/execute";

function normalizeRasterCoordinates(
  coordinates: number[][],
): RasterCoordinates {
  if (
    coordinates.length !== 4 ||
    coordinates.some(
      (coordinate) =>
        coordinate.length !== 2 ||
        !coordinate.every((value) => Number.isFinite(value)),
    )
  ) {
    throw new Error("Backend returned invalid raster image coordinates.");
  }

  return coordinates as RasterCoordinates;
}

function normalizeMapData(data: ApiResponse["data"]): MapData {
  return {
    vector: data.vector,
    raster: data.raster
      ? {
          url: data.raster.url,
          coordinates: normalizeRasterCoordinates(data.raster.coordinates),
        }
      : undefined,
    results: {
      variables: Array.isArray(data.results?.variables)
        ? data.results.variables.map(String)
        : [],
      rows: Array.isArray(data.results?.rows) ? data.results.rows : [],
    },
  };
}

function getErrorMessage(payload: unknown, status: number) {
  if (typeof payload === "object" && payload !== null && "detail" in payload) {
    const detail = payload.detail;
    if (typeof detail === "string") return detail;
    return JSON.stringify(detail);
  }

  return `Backend request failed with HTTP ${status}.`;
}

export function useJitExecution() {
  const [isLoading, setIsLoading] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [mapData, setMapData] = useState<MapData | null>(null);
  const running = useRef(false);

  const execute = useCallback(
    async (sparqlQuery: string, rmlMapping: string) => {
      if (running.current) return;

      running.current = true;
      setIsLoading(true);
      setLogs([]);
      setMapData(null);

      try {
        const response = await fetch(API_ENDPOINT, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            sparql_query: sparqlQuery,
            rml_mapping: rmlMapping,
          }),
        });
        const payload: unknown = await response.json().catch(() => null);

        if (!response.ok) {
          throw new Error(getErrorMessage(payload, response.status));
        }

        const result = payload as ApiResponse;
        if (
          !result ||
          typeof result.status !== "string" ||
          !Array.isArray(result.logs) ||
          typeof result.data !== "object" ||
          result.data === null
        ) {
          throw new Error("Backend returned an invalid execution response.");
        }

        const responseLogs = result.logs.map(String);
        setLogs(
          responseLogs.length > 0
            ? responseLogs
            : [`[INFO] Backend execution status: ${result.status}`],
        );
        setMapData(normalizeMapData(result.data));
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "Unknown execution error.";
        setLogs((current) => [...current, `[ERROR] ${message}`]);
      } finally {
        running.current = false;
        setIsLoading(false);
      }
    },
    [],
  );

  const clearLogs = useCallback(() => setLogs([]), []);

  return {
    clearLogs,
    execute,
    isLoading,
    logs,
    mapData,
  };
}
