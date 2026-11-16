# Pasta `data/`

## Dados do sistema

| Arquivo | Para que serve |
| :--- | :--- |
| `itens_prova_2009_2024_llm_texto.csv` | Questões históricas de Matemática do ENEM. É a fonte do banco (`python cli.py seed`) e do RAG |
| `habilidades_queries.json` | As 30 habilidades, com as consultas do RAG e as tipologias usadas na geração |
| `relatorio_defeitos_itens_prova_llm_texto.md` | Defeitos de extração conhecidos no CSV acima |

## Experimento 1: seleção do modelo avaliador (`experimento1/`)

Os arquivos estão na ordem em que foram produzidos:

| Passo | Arquivo | Script que gera |
| :--- | :--- | :--- |
| 1. Amostra | `amostra_140_historicas.csv`: 140 questões autênticas, 5 por habilidade | (sorteio inicial) |
| 2. Divisão | `atribuicao.csv`: qual LLM adultera cada questão e com qual tipo de erro | `gerar_atribuicao.py` |
| 3. Pedidos | `lotes/`: os prompts enviados ao GPT, ao DeepSeek e ao Gemini (ver `lotes/LEIA-ME.md`) | `gerar_lotes.py`, `gerar_reenvio.py` |
| 4. Respostas | `adulteracoes_brutas/`: as versões com erro devolvidas por cada LLM | (coladas à mão) |
| 5. Checagem | `validacao_adulteracoes.csv`, `validacao_reenvio.csv`: checagem automática das respostas | `validar_adulteracoes.py` |
| 6. Revisão | `revisao/`: a revisão humana de cada versão com erro | `gerar_pagina_revisao.py`, `consolidar_revisao.py` |
| 7. Base final | `autenticas.jsonl`, `modificadas.jsonl` e `base_experimento.jsonl`, com os 280 itens embaralhados, sem rótulo | `montar_base.py` |
| 8. Chave | `base_experimento_chave.csv`: quais itens são autênticos e qual é o erro de cada adulterado | `montar_base.py` |
| 9. Calibração | `calibracao.jsonl`: 30 autênticas fora da base, para testar ajustes sem usar a base | `montar_calibracao.py` |
| 10. Resultados | `avaliacoes/`: as respostas dos 4 modelos (ver `avaliacoes/LEIAME.md`) | `avaliar_base.py` |

Os scripts ficam em `scripts/experimento1/`.

## Experimento 2: seleção do modelo gerador (`experimento2/`)

| Arquivo | Para que serve | Script que gera |
| :--- | :--- | :--- |
| `geracoes.jsonl` | Um registro por pedido de geração (3 geradores × 140) | `experimento2.py gerar` |
| `avaliacoes.jsonl` | Um registro por avaliação feita pelo avaliador | `experimento2.py avaliar` |
| `questoes_geradas.jsonl` | As 420 questões geradas, com veredito (cópia do SQLite, que fica fora do git) | (exportação do banco) |
| `resultados/` | Tabela final do experimento | `experimento2.py resumo` |

As questões geradas ficam no SQLite (`questoes_ineditas.db`), e os manifestos apontam para elas. Detalhes em `experimento2/LEIAME.md`.

Os scripts ficam em `scripts/experimento2/`.
