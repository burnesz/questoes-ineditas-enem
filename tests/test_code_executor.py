import pytest
from app.services.code_executor import (
    execute_solver_code,
    check_code_safety,
    validate_solver_consistency,
    assemble_alternatives_and_gabarito,
    format_number,
    sanitize_solver_code,
    auto_heal_distractors
)


def test_format_number():
    assert format_number(34) == "34"
    assert format_number(34.0) == "34"
    assert format_number(12.5) == "12,5"
    assert format_number(12.50) == "12,5"
    assert format_number(3.14) == "3,14"
    assert format_number("teste") == "teste"


def test_sanitize_solver_code():
    code_with_md = "```python\ndef resolver():\n    return {'correta': 1, 'distratores': [2, 3, 4, 5]}\n```"
    cleaned = sanitize_solver_code(code_with_md)
    assert cleaned.startswith("def resolver():")
    assert not cleaned.endswith("```")


def test_execute_solver_code_success():
    code = """
def resolver():
    preco = 50.0
    desc = 0.20
    final = preco * (1 - desc)
    d1 = preco * desc  # 10
    d2 = preco * 1.20  # 60
    d3 = preco + 10    # 60 (ajustando para 65)
    d4 = 35.0
    return {
        'correta': final,
        'distratores': [10.0, 60.0, 65.0, 35.0]
    }
"""
    result = execute_solver_code(code, timeout=3)
    assert "correta" in result
    assert result["correta"] == 40.0
    assert len(result["distratores"]) == 4


def test_check_code_safety_blocked_imports():
    code_os = "import os\ndef resolver():\n    return {'correta': 1, 'distratores': [2, 3, 4, 5]}"
    with pytest.raises(PermissionError, match="Import não permitido"):
        check_code_safety(code_os)

    code_sub = "from subprocess import run\ndef resolver():\n    return {'correta': 1, 'distratores': [2, 3, 4, 5]}"
    with pytest.raises(PermissionError, match="ImportFrom não permitido"):
        check_code_safety(code_sub)


def test_check_code_safety_blocked_calls():
    code_eval = "def resolver():\n    eval('2+2')\n    return {'correta': 4, 'distratores': [1, 2, 3, 5]}"
    with pytest.raises(PermissionError, match="Chamada de função não permitida"):
        check_code_safety(code_eval)

    code_open = "def resolver():\n    open('/etc/passwd')\n    return {'correta': 1, 'distratores': [2, 3, 4, 5]}"
    with pytest.raises(PermissionError, match="Chamada de função não permitida"):
        check_code_safety(code_open)


def test_execute_solver_code_timeout():
    code_infinite = """
def resolver():
    while True:
        pass
    return {'correta': 1, 'distratores': [2, 3, 4, 5]}
"""
    with pytest.raises(TimeoutError, match="tempo limite de execução"):
        execute_solver_code(code_infinite, timeout=1)


def test_validate_solver_consistency_valid():
    enunciado = (
        "Um reservatório com capacidade de 1.200 litros é abastecido a uma taxa de 40 litros por minuto, "
        "enquanto uma válvula esvazia a 10 litros por minuto. Qual o tempo necessário para enchê-lo?"
    )
    code = """
def resolver():
    capacidade = 1200
    entrada = 40
    saida = 10
    taxa = entrada - saida
    tempo = capacidade / taxa
    return {'correta': tempo, 'distratores': [30, 50, 60, 80]}
"""
    result = {'correta': 40.0, 'distratores': [30.0, 50.0, 60.0, 80.0]}
    formatted_vals = validate_solver_consistency(enunciado, code, result)
    assert len(formatted_vals) == 5
    assert formatted_vals[0] == "40"
    assert "30" in formatted_vals


def test_auto_heal_distractors_with_duplicates_and_correct_collision():
    # Caso 1: Colisão com a correta (10) e repetição de distratores (30 e 30)
    correta = 10
    distratores = [10, 20, 30, 30]
    healed = auto_heal_distractors(correta, distratores)
    assert len(healed) == 4
    # Todos devem ser distintos entre si e distintos da resposta correta ("10")
    all_5 = [format_number(correta)] + healed
    assert len(set(all_5)) == 5
    assert "10" not in healed
    assert "20" in healed
    assert "30" in healed


