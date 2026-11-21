# Dados e experimentos

Esta pasta guarda os dados do sistema e os dois experimentos do protocolo de seleção de LLMs para geração de questões de Matemática do ENEM:

| Experimento | Pergunta | Resultado |
| :--- | :--- | :--- |
| 1. Seleção do avaliador | Qual LLM identifica melhor questões corretas e com erro? | **Qwen3 8B** (F1 = 0,719) |
| 2. Seleção do gerador | Qual LLM gera mais questões aprovadas, com menos tentativas e menos tempo? | **Qwen2.5 7B** (20% aprovadas, 10,9 min por aprovada) |

Todos os modelos rodam pelo Ollama, com pesos abertos e quantizados, sem API paga.

**Conteúdo:**
- **Parte A** diz onde está cada arquivo.
- **Parte B** registra o protocolo, as condições de execução, as métricas e os resultados.

---

## Parte A — Arquivos

### Dados do sistema

| Arquivo | Para que serve |
| :--- | :--- |
| `itens_prova_2009_2024_llm_texto.csv` | Questões históricas de Matemática do ENEM. É a fonte do banco (`python cli.py seed`) e do RAG |
| `habilidades_queries.json` | As 30 habilidades, com as consultas do RAG e as tipologias usadas na geração |
| `relatorio_defeitos_itens_prova_llm_texto.md` | Defeitos de extração conhecidos no CSV acima |

### Experimento 1: seleção do modelo avaliador (`experimento1/`)

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

### Experimento 2: seleção do modelo gerador (`experimento2/`)

| Arquivo | Para que serve | Script que gera |
| :--- | :--- | :--- |
| `geracoes.jsonl` | Um registro por pedido de geração (3 geradores × 140) | `experimento2.py gerar` |
| `avaliacoes.jsonl` | Um registro por avaliação feita pelo avaliador | `experimento2.py avaliar` |
| `questoes_geradas.jsonl` | As 420 questões geradas, com veredito (cópia do SQLite, que fica fora do git) | (exportação do banco) |
| `resultados/` | Tabela final do experimento | `experimento2.py resumo` |

As questões geradas ficam no SQLite (`questoes_ineditas.db`), e os manifestos apontam para elas. Detalhes em `experimento2/LEIAME.md`.

Os scripts ficam em `scripts/experimento2/`.

### Avaliação por especialista (`avaliacao_especialista/`)

Um caderno único serve à validação humana do Experimento 2 (artigo) e à comparação VERA × baseline zero-shot (TCC, critério R7).

| Arquivo | Para que serve | Script que gera |
| :--- | :--- | :--- |
| `pares_questoes.jsonl`, `manifest.json` | 10 pares: uma questão aprovada do Qwen2.5 e a questão da baseline para o mesmo insumo | `gerar_pares_questoes.py` |
| `caderno/caderno_especialista.html` | O caderno cego com os 40 itens (abre no navegador e imprime) | `montar_caderno.py` |
| `caderno/ficha_respostas.csv` | A planilha em que o especialista registra as notas | `montar_caderno.py` |
| `caderno/chave_caderno.csv` | A origem de cada item. **Não** deve ser entregue ao especialista | `montar_caderno.py` |
| `resultados/tabela_avaliacao_especialista.md` | Tabelas do artigo e do TCC, depois de preenchida a ficha | `analisar_caderno.py` |

Os scripts ficam em `scripts/avaliacao_especialista/`.

---

## Parte B — Protocolo, métodos e resultados

### 1. Experimento 1 — Seleção do modelo avaliador

#### 1.1 Base experimental (280 questões)

**Autênticas: 140 questões**
- Questões de Matemática do ENEM (2009–2024), só texto, tiradas do dataset histórico (`data/itens_prova_2009_2024_llm_texto.csv`).
- São **5 por habilidade** nas **28 habilidades ativas**.
- **H06 e H20 ficam de fora.** Elas dependem de mapas e gráficos, e o dataset tem só 5 itens sem imagem para as duas juntas. Por isso a base tem 280 itens, e não 300.

**Com erro: 140 questões**
- São versões modificadas das mesmas 140 autênticas, uma por questão, com **35 de cada tipo de erro**:

