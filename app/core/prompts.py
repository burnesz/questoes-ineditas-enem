"""
Módulo de prompts, schemas e contextos criativos para a arquitetura
Program-Aided Generation (PoT) e Validação Cega em 3 sub-etapas (Etapa 4) de Questões do ENEM.
"""

import re
import json
import random
from collections import deque
from typing import Dict, Any, Optional, List, Tuple


# ==============================================================================
# DIVERSIDADE DE CONTEXTO E NARRATIVA
# ==============================================================================

TEMAS_COTIDIANO: List[str] = [
    "Saúde pública, medicina ou nutrição",
    "Práticas esportivas, atletas ou competições",
    "Mobilidade urbana, transporte coletivo ou trânsito",
    "Energia renovável, consumo elétrico ou sustentabilidade",
    "Economia doméstica, planejamento financeiro ou compras",
    "Recursos hídricos, meio ambiente ou meteorologia",
    "Agropecuária, produção de alimentos ou cultivo",
    "Tecnologia da informação, telecomunicações ou dados",
    "Comércio, varejo ou gestão de estoque",
    "Planejamento urbano, saneamento ou habitação",
]

FORMAS_ABERTURA: List[str] = [
    "Inicie apresentando o resultado de uma pesquisa amostral ou levantamento local (ex: 'Em uma pesquisa com 400 clientes...', 'Um levantamento sobre o consumo de água em um condomínio revelou...')",
    "Inicie contextualizando o cenário territorial ou comunitário (ex: 'Em um município...', 'Para interligar dois distritos agrícolas...', 'Uma cooperativa local...')",
    "Inicie descrevendo um processo técnico, produtivo ou logístico (ex: 'Uma linha de envase industrial...', 'Um centro de distribuição organiza o transporte...')",
    "Inicie com uma situação prática de tomada de decisão financeira ou orçamento (ex: 'Um consumidor compara duas opções de parcelamento...', 'Para o orçamento de uma reforma...')",
    "Inicie apresentando um ensaio técnico, medição laboratorial ou monitoramento periódico (ex: 'Durante o monitoramento da vazão de um reservatório...', 'Em um teste de rendimento térmico...')",
    "Inicie relatando o regulamento de uma competição, sistema de pontuação ou evento recreativo (ex: 'Em um torneio escolar...', 'Uma gincana comunitária...')",
    "Inicie com o dimensionamento de um projeto de arquitetura, embalagem ou armazenamento (ex: 'Uma fábrica projeta uma embalagem cilíndrica...', 'O projeto de um galpão de armazenamento...')",
]

_TEMAS_RECENTES: "deque[str]" = deque(maxlen=4)
_ABERTURAS_RECENTES: "deque[str]" = deque(maxlen=3)


def sortear_contexto_criativo() -> Tuple[str, str]:
    """
    Sorteia um tema do cotidiano e uma estrutura narrativa de abertura,
    evitando repetir os últimos sorteados no mesmo processo.
    """
    temas = [t for t in TEMAS_COTIDIANO if t not in _TEMAS_RECENTES] or TEMAS_COTIDIANO
    aberturas = [a for a in FORMAS_ABERTURA if a not in _ABERTURAS_RECENTES] or FORMAS_ABERTURA
    tema, abertura = random.choice(temas), random.choice(aberturas)
    _TEMAS_RECENTES.append(tema)
    _ABERTURAS_RECENTES.append(abertura)
    return tema, abertura


# ==============================================================================
# PROMPTS PARA ARQUITETURA PROGRAM-AIDED (PoT: ENUNCIADO + SOLVER EM PYTHON)
# ==============================================================================

