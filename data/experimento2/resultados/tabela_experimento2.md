# Experimento 2: resultados dos modelos geradores

Uma tentativa por pedido. Etapas 1 a 3 com o gerador; Etapa 4 com o avaliador escolhido no Experimento 1.

| Gerador | Pedidos | Passaram na Etapa 3 | Aprovadas | % aprovadas | Tentativas por aprovada | Tempo por aprovada | Falhas técnicas | Pendentes de avaliação |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| llama3.1:8b-instruct-q4_K_M | 140 | 49 | 14 | 10,1% | 9,9 | 23,7 min | 1 | 0 |
| qwen2.5:7b-instruct-q4_K_M | 140 | 61 | 28 | 20,0% | 5,0 | 10,9 min | 0 | 0 |
| qwen3:8b-q4_K_M | 140 | 54 | 26 | 18,6% | 5,4 | 18,7 min | 0 | 0 |

## Onde as tentativas foram reprovadas

| Etapa | llama3.1:8b-instruct-q4_K_M | qwen2.5:7b-instruct-q4_K_M | qwen3:8b-q4_K_M |
| :--- | ---: | ---: | ---: |
| 2a_planejamento | 5 | 2 | 21 |
| 2b_solver | 11 | 11 | 9 |
| 3_execucao_solver | 25 | 28 | 33 |
| 3_nexo_complexidade | 50 | 38 | 23 |
| 4.1_dados_ociosos | 3 | 1 | 0 |
| 4.1_nao_respondivel | 6 | 2 | 3 |
| 4.1_premissa_oculta | 8 | 3 | 3 |
| 4.2_equivalencia | 17 | 26 | 21 |
| 4.3_auditoria_pedagogica | 0 | 1 | 1 |

## Comparação estatística

Teste qui-quadrado da taxa de aprovação entre os geradores: χ² = 5,91, p = 0,052. p < 0,05 indica que a taxa de aprovação difere entre os geradores.

## Como ler

- **% aprovadas**: aprovadas ÷ pedidos com veredito final (falhas técnicas e pendentes ficam de fora).
- **Falhas técnicas**: o avaliador não chegou a um veredito (resposta abortada pelo Ollama).
- **Tentativas por aprovada**: 1 ÷ taxa de aprovação; é o número médio de tentativas para obter uma questão aprovada.
- **Tempo por aprovada**: todo o tempo de geração e avaliação gasto pelo gerador ÷ número de aprovadas.
