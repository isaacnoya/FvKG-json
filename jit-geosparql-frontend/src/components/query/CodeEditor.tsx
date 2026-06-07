import Editor, { type Monaco } from "@monaco-editor/react";

type EditorLanguage = "sparql" | "turtle";

interface CodeEditorProps {
  language: EditorLanguage;
  value: string;
  onChange: (value: string) => void;
}

function registerLanguages(monaco: Monaco) {
  const registered = monaco.languages
    .getLanguages()
    .map((language: { id: string }) => language.id);

  if (!registered.includes("sparql")) {
    monaco.languages.register({ id: "sparql" });
    monaco.languages.setMonarchTokensProvider("sparql", {
      ignoreCase: true,
      keywords: [
        "SELECT",
        "WHERE",
        "PREFIX",
        "BASE",
        "FILTER",
        "OPTIONAL",
        "UNION",
        "GRAPH",
        "SERVICE",
        "BIND",
        "VALUES",
        "LIMIT",
        "OFFSET",
        "ORDER",
        "BY",
        "ASC",
        "DESC",
        "DISTINCT",
        "REDUCED",
        "CONSTRUCT",
        "ASK",
        "DESCRIBE",
        "FROM",
        "NAMED",
        "GROUP",
        "HAVING",
        "AS",
        "A",
      ],
      tokenizer: {
        root: [
          [/#.*$/, "comment"],
          [/<[^>]*>/, "string"],
          [/"(?:[^"\\]|\\.)*"(?:\^\^[^\s;,.]+|@[a-z-]+)?/, "string"],
          [/\?[a-zA-Z_]\w*/, "variable"],
          [/[a-zA-Z_][\w-]*:[\w.-]*/, "type.identifier"],
          [
            /[a-zA-Z_]\w*/,
            {
              cases: {
                "@keywords": "keyword",
                "@default": "identifier",
              },
            },
          ],
          [/[{}()[\].,;]/, "delimiter"],
          [/[=<>!+\-*/|&^]+/, "operator"],
          [/\d+(?:\.\d+)?/, "number"],
        ],
      },
    });
  }

  if (!registered.includes("turtle")) {
    monaco.languages.register({ id: "turtle" });
    monaco.languages.setMonarchTokensProvider("turtle", {
      tokenizer: {
        root: [
          [/#.*$/, "comment"],
          [/@(?:prefix|base)\b/, "keyword"],
          [/\b(?:PREFIX|BASE|a)\b/, "keyword"],
          [/<[^>]*>/, "string"],
          [/"(?:[^"\\]|\\.)*"(?:\^\^[^\s;,.]+|@[a-z-]+)?/, "string"],
          [/_:[\w-]+/, "variable"],
          [/[a-zA-Z_][\w-]*:[\w.-]*/, "type.identifier"],
          [/[.;,()[\]]/, "delimiter"],
          [/\d+(?:\.\d+)?/, "number"],
        ],
      },
    });
  }

  monaco.editor.defineTheme("jit-dark", {
    base: "vs-dark",
    inherit: true,
    rules: [
      { token: "comment", foreground: "5F7185", fontStyle: "italic" },
      { token: "keyword", foreground: "67E8F9", fontStyle: "bold" },
      { token: "variable", foreground: "FDE68A" },
      { token: "type.identifier", foreground: "A7F3D0" },
      { token: "string", foreground: "C4B5FD" },
      { token: "number", foreground: "FDBA74" },
    ],
    colors: {
      "editor.background": "#0A0F16",
      "editor.foreground": "#D4DEE9",
      "editorLineNumber.foreground": "#364352",
      "editorLineNumber.activeForeground": "#8CA0B3",
      "editor.lineHighlightBackground": "#111923",
      "editor.selectionBackground": "#164E6355",
      "editorCursor.foreground": "#67E8F9",
      "editorIndentGuide.background1": "#17212D",
      "editorIndentGuide.activeBackground1": "#334155",
      "editorWidget.background": "#101822",
      "editorWidget.border": "#243244",
    },
  });
}

export function CodeEditor({
  language,
  value,
  onChange,
}: CodeEditorProps) {
  return (
    <Editor
      beforeMount={registerLanguages}
      height="100%"
      language={language}
      onChange={(nextValue) => onChange(nextValue ?? "")}
      theme="jit-dark"
      value={value}
      options={{
        minimap: { enabled: false },
        fontFamily:
          "'JetBrains Mono', 'SFMono-Regular', Consolas, monospace",
        fontSize: 12,
        lineHeight: 20,
        lineNumbersMinChars: 3,
        padding: { top: 14, bottom: 14 },
        scrollBeyondLastLine: false,
        smoothScrolling: true,
        tabSize: 2,
        wordWrap: "on",
        automaticLayout: true,
        renderLineHighlight: "line",
        overviewRulerBorder: false,
        hideCursorInOverviewRuler: true,
      }}
    />
  );
}
