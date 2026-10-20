import pytest
from app.services.question_validator import validate_questao_inedita, extract_json_from_text


def test_extract_json_from_text():
    # Caso 1: JSON com bloco markdown
    raw_md = 'Aqui está a questão:\n```json\n{"enunciado": "Teste", "gabarito": "A"}\n```\nEspero que ajude!'
    extracted = extract_json_from_text(raw_md)
    assert extracted == '{"enunciado": "Teste", "gabarito": "A"}'

    # Caso 2: JSON puro
    raw_pure = '{"enunciado": "Teste", "gabarito": "B"}'
    assert extract_json_from_text(raw_pure) == raw_pure


def test_validate_questao_inedita_valid():
    valid_payload = {
        "thought_scratchpad": "Planejando questão sobre proporcionalidade direta.",
        "enunciado": "Um estudante deseja calcular o consumo total de combustível para uma viagem de 480 km, sabendo que o carro consome 1 litro a cada 12 km rodados. Qual a quantidade necessária em litros?",
        "alternativas": {
            "A": "30 litros.",
            "B": "35 litros.",
            "C": "40 litros.",
            "D": "45 litros.",
            "E": "50 litros."
        },
        "gabarito": "C",
        "justificativa": "Dividindo 480 por 12, obtemos 40 litros. Portanto, alternativa C."
    }

    is_valid, error, item = validate_questao_inedita(valid_payload)
    assert is_valid is True
    assert error is None
    assert item is not None
    assert item.gabarito == "C"
    assert len(item.alternativas) == 5


def test_validate_questao_inedita_duplicate_alternatives_fails():
    """Valida cumprimento estrito de RN-Q01: ausência de alternativas duplicadas."""
    payload_com_duplicata = {
        "enunciado": "Em uma fábrica de calçados, a produção diária foi mapeada e a gerência precisa calcular a média aritmética dos pares produzidos.",
        "alternativas": {
            "A": "150 pares.",
            "B": "150 pares.",  # DUPLICATA!
            "C": "200 pares.",
            "D": "250 pares.",
            "E": "300 pares."
        },
        "gabarito": "C",
        "justificativa": "A média calculada é 200."
    }

    is_valid, error, item = validate_questao_inedita(payload_com_duplicata)
    assert is_valid is False
    assert item is None
    assert "RN-Q01 violada" in error or "duplicados" in error


def test_validate_questao_inedita_invalid_gabarito():
    payload_gabarito_invalido = {
        "enunciado": "Em um parque da cidade, uma pista de corrida circular tem raio de 50 metros. Um corredor completa 10 voltas na pista.",
        "alternativas": {
            "A": "1 000 m.",
            "B": "2 000 m.",
            "C": "3 140 m.",
            "D": "4 000 m.",
            "E": "5 000 m."
        },
        "gabarito": "F",  # Inválido! Deve ser A-E
        "justificativa": "Resolução..."
    }

    is_valid, error, item = validate_questao_inedita(payload_gabarito_invalido)
    assert is_valid is False
    assert "Gabarito deve ser exatamente uma das letras A, B, C, D ou E" in error


def test_validate_questao_inedita_missing_alternative():
    payload_faltando_alt = {
        "enunciado": "Uma caixa d'água no formato de paralelepípedo reto retângulo tem dimensões 2 m x 3 m x 1,5 m. O volume em metros cúbicos é:",
        "alternativas": {
            "A": "6 m³.",
            "B": "7 m³.",
            "C": "8 m³.",
            "D": "9 m³."
            # Falta E!
        },
        "gabarito": "D",
        "justificativa": "Volume = 2 * 3 * 1.5 = 9."
    }

    is_valid, error, item = validate_questao_inedita(payload_faltando_alt)
    assert is_valid is False
    assert "exatamente as chaves A, B, C, D, E" in error


def test_validate_questao_inedita_anti_plagiarism():
    exemplo_historico = {
        "enunciado": "O medidor de energia elétrica das residências, conhecido por relógio de luz, é constituído de quatro pequenos relógios dispostos lado a lado.",
        "alternativas": {"A": "1", "B": "2", "C": "3", "D": "4", "E": "5"},
        "gabarito": "A"
    }

    payload_copiado = {
        "enunciado": "O medidor de energia elétrica das residências, conhecido por relógio de luz, é constituído de quatro pequenos relógios dispostos lado a lado com ponteiros.",
        "alternativas": {"A": "10", "B": "20", "C": "30", "D": "40", "E": "50"},
        "gabarito": "A",
        "justificativa": "Mesma questão copiada."
    }

    is_valid, error, item = validate_questao_inedita(payload_copiado, few_shot_exemplos=[exemplo_historico])
    assert is_valid is False
    assert "excessivamente similar" in error or "ineditismo" in error


