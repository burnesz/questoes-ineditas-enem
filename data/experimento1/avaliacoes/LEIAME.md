# Avaliações do Experimento 1

As rodadas oficiais estão nos arquivos `rtx4090__*.jsonl`, um por modelo. Cada arquivo tem 280 itens e todos foram gerados nas mesmas condições:
- Ollama 0.40.16;
- GPU NVIDIA RTX 4090 (24 GB);
- `LLM_NUM_THREAD=4`;
- a mesma versão da pipeline.

Cada registro inclui a tag do modelo, o digest e a versão do Ollama.

| Pasta / arquivo | Conteúdo |
| :--- | :--- |
| `rtx4090__*.jsonl` | Rodadas oficiais dos 4 modelos |
| `calibracao__*.jsonl` | Conjunto de calibração (30 autênticas fora da base) com a pipeline v2 |
| `_piloto_v1/` | Rodada piloto (pipeline v1) que motivou as correções da Etapa 4 |
| `logs/` | Logs das rodadas |
