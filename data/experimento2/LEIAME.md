# Experimento 2 — seleção do modelo gerador

Três geradores (Qwen2.5 7B, Qwen3 8B sem raciocínio e Llama 3.1 8B) fizeram 140 pedidos cada: 28 habilidades × 5, com uma tentativa por pedido. As questões que passaram pelas Etapas 1 a 3 foram avaliadas depois pelo Qwen3 8B sem raciocínio, o avaliador escolhido no Experimento 1.

A execução foi num notebook com RTX 3050 Laptop (4 GB) e Ollama 0.34.1, em 15/11/2026.

| Arquivo | Conteúdo |
| :--- | :--- |
| `geracoes.jsonl` | Uma linha por pedido: gerador, digest, habilidade, rodada, resultado da geração (`passou_etapa3` ou `reprovada_etapa2_3`, com a etapa), tempo e ids da questão e do ciclo no SQLite |
| `avaliacoes.jsonl` | Uma linha por avaliação: questão, gerador, avaliador, veredito (`aprovada`, `reprovada` ou `erro` = falha técnica), etapa de reprovação e tempo |
| `questoes_geradas.jsonl` | As 420 questões (aprovadas e reprovadas), com enunciado, alternativas, gabarito, solver, veredito, motivo, tema, tipologia e seed. É uma cópia do SQLite, que fica fora do git |
| `resultados/tabela_experimento2.md` | Tabela final: % aprovadas, tentativas e tempo por aprovada, erros por etapa e testes estatísticos |
| `validacao_humana/` | Amostra cega para os professores: 10 aprovadas por gerador, 30 no total (`caderno_professores.html`, `ficha_respostas.csv`). A `chave_amostra.csv` diz o gerador de cada questão e **não deve ser entregue aos professores**. Gerada por `scripts/experimento2/montar_validacao_humana.py` |

No SQLite do projeto (`questoes_ineditas.db`), as questões ficam nas tabelas `ciclos_geracao`, `tentativas_geracao` e `questoes_ineditas`. Os ids nos manifestos e em `questoes_geradas.jsonl` são os mesmos do banco.

Para gerar a tabela de novo:

```bash
python scripts/experimento2/experimento2.py resumo
```