def test_auto_heal_distractors_float_values():
    # Caso 2: Valores decimais
    correta = 12.5
    distratores = [10.0, 12.5, 15.0, 15.0]
    healed = auto_heal_distractors(correta, distratores)
    assert len(healed) == 4
    all_5 = [format_number(correta)] + healed
    assert len(set(all_5)) == 5
    assert "12,5" not in healed


def test_validate_solver_consistency_auto_heals_duplicate_alternatives():
    enunciado = "Teste com 100 reais e taxa de 10%."
    code = "def resolver():\n    return {'correta': 10, 'distratores': [10, 20, 30, 40]}"
    result = {'correta': 10, 'distratores': [10, 20, 30, 40]}  # Duplicata: 10 e 10

    formatted_vals = validate_solver_consistency(enunciado, code, result)
    assert len(formatted_vals) == 5
    assert len(set(formatted_vals)) == 5
    assert formatted_vals[0] == "10"


def test_validate_solver_consistency_missing_nexo_fails():
    enunciado = "Um comerciante comprou 5 caixas por 20 reais cada."
    code = """
def resolver():
    qtd = 5
    unit = 20
    # Alucinação: 99 não consta no enunciado nem é constante neutra
    bonus = 99
    total = (qtd * unit) + bonus
    return {'correta': total, 'distratores': [100, 150, 180, 200]}
"""
    result = {'correta': 199, 'distratores': [100, 150, 180, 200]}

    with pytest.raises(ValueError, match="Números utilizados na lógica do solver ausentes"):
        validate_solver_consistency(enunciado, code, result)


def test_assemble_alternatives_and_gabarito():
    formatted_vals = ["40", "30", "50", "60", "80"]
    alternativas, gabarito = assemble_alternatives_and_gabarito(formatted_vals)

    assert set(alternativas.keys()) == {"A", "B", "C", "D", "E"}
    assert len(set(alternativas.values())) == 5
    assert gabarito in {"A", "B", "C", "D", "E"}
    assert alternativas[gabarito] == "40"


def test_pot_few_shot_examples_pass_groundedness_and_execution():
    import json
    from app.core.prompts import POT_FEW_SHOT_EXAMPLES
    from app.schemas.question import QuestaoEnunciadoSolverOutput
    from app.services.question_validator import format_enunciado_with_table

    for idx, raw_ex in enumerate(POT_FEW_SHOT_EXAMPLES, 1):
        data = json.loads(raw_ex)
        pot_out = QuestaoEnunciadoSolverOutput(**data)
        assert pot_out.planejamento is not None and len(pot_out.planejamento) > 10
        enunciado_full = format_enunciado_with_table(pot_out.enunciado, pot_out.tabela_dados)
        res = execute_solver_code(pot_out.solver, timeout=5)
        vals = validate_solver_consistency(enunciado_full, pot_out.solver, res)
        assert len(vals) == 5, f"Exemplo {idx} falhou em retornar 5 alternativas"
        assert len(set(vals)) == 5, f"Exemplo {idx} gerou alternativas duplicadas: {vals}"


def test_validate_solver_consistency_words_to_numbers():
    enunciado = "Uma cooperativa dividiu oitocentos quilos de grãos igualmente entre oito silos durante um semestre."
    code = """
def resolver():
    total = 800
    silos = 8
    meses = 6
    por_silo = total / silos
    return {'correta': por_silo, 'distratores': [por_silo / meses, total / meses, por_silo + 20, por_silo - 20]}
"""
    res = execute_solver_code(code)
    vals = validate_solver_consistency(enunciado, code, res)
    assert len(vals) == 5
    assert vals[0] == "100"


def test_execute_and_validate_five_distractors_discards_gabarito_match():
    code = """
def resolver():
    a = 50
    b = 4
    correta = a * b
    # Incluiu 5 distratores onde 1 deles (200) é igual à correta
    return {'correta': correta, 'distratores': [200, 150, 180, 220, 250]}
"""
    res = execute_solver_code(code)
    assert len(res["distratores"]) == 4
    assert 200 not in res["distratores"]
    vals = validate_solver_consistency("Uma compra de 50 itens a 4 reais cada.", code, res)
    assert vals == ["200", "150", "180", "220", "250"]