def test_validate_questao_inedita_sanitizes_corrupted_latex():
    """Valida se o validador repara form feed residual e comandos LaTeX corrompidos."""
    raw_corrupted_json = (
        '{\n'
        '  "thought_scratchpad": "Etapa 1: V(x) = 50 - \\frac{1}{4}x^2",\n'
        '  "enunciado": "Em uma loja, o valor unitário é V(x) = 50 - \\x0crac{1}{4}x^2. Calcule para x=4.",\n'
        '  "alternativas": {\n'
        '    "A": "46",\n'
        '    "B": "48",\n'
        '    "C": "50",\n'
        '    "D": "52",\n'
        '    "E": "54"\n'
        '  },\n'
        '  "gabarito": "A",\n'
        '  "justificativa": "Para x=4, V(4) = 50 - 4 = 46. Alternativa A."\n'
        '}'
    )

    is_valid, error, item = validate_questao_inedita(raw_corrupted_json)
    assert is_valid is True
    assert item is not None
    # Garante que \x0crac foi restaurado para \frac
    assert "\\frac" in item.enunciado or r"\frac" in item.enunciado
    assert "\x0c" not in item.enunciado


def test_validate_questao_inedita_rejects_shortcut_reasoning():
    """Valida se o validador rejeita questão onde o comando pede valor total mas o gabarito é o unitário."""
    payload_shortcut = {
        "thought_scratchpad": "Calculando: V(8) = 34. Total: 8 * 34 = 272.",
        "enunciado": "Uma loja vende camisas cujo valor unitário com desconto é dado por V(x). Qual será o valor total pago por 8 camisas?",
        "alternativas": {
            "A": "34",  # Erro! 34 é o valor unitário, não o total pedido
            "B": "50",
            "C": "272",
            "D": "300",
            "E": "350"
        },
        "gabarito": "A",  # Erro! Gabarito deveria ser C (272)
        "justificativa": "Calculamos V(8) = 34. Logo a alternativa A está correta."
    }

    is_valid, error, item = validate_questao_inedita(payload_shortcut)
    assert is_valid is False
    assert item is None
    assert "Shortcut Reasoning" in error or "Inconsistência semântica" in error


def test_check_table_markdown_structure_valid():
    """Valida que uma questão contendo tabela Markdown válida é aprovada."""
    from app.services.question_validator import check_table_markdown_structure

    enunciado_com_tabela = (
        "A tabela a seguir apresenta os dados de vendas de uma loja em três meses:\n\n"
        "| Mês | Vendas (unidades) | Faturamento (R$) |\n"
        "| :--- | :---: | :---: |\n"
        "| Janeiro | 100 | 5 000 |\n"
        "| Fevereiro | 150 | 7 500 |\n"
        "| Março | 200 | 10 000 |\n\n"
        "Qual foi o faturamento médio mensal?"
    )

    is_valid, error = check_table_markdown_structure(enunciado_com_tabela)
    assert is_valid is True
    assert error is None


def test_check_table_markdown_structure_flattened_fails():
    """Valida que uma questão que anuncia 'tabela a seguir' mas achata em texto corrido é rejeitada."""
    from app.services.question_validator import check_table_markdown_structure

    # Exemplo similar ao caso real f1e07d2c-0bb4-40fa-851b-9f7c7b7f2f9d
    enunciado_achatado = (
        "Um restaurante registra o número de clientes em três dias da semana. "
        "Os dados são apresentados na tabela a seguir. Número de Clientes Segunda-feira em abril 120 "
        "Quarta-feira 80 Sexta-feira 200. Qual foi o total?"
    )

    is_valid, error = check_table_markdown_structure(enunciado_achatado)
    assert is_valid is False
    assert "Problema de formatação tabular" in error
    assert "tabela Markdown" in error


def test_check_table_markdown_structure_without_table_passes():
    """Valida que questões regulares sem menção a tabela passam sem interferência."""
    from app.services.question_validator import check_table_markdown_structure

    enunciado_comum = (
        "Uma gráfica cobra R$ 80,00 para imprimir um lote de 500 panfletos. "
        "Qual o valor total de 2000 panfletos?"
    )

    is_valid, error = check_table_markdown_structure(enunciado_comum)
    assert is_valid is True
    assert error is None