POT_QUESTION_GENERATOR_SYSTEM_PROMPT = """Você é um Elaborador de Itens de Matemática para o ENEM.
Gere uma QUESTÃO INÉDITA em JSON: planejamento + enunciado + (tabela opcional) + solver em Python.
O solver calcula a resposta correta e 4 distratores. NÃO gere letras A-E nem gabarito.

=== REGRAS (em ordem de importância) ===

1. A PERGUNTA FINAL SEMPRE PEDE UM NÚMERO.
   As alternativas serão 5 valores numéricos. Portanto o comando final deve pedir uma quantidade, valor, média, percentual, área etc.
   NUNCA pergunte "qual plano", "qual embalagem", "qual opção é mais vantajosa" (a resposta seria um nome, não um número).
   RUIM: "Qual plano será mais econômico?" (alternativas: 190, 205, 185...)
   BOM:  "Qual é o custo total, em reais, do plano mais econômico?"
   Informe sempre a unidade pedida no comando final (reais, litros, km, %...).

2. NÍVEL MÍNIMO: pelo menos 2 ETAPAS DE RACIOCÍNIO.
   PROIBIDO: apenas somar uma coluna, apenas ler um valor da tabela, ou aplicar uma única fórmula direta.
   Exemplos de etapas: converter unidades, calcular uma média ponderada, aplicar porcentagem sobre porcentagem,
   comparar duas opções e então calcular a diferença, usar proporção/regra de três, calcular área e depois custo.
   RUIM: "Qual foi a quantidade total de papel recolhida nos três dias?" (só somar)
   BOM:  "Qual é o custo total para encher a piscina, sabendo que ela é um bloco retangular e que cada m³ custa R$ X?"

3. NENHUMA INFORMAÇÃO OCULTA (premissa implícita).
   O aluno precisa conseguir resolver SÓ com o que está escrito.
   - Se pedir "por hectare", "por pessoa", "por viagem", o enunciado deve dar a base (a área, o número de pessoas...).
   - Se a tabela tiver percentuais, diga de QUÊ cada percentual é (ex.: "percentual dos moradores de cada faixa etária") e
     informe o tamanho de cada grupo, para permitir a média ponderada.
   - Se o resultado não for exato, o enunciado deve dizer como arredondar. Prefira dados que deem resultado exato ou com no máximo 2 casas decimais exatas (evite dízimas como 2766,666...).

4. TODO DADO DEVE TER FUNÇÃO.
   Cada número do enunciado/tabela deve ser usado no cálculo. Máximo de UMA coluna/linha extra de distração, e somente se for relevante ao contexto.
   Não cite tempos, medidas ou valores que não entram em nenhuma regra de cálculo.
   RUIM: listar os tempos de um atleta e dar uma tabela de pontos fixos por prova (os tempos não são usados).

5. CONSISTÊNCIA ENTRE TEXTO E TABELA.
   Se o texto citar um total (ex.: "trajeto de 15 km"), a tabela deve somar exatamente esse total. Se citar "uma semana", a tabela deve ter 7 dias (ou diga "nos cinco primeiros dias" de forma coerente).
   Se o texto citar quantidade de itens (ex.: "10 estações"), a tabela deve ter exatamente essa quantidade de linhas/trechos.

6. VEROSSIMILHANÇA NUMÉRICA E LÓGICA. Use ordens de grandeza reais:
   - consumo residencial de água: 100 a 250 litros por pessoa por dia (NUNCA 4 ou 5 litros por casa)
   - tempo de 50 m livre: 22 a 35 segundos (use SEGUNDOS, não minutos decimais); 100 m livre: 48 a 70 s
   - corrida de bicicleta (etapa): 40 a 200 km; ônibus urbano: tarifa de R$ 4 a R$ 6
   - treino: use "calorias GASTAS" (consumir calorias = ingerir)
   - esporte e equipamento devem combinar (nada de capacete no futebol de campo; use ciclismo, skate, etc.)
   - tabelas devem ter dados IRREGULARES, não progressões aritméticas óbvias (20, 25, 30, 35).
   Use palavras exatas: a pergunta só pode falar de "dia", "semana", "mês" se a tabela falar do mesmo período.

7. DISTRATORES = ERROS TÍPICOS DE ALUNOS (nunca fórmula aleatória).
   PROIBIDO: correta ± valor fixo, correta × 0,8, correta × 1,2, correta × 1,1 ou × 0,9.
   Cada distrator deve ser calculado por uma VARIÁVEL com nome do erro. Exemplos de erros reais:
   - média simples no lugar da ponderada; esquecer uma linha/grupo; trocar os pesos
   - somar percentuais em vez de aplicar em sequência; aplicar o percentual sobre a base errada
   - dividir pelo número errado de itens; esquecer de converter unidade (m para cm, min para s)
   - responder só a etapa intermediária; confundir área com perímetro; inverter a razão
   Os 4 distratores devem ser números DIFERENTES entre si e da correta, positivos, com a mesma unidade e a mesma quantidade de casas decimais da correta, sem decimais sem sentido para contagens (não existe 104,4 camisas).

8. TABELA: ISOLAMENTO, CHAVES UNIFORMES E LIMITE DE 6 LINHAS.
   Se usar tabela, no 'enunciado' escreva só o contexto, o anúncio ("A tabela a seguir apresenta...") e a pergunta.
   NUNCA repita os dados da tabela no enunciado (nem em listas, nem em texto corrido, nem com pipes '|').
   Os dados ficam SOMENTE em 'tabela_dados' (lista de dicionários com no MÁXIMO 6 linhas; todas as linhas devem ter exatamente as mesmas chaves/colunas; números em formato JSON: ponto decimal, sem aspas).
   Pode haver questão SEM tabela: nesse caso omita 'tabela_dados' e coloque todos os dados no enunciado.

9. SOLVER: Python puro, função resolver().
   - Declare no início uma variável para cada dado do enunciado/tabela (ex.: preco_original = 250).
   - Nunca use números que não estejam no enunciado ou na tabela (exceto constantes universais, como 100 em porcentagem).
   - Defina a resposta final na variável `correta` e os 4 distratores em variáveis nomeadas iniciadas por `erro_` (ex.: `erro_media_simples`, `erro_soma_percentuais`).
   - NÃO escreva `return` no solver: o sistema coleta automaticamente `correta` e as variáveis `erro_*`.
   - Use round(x, 2) quando necessário.

10. PROIBIDO no enunciado: as palavras "solver", "python", "algoritmo", "código", "distrator", "gabarito".

11. INTEGRIDADE FACTUAL: não invente notícias, pesquisadores nem dados atribuídos a órgãos reais (IBGE, OMS, ministérios).
    Use cenários hipotéticos bem definidos ou pesquisas amostrais locais.

12. SAÍDA: apenas o JSON válido, sem comentários antes ou depois.
    A chave "planejamento" vem PRIMEIRO e é obrigatória: use-a para decidir as etapas, os dados e os erros típicos ANTES de escrever o enunciado.
"""

