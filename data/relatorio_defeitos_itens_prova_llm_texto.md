# Relatório de defeitos — `itens_prova_2009_2024_llm_texto.csv`

## Contexto

O arquivo `itens_prova_2009_2024_llm_texto.csv` (510 itens de Matemática do ENEM 2009–2024,
separador `;`, UTF-8 com BOM) é consumido por um sistema que usa as questões como
**referência de questões corretas**: elas alimentam um banco vetorial (RAG) e uma amostra
experimental em que cada questão é tratada como item válido e sem defeitos.

Uma varredura automática encontrou **13 itens** cuja transcrição do PDF corrompeu
enunciado ou alternativas a ponto de tornar a questão **irrespondível ou ambígua**.
O problema está na conversão PDF → texto, não na prova original.

**Pedido:** corrigir os 13 itens a partir dos PDFs originais (coluna `REF_ARQUIVO_PDF`,
posição `CO_POSICAO`), mantendo o formato atual do CSV (mesmas colunas, LaTeX entre `$...$`,
tabelas em Markdown dentro de `DESC_ENUNCIADO`), e incorporar ao pipeline de extração as
verificações da seção "Checagens de regressão sugeridas".

## Padrões de corrupção identificados

1. **Subscritos/índices descolados do símbolo.** Os índices saem como uma sequência de dígitos
   ou letras no fim da linha, e o símbolo fica sem índice.
   Ex.: `tipo I, pois p < p < p . 1 2 3` deveria ser `tipo I, pois $p_1 < p_2 < p_3$.`;
   `R .` deveria ser `$R_1$.`
2. **Matrizes, binomiais e frações empilhadas desmontadas.** Estruturas em várias linhas viram
   parênteses vazios e números soltos. Ex.: `$( )\cdot( ) (2 3) (Y ) (1 2) ( X )$`.
3. **Trecho inicial de alternativa perdido.** Uma fração ou expressão que abre a alternativa some
   e restam só o conectivo e o texto. Ex.: `, o que mostra que Antônio tem mais chances de acertar.`
4. **LaTeX mal delimitado.** Há `$` dentro de `\frac{...}` ou texto comum dentro de `$...$`.
   Ex.: `\frac{m_{1}$m_{2}$}{d^{2}}`; `$O valor de \frac{A_{1}}{A_{2}} é$`.
5. **Símbolos perdidos dentro de fórmulas.** Ex.: `L / (2 2)`, provavelmente `L/(2\sqrt{2})`.
6. **Conteúdo visual transcrito sem a informação essencial.** Ex.: uma nuvem de palavras em que a
   resposta depende do tamanho da fonte.
7. **Enunciado truncado.**

## Itens afetados

Prioridade **ALTA**: o item está na amostra experimental e bloqueia o experimento.
Prioridade **MÉDIA**: o item está apenas no acervo RAG.

| CO_ITEM | Hab. | Ano | Posição | Cor | PDF | Prioridade | Padrão |
|---|---|---|---|---|---|---|---|
| 111626 | H09 | 2022 | 180 | AMARELA | `ENEM_2022_P2_CAD_05_DIA_2_AMARELO.pdf` | ALTA | 1 |
| 70496 | H29 | 2011 | 159 | Cinza | `ENEM_2011_P2_CAD_06_DIA_2_CINZA.pdf` | ALTA | 3 |
| 83220 | H19 | 2022 | 146 | AMARELA | `ENEM_2022_P2_CAD_05_DIA_2_AMARELO.pdf` | ALTA | 2 |
| 141540 | H29 | 2023 | 157 | AMARELA | `ENEM_2023_P1_CAD_05_DIA_2_AMARELO.pdf` | ALTA | 1 |
| 72821 | H08 | 2011 | 151 | Cinza | `ENEM_2011_P1_CAD_06_DIA_2_CINZA_LEDOR.pdf` | ALTA | 7 |
| 9214 | H09 | 2012 | 165 | AMARELA | `caderno_enem2012_dom_amarelo.pdf` | MÉDIA | 5 |
| 38786 | H03 | 2016 | 168 | AMARELA | `CAD_ENEM_2016_DIA_2_05_AMARELO.pdf` | MÉDIA | 1 |
| 44285 | H08 | 2023 | 160 | AMARELA | `ENEM_2023_P2_CAD_05_DIA_2_AMARELO.pdf` | MÉDIA | 1, 4 |
| 47309 | H02 | 2022 | 150 | AMARELA | `ENEM_2022_P1_CAD_05_DIA_2_AMARELO.pdf` | MÉDIA | 2 |
| 60335 | H02 | 2024 | 139 | AMARELA | `ENEM_2024_P1_CAD_05_DIA_2_AMARELO.pdf` | MÉDIA | 2 |
| 38236 | H25 | 2023 | 176 | AMARELA | `ENEM_2023_P2_CAD_05_DIA_2_AMARELO.pdf` | MÉDIA | 2 |
| 26563 | H10 | 2018 | 146 | Amarela | `ENEM_2018_P2_CAD_05_DIA_2_AMARELO.pdf` | MÉDIA | 4 |
| 31817 | H01 | 2018 | 138 | Amarela | `ENEM_2018_P2_CAD_05_DIA_2_AMARELO.pdf` | MÉDIA | 6 |