| Tipo | O que muda |
| :--- | :--- |
| GABARITO | O gabarito indicado não é a resposta correta |
| CALCULO | Um dado do enunciado muda e nenhuma alternativa fica correta |
| AMBIGUIDADE | O enunciado admite mais de uma leitura, com respostas diferentes |
| CONTRADICAO | Duas informações do enunciado se contradizem |

**Como os erros foram inseridos**
- As modificações foram geradas por três LLMs de mercado, pela interface web. Cada LLM recebeu 12 lotes de 3 ou 4 questões, cada lote com um único tipo de erro.

| LLM adulterador | Itens | Versão registrada | Data |
| :--- | ---: | :--- | :--- |
| GPT | 47 | GPT-6 Luna (ChatGPT web; Think) | 27/10/2026 |
| DeepSeek | 47 | DeepSeek-V4.1 Flash (web; DeepThink) | 27/10/2026 |
| Gemini | 46 | Gemini 3.8 Flash (raciocínio medium) | 27/10/2026 |

- Os prompts estão em `data/experimento1/lotes/` e as respostas, em `data/experimento1/adulteracoes_brutas/`. Cada lote foi enviado numa conversa nova, para que um lote não influenciasse o seguinte.

**Conferência dos erros, antes de usar a base**
1. **Checagem automática** (`validar_adulteracoes.py`): confere o formato da resposta, se o tipo de erro é o pedido e se a modificação foi mínima.
2. **Revisão item a item** numa página de revisão (`revisao/`). O critério é que cada versão modificada tenha **um único defeito, objetivo e do tipo declarado**.
   - Uma versão é rejeitada se a informação retirada continua no texto ou nas alternativas, se a troca parece só um erro de redação, ou se a mudança cria um defeito extra.
3. **Reenvio dos itens rejeitados:** 10 lotes, em 11/11/2026, aos mesmos LLMs, seguidos de nova revisão.
4. **Ajuste manual pontual em 9 itens**, quando a ideia do LLM era boa mas a redação precisava de correção. Cada ajuste está descrito na coluna `ajuste_manual` da chave.

Ao final, as 140 versões modificadas foram aprovadas na revisão.

**Base cega**
- Autênticas e modificadas foram embaralhadas em `base_experimento.jsonl`, sem nenhum rótulo.
- A chave, com o que é autêntico e qual é o erro de cada item, fica separada em `base_experimento_chave.csv`.
- Os modelos avaliadores nunca veem a chave.

#### 1.2 O que cada modelo faz com cada questão (Etapa 4 do VERA, perfil `enem`)

1. **4.1 Resolução cega:** o modelo recebe só o enunciado, sem alternativas e sem gabarito.
   - Ele resolve a questão e escreve um pequeno programa Python (`def resolver():`) que faz a conta. O programa roda isolado, e o número calculado substitui a conta "de cabeça".
   - O item é reprovado se o modelo declarar que a pergunta não tem resposta (`NAO_RESPONDIVEL`) ou que precisou assumir premissas que o enunciado não dá (`PREMISSA_OCULTA`).
2. **4.2 Confronto com o gabarito:**
   - **Alternativas numéricas:** a resposta da resolução cega é comparada a elas em Python.
   - **Alternativas não numéricas:** o modelo escolhe a alternativa a partir da própria resolução, ainda sem ver o gabarito.
   - O item é reprovado se a alternativa obtida não for a do gabarito informado.
3. **4.3 Auditoria pedagógica:** 5 perguntas de sim ou não, uma por critério, parando no primeiro defeito. O auditor **não vê o gabarito**.

A questão é **aprovada** se passar pelas três etapas e **reprovada** se parar em qualquer uma.

#### 1.3 Pipeline v1 (piloto), calibração e pipeline v2

**Piloto v1**
- Foi uma primeira rodada completa com o Qwen2.5, guardada em `avaliacoes/_piloto_v1/`. Ele aprovou só 54 das 280 questões e **reprovou 74% das autênticas**.
- O diagnóstico encontrou problemas na própria pipeline, que afetariam qualquer modelo:
  - O critério "dados não utilizados" reprovava questões normais do ENEM, que costumam trazer dados que não entram na conta.
  - O exemplo de resposta no prompt de mapeamento era `["B"]`, e o modelo respondia B em 50% dos casos.
  - O auditor via o gabarito, o que favorecia concordar com ele.
  - O modelo fazia as contas em texto e errava muito.
  - Algumas alternativas, como razões do tipo "1 : 100", não eram lidas como número.
  - Havia erros de leitura de JSON com barras invertidas.