POT_FEW_SHOT_EXAMPLES: List[str] = [
    # --- Exemplo 1: com tabela, média ponderada, 3 etapas ---
    """{
  "planejamento": "Dados: três turmas com nº de alunos e nota média. Etapas: (1) multiplicar nota média por nº de alunos em cada turma; (2) somar os produtos; (3) dividir pelo total de alunos. Erros típicos: usar média simples; esquecer uma turma; trocar os pesos; esquecer a turma A no divisor.",
  "enunciado": "Em um simulado aplicado em uma escola, três turmas obtiveram notas médias diferentes, conforme a tabela a seguir. Qual foi a nota média, em pontos, de todos os alunos que fizeram o simulado?",
  "tabela_dados": [
    {"Turma": "A", "Alunos": 40, "Nota média": 4},
    {"Turma": "B", "Alunos": 40, "Nota média": 6},
    {"Turma": "C", "Alunos": 20, "Nota média": 8}
  ],
  "erros_tipicos": [
    "Calcular a média aritmética simples das notas sem ponderar pelo número de alunos",
    "Esquecer de incluir a turma C na soma e no divisor",
    "Inverter os pesos das turmas A e C",
    "Esquecer a turma A no cálculo"
  ],
  "solver": "def resolver():\\n    alunos_a, alunos_b, alunos_c = 40, 40, 20\\n    nota_a, nota_b, nota_c = 4, 6, 8\\n    total_alunos = alunos_a + alunos_b + alunos_c\\n    correta = round((alunos_a*nota_a + alunos_b*nota_b + alunos_c*nota_c) / total_alunos, 2)\\n    erro_media_simples = round((nota_a + nota_b + nota_c) / len([nota_a, nota_b, nota_c]), 2)\\n    erro_esqueceu_turma_c = round((alunos_a*nota_a + alunos_b*nota_b) / (alunos_a + alunos_b), 2)\\n    erro_pesos_trocados = round((alunos_c*nota_a + alunos_b*nota_b + alunos_a*nota_c) / total_alunos, 2)\\n    erro_esqueceu_turma_a = round((alunos_b*nota_b + alunos_c*nota_c) / (alunos_b + alunos_c), 2)"
}""",
    # --- Exemplo 2: sem tabela, porcentagens sucessivas ---
    """{
  "planejamento": "Dados: preço R$ 250, desconto de 20%, acréscimo de 10% sobre o valor já com desconto. Etapas: (1) aplicar o desconto; (2) aplicar o acréscimo sobre o resultado. Erros típicos: somar os percentuais (-20% + 10%); parar após o desconto; ignorar o desconto; responder o valor do desconto.",
  "enunciado": "Uma loja de eletrodomésticos anuncia um liquidificador por R$ 250,00. Na promoção de fim de semana, o preço recebe um desconto de 20%. Quem opta pelo pagamento parcelado paga um acréscimo de 10% sobre o valor já com desconto. Qual é o valor total, em reais, pago por um cliente que compra esse liquidificador de forma parcelada na promoção?",
  "erros_tipicos": [
    "Somar algebricamente os percentuais (-20% + 10% = -10%) sobre o preço original",
    "Parar na primeira etapa, informando apenas o preço com desconto à vista",
    "Aplicar apenas o acréscimo de 10% sobre o preço original ignorando o desconto",
    "Calcular apenas o valor absoluto do desconto inicial"
  ],
  "solver": "def resolver():\\n    preco = 250\\n    desconto = 20\\n    acrescimo = 10\\n    com_desconto = preco * (1 - desconto/100)\\n    correta = round(com_desconto * (1 + acrescimo/100), 2)\\n    erro_soma_percentuais = round(preco * (1 - desconto/100 + acrescimo/100), 2)\\n    erro_so_desconto = round(com_desconto, 2)\\n    erro_ignorou_desconto = round(preco * (1 + acrescimo/100), 2)\\n    erro_valor_do_desconto = round(preco * desconto/100, 2)"
}""",
    # --- Exemplo 3: com tabela, conversão de unidades + área + custo ---
    """{
  "planejamento": "Dados: dimensões em metros de dois cômodos e preço do piso por m². Etapas: (1) calcular a área de cada cômodo; (2) somar as áreas; (3) multiplicar pelo preço por m². Erros típicos: somar perímetros no lugar de áreas; esquecer um cômodo; usar o preço sem multiplicar; multiplicar só pelo cômodo maior.",
  "enunciado": "Um proprietário vai trocar o piso de dois cômodos de sua casa e pediu um orçamento. As dimensões dos cômodos estão na tabela a seguir, e o piso escolhido custa R$ 45,00 por metro quadrado, já instalado. Qual será o custo total, em reais, para cobrir os dois cômodos?",
  "tabela_dados": [
    {"Cômodo": "Sala", "Largura (m)": 5, "Comprimento (m)": 6},
    {"Cômodo": "Quarto", "Largura (m)": 3, "Comprimento (m)": 4}
  ],
  "erros_tipicos": [
    "Calcular o perímetro de cada cômodo em vez da área antes de multiplicar pelo preço",
    "Considerar apenas a área da sala no orçamento",
    "Somar as áreas dos dois cômodos esquecendo de multiplicar pelo preço por m²",
    "Considerar apenas a área do quarto no cálculo do custo"
  ],
  "solver": "def resolver():\\n    largura_sala, comp_sala = 5, 6\\n    largura_quarto, comp_quarto = 3, 4\\n    preco_m2 = 45\\n    area_sala = largura_sala * comp_sala\\n    area_quarto = largura_quarto * comp_quarto\\n    correta = (area_sala + area_quarto) * preco_m2\\n    erro_perimetro = (2*(largura_sala+comp_sala) + 2*(largura_quarto+comp_quarto)) * preco_m2\\n    erro_esqueceu_quarto = area_sala * preco_m2\\n    erro_esqueceu_preco = area_sala + area_quarto\\n    erro_so_quarto = area_quarto * preco_m2"
}""",
]


