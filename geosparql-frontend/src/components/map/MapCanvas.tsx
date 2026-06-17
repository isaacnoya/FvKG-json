import { useEffect, useMemo, useRef, useState } from "react";
import {
  Box,
  Check,
  Image,
  Layers3,
  LocateFixed,
  Map as MapIcon,
} from "lucide-react";
import Map, {
  AttributionControl,
  NavigationControl,
  Popup,
  ScaleControl,
  type MapRef,
} from "react-map-gl/maplibre";
import type { MapLayerMouseEvent } from "maplibre-gl";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  getGeoJsonBounds,
  styleFeatureCollection,
} from "@/lib/geojson";
import { cn } from "@/lib/utils";
import type { MapData, SparqlBinding } from "@/types/api";
import { INTERACTIVE_VECTOR_LAYER_IDS } from "@/types/map";
import { RasterOverlay, VectorLayer } from "./layers";

const MAP_STYLE =
  "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";

interface MapCanvasProps {
  mapData: MapData | null;
  isLoading: boolean;
}

interface SelectedFeature {
  id: string;
  longitude: number;
  latitude: number;
  properties: Record<string, unknown>;
}

const INTERNAL_PROPERTIES = new Set([
  "fvkgJsonClass",
  "fvkgJsonClassLabel",
  "fvkgJsonColor",
  "fvkgJsonLabel",
  "type",
]);