**Calibração e pipeline v2**
- As correções foram estruturais, sem ajuste para nenhum item específico, e formam a pipeline v2.
- Para **não ajustar a pipeline na base de teste**, elas foram conferidas antes num **conjunto de calibração**: 30 autênticas sorteadas fora da amostra de 140, com semente 7 (`calibracao.jsonl`). Nessa calibração, o Qwen2.5 aprovou 9 das 30.
- Só depois disso os 4 modelos rodaram na base de 280 com a pipeline v2.

#### 1.4 Condições de execução

| Item | Valor |
| :--- | :--- |
| Hardware | GPU NVIDIA RTX 4090 (24 GB) |
| Ollama | 0.40.16 |
| Threads de CPU (`LLM_NUM_THREAD`) | 4 |
| Temperatura nas chamadas da Etapa 4 | 0,0 |
| Raciocínio ("thinking") | Qwen3 **desligado**; DeepSeek-R1 **ligado**, porque o modelo é feito para raciocinar. Orçamento de raciocínio: 8192 tokens, contexto de 16384 |

| Modelo | Tag no Ollama | Digest |
| :--- | :--- | :--- |
| Qwen2.5 7B | `qwen2.5:7b-instruct-q4_K_M` | `845dbda0ea48` |
| Qwen3 8B | `qwen3:8b-q4_K_M` | `500a1f067a9f` |
| Llama 3.1 8B | `llama3.1:8b-instruct-q4_K_M` | `46e0c10c039e` |
| DeepSeek-R1 8B | `deepseek-r1:8b` | `6995872bfe4c` |

Os 4 modelos rodaram no **mesmo hardware**, com a mesma versão do Ollama e da pipeline. Isso importa: numa rodada de teste, o mesmo modelo deu resultados diferentes em outra máquina.

#### 1.5 Métricas

As métricas são calculadas por `scripts/experimento1/analisar_resultados.py`:

- **Acurácia nas autênticas:** % das 140 autênticas em que o modelo chegou à alternativa do gabarito oficial.
- **Precisão, recall e F1** na detecção: a classe positiva é "questão com erro" e a predição positiva é "reprovada".
- **Falso positivo:** % das autênticas reprovadas.
- **Tempo médio por avaliação.**
- **Falhas técnicas:** resposta vazia ou JSON inválido do modelo, ou erro do servidor. Ficam **fora** da precisão e do recall, porque não são veredito, e contam como não resolvidas na acurácia.
- **Comparação estatística:** teste de **McNemar exato**, pareado item a item, entre o modelo de maior F1 e cada um dos outros, sobre o acerto do veredito.

#### 1.6 Resultados

| Modelo | Acurácia nas autênticas | Precisão | Recall | F1 | Falso positivo | Tempo médio | Falhas técnicas |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **Qwen3 8B** | **61,4%** | **0,644** | 0,814 | **0,719** | **45,0%** | 7,4 s | 0 |
| DeepSeek-R1 8B | 43,6% | 0,502 | 0,963 | 0,660 | 85,2% | 45,2 s | 49 |
| Qwen2.5 7B | 43,6% | 0,556 | 0,779 | 0,649 | 62,1% | 4,7 s | 0 |
| Llama 3.1 8B | 21,4% | 0,507 | 0,831 | 0,630 | 77,8% | 5,3 s | 15 |

**Recall por tipo de erro**

| Modelo | Gabarito | Cálculo | Ambiguidade | Contradição |
| :--- | ---: | ---: | ---: | ---: |
| Qwen3 8B | 88,6% | 94,3% | 71,4% | 71,4% |
| DeepSeek-R1 8B | 100,0% | 100,0% | 93,1% | 91,3% |
| Qwen2.5 7B | 82,9% | 82,9% | 77,1% | 68,6% |
| Llama 3.1 8B | 74,3% | 78,6% | 100,0% | 79,4% |

**McNemar, Qwen3 contra os demais**

| Comparação | p-valor |
| :--- | :--- |
| × DeepSeek-R1 | < 0,001 |
| × Qwen2.5 | 0,002 |
| × Llama 3.1 | < 0,001 |

