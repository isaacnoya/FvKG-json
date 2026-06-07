import { useEffect, useState } from "react";
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

function App() {
  const [sparql, setSparql] = useState(DEFAULT_SPARQL);
  const [rml, setRml] = useState(DEFAULT_RML);
  const [consoleOpen, setConsoleOpen] = useState(true);
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
                MorphGEO
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

        <main className="grid h-[calc(100vh-3.5rem)] grid-cols-[30%_70%]">
          <QueryPanel
            isLoading={isLoading}
            onExecute={handleExecute}
            onRmlChange={setRml}
            onSparqlChange={setSparql}
            rml={rml}
            sparql={sparql}
          />
          <MapCanvas isLoading={isLoading} mapData={mapData} />
        </main>

        <ExecutionConsole
          isLoading={isLoading}
          isOpen={consoleOpen}
          logs={logs}
          onClear={clearLogs}
          onOpenChange={setConsoleOpen}
        />
      </div>
    </TooltipProvider>
  );
}

export default App;
