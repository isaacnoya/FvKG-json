import * as Collapsible from "@radix-ui/react-collapsible";
import { useEffect, useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  CircleDot,
  ListTree,
  TerminalSquare,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { SparqlBinding, SparqlResults } from "@/types/api";

interface ExecutionConsoleProps {
  isOpen: boolean;
  isLoading: boolean;
  leftOffsetPercent: number;
  logs: string[];
  results: SparqlResults | null;
  onOpenChange: (open: boolean) => void;
  onClear: () => void;
}

type LogLevel = "info" | "success" | "warning" | "error";
type ConsoleView = "logs" | "results";

const levelClasses: Record<LogLevel, string> = {
  info: "text-sky-300",
  success: "text-emerald-300",
  warning: "text-amber-300",
  error: "text-rose-300",
};

function parseLog(log: string): { level: LogLevel; message: string } {
  const match = log.match(/^\[(INFO|SUCCESS|WARNING|WARN|ERROR)\]\s*/i);
  const rawLevel = match?.[1].toLowerCase();
  const level =
    rawLevel === "warn"
      ? "warning"
      : rawLevel === "success" ||
          rawLevel === "warning" ||
          rawLevel === "error"
        ? rawLevel
        : "info";

  return {
    level,
    message: match ? log.slice(match[0].length) : log,
  };
}

function bindingValue(binding: SparqlBinding | undefined) {
  if (!binding || binding.value === null) return "";
  return String(binding.value);
}

export function ExecutionConsole({
  isOpen,
  isLoading,
  leftOffsetPercent,
  logs,
  results,
  onOpenChange,
  onClear,
}: ExecutionConsoleProps) {
  const [view, setView] = useState<ConsoleView>("logs");

  useEffect(() => {
    if (isLoading) {
      setView("logs");
    } else if (results && results.rows.length > 0) {
      setView("results");
    }
  }, [isLoading, results]);

  return (
    <Collapsible.Root
      className="absolute bottom-4 right-4 z-30 overflow-hidden rounded-xl border border-white/10 bg-[#070b11]/95 shadow-console backdrop-blur-xl"
      onOpenChange={onOpenChange}
      open={isOpen}
      style={{ left: `calc(${leftOffsetPercent}% + 1rem)` }}
    >
      <div className="flex h-11 items-center justify-between border-b border-white/[0.07] px-3.5">
        <Collapsible.Trigger className="flex min-w-0 flex-1 items-center gap-2.5 text-left">
          <TerminalSquare className="size-4 text-cyan-300" />
          <span className="text-[11px] font-semibold uppercase tracking-[0.15em] text-slate-300">
            Execution console
          </span>
          <span className="hidden text-[10px] text-slate-600 sm:inline">
            /
          </span>
          <span className="truncate font-mono text-[10px] text-slate-500">
            {isLoading
              ? "waiting for backend response"
              : `${results?.rows.length ?? 0} result row${
                  results?.rows.length === 1 ? "" : "s"
                }`}
          </span>
          {isLoading && (
            <span className="flex items-center gap-1.5 text-[9px] uppercase tracking-wider text-cyan-300">
              <CircleDot className="size-3 animate-pulse" />
              Live
            </span>
          )}
        </Collapsible.Trigger>

        <div className="flex items-center gap-1">
          <div className="mr-1 flex items-center rounded-md border border-white/[0.07] bg-black/20 p-0.5">
            <button
              className={cn(
                "rounded px-2 py-1 text-[9px] uppercase tracking-wider text-slate-500 transition-colors",
                view === "logs" && "bg-white/[0.07] text-slate-200",
              )}
              onClick={() => setView("logs")}
              type="button"
            >
              Logs
            </button>
            <button
              className={cn(
                "rounded px-2 py-1 text-[9px] uppercase tracking-wider text-slate-500 transition-colors",
                view === "results" && "bg-white/[0.07] text-cyan-200",
              )}
              onClick={() => setView("results")}
              type="button"
            >
              Results
            </button>
          </div>
          <Button
            aria-label="Clear execution logs"
            disabled={logs.length === 0 || isLoading}
            onClick={onClear}
            size="icon"
            variant="ghost"
          >
            <Trash2 className="size-3.5" />
          </Button>
          <Collapsible.Trigger asChild>
            <Button aria-label="Toggle console" size="icon" variant="ghost">
              <ChevronDown
                className={cn(
                  "size-4 transition-transform",
                  !isOpen && "rotate-180",
                )}
              />
            </Button>
          </Collapsible.Trigger>
        </div>
      </div>

      <Collapsible.Content>
        {view === "logs" ? (
          <div className="h-36 overflow-y-auto px-4 py-3 font-mono text-[10px] leading-5">
            {logs.length === 0 ? (
              <div className="flex h-full items-center justify-center text-slate-600">
                Pipeline events will appear here after execution.
              </div>
            ) : (
              <div className="space-y-0.5">
                {logs.map((log, index) => {
                  const parsedLog = parseLog(log);

                  return (
                    <div
                      className="grid grid-cols-[60px_1fr] gap-2"
                      key={`${index}-${log}`}
                    >
                      <span
                        className={cn(
                          "font-semibold",
                          levelClasses[parsedLog.level],
                        )}
                      >
                        [{parsedLog.level.toUpperCase()}]
                      </span>
                      <span className="text-slate-300">
                        {parsedLog.message}
                      </span>
                    </div>
                  );
                })}
                {isLoading && (
                  <div className="grid grid-cols-[60px_1fr] gap-2">
                    <span />
                    <span className="flex items-center gap-2 text-slate-500">
                      <span className="inline-block h-3 w-1.5 animate-pulse-soft bg-cyan-300/80" />
                      Processing
                    </span>
                  </div>
                )}
              </div>
            )}
          </div>
        ) : (
          <div className="h-36 overflow-auto">
            {!results || results.variables.length === 0 ? (
              <div className="flex h-full items-center justify-center gap-2 text-[10px] text-slate-600">
                <ListTree className="size-3.5" />
                Execute a SELECT query to inspect its bindings.
              </div>
            ) : (
              <table className="min-w-full border-collapse font-mono text-[10px]">
                <thead className="sticky top-0 z-10 bg-[#0a1018]">
                  <tr>
                    <th className="border-b border-r border-white/[0.07] px-3 py-2 text-right font-normal text-slate-600">
                      #
                    </th>
                    {results.variables.map((variable) => (
                      <th
                        className="min-w-36 border-b border-r border-white/[0.07] px-3 py-2 text-left font-semibold text-cyan-300"
                        key={variable}
                      >
                        ?{variable}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {results.rows.map((row, rowIndex) => (
                    <tr
                      className="odd:bg-white/[0.015] hover:bg-cyan-300/[0.04]"
                      key={rowIndex}
                    >
                      <td className="border-b border-r border-white/[0.05] px-3 py-1.5 text-right text-slate-600">
                        {rowIndex + 1}
                      </td>
                      {results.variables.map((variable) => {
                        const value = bindingValue(row[variable]);

                        return (
                          <td
                            className="max-w-72 border-b border-r border-white/[0.05] px-3 py-1.5 text-slate-300"
                            key={variable}
                            title={value}
                          >
                            <div className="truncate">{value || "-"}</div>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
        <div className="flex h-7 items-center justify-between border-t border-white/[0.06] px-4 text-[9px] text-slate-600">
          <span>MorphGEO engine v0.1 - Isaac Noya Vázquez</span>
          {!isLoading &&
            logs.some((log) => parseLog(log).level === "success") && (
              <span className="flex items-center gap-1 text-emerald-400/70">
                <CheckCircle2 className="size-3" />
                Pipeline complete
              </span>
            )}
        </div>
      </Collapsible.Content>
    </Collapsible.Root>
  );
}