**Escolha: Qwen3 8B, sem raciocínio, como avaliador.**
- O orientador pediu atenção especial à capacidade de **não aprovar questões com erro**, que é o recall. Por esse critério isolado, o DeepSeek-R1 (0,963) e o Llama 3.1 (0,831) ficam à frente do Qwen3 (0,814).
- Mas o recall sozinho é enganoso: um avaliador que reprova tudo teria recall de 100% e seria inútil. O DeepSeek-R1 chega a 0,963 reprovando também 85% das autênticas.
- Por isso, a escolha usa o **F1**, que junta o recall com a precisão. O Qwen3 é o que barra a maior parte das questões com erro (81%) sem reprovar demais as boas.
- Teve o maior F1 e a maior acurácia, o menor falso positivo e nenhuma falha técnica.
- É estatisticamente superior aos outros três.

**Leitura dos resultados**
- O DeepSeek-R1 tem o maior recall, mas reprova 85% das autênticas, ou seja, não discrimina. Também é cerca de 6 vezes mais lento e teve 17,5% de falhas técnicas.
- Ambiguidade e contradição são os erros mais difíceis de detectar, porque são defeitos de redação, e não de conta.

**Limitação**
- Mesmo o melhor avaliador reprova 45% das autênticas. Sem acesso ao gabarito, qualquer erro de resolução do modelo vira reprovação.
- Por isso, o falso positivo é limitado pela capacidade de um modelo de 7 a 8B no ENEM.

Os resultados estão em `data/experimento1/resultados/` e os dados brutos, em `data/experimento1/avaliacoes/rtx4090__*.jsonl`.

---

### 2. Experimento 2 — Seleção do modelo gerador

#### 2.1 Desenho

| Item | Valor |
| :--- | :--- |
| Geradores | Qwen2.5 7B, Qwen3 8B (sem raciocínio), Llama 3.1 8B |
| Avaliador | Qwen3 8B sem raciocínio, o escolhido no Experimento 1 |
| Pedidos | 28 habilidades × 5 = **140 por gerador**, 420 no total |
| Tentativas por pedido | **1** (sem nova tentativa com dica de correção) |
| Ordem das habilidades | Rodízio, embaralhado com semente fixa (2026), igual para todos os geradores |
| Few-shot RAG | 2 exemplos históricos por pedido |
| Temperaturas | 0,2 no enunciado (Fase 2A), 0,0 no solver (Fase 2B) e 0,0 na avaliação |

**Duas fases por pedido**
1. **Geração, com o gerador:** Etapas 1 a 3 do VERA, que incluem:
   - a busca de exemplos (RAG);
   - o enunciado;
   - o solver Python;
   - a execução isolada;
   - o nexo numérico e a complexidade;
   - a montagem das alternativas.

   Se o pedido falhar nessa fase, ele é reprovado ali mesmo. Se passar, a questão é gravada como **pendente de avaliação**.
2. **Avaliação, com o avaliador:** a Etapa 4 completa (perfil `gerada`) roda sobre todas as pendentes:
   - resolução cega;
   - confronto com o gabarito;
   - auditoria pedagógica.

**Por que separar as fases e usar uma tentativa por pedido**
- **Separar as fases:** a GPU disponível tem 4 GB e só comporta um modelo por vez. No fluxo original, gerador e avaliador se alternam várias vezes em cada tentativa, e cada troca obriga a recarregar o modelo. Separar as fases elimina essas trocas.
- **Uma tentativa por pedido:** sem retentativas, a comparação mede só a capacidade de cada gerador, sem a ajuda do mecanismo de correção. O número médio de tentativas até a aprovação passa a ser estimado por `1 ÷ taxa de aprovação`.

#### 2.2 Exclusão do DeepSeek-R1

O DeepSeek-R1 8B foi excluído do Experimento 2 por dois motivos medidos no Experimento 1:
- **Falhas de formato na saída estruturada:** 49 de 280 itens (17,5%), contra no máximo 15 (5,4%) dos demais.
- **Tempo de inferência cerca de seis vezes maior:** 45,2 s, contra 4,7 a 7,4 s por item.

As Fases 2A e 2B exigem JSON num formato rígido. Com o DeepSeek, as falhas técnicas se confundiriam com falhas de qualidade das questões, e o tempo tornaria a geração inviável no hardware disponível.

#### 2.3 Condições de execução

| Item | Valor |
| :--- | :--- |
| Hardware | Notebook com GPU NVIDIA RTX 3050 Laptop (4 GB) |
| Ollama | 0.34.1 |
| Período | 15/11/2026, em três rodadas: 00h26–08h26, 09h52–17h52 e 18h16–21h05 |
| Digests | Os mesmos do Experimento 1 |