def test_validate_questao_inedita_rejects_unstructured_table():
    """Valida que a validação completa via validate_questao_inedita rejeita tabela sem formatação Markdown."""
    payload_tabela_achatada = {
        "thought_scratchpad": "Cálculos da tabela",
        "enunciado": "Os dados de produção constam na tabela a seguir. Turno Manha 10 Tarde 20 Noite 30. Qual a produção total?",
        "alternativas": {
            "A": "40",
            "B": "50",
            "C": "60",
            "D": "70",
            "E": "80"
        },
        "gabarito": "C",
        "justificativa": "10 + 20 + 30 = 60. Alternativa C."
    }

    is_valid, error, item = validate_questao_inedita(payload_tabela_achatada)
    assert is_valid is False
    assert item is None
    assert "Problema de formatação tabular" in error


def test_check_prohibited_terms():
    from app.services.question_validator import check_prohibited_terms

    # Texto limpo
    ok, err = check_prohibited_terms("Um fazendeiro comprou 30 sacas de milho.")
    assert ok is True
    assert err is None

    # Texto com vazamentos proibidos
    termos = ["o solver calcula", "segundo o código", "no algoritmo", "o distrator A", "o gabarito oficial", "em python"]
    for termo in termos:
        ok, err = check_prohibited_terms(f"Contexto: {termo} para a resposta.")
        assert ok is False
        assert "Presença de termo técnico de bastidor proibido" in err


def test_check_table_duplication():
    from app.services.question_validator import check_table_duplication

    # Sem tabela_dados: passa
    ok, err = check_table_duplication("Texto qualquer sem tabela", None)
    assert ok is True

    # Com tabela_dados e enunciado limpo (sem pipes): passa
    tabela = [{"A": 1, "B": 2}]
    ok, err = check_table_duplication("A tabela a seguir apresenta os dados. Qual o total?", tabela)
    assert ok is True

    # Com tabela_dados e enunciado com pipes (|): rejeita
    ok, err = check_table_duplication("A tabela | Coluna 1 | Coluna 2 | apresenta dados", tabela)
    assert ok is False
    assert "estrutura de tabela bruta" in err


def test_questao_auditoria_semantica_4_macro_criteria():
    from app.schemas.question import QuestaoAuditoriaSemanticaOutput

    # Item perfeito
    audit_ok = QuestaoAuditoriaSemanticaOutput(
        analise="Item verossímil e adequado ao padrão ENEM.",
        incoerencia_ou_absurdo=False,
        comando_ambiguo_ou_incompativel=False,
        deficit_ou_contradicao=False,
        complexidade_insuficiente=False
    )
    assert audit_ok.aprovada is True
    assert audit_ok.motivo_rejeicao is None

    # Item com incoerência
    audit_incoerente = QuestaoAuditoriaSemanticaOutput(
        analise="Consumo de 4 litros de água por casa por dia é absurdo.",
        incoerencia_ou_absurdo=True
    )
    assert audit_incoerente.aprovada is False
    assert "Incoerência semântica ou física" in audit_incoerente.motivo_rejeicao

    # Compatibilidade com flags legadas
    audit_legado = QuestaoAuditoriaSemanticaOutput(
        possui_incoerencia=True
    )
    assert audit_legado.aprovada is False
    assert "Incoerência semântica ou física" in audit_legado.motivo_rejeicao


def test_a3_tabela_dados_heterogeneous_keys_rejected():
    """A3: Reprova tabela_dados quando as linhas possuem chaves heterogêneas."""
    from pydantic import ValidationError
    from app.schemas.question import QuestaoEnunciadoSolverOutput
    from app.services.question_validator import validate_tabela_dados

    tabela_heterogenea = [
        {"Setor": "A", "Consumo (kWh)": 120},
        {"Setor": "B", "Gasto (kWh)": 150},  # Chave diferente!
    ]
    ok, err = validate_tabela_dados(tabela_heterogenea)
    assert ok is False
    assert "TABELA_INVALIDA" in err

    with pytest.raises(ValidationError) as exc_info:
        QuestaoEnunciadoSolverOutput(
            enunciado="A tabela a seguir mostra o consumo elétrico de dois setores de uma empresa. Qual o consumo total?",
            tabela_dados=tabela_heterogenea,
            solver="def resolver():\n    correta = 270\n    erro_1 = 120\n    erro_2 = 150\n    erro_3 = 30"
        )
    assert "TABELA_INVALIDA" in str(exc_info.value)