POT_FEW_SHOT_BY_COMPETENCIA: Dict[int, List[str]] = {
    1: [
        POT_FEW_SHOT_EXAMPLES[1],
        """{
  "planejamento": "Dados: 4 opções de prato principal, 3 de bebida e 2 de sobremesa; desconto de 5 reais no combo completo de 35 reais para 20 clientes. Etapas: (1) calcular o total de combinações distintas pelo princípio multiplicativo (4 * 3 * 2); (2) somar ao valor arrecadado com 20 combos com desconto. Erros típicos: somar as opções em vez de multiplicar; esquecer as sobremesas; multiplicar sem o desconto.",
  "enunciado": "Um restaurante universitário oferece um combo promocional em que o cliente escolhe 1 entre 4 pratos principais, 1 entre 3 sucos naturais e 1 entre 2 sobremesas. Para comemorar o aniversário do restaurante, cada combo completo, cujo preço normal é R$ 35,00, recebeu um desconto de R$ 5,00, e um grupo de estudantes comprou exatamente uma unidade de cada combinação distinta possível. Qual foi o valor total, em reais, arrecadado com a venda de todas essas combinações distintas?",
  "erros_tipicos": [
    "Somar as quantidades de opções (4 + 3 + 2) em vez de aplicar o princípio multiplicativo",
    "Multiplicar o número correto de combinações pelo preço cheio de R$ 35,00 sem subtrair o desconto",
    "Calcular apenas o número de combinações possíveis (4 * 3 * 2) sem multiplicar pelo valor pago por combo",
    "Esquecer de incluir as 2 opções de sobremesa na contagem das combinações"
  ],
  "solver": "def resolver():\\n    pratos, sucos, sobremesas = 4, 3, 2\\n    preco_cheio, desconto = 35, 5\\n    total_combinacoes = pratos * sucos * sobremesas\\n    preco_combo = preco_cheio - desconto\\n    correta = total_combinacoes * preco_combo\\n    erro_soma_opcoes = (pratos + sucos + sobremesas) * preco_combo\\n    erro_sem_desconto = total_combinacoes * preco_cheio\\n    erro_so_combinacoes = total_combinacoes\\n    erro_sem_sobremesa = (pratos * sucos) * preco_combo"
}"""
    ],
    2: [
        """{
  "planejamento": "Dados: deslocamento ortogonal de 60 m para leste e 80 m para norte em um terreno, cercado com 3 fios de arame na diagonal. Etapas: (1) calcular a distância em linha reta pela hipotenusa (sqrt(60^2 + 80^2) = 100 m); (2) multiplicar por 3 fios de arame. Erros típicos: somar os catetos (60 + 80) em vez de usar Pitágoras; parar na medida de 1 fio; esquecer de extrair a raiz.",
  "enunciado": "Em um parque ecológico, uma trilha liga o portão de entrada a um mirante por meio de dois trechos perpendiculares: 60 metros na direção leste e, em seguida, 80 metros na direção norte. A administração decidiu instalar uma cerca de proteção em linha reta ligando diretamente o portão ao mirante, utilizando 3 fios paralelos de aço em toda a extensão dessa linha reta. Qual é o comprimento total, em metros, de fio de aço necessário para construir essa cerca?",
  "erros_tipicos": [
    "Somar os comprimentos dos dois trechos perpendiculares (60 + 80) em vez de aplicar o Teorema de Pitágoras",
    "Calcular apenas a distância em linha reta (hipotenusa) esquecendo de multiplicar pelos 3 fios",
    "Multiplicar a diferença entre os trechos (80 - 60) pelos 3 fios",
    "Calcular o perímetro completo do triângulo retângulo (60 + 80 + 100) sem multiplicar pelos 3 fios"
  ],
  "solver": "def resolver():\\n    trecho_leste = 60\\n    trecho_norte = 80\\n    num_fios = 3\\n    distancia_reta = (trecho_leste**2 + trecho_norte**2) ** 0.5\\n    correta = round(distancia_reta * num_fios, 2)\\n    erro_soma_catetos = (trecho_leste + trecho_norte) * num_fios\\n    erro_um_fio = round(distancia_reta, 2)\\n    erro_diferenca = (trecho_norte - trecho_leste) * num_fios\\n    erro_perimetro = round(trecho_leste + trecho_norte + distancia_reta, 2)"
}"""
    ],
    3: [
        POT_FEW_SHOT_EXAMPLES[2]
    ],
    4: [
        """{
  "planejamento": "Dados: reservatório de 1200 L com vazão de entrada de 40 L/min e vazão de saída de 15 L/min, iniciando já com 200 L. Etapas: (1) calcular o volume que falta encher (1200 - 200 = 1000 L); (2) calcular a vazão líquida (40 - 15 = 25 L/min); (3) dividir o volume restante pela vazão líquida. Erros típicos: esquecer de descontar os 200 L iniciais; somar as vazões; dividir apenas pela vazão de entrada.",
  "enunciado": "Um tanque industrial com capacidade total de 1.200 litros já contém inicialmente 200 litros de água. Para completá-lo, abre-se uma torneira que despeja 40 litros por minuto, ao mesmo tempo em que uma válvula de drenagem retira 15 litros por minuto de forma contínua. Mantendo-se essas vazões constantes, em quantos minutos o tanque atingirá sua capacidade máxima?",
  "erros_tipicos": [
    "Esquecer de subtrair os 200 litros iniciais, dividindo 1.200 litros pela vazão líquida",
    "Dividir o volume restante apenas pela vazão de entrada de 40 L/min, ignorando a drenagem",
    "Somar as vazões de entrada e saída (40 + 15) em vez de subtrair",
    "Somar o volume inicial de 200 litros à capacidade total antes de dividir pela vazão líquida"
  ],
  "solver": "def resolver():\\n    capacidade = 1200\\n    volume_inicial = 200\\n    entrada = 40\\n    saida = 15\\n    falta_encher = capacidade - volume_inicial\\n    vazao_liquida = entrada - saida\\n    correta = round(falta_encher / vazao_liquida, 2)\\n    erro_sem_volume_inicial = round(capacidade / vazao_liquida, 2)\\n    erro_sem_saida = round(falta_encher / entrada, 2)\\n    erro_soma_vazoes = round(falta_encher / (entrada + saida), 2)\\n    erro_somou_inicial = round((capacidade + volume_inicial) / vazao_liquida, 2)"
}"""
    ],
    5: [
        """{
  "planejamento": "Dados: plano A cobra R$ 120 fixos mais R$ 3 por entrega; plano B cobra R$ 60 fixos mais R$ 5 por entrega. Etapas: (1) igualar ou comparar os custos para 40 entregas mensais; (2) calcular a economia ao escolher o plano mais barato para 40 entregas (ou o custo do plano mais econômico). Vamos pedir o custo total, em reais, no plano mais econômico para 40 entregas.",
  "enunciado": "Uma cooperativa de entregas analisa duas propostas de contrato mensal com uma empresa de logística:\\n- Plano A: taxa fixa mensal de R$ 120,00 mais R$ 3,00 por entrega realizada;\\n- Plano B: taxa fixa mensal de R$ 60,00 mais R$ 5,00 por entrega realizada.\\nPara um mês em que a cooperativa realizará exatamente 40 entregas, qual será o valor total pago, em reais, caso escolha o plano mais econômico?",
  "erros_tipicos": [
    "Escolher o custo do plano mais caro (Plano B) em vez do mais econômico",
    "Calcular a média aritmética entre os custos dos dois planos",
    "Calcular apenas a parcela variável das 40 entregas no Plano A esquecendo a taxa fixa",
    "Calcular a diferença de custo entre os dois planos em vez do valor total do mais econômico"
  ],
  "solver": "def resolver():\\n    fixo_a, var_a = 120, 3\\n    fixo_b, var_b = 60, 5\\n    entregas = 40\\n    custo_a = fixo_a + var_a * entregas\\n    custo_b = fixo_b + var_b * entregas\\n    correta = min(custo_a, custo_b)\\n    erro_plano_caro = max(custo_a, custo_b)\\n    erro_media_planos = (custo_a + custo_b) / 2\\n    erro_sem_taxa_fixa = var_a * entregas\\n    erro_diferenca = abs(custo_b - custo_a)"
}"""
    ],
    6: [
        POT_FEW_SHOT_EXAMPLES[0],
        POT_FEW_SHOT_EXAMPLES[2]
    ],
    7: [
        POT_FEW_SHOT_EXAMPLES[0]
    ]
}


