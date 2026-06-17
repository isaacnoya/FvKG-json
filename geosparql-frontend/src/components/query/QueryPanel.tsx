import { type ChangeEvent, useRef } from "react";
import {
  Braces,
  ChevronDown,
  Code2,
  Database,
  LoaderCircle,
  Play,
  Route,
  Upload,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { CodeEditor } from "./CodeEditor";

interface QueryPanelProps {
  sparql: string;
  rml: string;
  theme: "dark" | "light";
  isLoading: boolean;
  onSparqlChange: (value: string) => void;
  onRmlChange: (value: string) => void;
  onExecute: () => void;
}

export function QueryPanel({
  sparql,
  rml,
  theme,
  isLoading,
  onSparqlChange,
  onRmlChange,
  onExecute,
}: QueryPanelProps) {
  const rmlFileInputRef = useRef<HTMLInputElement>(null);

  const handleRmlFileChange = async (
    event: ChangeEvent<HTMLInputElement>,
  ) => {
    const input = event.currentTarget;
    const files = Array.from(input.files ?? []);
    if (files.length === 0) return;

    try {
      const mappings = await Promise.all(
        files.map(async (file) => {
          const content = await file.text();
          const filename = file.name.replace(/[\r\n]/g, " ");

          return `# --- MAPPING: ${filename} ---\n\n${content}`;
        }),
      );

      onRmlChange(mappings.join("\n\n"));
    } finally {
      input.value = "";
    }
  };

  return (
    <aside className="relative z-20 flex h-full min-h-0 min-w-0 flex-col border-r border-border bg-background">
      <div className="flex h-16 shrink-0 items-center justify-between border-b border-border px-5">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-cyan-300">
            Query workspace
          </p>
          <h2 className="mt-1 text-sm font-semibold text-foreground">
            Virtual endpoint definition
          </h2>
        </div>
        <div className="flex size-8 items-center justify-center rounded-lg border border-border bg-secondary/50">
          <Code2 className="size-4 text-muted-foreground" />
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col px-4 pb-3 pt-4">
        <Tabs
          className="flex min-h-0 flex-1 flex-col"
          defaultValue="sparql"
        >
          <TabsList className="mb-3 grid w-full shrink-0 grid-cols-2">
            <TabsTrigger value="sparql">
              <Braces className="size-3.5" />
              SPARQL Query
            </TabsTrigger>
            <TabsTrigger value="rml">
              <Route className="size-3.5" />
              RML Mappings
            </TabsTrigger>
          </TabsList>

          <div className="mb-2 flex items-center justify-between px-1 text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
            <span>Editor</span>
            <span className="flex items-center gap-1.5">
              UTF-8
              <span className="size-1 rounded-full bg-emerald-400" />
              Ready
            </span>
          </div>

          <TabsContent
            className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-border bg-secondary"
            value="sparql"
          >
            <div className="min-h-0 flex-1">
              <CodeEditor
                language="sparql"
                onChange={onSparqlChange}
                theme={theme}
                value={sparql}
              />
            </div>
          </TabsContent>
          <TabsContent
            className="flex min-h-0 flex-col overflow-hidden rounded-lg border border-border bg-secondary"
            value="rml"
          >
            <div className="flex shrink-0 items-center justify-between border-b border-border bg-secondary/70 px-3 py-2">
              <span className="text-[10px] text-muted-foreground">
                Import Turtle or RML mapping files
              </span>
              <input
                accept=".ttl,.rml,.txt"
                className="hidden"
                multiple
                onChange={handleRmlFileChange}
                ref={rmlFileInputRef}
                type="file"
              />
              <Button
                onClick={() => rmlFileInputRef.current?.click()}
                size="sm"
                type="button"
                variant="outline"
              >
                <Upload className="size-3.5" />
                Upload Files
              </Button>
            </div>
            <div className="min-h-0 flex-1">
              <CodeEditor
                language="turtle"
                onChange={onRmlChange}
                theme={theme}
                value={rml}
              />
            </div>
          </TabsContent>
        </Tabs>
      </div>

      <div className="shrink-0 border-t border-border bg-secondary p-4">
        <button
          className="mb-3 flex w-full items-center justify-between rounded-lg border border-border bg-background/50 px-3 py-2.5 text-left transition-colors hover:border-primary/35"
          type="button"
        >
          <span className="flex items-center gap-2.5">
            <Database className="size-3.5 text-cyan-300" />
            <span>
              <span className="block text-[10px] uppercase tracking-wider text-muted-foreground">
                Target endpoint
              </span>
              <span className="mt-0.5 block text-xs text-foreground">
                Local FvKG[json] endpoint
              </span>
            </span>
          </span>
          <ChevronDown className="size-3.5 text-muted-foreground" />
        </button>

        <Button
          className="h-11 w-full"
          disabled={isLoading}
          onClick={onExecute}
        >
          {isLoading ? (
            <>
              <LoaderCircle className="size-4 animate-spin" />
              Executing query...
            </>
          ) : (
            <>
              <Play className="size-4 fill-current" />
              Execute FvKG[json] Query
              <kbd className="ml-auto rounded border border-primary/30 bg-accent px-1.5 py-0.5 font-mono text-[9px] font-normal text-accent-foreground">
                Cmd Enter
              </kbd>
            </>
          )}
        </Button>
      </div>
    </aside>
  );
}