def test_validate_solver_consistency_rejects_two_or_more_collisions():
    enunciado = "Teste com 100 reais e taxa de 10%."
    code = "def resolver():\n    return {'correta': 10, 'distratores': [10, 10, 20, 30]}"
    result = {"correta": 10, "distratores": [10, 10, 20, 30]}  # 2 colisões (apenas 20 e 30 são únicos != 10)

    with pytest.raises(ValueError, match="Colisão excessiva de alternativas"):
        validate_solver_consistency(enunciado, code, result)


def test_a1_solver_without_return_collects_correta_and_erros():
    """A1: O LLM define apenas 'correta' e variáveis 'erro_*' dentro de resolver(), sem escrever return."""
    enunciado = "Uma fábrica produz 120 peças por hora em 5 horas, com perda de 20 peças ao final."
    code = """
def resolver():
    taxa = 120
    horas = 5
    perda = 20
    bruto = taxa * horas
    correta = bruto - perda
    erro_sem_perda = bruto
    erro_somou_perda = bruto + perda
    erro_perda_por_hora = (taxa - perda) * horas
    erro_dividiu = taxa / horas + perda
"""
    res = execute_solver_code(code)
    assert res["correta"] == 580
    assert res["distratores"] == [600, 620, 500, 44.0]
    vals = validate_solver_consistency(enunciado, code, res)
    assert vals == ["580", "600", "620", "500", "44"]


def test_a1_solver_with_three_distinct_distractors_auto_heals_fourth():
    """A1: Com exatamente 3 distratores distintos, o auto_heal completa o quarto (dentro do limite de 1)."""
    enunciado = "Uma fábrica produz 120 peças por hora em 5 horas, com perda de 20 peças ao final."
    code = """
def resolver():
    taxa = 120
    horas = 5
    perda = 20
    bruto = taxa * horas
    correta = bruto - perda
    erro_sem_perda = bruto
    erro_somou_perda = bruto + perda
    erro_perda_por_hora = (taxa - perda) * horas
"""
    res = execute_solver_code(code)
    assert res["correta"] == 580
    assert len(res["distratores"]) == 3
    vals = validate_solver_consistency(enunciado, code, res)
    assert len(vals) == 5
    assert len(set(vals)) == 5
    assert vals[0] == "580"
    assert {"600", "620", "500"}.issubset(set(vals))


def test_a1_solver_with_fewer_than_three_distractors_fails():
    """A1: Com menos de 3 distratores, reprovar."""
    code = """
def resolver():
    a = 100
    b = 20
    correta = a - b
    erro_soma = a + b
    erro_mult = a * b
"""
    with pytest.raises(ValueError, match="Distratores insuficientes"):
        execute_solver_code(code)


def test_a2_static_gate_syntax_error_classified():
    """A2: ast.parse classifica SyntaxError em 0ms antes de executar subprocesso."""
    bad_code = "def resolver():\n    correta = (10 + 20\n    erro_1 = 5\n"
    with pytest.raises(ValueError, match="Erro de sintaxe no código Python do solver"):
        execute_solver_code(bad_code)


def test_a2_static_gate_detects_free_variable_tabela_dados():
    """A2: Detecta nomes livres (ex: tabela_dados) em 0ms com hint específico."""
    from app.services.question_service import _classify_retry_hint
    from app.schemas.question import PipelineErrorCode, PipelineValidationError

    code_with_free_var = """
def resolver():
    total = sum(linha['Valor'] for linha in tabela_dados)
    correta = total
    erro_1 = total + 10
    erro_2 = total - 10
    erro_3 = total * 2
    erro_4 = total / 2
"""
    with pytest.raises(PipelineValidationError) as exc_info:
        execute_solver_code(code_with_free_var)

    err_msg = str(exc_info.value)
    assert exc_info.value.code == PipelineErrorCode.NOME_LIVRE
    assert "tabela_dados" in err_msg
    assert "declare os valores como variáveis dentro de resolver(); não use variáveis externas" in err_msg
    assert _classify_retry_hint(exc_info.value) == "declare os valores como variáveis dentro de resolver(); não use variáveis externas"