def _infer_competencia_from_habilidade(habilidade_codigo: Optional[str]) -> Optional[int]:
    """Infere o número da competência (1 a 7) a partir do código da habilidade (H01 a H30)."""
    if not habilidade_codigo:
        return None
    clean = habilidade_codigo.strip().upper()
    if clean.startswith("H") and clean[1:].isdigit():
        num = int(clean[1:])
        if 1 <= num <= 5:
            return 1
        if 6 <= num <= 9:
            return 2
        if 10 <= num <= 14:
            return 3
        if 15 <= num <= 18:
            return 4
        if 19 <= num <= 23:
            return 5
        if 24 <= num <= 26:
            return 6
        if 27 <= num <= 30:
            return 7
    return None


def sortear_few_shot(
    competencia: Optional[int] = None,
    habilidade_codigo: Optional[str] = None
) -> str:
    """
    Retorna um exemplo few-shot alinhado à competência ou habilidade,
    evitando ancorar sempre nos mesmos exemplos genéricos.
    """
    comp = competencia or _infer_competencia_from_habilidade(habilidade_codigo)
    pool = POT_FEW_SHOT_BY_COMPETENCIA.get(comp, []) if comp else []
    if not pool:
        pool = POT_FEW_SHOT_EXAMPLES
    exemplo = random.choice(pool)
    return (
        "--- [EXEMPLO DE FORMATO E DE QUALIDADE ESPERADOS] ---\n"
        "(Copie apenas o FORMATO e o nível de exigência. NÃO copie o tema, os números nem o tipo de cálculo.)\n"
        f"{exemplo}\n"
    )