function localName(value: string) {
  const normalized = value.replace(/[/#]+$/, "");
  return normalized.split(/[/#]/).pop() || value;
}

function displayValue(value: unknown) {
  if (Array.isArray(value)) return value.join(", ");
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function compactBinding(binding: SparqlBinding) {
  const value = displayValue(binding.value);
  return binding.type === "uri" ? localName(value) : value;
}

export function MapCanvas({
  mapData,
  isLoading,
}: MapCanvasProps) {
  const mapRef = useRef<MapRef>(null);
  const [mapLoaded, setMapLoaded] = useState(false);
  const [vectorVisible, setVectorVisible] = useState(true);
  const [rasterVisible, setRasterVisible] = useState(true);
  const [isHoveringFeature, setIsHoveringFeature] = useState(false);
  const [selectedFeature, setSelectedFeature] =
    useState<SelectedFeature | null>(null);
  const styledVector = useMemo(
    () => (mapData?.vector ? styleFeatureCollection(mapData.vector) : null),
    [mapData?.vector],
  );
  const vectorData = styledVector?.data;
  const featureClasses = styledVector?.classes ?? [];
  const rasterData = mapData?.raster;
  const results = mapData?.results;

  const selectedProperties = useMemo(
    () =>
      Object.entries(selectedFeature?.properties ?? {}).filter(
        ([key]) => !INTERNAL_PROPERTIES.has(key),
      ),
    [selectedFeature],
  );
  const matchingRows = useMemo(() => {
    if (!selectedFeature || !results) return [];

    return results.rows.filter((row) =>
      Object.values(row).some(
        (binding) => String(binding.value) === selectedFeature.id,
      ),
    );
  }, [results, selectedFeature]);

  useEffect(() => {
    if (vectorData) setVectorVisible(true);
    if (rasterData) setRasterVisible(true);
    setSelectedFeature(null);
  }, [rasterData, vectorData]);

  useEffect(() => {
    if (!mapLoaded) return;

    const bounds = vectorData
      ? getGeoJsonBounds(vectorData)
      : rasterData
        ? ([
            [
              Math.min(...rasterData.coordinates.map(([x]) => x)),
              Math.min(...rasterData.coordinates.map(([, y]) => y)),
            ],
            [
              Math.max(...rasterData.coordinates.map(([x]) => x)),
              Math.max(...rasterData.coordinates.map(([, y]) => y)),
            ],
          ] as [[number, number], [number, number]])
        : null;

    if (bounds) {
      mapRef.current?.fitBounds(bounds, {
        padding: { top: 100, right: 100, bottom: 210, left: 100 },
        duration: 1200,
        maxZoom: 9,
      });
    }
  }, [mapLoaded, rasterData, vectorData]);

  const resetView = () => {
    mapRef.current?.flyTo({
      center: [-3.7038, 40.4168],
      zoom: 5.2,
      duration: 900,
    });
  };

  const handleFeatureClick = (event: MapLayerMouseEvent) => {
    const feature = event.features?.[0];
    if (!feature) {
      setSelectedFeature(null);
      return;
    }

    const properties = feature.properties ?? {};
    setSelectedFeature({
      id: String(properties.id ?? feature.id ?? ""),
      longitude: event.lngLat.lng,
      latitude: event.lngLat.lat,
      properties,
    });
  };

  return (
    <section className="relative min-w-0 overflow-hidden bg-[#071015]">
      <Map
        attributionControl={false}
        cursor={isHoveringFeature ? "pointer" : "grab"}
        initialViewState={{
          longitude: -3.7038,
          latitude: 40.4168,
          zoom: 5.2,
          pitch: 0,
          bearing: 0,
        }}
        interactiveLayerIds={
          vectorVisible && vectorData ? INTERACTIVE_VECTOR_LAYER_IDS : []
        }
        mapStyle={MAP_STYLE}
        onClick={handleFeatureClick}
        onMouseEnter={() => setIsHoveringFeature(true)}
        onMouseLeave={() => setIsHoveringFeature(false)}
        onLoad={() => setMapLoaded(true)}
        ref={mapRef}
        reuseMaps
      >
        {rasterData && (
          <RasterOverlay data={rasterData} visible={rasterVisible} />
        )}
        {vectorData && (
          <VectorLayer data={vectorData} visible={vectorVisible} />
        )}
        <NavigationControl position="bottom-right" showCompass={false} />
        <ScaleControl maxWidth={120} position="bottom-left" />
        <AttributionControl compact position="bottom-right" />

        {selectedFeature && (
          <Popup
            anchor="bottom"
            className="feature-popup"
            closeOnClick={false}
            latitude={selectedFeature.latitude}
            longitude={selectedFeature.longitude}
            maxWidth="340px"
            onClose={() => setSelectedFeature(null)}
            offset={12}
          >
            <div className="max-h-80 min-w-64 overflow-y-auto p-3">
              <div className="flex items-start gap-2.5 border-b border-white/10 pb-2.5">
                <span
                  className="mt-1 size-2.5 shrink-0 rounded-full"
                  style={{
                    backgroundColor: String(
                      selectedFeature.properties.fvkgJsonColor ?? "#22d3ee",
                    ),
                  }}
                />
                <div className="min-w-0">
                  <p className="truncate text-xs font-semibold text-slate-100">
                    {displayValue(
                      selectedFeature.properties.fvkgJsonLabel ??
                        localName(selectedFeature.id),
                    )}
                  </p>
                  <p className="mt-0.5 truncate text-[10px] text-slate-500">
                    {displayValue(
                      selectedFeature.properties.fvkgJsonClassLabel ??
                        "Unclassified",
                    )}
                  </p>
                </div>
              </div>

              <dl className="space-y-1.5 py-2.5 text-[10px]">
                {selectedProperties.map(([key, value]) => (
                  <div className="grid grid-cols-[90px_1fr] gap-2" key={key}>
                    <dt className="truncate text-slate-500" title={key}>
                      {key}
                    </dt>
                    <dd
                      className="break-words text-slate-200"
                      title={displayValue(value)}
                    >
                      {displayValue(value)}
                    </dd>
                  </div>
                ))}
              </dl>

              {matchingRows.length > 0 && (
                <div className="border-t border-white/10 pt-2.5">
                  <p className="mb-2 text-[9px] font-semibold uppercase tracking-[0.14em] text-cyan-300">
                    Matching result rows
                  </p>
                  <div className="space-y-2">
                    {matchingRows.slice(0, 3).map((row, rowIndex) => (
                      <div
                        className="rounded border border-white/[0.07] bg-black/20 p-2"
                        key={rowIndex}
                      >
                        {Object.entries(row)
                          .filter(
                            ([, binding]) =>
                              String(binding.value) !== selectedFeature.id,
                          )
                          .map(([variable, binding]) => (
                            <div
                              className="grid grid-cols-[70px_1fr] gap-2 text-[9px] leading-4"
                              key={variable}
                            >
                              <span className="text-slate-500">
                                ?{variable}
                              </span>
                              <span
                                className="truncate text-slate-300"
                                title={displayValue(binding.value)}
                              >
                                {compactBinding(binding)}
                              </span>
                            </div>
                          ))}
                      </div>
                    ))}
                  </div>
                  {matchingRows.length > 3 && (
                    <p className="mt-2 text-[9px] text-slate-500">
                      +{matchingRows.length - 3} more rows in Results
                    </p>
                  )}
                </div>
              )}
            </div>
          </Popup>
        )}
      </Map>

      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_35%,transparent_0%,rgba(5,10,15,0.08)_55%,rgba(5,10,15,0.28)_100%)]" />

      <div className="absolute left-5 top-5 flex items-center gap-2 rounded-lg border border-white/10 bg-[#090f17]/90 px-3 py-2 shadow-panel backdrop-blur-xl">
        <span
          className={cn(
            "size-2 rounded-full",
            mapLoaded ? "bg-emerald-400" : "animate-pulse bg-amber-300",
          )}
        />
        <div>
          <p className="text-[9px] uppercase tracking-[0.18em] text-slate-500">
            Map renderer
          </p>
          <p className="text-[11px] font-medium text-slate-200">
            {mapLoaded ? "MapLibre connected" : "Loading basemap..."}
          </p>
        </div>
      </div>

      <TooltipProvider delayDuration={200}>
        <div className="absolute right-5 top-5 flex items-center gap-1 rounded-lg border border-white/10 bg-[#090f17]/90 p-1 shadow-panel backdrop-blur-xl">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                aria-label="Reset map view"
                onClick={resetView}
                size="icon"
                variant="ghost"
              >
                <LocateFixed className="size-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Reset map view</TooltipContent>
          </Tooltip>
          <div className="mx-1 h-5 w-px bg-border" />
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                aria-label="Toggle vector output"
                className={cn(vectorVisible && vectorData && "text-cyan-300")}
                disabled={!vectorData}
                onClick={() => setVectorVisible((visible) => !visible)}
                size="icon"
                variant="ghost"
              >
                <Box className="size-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Toggle GeoJSON vector</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                aria-label="Toggle raster output"
                className={cn(rasterVisible && rasterData && "text-violet-300")}
                disabled={!rasterData}
                onClick={() => setRasterVisible((visible) => !visible)}
                size="icon"
                variant="ghost"
              >
                <Image className="size-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Toggle WCS raster</TooltipContent>
          </Tooltip>
        </div>
      </TooltipProvider>

      <div className="absolute right-5 top-20 w-56 rounded-lg border border-white/10 bg-[#090f17]/90 p-3 shadow-panel backdrop-blur-xl">
        <div className="mb-3 flex items-center justify-between">
          <span className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-400">
            <Layers3 className="size-3.5" />
            Layers
          </span>
          <span className="rounded bg-white/5 px-1.5 py-0.5 font-mono text-[9px] text-slate-500">
            EPSG:4326
          </span>
        </div>
        <div className="space-y-2">
          <button
            className="flex w-full items-center justify-between rounded-md px-1 py-1 text-left disabled:cursor-not-allowed disabled:opacity-40"
            disabled={!vectorData}
            onClick={() => setVectorVisible((visible) => !visible)}
            type="button"
          >
            <span className="flex items-center gap-2 text-[11px] text-slate-300">
              <span className="size-2.5 rounded-sm border border-cyan-300 bg-cyan-400/25" />
              Query GeoJSON
            </span>
            {vectorData && vectorVisible && (
              <Check className="size-3 text-cyan-300" />
            )}
          </button>
          {vectorData && vectorVisible && featureClasses.length > 0 && (
            <div className="max-h-28 space-y-1 overflow-y-auto border-l border-white/[0.07] pl-3">
              {featureClasses.map((featureClass) => (
                <div
                  className="flex items-center justify-between gap-2 text-[9px]"
                  key={featureClass.id}
                  title={featureClass.id}
                >
                  <span className="flex min-w-0 items-center gap-2 text-slate-400">
                    <span
                      className="size-2 shrink-0 rounded-full"
                      style={{ backgroundColor: featureClass.color }}
                    />
                    <span className="truncate">{featureClass.label}</span>
                  </span>
                  <span className="font-mono text-slate-600">
                    {featureClass.count}
                  </span>
                </div>
              ))}
            </div>
          )}
          <button
            className="flex w-full items-center justify-between rounded-md px-1 py-1 text-left disabled:cursor-not-allowed disabled:opacity-40"
            disabled={!rasterData}
            onClick={() => setRasterVisible((visible) => !visible)}
            type="button"
          >
            <span className="flex items-center gap-2 text-[11px] text-slate-300">
              <span className="size-2.5 rounded-sm bg-gradient-to-br from-violet-400 to-orange-300" />
              Copernicus WCS
            </span>
            {rasterData && rasterVisible && (
              <Check className="size-3 text-violet-300" />
            )}
          </button>
        </div>
      </div>

      {!vectorData && !rasterData && !isLoading && (
        <div className="absolute left-1/2 top-[42%] -translate-x-1/2 -translate-y-1/2 text-center">
          <div className="mx-auto flex size-12 items-center justify-center rounded-xl border border-white/10 bg-[#0a111a]/80 shadow-panel backdrop-blur">
            <MapIcon className="size-5 text-slate-500" />
          </div>
          <p className="mt-3 text-xs font-medium text-slate-400">
            No spatial result loaded
          </p>
          <p className="mt-1 text-[10px] text-slate-600">
            Execute the query to visualize its extent
          </p>
        </div>
      )}

      {isLoading && (
        <div className="absolute left-1/2 top-[42%] -translate-x-1/2 -translate-y-1/2 rounded-xl border border-cyan-300/15 bg-[#071018]/90 px-5 py-4 text-center shadow-panel backdrop-blur-xl">
          <div className="mx-auto size-5 animate-spin rounded-full border-2 border-cyan-300/20 border-t-cyan-300" />
          <p className="mt-3 text-xs font-medium text-cyan-50">
            Materializing spatial result
          </p>
          <p className="mt-1 font-mono text-[9px] text-cyan-200/50">
            FILTER - SOURCE - GEOJSON
          </p>
        </div>
      )}
    </section>
  );
}
