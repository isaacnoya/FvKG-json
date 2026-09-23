#!/usr/bin/env bash
set -euo pipefail

CONFIG_FILE="$HOME/.emacs.d/elisp/config.el"
MARKER="Make Lean's Elan-managed tools visible to Emacs and lean4-mode."

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "No existe $CONFIG_FILE"
  exit 1
fi

if [[ ! -d "$HOME/.elan/bin" ]]; then
  echo "No existe $HOME/.elan/bin; instala Lean con elan antes de continuar."
  exit 1
fi

if grep -Fq "$MARKER" "$CONFIG_FILE"; then
  echo "La configuracion de Lean/Elan ya esta aplicada en $CONFIG_FILE"
  exit 0
fi

BACKUP_FILE="$CONFIG_FILE.bak.$(date +%Y%m%d-%H%M%S)"
cp "$CONFIG_FILE" "$BACKUP_FILE"

python3 - "$CONFIG_FILE" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()

needle = '''(setq package-archives '((\"melpa\"          . \"https://melpa.org/packages/\")
                         (\"melpa (stable)\" . \"https://stable.melpa.org/packages/\")
                         (\"org\"            . \"https://orgmode.org/elpa/\")
                         (\"elpa\"           . \"https://elpa.gnu.org/packages/\")))
'''

insert = '''
;; Make Lean's Elan-managed tools visible to Emacs and lean4-mode.
(let ((elan-bin (expand-file-name "~/.elan/bin")))
  (when (file-directory-p elan-bin)
    (add-to-list 'exec-path elan-bin)
    (setenv "PATH" (concat elan-bin path-separator (getenv "PATH")))))
'''

if needle not in text:
    raise SystemExit("No se encontro el bloque package-archives esperado; no modifico el archivo.")

path.write_text(text.replace(needle, needle + insert, 1))
PY

echo "Cambio aplicado en $CONFIG_FILE"
echo "Copia de seguridad: $BACKUP_FILE"
echo
echo "Ahora reinicia Emacs, o evalua este bloque en Emacs:"
echo '(let ((elan-bin (expand-file-name "~/.elan/bin")))'
echo '  (when (file-directory-p elan-bin)'
echo "    (add-to-list 'exec-path elan-bin)"
echo '    (setenv "PATH" (concat elan-bin path-separator (getenv "PATH")))))'