def build_enunciado_solver_prompt(
    habilidade_codigo: str,
    habilidade_descricao: str,
    competencia: int,
    eixo_tematico: Optional[str] = None,
    exemplos_referencia: Optional[List[Dict[str, Any]]] = None,
    tema: Optional[str] = None,
    abertura: Optional[str] = None,
    tipologia: Optional[str] = None,
    exemplo_few_shot: Optional[str] = None,
    enunciados_recentes: Optional[List[str]] = None,
    alerta_tentativa_anterior: Optional[str] = None
) -> str:
    """
    Constrói prompt estruturado para a Fase 1 da geração PoT (Enunciado + Solver em Python).
    """
    ref_text = ""
    if exemplos_referencia:
        blocos = []
        for idx, ex in enumerate(exemplos_referencia, 1):
            ano = ex.get("ano", "ENEM")
            enun = ex.get("enunciado", "").strip()
            if len(enun) > 900:
                enun = enun[:900].rstrip() + "..."
            gab = str(ex.get("gabarito", "")).strip().upper()
            alts = ex.get("alternativas") or {}
            valor_resp = alts.get(gab, "").strip() if isinstance(alts, dict) and gab else ""
            linha_resp = (
                f"\nResposta Correta Oficial: {valor_resp}"
                if valor_resp
                else (f"\nGabarito Oficial: {gab}" if gab else "")
            )
            bloco = (
                f"--- [Questão Histórica do ENEM {idx} para Ancoragem Isomórfica (ENEM {ano})] ---\n"
                f"Enunciado Real: {enun}"
                f"{linha_resp}"
            )
            blocos.append(bloco)

        ref_text = "\n\n".join(blocos) + (
            "\n\n(Crie uma questão inédita ISOMÓRFICA: mesma lógica matemática e MESMO NÍVEL DE COMPLEXIDADE das questões acima "
            "(número de etapas de raciocínio incluído), com um novo contexto do cotidiano e novos dados numéricos. "
            "Não simplifique para uma soma ou leitura direta de tabela)."
        )
    else:
        ref_text = (
            "(Sem questão de referência: siga os conceitos da habilidade alvo e mantenha o nível do ENEM, "
            "com pelo menos 2 etapas de raciocínio.)"
        )

    secao_recentes = ""
    if enunciados_recentes:
        itens = "\n".join(f"- {e.strip()[:160]}..." for e in enunciados_recentes[-3:] if e and e.strip())
        if itens:
            secao_recentes = f"""
JÁ FORAM GERADOS (NÃO repita contexto, estrutura nem tipo de cálculo):
{itens}
"""

    diretriz_criativa = ""
    if tema or abertura or tipologia:
        linhas_criativas = []
        if tipologia:
            linhas_criativas.append(f"- Tipologia matemática obrigatória para esta questão: {tipologia}.")
        if tema:
            linhas_criativas.append(f"- Contexto temático sugerido: {tema}.")
        if abertura:
            linhas_criativas.append(f"- Abertura narrativa: {abertura}. (Evite começar com 'Um [profissional] está...').")
        diretriz_criativa = "\n" + "\n".join(linhas_criativas)

    bloco_alerta_retry = ""
    if alerta_tentativa_anterior:
        bloco_alerta_retry = (
            f"\nATENÇÃO — ORIENTAÇÃO DE QUALIDADE PARA ESTA TENTATIVA:\n"
            f"- {alerta_tentativa_anterior}\n"
        )

    few_shot = (
        exemplo_few_shot
        if exemplo_few_shot is not None
        else sortear_few_shot(competencia=competencia, habilidade_codigo=habilidade_codigo)
    )

    prompt = f"""{POT_QUESTION_GENERATOR_SYSTEM_PROMPT}

============================================================
ESPECIFICAÇÃO DA HABILIDADE ALVO (MATRIZ DO ENEM):
============================================================
- Código da Habilidade: {habilidade_codigo}
- Competência de Área: {competencia}
- Eixo Temático: {eixo_tematico or 'Matemática e suas Tecnologias'}
- Descrição Oficial do INEP: {habilidade_descricao}

A questão deve EXERCITAR a habilidade acima (não apenas citar o tema). Se a descrição pede, por exemplo, interpretar
gráfico, estimar, comparar ou usar proporção, o raciocínio do aluno precisa envolver exatamente isso.

{ref_text}

{few_shot}
{secao_recentes}============================================================
SUA TAREFA:
============================================================
Gere agora uma QUESTÃO INÉDITA para a habilidade {habilidade_codigo}.{diretriz_criativa}{bloco_alerta_retry}

Antes de responder, confira mentalmente:
[ ] a pergunta pede um NÚMERO com unidade?   [ ] há pelo menos 2 etapas?
[ ] todo dado é usado e nenhum dado essencial falta (base, área, pesos)?   [ ] texto e tabela não se contradizem?
[ ] os valores são realistas?   [ ] 'erros_tipicos' tem exatamente 4 itens e os 4 distratores vêm de variáveis `erro_*` nomeadas (nada de ± fixo, × 0,8, × 1,2)?

Responda EXCLUSIVAMENTE em formato JSON com as chaves 'planejamento', 'enunciado', 'tabela_dados' (opcional), 'erros_tipicos' (4 itens) e 'solver':
{{
  "planejamento": "Dados, etapas de raciocínio e erros típicos que viram distratores...",
  "enunciado": "Texto contextualizado da questão com comando final que pede um número...",
  "tabela_dados": [{{"Coluna1": "A", "Coluna2": 10}}],
  "erros_tipicos": ["Erro 1...", "Erro 2...", "Erro 3...", "Erro 4..."],
  "solver": "def resolver():\\n    # variáveis com os dados do enunciado\\n    correta = ...\\n    erro_tipo_1 = ...\\n    erro_tipo_2 = ...\\n    erro_tipo_3 = ...\\n    erro_tipo_4 = ..."
}}
"""
    return prompt


def build_enunciado_plan_only_prompt(
    habilidade_codigo: str,
    habilidade_descricao: str,
    competencia: int,
    eixo_tematico: Optional[str] = None,
    exemplos_referencia: Optional[List[Dict[str, Any]]] = None,
    tema: Optional[str] = None,
    abertura: Optional[str] = None,
    tipologia: Optional[str] = None,
    enunciados_recentes: Optional[List[str]] = None,
    alerta_tentativa_anterior: Optional[str] = None
) -> str:
    """
    Fase 2A da decomposição PoT:
    Gera apenas 'planejamento', 'enunciado', 'tabela_dados' (opcional, máx 6 linhas) e 'erros_tipicos' (4 itens).
    """
    base = build_enunciado_solver_prompt(
        habilidade_codigo=habilidade_codigo,
        habilidade_descricao=habilidade_descricao,
        competencia=competencia,
        eixo_tematico=eixo_tematico,
        exemplos_referencia=exemplos_referencia,
        tema=tema,
        abertura=abertura,
        tipologia=tipologia,
        enunciados_recentes=enunciados_recentes,
        alerta_tentativa_anterior=alerta_tentativa_anterior
    )
    return (
        base
        + "\nNOTA IMPORTANTE (ETAPA 1A — PLANEJAMENTO E ENUNCIADO):\n"
        "Nesta chamada, gere APENAS 'planejamento', 'enunciado', 'tabela_dados' (ou null) e 'erros_tipicos' (exatamente 4 itens). "
        "NÃO inclua a chave 'solver' ainda.\n"
    )


