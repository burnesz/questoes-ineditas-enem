#!/bin/bash
# Experimento 2 — uma noite de execução (8 h por padrão).
# Rode o MESMO comando todas as noites: cada etapa retoma de onde parou, e nenhum pedido novo começa
# depois do prazo. Ordem: geração com os 3 geradores e, ao final, avaliação de tudo com o Qwen3.
#
# Uso:  bash scripts/experimento2/rodar_noite.sh [horas]      (padrão: 8)
set -u
cd "$(dirname "$0")/../.."
HORAS=${1:-8}
PRAZO=$(date -d "+${HORAS} hours" '+%Y-%m-%d %H:%M')
HARDWARE="RTX 3050 Laptop 4GB"
LOG=data/experimento2/logs/noite_$(date '+%Y-%m-%d_%H%M').log
mkdir -p data/experimento2/logs
PY="./.venv/bin/python scripts/experimento2/experimento2.py"

echo "Início: $(date) | prazo: $PRAZO | log: $LOG"
{
  $PY gerar --modelo qwen2.5:7b-instruct-q4_K_M --hardware "$HARDWARE" --prazo "$PRAZO"
  $PY gerar --modelo llama3.1:8b-instruct-q4_K_M --hardware "$HARDWARE" --prazo "$PRAZO"
  $PY gerar --modelo qwen3:8b-q4_K_M --think false --hardware "$HARDWARE" --prazo "$PRAZO"
  $PY avaliar --avaliador qwen3:8b-q4_K_M --think false --hardware "$HARDWARE" --prazo "$PRAZO"
  $PY resumo
} 2>&1 | grep --line-buffered -E "^(GERAR|AVALIAR|\[|Prazo|#|\||[0-9]+ quedas)|Error|Traceback" | tee -a "$LOG"
echo "Fim: $(date)"
