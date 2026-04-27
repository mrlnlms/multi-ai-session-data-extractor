#!/bin/bash
# Snapshot automatico dos dados no DVC + push pro Google Drive.
# Chamado no final dos scripts de ingestao.
#
# O que faz:
# 1. dvc add das pastas trackadas (rapido — DVC so re-hasha o que mudou)
# 2. Se os ponteiros mudaram, commita via ~/.claude/scripts/commit.sh
# 3. dvc push pro Google Drive (deltas apenas — DVC nao re-envia o que ja esta la)
#
# Pra incluir data/raw/ quando for decidido (backlog #28), adicionar em TRACKED_DIRS.
# Runbook completo: docs/dvc-runbook.md

set -e

# Pastas sob DVC. Aumentar quando raw entrar.
TRACKED_DIRS=(data/curated data/processed data/unified)

# Root do repo (script vive em scripts/)
cd "$(dirname "$0")/.."

# Venv — dvc precisa estar no PATH
if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
fi

if ! command -v dvc &> /dev/null; then
    echo "[backup_to_dvc] AVISO: dvc nao encontrado no PATH — pulando backup"
    exit 0
fi

echo ""
echo "=== [backup_to_dvc] Capturando estado dos dados ==="
dvc add "${TRACKED_DIRS[@]}"

# Commit so se houver mudanca (porcelain detecta modified + untracked)
if [ -n "$(git status --porcelain -- data/*.dvc data/.gitignore 2>/dev/null)" ]; then
    echo "=== [backup_to_dvc] Mudancas detectadas, commitando ==="
    git add data/*.dvc data/.gitignore
    ~/.claude/scripts/commit.sh "data: snapshot $(date +'%Y-%m-%d %H:%M')"
else
    echo "=== [backup_to_dvc] Ponteiros ja atualizados ==="
fi

echo "=== [backup_to_dvc] Pushing pro Google Drive ==="
dvc push

echo "=== [backup_to_dvc] OK ==="
