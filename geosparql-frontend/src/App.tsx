import {
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  useEffect,
  useRef,
  useState,
} from "react";
import { Activity, Braces, CircleHelp, Github, RadioTower } from "lucide-react";
import { ExecutionConsole } from "@/components/console/ExecutionConsole";
import { MapCanvas } from "@/components/map/MapCanvas";
import { QueryPanel } from "@/components/query/QueryPanel";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { DEFAULT_RML, DEFAULT_SPARQL } from "@/data/mock";
import { useJitExecution } from "@/hooks/useJitExecution";

const MIN_QUERY_PANEL_WIDTH = 24;
const MAX_QUERY_PANEL_WIDTH = 55;
const QUERY_PANEL_KEYBOARD_STEP = 2;

function clampQueryPanelWidth(width: number) {
  return Math.min(
    MAX_QUERY_PANEL_WIDTH,
    Math.max(MIN_QUERY_PANEL_WIDTH, width),
  );
}

function App() {
  const [sparql, setSparql] = useState(DEFAULT_SPARQL);
  const [rml, setRml] = useState(DEFAULT_RML);
  const [consoleOpen, setConsoleOpen] = useState(true);
  const [queryPanelWidth, setQueryPanelWidth] = useState(30);
  const [isResizingPanels, setIsResizingPanels] = useState(false);
  const mainRef = useRef<HTMLElement>(null);
  const {
    clearLogs,
    execute,
    isLoading,
    logs,
    mapData,
  } = useJitExecution();

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
        event.preventDefault();
        setConsoleOpen(true);
        void execute(sparql, rml);
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [execute, rml, sparql]);

  const handleExecute = () => {
    setConsoleOpen(true);
    void execute(sparql, rml);
  };

  useEffect(() => {
    if (!isResizingPanels) return;

    document.body.classList.add("is-resizing-panels");
    return () => document.body.classList.remove("is-resizing-panels");
  }, [isResizingPanels]);

  const resizePanels = (clientX: number) => {
    const bounds = mainRef.current?.getBoundingClientRect();
    if (!bounds) return;

    const width = ((clientX - bounds.left) / bounds.width) * 100;
    setQueryPanelWidth(clampQueryPanelWidth(width));
  };

  const handleResizePointerDown = (
    event: ReactPointerEvent<HTMLDivElement>,
  ) => {
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    setIsResizingPanels(true);
    resizePanels(event.clientX);
  };

  const handleResizePointerMove = (
    event: ReactPointerEvent<HTMLDivElement>,
  ) => {
    if (isResizingPanels) resizePanels(event.clientX);
  };

  const handleResizePointerUp = (
    event: ReactPointerEvent<HTMLDivElement>,
  ) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    setIsResizingPanels(false);
  };

  const handleResizeKeyDown = (
    event: ReactKeyboardEvent<HTMLDivElement>,
  ) => {
    let nextWidth: number | undefined;

    if (event.key === "ArrowLeft") {
      nextWidth = queryPanelWidth - QUERY_PANEL_KEYBOARD_STEP;
    } else if (event.key === "ArrowRight") {
      nextWidth = queryPanelWidth + QUERY_PANEL_KEYBOARD_STEP;
    } else if (event.key === "Home") {
      nextWidth = MIN_QUERY_PANEL_WIDTH;
    } else if (event.key === "End") {
      nextWidth = MAX_QUERY_PANEL_WIDTH;
    }

    if (nextWidth === undefined) return;
    event.preventDefault();
    setQueryPanelWidth(clampQueryPanelWidth(nextWidth));
  };

  return (
    <TooltipProvider delayDuration={200}>
      <div className="relative h-screen min-h-[640px] overflow-hidden bg-background text-foreground">
        <header className="relative z-40 flex h-14 items-center justify-between border-b border-border bg-[#080c12]/95 px-4 backdrop-blur">
          <div className="flex items-center gap-3">
            <div className="relative flex size-8 items-center justify-center rounded-lg border border-cyan-300/20 bg-cyan-300/[0.08]">
              <Braces className="size-4 text-cyan-300" />
              <span className="absolute -right-0.5 -top-0.5 size-2 rounded-full border-2 border-[#080c12] bg-emerald-400" />
            </div>
            <div className="flex items-baseline gap-2">
              <h1 className="text-sm font-semibold tracking-tight text-slate-100">
                FvKG-json
              </h1>
              <span className="hidden text-[10px] uppercase tracking-[0.18em] text-slate-600 sm:block">
                Spatial virtualization workbench
              </span>
              <span className="hidden text-[10px] text-slate-600 xl:block">
                by Isaac Noya Vázquez
              </span>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <div className="mr-1 hidden items-center gap-2 rounded-md border border-border bg-black/20 px-2.5 py-1.5 lg:flex">
              <RadioTower className="size-3 text-emerald-400" />
              <span className="text-[10px] text-slate-400">
                FastAPI endpoint
              </span>
              <span className="font-mono text-[9px] text-slate-600">
                localhost:8000
              </span>
            </div>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button aria-label="System status" size="icon" variant="ghost">
                  <Activity className="size-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>System status</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button aria-label="Project repository" size="icon" variant="ghost">
                  <Github className="size-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Project repository</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button aria-label="Open help" size="icon" variant="ghost">
                  <CircleHelp className="size-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>GeoSPARQL help</TooltipContent>
            </Tooltip>
          </div>
        </header>

        <main
          className="relative grid h-[calc(100vh-3.5rem)]"
          ref={mainRef}
          style={{
            gridTemplateColumns: `${queryPanelWidth}% minmax(0, 1fr)`,
          }}
        >
          <QueryPanel
            isLoading={isLoading}
            onExecute={handleExecute}
            onRmlChange={setRml}
            onSparqlChange={setSparql}
            rml={rml}
            sparql={sparql}
          />
          <MapCanvas isLoading={isLoading} mapData={mapData} />
          <div
            aria-label="Resize query and map panels"
            aria-orientation="vertical"
            aria-valuemax={MAX_QUERY_PANEL_WIDTH}
            aria-valuemin={MIN_QUERY_PANEL_WIDTH}
            aria-valuenow={Math.round(queryPanelWidth)}
            className="group absolute inset-y-0 z-30 w-3 -translate-x-1/2 cursor-col-resize touch-none focus-visible:outline-none"
            onKeyDown={handleResizeKeyDown}
            onLostPointerCapture={() => setIsResizingPanels(false)}
            onPointerDown={handleResizePointerDown}
            onPointerMove={handleResizePointerMove}
            onPointerUp={handleResizePointerUp}
            role="separator"
            style={{ left: `${queryPanelWidth}%` }}
            tabIndex={0}
          >
            <span className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-border transition-colors group-hover:bg-cyan-300/70 group-focus-visible:bg-cyan-300" />
            <span className="absolute left-1/2 top-1/2 h-12 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-slate-600 opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100" />
          </div>
        </main>

        <ExecutionConsole
          isLoading={isLoading}
          isOpen={consoleOpen}
          leftOffsetPercent={queryPanelWidth}
          logs={logs}
          onClear={clearLogs}
          onOpenChange={setConsoleOpen}
          results={mapData?.results ?? null}
        />
      </div>
    </TooltipProvider>
  );
}

export default App;