def test_a6_percentage_in_table_header_accepts_decimal_and_complement():
    """A6: Coluna 'Percentual Utilizado (%)' com 70 e 60 aceita 0.7, 0.6, 0.3 e 0.4 no solver."""
    from app.services.question_validator import format_enunciado_with_table

    enunciado_base = (
        "Dois servidores de armazenamento possuem capacidades de 500 GB e 800 GB. "
        "A tabela a seguir informa o percentual utilizado de cada servidor. "
        "Qual é o espaço total utilizado, em GB, somando os dois servidores?"
    )
    tabela = [
        {"Servidor": "S1", "Capacidade (GB)": 500, "Percentual Utilizado (%)": 70},
        {"Servidor": "S2", "Capacidade (GB)": 800, "Percentual Utilizado (%)": 60},
    ]
    enunciado_full = format_enunciado_with_table(enunciado_base, tabela)
    code = """
def resolver():
    cap_s1 = 500
    cap_s2 = 800
    uso_s1 = cap_s1 * 0.7
    uso_s2 = cap_s2 * 0.6
    correta = uso_s1 + uso_s2
    erro_complemento = cap_s1 * 0.3 + cap_s2 * 0.4
    erro_so_s1 = uso_s1
    erro_so_s2 = uso_s2
    erro_media_simples = (cap_s1 + cap_s2) * 0.5
"""
    res = execute_solver_code(code)
    vals = validate_solver_consistency(enunciado_full, code, res, tabela_dados=tabela)
    assert vals[0] == "830"
    assert len(set(vals)) == 5


def test_a7_typed_error_codes_and_pi_hint():
    """A7: Erros tipificados com código Enum corrigem precedência COLISAO vs NEXO_NUMERICO e dão hint de pi."""
    from app.services.question_service import _classify_retry_hint
    from app.schemas.question import PipelineErrorCode, PipelineValidationError

    # 1. Caso math.pi no solver -> código USO_PI -> hint específico de pi
    code_math_pi = """
def resolver():
    r = 10
    correta = math.pi * r * r
    erro_1 = 2 * math.pi * r
    erro_2 = r * r
    erro_3 = 4 * math.pi * r
    erro_4 = math.pi * r
"""
    with pytest.raises(PipelineValidationError) as exc_pi:
        execute_solver_code(code_math_pi)
    assert exc_pi.value.code == PipelineErrorCode.USO_PI
    assert _classify_retry_hint(exc_pi.value) == "se usar π, escreva 'considere π = 3,14' no enunciado e use 3.14 no solver"

    # 2. Caso 3.14 sem estar no enunciado -> código USO_PI -> hint específico de pi
    code_314 = """
def resolver():
    r = 10
    correta = 3.14 * r * r
    erro_1 = 2 * 3.14 * r
    erro_2 = r * r
    erro_3 = 4 * 3.14 * r
    erro_4 = 3.14 * r
"""
    res_314 = execute_solver_code(code_314)
    with pytest.raises(PipelineValidationError) as exc_314:
        validate_solver_consistency(
            "Um jardim circular possui raio de 10 metros. Qual sua área?",
            code_314,
            res_314
        )
    assert exc_314.value.code == PipelineErrorCode.USO_PI
    assert _classify_retry_hint(exc_314.value) == "se usar π, escreva 'considere π = 3,14' no enunciado e use 3.14 no solver"

    # 3. Colisão de distratores em validate_solver_consistency (antes envolvida em 'Erro de nexo numérico: Colisão...')
    # deve carregar código COLISAO e mapear para hint de distratores distintos, nunca NEXO_NUMERICO!
    with pytest.raises(PipelineValidationError) as exc_col:
        validate_solver_consistency(
            "Em uma corrida de 100 metros rasos em 10 segundos, qual a velocidade média?",
            "def resolver():\n    d = 100\n    t = 10\n    correta = d / t\n    return {'correta': correta, 'distratores': [10, 10, 20, 30]}",
            {"correta": 10, "distratores": [10, 10, 20, 30]}
        )
    assert exc_col.value.code == PipelineErrorCode.COLISAO
    hint_col = _classify_retry_hint(exc_col.value)
    assert "Distratores distintos" in hint_col
    assert "Nexo numérico" not in hint_col


