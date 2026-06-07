import { useEffect, useRef, useState } from "react";
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
  ScaleControl,
  type MapRef,
} from "react-map-gl/maplibre";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { getGeoJsonBounds } from "@/lib/geojson";
import { cn } from "@/lib/utils";
import type { MapData } from "@/types/api";
import { RasterOverlay, VectorLayer } from "./layers";

const MAP_STYLE =
  "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";

interface MapCanvasProps {
  mapData: MapData | null;
  isLoading: boolean;
}

export function MapCanvas({
  mapData,
  isLoading,
}: MapCanvasProps) {
  const mapRef = useRef<MapRef>(null);
  const [mapLoaded, setMapLoaded] = useState(false);
  const [vectorVisible, setVectorVisible] = useState(true);
  const [rasterVisible, setRasterVisible] = useState(true);
  const vectorData = mapData?.vector;
  const rasterData = mapData?.raster;

  useEffect(() => {
    if (vectorData) setVectorVisible(true);
    if (rasterData) setRasterVisible(true);
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

  return (
    <section className="relative min-w-0 overflow-hidden bg-[#071015]">
      <Map
        attributionControl={false}
        initialViewState={{
          longitude: -3.7038,
          latitude: 40.4168,
          zoom: 5.2,
          pitch: 0,
          bearing: 0,
        }}
        mapStyle={MAP_STYLE}
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

      <div className="absolute right-5 top-20 w-48 rounded-lg border border-white/10 bg-[#090f17]/90 p-3 shadow-panel backdrop-blur-xl">
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