def build_solver_only_prompt(
    enunciado: str,
    tabela_dados: Optional[List[Dict[str, Any]]],
    planejamento: str,
    erros_tipicos: List[str],
    alerta_tentativa_anterior: Optional[str] = None
) -> str:
    """
    Fase 2B da decomposição PoT:
    Gera apenas o 'solver' (`def resolver(): ...`) condicionado ao enunciado, tabela, planejamento e 4 erros típicos da Fase 2A.
    """
    tabela_json = json.dumps(tabela_dados, ensure_ascii=False) if tabela_dados else "null"
    erros_json = json.dumps(erros_tipicos, ensure_ascii=False)
    bloco_alerta = f"\nATENÇÃO: {alerta_tentativa_anterior}\n" if alerta_tentativa_anterior else ""
    return f"""Você é um programador matemático especialista no ENEM.
Escreva EXCLUSIVAMENTE a função Python `def resolver():` para resolver a questão abaixo e calcular a variável `correta` e as 4 variáveis `erro_*` correspondentes aos 4 erros típicos listados.

REGRAS OBRIGATÓRIAS DO SOLVER:
1. Declare todos os dados do enunciado e da tabela como variáveis locais numéricas dentro de `def resolver():`. NÃO use variáveis externas (como `tabela_dados`).
2. A fatia de cálculo de `correta` deve ter pelo menos 3 operações e 2 tipos distintos de operação.
3. Todo número usado em `correta` deve constar no enunciado/tabela. Se usar π, use o valor declarado no enunciado (ex: 3.14).
4. Defina `correta` e exatamente 4 variáveis começando com `erro_` (ex: `erro_1`, `erro_2`, `erro_3`, `erro_4`), onde cada `erro_*` depende de pelo menos uma variável fundamentada no enunciado/tabela e produz valor distinto de `correta`.
5. NÃO escreva `return` no final da função.{bloco_alerta}

PLANEJAMENTO:
{planejamento}

ENUNCIADO:
{enunciado}

TABELA DE DADOS:
{tabela_json}

4 ERROS TÍPICOS A CODIFICAR NAS VARIÁVEIS `erro_*`:
{erros_json}

Responda EXCLUSIVAMENTE em JSON:
{{
  "solver": "def resolver():\\n    ..."
}}
"""


def _formatar_tabela(tabela_dados: Optional[List[Dict[str, Any]]]) -> str:
    """Renderiza tabela_dados como texto simples para os prompts de validação."""
    if not tabela_dados:
        return ""
    colunas = list(tabela_dados[0].keys())
    linhas = [" | ".join(colunas)]
    for row in tabela_dados:
        linhas.append(" | ".join(str(row.get(c, "")) for c in colunas))
    return "\n".join(linhas)


def build_blind_solving_prompt(
    enunciado: str,
    tabela_dados: Optional[List[Dict[str, Any]]] = None
) -> str:
    """
    Constrói prompt para a Chamada 1 da Fase de Validação: Resolução Cega.
    O LLM recebe o enunciado (e a tabela, se houver), sem alternativas e sem gabarito.
    """
    has_md_table = bool(re.search(r"\|(?:\s*:?-+:?\s*\|)+", enunciado or ""))
    tabela_txt = "" if has_md_table else _formatar_tabela(tabela_dados)
    bloco_tabela = f"\nTABELA DE DADOS:\n{tabela_txt}\n" if tabela_txt else ""

    prompt = f"""Você é um estudante de alto desempenho resolvendo uma questão de Matemática do ENEM.
Resolva usando EXCLUSIVAMENTE o que está escrito no enunciado e na tabela. Não complete lacunas por conta própria.

============================================================
ENUNCIADO DA QUESTÃO:
============================================================
{enunciado}
{bloco_tabela}
============================================================
SUA TAREFA:
============================================================
1. Resolva passo a passo, com rigor, em 'resolucao_passo_a_passo'.
2. Em 'premissas_assumidas', liste TODA suposição que você precisou fazer porque o texto não informa
   (ex.: "assumi que cada parcela tem 1 hectare", "assumi que os grupos têm o mesmo tamanho", "assumi que a pontuação não depende do tempo").
   Se não precisou supor nada, use uma lista vazia [].
3. Em 'dados_nao_utilizados', liste os números ou colunas fornecidos que NÃO entraram na sua resolução. Se todos foram usados, use [].
4. Em 'pergunta_respondivel', informe false se o comando final não puder ser respondido com um número a partir dos dados
   (ex.: pergunta "qual plano?" ou faltam dados). Caso contrário, true.
5. Em 'resultado_obtido', dê o resultado final como TIPO PRIMÁRIO do Python:
   - valor numérico único: apenas o número (int ou float), sem texto nem unidade (ex.: 35.0, 30, 1.9);
   - conclusão conceitual: texto;
   - vários valores: dict (ex.: {{"media": 135.0, "moda": None}}).

Responda EXCLUSIVAMENTE em formato JSON com o schema abaixo:
{{
  "resolucao_passo_a_passo": "Resolução detalhada...",
  "premissas_assumidas": [],
  "dados_nao_utilizados": [],
  "pergunta_respondivel": true,
  "resultado_obtido": "Valor numérico ou conclusão final"
}}
"""
    return prompt