### Evidências por item

- **111626**: as 5 alternativas são idênticas (`R .`). Faltam os índices `$R_1$` … `$R_5$`, que
  aparecem corretamente nas tabelas do enunciado.
- **70496**: as alternativas perderam a razão numérica inicial. Sobraram só
  `, o que mostra que Antônio/José tem mais chances de acertar.`, com A = B = D e C = E.
- **83220**: as 5 alternativas são produtos de matrizes desmontados
  (`$( )\cdot( ) (2 3) (Y ) (1 2) ( X )$`). O enunciado termina com o lixo `(1 1) ( X )`
  depois da pergunta.
- **141540**: nas alternativas A e D, `p < p < p . 1 2 3` e `p < p < p . 3 2 1`. No enunciado,
  `as probabilidades de se 1 2 3 descobrirem`, em que os índices de p₁, p₂, p₃ caíram no meio do texto.
- **72821**: o enunciado tem só `Um hexágono regular é invariante por rotações, em torno de seu centro, de`.
  É preciso conferir se falta texto do caderno LEDOR, que costuma descrever a figura.
- **9214**: as alternativas A e D são iguais (`$R \ge L / 2$`), e a E está corrompida (`$R \ge L / (2 2)$`).
- **38786**: as alternativas estão como `d < d < d || A C B`, com os índices dos d separados.
- **44285**: `Sejam A a área de S e A a área de S . 1 1 2 2` deveria ser
  `Sejam $A_1$ a área de $S_1$ e $A_2$ a área de $S_2$`. Além disso, texto comum está dentro de `$...$`.
- **47309**: as alternativas trazem parênteses vazios `( )`, sobra de um binomial ou de uma fração empilhada.
- **60335**: as alternativas trazem parênteses vazios `( ) ( ) ( )` depois das frações.
- **38236**: as alternativas são matrizes desmontadas (`(52 37 43) (46) ( )`, `$46 \left( \right) (43)`).
- **26563**: no enunciado, `F = g \frac{m_{1}$m_{2}$}{d^{2}}`, com `$` dentro de `\frac`, que deveria ser
  `$F = g\frac{m_1 m_2}{d^2}$`. Conferir também se os dados dos satélites, provavelmente de uma
  figura, estão completos.
- **31817**: a nuvem de palavras foi transcrita como lista. A resposta depende do tamanho da fonte
  de cada palavra, informação que se perdeu. Se não houver como descrevê-la em texto, marcar
  `IN_ITEM_IMAGEM = 1`.

## Checagens de regressão sugeridas para o pipeline de extração

Aplicar a cada linha do CSV e falhar, ou sinalizar o item, se alguma regra disparar:

1. **Alternativas distintas:** `len({A, B, C, D, E}) == 5`.
2. **Alternativa não vazia e não truncada:** a alternativa não começa com `,`, `;` ou `:` e
   não fica vazia depois de remover espaços e pontuação.
3. **Delimitadores LaTeX balanceados:** número par de `$` depois de remover `R$` e `US$`.
   Também não pode haver `$` dentro de `{...}`.
4. **Estruturas vazias:** sem `( )`, `{}`, `\left( \right)` vazios.
5. **Índices soltos:** sem padrões como `x < x < x`, `X e X`, ou letra isolada seguida de
   sequência de dígitos (`p . 1 2 3`, `S . 1 1 2 2`).
6. **Texto após a pergunta:** nada além de pontuação depois do último `?` do enunciado.
7. **Enunciado mínimo:** o enunciado tem pelo menos 120 caracteres, ou passa por revisão manual.
8. **Dependência visual:** menção a figura, imagem ou gráfico sem descrição textual
   equivalente leva a `IN_ITEM_IMAGEM = 1`.

Observação: a varredura foi heurística e pode não ter pegado todos os casos.
Depois da correção, vale rodar as checagens 1 a 8 no arquivo inteiro.

## Correção posterior: alternativas cortadas na quebra de linha (2026-11-16)

A revisão visual do caderno de explicações encontrou mais um padrão, que a varredura acima não pegava.

- **Padrão:** a alternativa termina no fim da linha do PDF, e a continuação, na linha seguinte, se perde.
- **Item 73134** (H17, ENEM 2010, posição 150, `ENEM_2010_PROVA_GAB_DIA_2_AZUL_7.pdf`): as alternativas A, B, D e E acabavam em "porque a", "mas", "mas" e "porque o".
- **Correção:** o texto foi refeito a partir da prova original, por exemplo "maior do que o valor da primeira encomenda, mas não o dobro.".
- **Atualizações:** o SQLite e o ChromaDB foram atualizados com `python cli.py seed`.
- **Checagem sugerida:** alternativa terminada em artigo, preposição ou conjunção (`a`, `o`, `de`, `que`, `mas`, `porque`, ...). No arquivo corrigido, nenhum item tem esse padrão.