Os três geradores e o avaliador rodaram no mesmo hardware. Os tempos do Experimento 2 não são comparáveis aos do Experimento 1, porque o hardware é outro.

#### 2.4 Métricas

As métricas são calculadas por `python scripts/experimento2/experimento2.py resumo`:

- **% de questões aprovadas:** aprovadas ÷ pedidos com veredito final.
- **Tentativas por aprovada:** 1 ÷ taxa de aprovação.
- **Tipos e frequência dos erros:** etapa em que cada tentativa foi reprovada.
- **Tempo por questão aprovada:** todo o tempo de geração e avaliação do gerador ÷ aprovadas.
- **Falhas técnicas:** o avaliador não chegou a um veredito. Ficam fora da taxa.
- **Comparação estatística:** qui-quadrado entre os três geradores e teste exato de Fisher entre pares.

#### 2.5 Resultados

| Gerador | Pedidos | Passaram na Etapa 3 | Aprovadas | % aprovadas | Tentativas por aprovada | Tempo por aprovada |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| **Qwen2.5 7B** | 140 | 61 | **28** | **20,0%** | **5,0** | **10,9 min** |
| Qwen3 8B | 140 | 54 | 26 | 18,6% | 5,4 | 18,7 min |
| Llama 3.1 8B | 140 (1 falha técnica) | 49 | 14 | 10,1% | 9,9 | 23,7 min |

**Onde as tentativas foram reprovadas**

| Etapa | Llama 3.1 | Qwen2.5 | Qwen3 |
| :--- | ---: | ---: | ---: |
| 2A — enunciado e planejamento | 5 | 2 | 21 |
| 2B — solver | 11 | 11 | 9 |
| 3 — execução do solver | 25 | 28 | 33 |
| 3 — nexo numérico e complexidade | 50 | 38 | 23 |
| 4.1 — dados ociosos | 3 | 1 | 0 |
| 4.1 — não respondível | 6 | 2 | 3 |
| 4.1 — premissa oculta | 8 | 3 | 3 |
| 4.2 — confronto com o gabarito | 17 | 26 | 21 |
| 4.3 — auditoria pedagógica | 0 | 1 | 1 |

**Comparação estatística**

| Comparação | Teste | p-valor |
| :--- | :--- | :--- |
| Entre os três | Qui-quadrado (χ² = 5,91) | 0,052 |
| Qwen2.5 × Llama 3.1 | Fisher | 0,029 |
| Qwen3 × Llama 3.1 | Fisher | 0,059 |
| Qwen2.5 × Qwen3 | Fisher | 0,88 |

**Leitura dos resultados**
- **O Qwen2.5 foi o melhor gerador:** maior taxa de aprovação, menos tentativas e o menor tempo por questão aprovada.
- **Qwen2.5 e Qwen3 estão empatados na taxa de aprovação** (p = 0,88). O Qwen2.5 se destaca pelo tempo, porque é menor e mais rápido.
- **O Llama 3.1 aprova cerca de metade.** A diferença para o Qwen2.5 é significativa (p = 0,03), e ele é o que mais falha no nexo numérico.
- **A maior parte das reprovações acontece antes do avaliador,** nas checagens determinísticas da Etapa 3. Na avaliação, quase tudo é barrado no confronto (4.2), e a auditoria (4.3) quase não reprova.
- **O teste entre os três ficou no limite** (p = 0,052). Com 140 pedidos por gerador, a amostra é pequena para separar modelos tão parecidos.

**Limitações**
- **O avaliador também é um dos geradores.** O Qwen3 avaliou as próprias questões, o que poderia favorecê-lo. Mesmo assim, o Qwen2.5 ficou à frente.
- **O avaliador não é perfeito:** no Experimento 1, ele reprovou 45% das autênticas e deixou passar 19% das questões com erro. O falso positivo baixa a taxa de todos os geradores por igual. Já a validação humana é que mostra quantas das aprovadas estão realmente corretas.
- **Uma tentativa por pedido** mede o gerador sozinho. No uso normal do VERA, com até 5 tentativas e dica de correção, a taxa por pedido seria maior.

Os resultados estão em `data/experimento2/resultados/tabela_experimento2.md`. As 420 questões, com o veredito de cada uma, estão em `data/experimento2/questoes_geradas.jsonl` e no SQLite.