def test_a5_backward_slicing_correta_and_distractor_dependency():
    """A5: Groundedness via backward slicing na fatia de 'correta'; 'erro_*' aceita literal solto só se depender de variável fundamentada."""
    from app.schemas.question import PipelineErrorCode, PipelineValidationError

    enunciado = "Uma fábrica produz 120 peças por hora durante 5 horas, descartando 20 peças defeituosas ao final."

    # 1. Caso válido: 'correta' 100% fundamentada; 'erro_4' usa literal solto (15), mas depende de 'bruto' (fundamentada)
    code_ok = """
def resolver():
    taxa = 120
    horas = 5
    descarte = 20
    bruto = taxa * horas
    correta = bruto - descarte
    erro_sem_descarte = bruto
    erro_somou_descarte = bruto + descarte
    erro_descarte_por_hora = (taxa - descarte) * horas
    erro_ajuste_arbitrario = bruto - 15
"""
    res_ok = execute_solver_code(code_ok)
    vals = validate_solver_consistency(enunciado, code_ok, res_ok)
    assert vals[0] == "580"
    assert "585" in vals

    # 2. Caso inválido (erro_* com literal solto sem depender de variável fundamentada): deve reprovar!
    code_ungrounded_distractor = """
def resolver():
    taxa = 120
    horas = 5
    descarte = 20
    bruto = taxa * horas
    correta = bruto - descarte
    erro_1 = bruto
    erro_2 = bruto + descarte
    erro_3 = (taxa - descarte) * horas
    erro_chute_solto = 499
"""
    res_bad_dist = execute_solver_code(code_ungrounded_distractor)
    with pytest.raises(PipelineValidationError) as exc_dist:
        validate_solver_consistency(enunciado, code_ungrounded_distractor, res_bad_dist)
    assert exc_dist.value.code == PipelineErrorCode.NEXO_NUMERICO
    assert "erro_chute_solto" in str(exc_dist.value)

    # 3. Caso inválido (literal não fundamentado na fatia de 'correta'): deve reprovar!
    code_ungrounded_correta = """
def resolver():
    taxa = 120
    horas = 5
    descarte = 20
    taxa_oculta = 35
    bruto = taxa * horas
    correta = bruto - descarte - taxa_oculta
    erro_1 = bruto
    erro_2 = bruto + descarte
    erro_3 = (taxa - descarte) * horas
    erro_4 = taxa * descarte
"""
    res_bad_correta = execute_solver_code(code_ungrounded_correta)
    with pytest.raises(PipelineValidationError) as exc_corr:
        validate_solver_consistency(enunciado, code_ungrounded_correta, res_bad_correta)
    assert exc_corr.value.code == PipelineErrorCode.NEXO_NUMERICO
    assert "35" in str(exc_corr.value)


def test_b5_degenerate_ties_detected():
    """B5: Detecta empate degenerado entre opções comparadas (via min/max ou variáveis comparadas em comando superlativo)."""
    from app.schemas.question import PipelineErrorCode, PipelineValidationError

    enunciado = (
        "Uma empresa analisa três planos de internet para 2 meses: "
        "Plano A tem taxa de 100 reais e mensalidade de 50 reais; "
        "Plano B tem taxa de 80 reais e mensalidade de 60 reais; "
        "Plano C tem taxa de 90 reais e mensalidade de 70 reais. "
        "Qual o custo total da opção mais econômica?"
    )

    # 1. Empate em min(custo_a, custo_b, custo_c): ambos A e B custam 200
    code_tie_min = """
def resolver():
    custo_a = 100 + 2 * 50
    custo_b = 80 + 2 * 60
    custo_c = 90 + 2 * 70
    correta = min(custo_a, custo_b, custo_c)
    erro_1 = custo_c
    erro_2 = 100 + 50
    erro_3 = 80 + 60
    erro_4 = 90 + 70
"""
    res_tie = execute_solver_code(code_tie_min)
    with pytest.raises(PipelineValidationError) as exc_tie:
        validate_solver_consistency(enunciado, code_tie_min, res_tie)
    assert exc_tie.value.code == PipelineErrorCode.CASO_DEGENERADO

    # 2. Empate sem usar min(), atribuindo correta = custo_a quando custo_a == custo_b e enunciado pede 'mais econômica'
    code_tie_vars = """
def resolver():
    custo_a = 100 + 2 * 50
    custo_b = 80 + 2 * 60
    custo_c = 90 + 2 * 70
    correta = custo_a
    erro_1 = custo_c
    erro_2 = 100 + 50
    erro_3 = 80 + 60
    erro_4 = 90 + 70
"""
    res_tie_vars = execute_solver_code(code_tie_vars)
    with pytest.raises(PipelineValidationError) as exc_tie_vars:
        validate_solver_consistency(enunciado, code_tie_vars, res_tie_vars)
    assert exc_tie_vars.value.code == PipelineErrorCode.CASO_DEGENERADO
