# Lotes de adulteração — Experimento 1 (Fase 2.3)

36 lotes (12 por LLM, 3–4 questões cada, um único tipo de erro por lote).
Gerados por `scripts/experimento1/gerar_lotes.py`; a lista completa está em `manifesto.csv`.

## Procedimento por lote

1. Abra uma **conversa nova** no LLM indicado pela pasta (`gpt/`, `deepseek/`, `gemini/`).
   Uma conversa por lote evita que respostas anteriores influenciem as seguintes.
2. Copie o conteúdo inteiro de `lotes/<llm>/lote_NN_<TIPO>.txt` e cole no chat.
3. Copie a resposta (o array JSON) e cole em
   `adulteracoes_brutas/<llm>/lote_NN_<TIPO>.json` (já existe vazio).
   Se o chat envolver a resposta em bloco de código (```json), pode colar assim mesmo.
4. No `manifesto.csv`, preencha `modelo_versao` (ex.: `GPT-5`, `DeepSeek-V3.2`,
   `Gemini 2.5 Pro`, como aparece na interface) e `data_execucao` (AAAA-MM-DD).

## Cuidados

- Use sempre o mesmo modelo/versão dentro de cada LLM durante todos os 12 lotes.
- Desative memória/personalização da conta, se disponível, para não vazar contexto.
- Se a resposta vier truncada ou com menos itens que o lote, peça "continue" na mesma
  conversa e cole o restante no mesmo arquivo `.json`.
- Não edite as respostas à mão nesta fase; correções entram na revisão (Fase 2.5).

## Reenvio (itens reprovados na revisão)

Os lotes `reenvio_NN_<TIPO>.txt` (gerados por `scripts/experimento1/gerar_reenvio.py`, lista
em `manifesto_reenvio.csv`) refazem os itens rejeitados ou marcados para ajuste. O
procedimento é o mesmo: conversa nova no mesmo LLM, colar o prompt, colar a resposta em
`adulteracoes_brutas/<llm>/reenvio_NN_<TIPO>.json` e preencher `modelo_versao` e
`data_execucao` em `manifesto_reenvio.csv`. A resposta do reenvio substitui a original
na página de revisão e na consolidação.