#### 2.6 Validação humana (caderno pronto, aguardando o especialista)

A validação humana do Experimento 2 e a comparação com a baseline zero-shot exigida pela monografia (R7) usam **o mesmo caderno**, para o especialista avaliar cada questão uma única vez.

- **Itens (40, misturados, sem indicar a origem):**
  - 10 aprovadas do Qwen2.5. São as questões da VERA nos 10 pares do TCC, uma por habilidade, sorteadas com semente 2026 entre as aprovadas;
  - 10 aprovadas do Llama 3.1 e 10 do Qwen3, sorteadas com semente 2026, uma por habilidade antes de repetir;
  - 10 da baseline: o mesmo Qwen2.5, para a mesma habilidade, tema, abertura e tipologia de cada questão da VERA nos pares, com o mesmo prompt de redação, mas sem RAG, sem exemplo few-shot, sem PoT e sem validação. O próprio modelo escreve as alternativas e o gabarito.
- **Cegamento:** o caderno não diz a origem de nenhum item. As duas questões de um mesmo par ficam a pelo menos 8 posições de distância, para o especialista não compará-las lado a lado.
- **Rubrica, igual para todos os itens:**
  - **Escala Likert de 1 a 5:** os 5 critérios da monografia para questões inéditas:
    1. plausibilidade da situação-problema;
    2. clareza e inequivocidade do comando;
    3. qualidade pedagógica dos distratores;
    4. adequação do grau de dificuldade ao ENEM;
    5. alinhamento à habilidade.
  - **Sim/Não:** dados suficientes e coerentes, gabarito correto e "usaria na prova?".
  - Os critérios Sim/Não da versão anterior do caderno (enunciado claro, distratores plausíveis, habilidade alinhada e contexto realista) passaram a ser os critérios Likert equivalentes. Nas tabelas, a nota ≥ 4 corresponde ao antigo "Sim".
- **Medidas para o artigo (por gerador, só aprovadas):**
  - % de gabarito correto;
  - % de dados coerentes;
  - % "aprovada pelo especialista" (as duas coisas ao mesmo tempo);
  - % "usaria na prova";
  - média e % de notas ≥ 4 em cada critério Likert.
- **Medidas para o TCC (10 pares):**
  - média da VERA e da baseline em cada critério e teste de Wilcoxon pareado;
  - % de gabarito correto em cada condição;
  - regra de aceitação da monografia: VERA ≥ baseline na média de todos os critérios.
- **Mais de um avaliador (recomendado para o artigo):**
  - cada um preenche a sua ficha de forma independente;
  - a análise usa a média das notas e a maioria nas respostas Sim/Não;
  - a análise também mede a concordância entre eles.
- **Limitação:** as questões da VERA nos pares já passaram pelo filtro de validação, e as da baseline não. A comparação mede o sistema completo (geração e filtro), não só a geração.

---

### 3. Reprodução

```bash
# Experimento 1: avaliação (um modelo por vez) e tabela
python scripts/experimento1/avaliar_base.py --modelo qwen3:8b-q4_K_M --think false --rotulo rtx4090
python scripts/experimento1/analisar_resultados.py

# Experimento 2: geração com cada gerador, avaliação e tabela
# (cada comando retoma de onde parou; --prazo "AAAA-MM-DD HH:MM" limita o horário de cada rodada)
python scripts/experimento2/experimento2.py gerar --modelo qwen2.5:7b-instruct-q4_K_M
python scripts/experimento2/experimento2.py gerar --modelo llama3.1:8b-instruct-q4_K_M
python scripts/experimento2/experimento2.py gerar --modelo qwen3:8b-q4_K_M --think false
python scripts/experimento2/experimento2.py avaliar --avaliador qwen3:8b-q4_K_M --think false
python scripts/experimento2/experimento2.py resumo
```

A construção da base do Experimento 1, passo a passo e com o script de cada etapa, está na Parte A, na tabela do Experimento 1.

O caderno do especialista e a análise das fichas preenchidas:

```bash
python scripts/avaliacao_especialista/gerar_pares_questoes.py   # pares VERA × baseline (usa o Ollama)
python scripts/avaliacao_especialista/montar_caderno.py
python scripts/avaliacao_especialista/analisar_caderno.py ficha_prof1.csv [ficha_prof2.csv ...]
```