def build_equivalencia_gabarito_prompt(resultado_solver: Any, resultado_obtido: Any) -> str:
    """
    Constrói prompt para a Chamada 2 da Fase de Validação: Confronto Direto de Equivalência.
    Juiz matemático objetivo que confronta o resultado calculado pelo Python com a conclusão da LLM.
    """
    prompt = f"""Você é um Juiz de Equivalência Matemática e Conceitual.
Sua única função é comparar objetivamente os dois resultados abaixo e determinar se eles expressam a mesma resposta matemática/conceitual.

============================================================
RESULTADOS A COMPARAR:
============================================================
- Resultado A (Cálculo do Solver): {resultado_solver}
- Resultado B (Resolução Dedutiva): {resultado_obtido}

============================================================
DIRETRIZES DE EQUIVALÊNCIA:
============================================================
1. Antes de comparar, normalize os valores, as representações matemáticas e as unidades de medida.
2. Considere equivalentes diferenças de formatação, notação, frações, decimais e unidades conversíveis.
3. A ausência de unidade em um resultado não implica divergência, desde que o valor e o contexto sejam compatíveis.
4. Considere o enunciado para verificar a grandeza esperada. Não invente informações nem converta grandezas incompatíveis.
5. Retorne `false` apenas quando houver divergência matemática ou conceitual real. Se as informações forem insuficientes, explique a limitação objetivamente e decida com base nas evidências disponíveis.

Responda EXCLUSIVAMENTE em formato JSON com o schema:
{{
  "equivalentes": bool,
  "explicacao_equivalencia": "Explicação objetiva comprovando a equivalência ou apontando a discrepância encontrada"
}}
"""
    return prompt



AUDITORIA_CRITERIOS_PEDAGOGICOS: Dict[str, str] = {
    "incoerencia_ou_absurdo": (
        "CRITÉRIO 1 (Incoerência ou Absurdo Físico/Semântico): "
        "A situação descrita é absurda, fisicamente impossível ou conceitualmente errada? "
        "(Ex.: consumo de 4 L de água por casa por dia, velocidades/tempos biologicamente impossíveis, "
        "equipamento incompatível com o esporte ou 'consumir calorias' em vez de 'gastar calorias' no treino)."
    ),
    "comando_ambiguo_ou_incompativel": (
        "CRITÉRIO 2 (Comando Ambíguo ou Incompatível com as Alternativas): "
        "O comando final é dúbio, omite a unidade esperada ou faz uma pergunta incompatível com alternativas numéricas "
        "(ex.: pergunta 'qual plano é mais econômico?' quando as alternativas são números), ou há empate entre opções comparadas?"
    ),
    "deficit_ou_contradicao": (
        "CRITÉRIO 3 (Déficit de Dados ou Contradição Texto-Tabela): "
        "Faltam informações/bases essenciais para calcular a resposta ou o texto contradiz os valores/totais da tabela?"
    ),
    "desalinhamento_comando_grandeza": (
        "CRITÉRIO 4 (Alinhamento Comando-Grandeza): "
        "O comando final deixa de perguntar exatamente a grandeza que o enunciado e o valor do gabarito definem "
        "(ex.: o enunciado e o gabarito calculam o desconto, mas a pergunta final pede o preço final, ou vice-versa)?"
    ),
    "fuga_habilidade_alvo": (
        "CRITÉRIO 5 (Aderência à Habilidade-Alvo do ENEM): "
        "A resolução da questão deixa de exigir o raciocínio matemático previsto na habilidade-alvo especificada abaixo?"
    ),
}


def build_auditoria_criterio_prompt(
    criterio: str,
    enunciado: str,
    alternativas: Dict[str, str],
    tabela_dados: Optional[List[Dict[str, Any]]] = None,
    letra_gabarito: Optional[str] = None,
    habilidade_codigo: Optional[str] = None,
    habilidade_descricao: Optional[str] = None
) -> str:
    """
    Constrói prompt binário curto para auditoria de um único critério pedagógico ou semântico.
    """
    alts_formatted = "\n".join([f"  {k}) {v}" for k, v in sorted(alternativas.items())])
    has_md_table = bool(re.search(r"\|(?:\s*:?-+:?\s*\|)+", enunciado or ""))
    tabela_txt = "" if has_md_table else _formatar_tabela(tabela_dados)
    bloco_tabela = f"\nTabela de Dados:\n{tabela_txt}\n" if tabela_txt else ""
    bloco_gab = (
        f"\nAlternativa correta segundo o sistema: {letra_gabarito} ({alternativas.get(letra_gabarito, '')})\n"
        if letra_gabarito
        else ""
    )
    bloco_hab = (
        f"\nHabilidade-Alvo: {habilidade_codigo} — {habilidade_descricao}\n"
        if habilidade_codigo or habilidade_descricao
        else ""
    )
    pergunta_criterio = AUDITORIA_CRITERIOS_PEDAGOGICOS.get(
        criterio,
        f"CRITÉRIO ({criterio}): O item apresenta este defeito pedagógico ou semântico?"
    )

    return f"""Você é um Revisor Técnico Oficial do INEP (Auditoria Binária de Critério Único — {criterio}).
Avalie EXCLUSIVAMENTE o critério abaixo sobre o item submetido.

ITEM SUBMETIDO:
Enunciado:
{enunciado}
{bloco_tabela}Alternativas:
{alts_formatted}{bloco_gab}{bloco_hab}
PERGUNTA DE AUDITORIA (true = o defeito EXISTE; false = o item está CORRETO neste critério):
{pergunta_criterio}

Responda EXCLUSIVAMENTE em JSON curto:
{{
  "defeito": false,
  "evidencia": "1 frase curta justificando"
}}
"""