def test_a3_tabela_dados_exceeds_six_rows_rejected():
    """A3: Reprova tabela_dados com mais de 6 linhas."""
    from pydantic import ValidationError
    from app.schemas.question import QuestaoEnunciadoSolverOutput
    from app.services.question_validator import validate_tabela_dados

    tabela_7_linhas = [{"Dia": f"Dia {i}", "Valor": i * 10} for i in range(1, 8)]
    ok, err = validate_tabela_dados(tabela_7_linhas)
    assert ok is False
    assert "TABELA_INVALIDA" in err

    with pytest.raises(ValidationError) as exc_info:
        QuestaoEnunciadoSolverOutput(
            enunciado="A tabela a seguir mostra os valores anotados ao longo de sete dias consecutivos. Qual a soma?",
            tabela_dados=tabela_7_linhas,
            solver="def resolver():\n    correta = 280\n    erro_1 = 210\n    erro_2 = 140\n    erro_3 = 70"
        )
    assert "TABELA_INVALIDA" in str(exc_info.value)


def test_a4_erros_tipicos_schema_and_pydantic_validation():
    """A4: Garante minItems = maxItems = 4 no JSON Schema do Ollama e validação Pydantic com hint específico."""
    from pydantic import ValidationError
    from app.schemas.question import QuestaoEnunciadoSolverOutput, POT_PHASE1_JSON_SCHEMA, PipelineErrorCode
    from app.services.question_service import _classify_retry_hint

    # 1. Verifica JSON Schema enviado no format do Ollama
    erros_schema = POT_PHASE1_JSON_SCHEMA["properties"]["erros_tipicos"]
    assert erros_schema["type"] == "array"
    assert erros_schema["minItems"] == 4
    assert erros_schema["maxItems"] == 4
    assert "erros_tipicos" in POT_PHASE1_JSON_SCHEMA["required"]

    # 2. Reprova quando erros_tipicos tem menos ou mais de 4 itens
    with pytest.raises(ValidationError) as exc_info:
        QuestaoEnunciadoSolverOutput(
            enunciado="Uma loja vende pacotes de café de 500 g por 20 reais. Qual o custo de 3 kg?",
            erros_tipicos=["Erro 1", "Erro 2", "Erro 3"],  # Apenas 3!
            solver="def resolver():\n    correta = 120\n    erro_1 = 60\n    erro_2 = 80\n    erro_3 = 100\n    erro_4 = 140"
        )
    err_str = str(exc_info.value)
    assert "ERROS_TIPICOS_INVALIDOS" in err_str
    hint = _classify_retry_hint(PipelineErrorCode.ERROS_TIPICOS_INVALIDOS)
    assert "exatamente 4 erros" in hint

    # 3. Aprova com exatamente 4 erros típicos não vazios
    valid_out = QuestaoEnunciadoSolverOutput(
        enunciado="Uma loja vende pacotes de café de 500 g por 20 reais. Qual o custo de 3 kg?",
        erros_tipicos=["Erro 1", "Erro 2", "Erro 3", "Erro 4"],
        solver="def resolver():\n    correta = 120\n    erro_1 = 60\n    erro_2 = 80\n    erro_3 = 100\n    erro_4 = 140"
    )
    assert len(valid_out.erros_tipicos) == 4


def test_b3_questao_auditoria_semantica_new_criteria():
    """B3: Verifica os novos critérios desalinhamento_comando_grandeza e fuga_habilidade_alvo no schema."""
    from app.schemas.question import QuestaoAuditoriaSemanticaOutput

    audit_desalinhado = QuestaoAuditoriaSemanticaOutput(
        analise="O comando pergunta o valor total em reais, mas o solver calcula a quantidade de pacotes.",
        desalinhamento_comando_grandeza=True,
    )
    assert audit_desalinhado.aprovada is False
    assert "Desalinhamento" in audit_desalinhado.motivo_rejeicao

    audit_fuga = QuestaoAuditoriaSemanticaOutput(
        analise="A questão exige análise combinatória em vez de leitura de gráficos (H24).",
        fuga_habilidade_alvo=True,
    )
    assert audit_fuga.aprovada is False
    assert "habilidade-alvo" in audit_fuga.motivo_rejeicao

