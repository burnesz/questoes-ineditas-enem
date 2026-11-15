# Experimento 1: resultados dos modelos avaliadores

Base: 280 questões (140 autênticas e 140 com erro). Modelos ordenados pelo F1.

## Tabela principal

| Modelo | Acurácia nas autênticas | Precisão | Recall | F1 | Falso positivo | Tempo médio | Falhas técnicas |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Qwen3 8B | 61,4% | 0,644 | 0,814 | **0,719** | 45,0% | 7,4 s | 0 |
| DeepSeek-R1 8B | 43,6% | 0,502 | 0,963 | **0,660** | 85,2% | 45,2 s | 49 |
| Qwen2.5 7B | 43,6% | 0,556 | 0,779 | **0,649** | 62,1% | 4,7 s | 0 |
| Llama 3.1 8B | 21,4% | 0,507 | 0,831 | **0,630** | 77,8% | 5,3 s | 15 |

## Recall por tipo de erro

| Modelo | Gabarito | Cálculo | Ambiguidade | Contradição |
| :--- | ---: | ---: | ---: | ---: |
| Qwen3 8B | 88,6% | 94,3% | 71,4% | 71,4% |
| DeepSeek-R1 8B | 100,0% | 100,0% | 93,1% | 91,3% |
| Qwen2.5 7B | 82,9% | 82,9% | 77,1% | 68,6% |
| Llama 3.1 8B | 74,3% | 78,6% | 100,0% | 79,4% |

## Comparação estatística (McNemar exato, Qwen3 8B contra os demais)

| Comparação | Itens comparados | Só Qwen3 8B acertou | Só o outro acertou | p-valor |
| :--- | ---: | ---: | ---: | ---: |
| Qwen3 8B × DeepSeek-R1 8B | 231 | 60 | 24 | < 0,001 |
| Qwen3 8B × Qwen2.5 7B | 280 | 56 | 27 | 0,002 |
| Qwen3 8B × Llama 3.1 8B | 265 | 70 | 27 | < 0,001 |

## Como ler

- **Acurácia nas autênticas**: % das 140 questões autênticas em que o modelo chegou à alternativa do gabarito oficial.
- **Precisão**: das questões que o modelo reprovou, quantas tinham erro de fato.
- **Recall**: das questões com erro, quantas o modelo reprovou.
- **F1**: média harmônica entre precisão e recall.
- **Falso positivo**: % das autênticas que o modelo reprovou sem motivo.
- **Falhas técnicas**: respostas vazias ou malformadas do modelo. Ficam fora da precisão e do recall e contam como não resolvidas na acurácia.
- **McNemar**: compara os dois modelos nos mesmos itens. p-valor < 0,05 indica diferença estatisticamente significativa.
