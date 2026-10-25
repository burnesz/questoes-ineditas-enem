import pytest
from app.services.question_validator import extract_json_from_text


def test_extract_json_from_text():
    # Caso 1: JSON com bloco markdown
    raw_md = 'Aqui está a questão:\n```json\n{"enunciado": "Teste", "gabarito": "A"}\n```\nEspero que ajude!'
    extracted = extract_json_from_text(raw_md)
    assert extracted == '{"enunciado": "Teste", "gabarito": "A"}'

    # Caso 2: JSON puro
    raw_pure = '{"enunciado": "Teste", "gabarito": "B"}'
    assert extract_json_from_text(raw_pure) == raw_pure


def test_sanitizacao_latex_no_json():
    """Valida se o sanitizador repara form feed residual e comandos LaTeX corrompidos."""
    raw_corrupted_json = (
        '{\n'
        '  "planejamento": "Etapa 1: V(x) = 50 - \\frac{1}{4}x^2",\n'
        '  "enunciado": "Em uma loja, o valor unitário é V(x) = 50 - \\x0crac{1}{4}x^2. Calcule para x=4.",\n'
        '  "erros_tipicos": ["Erro 1", "Erro 2", "Erro 3", "Erro 4"],\n'
        '  "solver": "def resolver():\\n    correta = 46\\n    erro_1 = 48\\n    erro_2 = 50\\n    erro_3 = 52\\n    erro_4 = 54"\n'
        '}'
    )
    from app.services.question_validator import sanitize_latex_json_text
    import json
    sanitized = sanitize_latex_json_text(raw_corrupted_json)
    data = json.loads(sanitized)
    assert "\\frac" in data["enunciado"]
    assert "\x0c" not in data["enunciado"]


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


def test_auditoria_pedagogica_new_criteria():
    """Auditoria pedagógica (Etapa 4.3): verifica os novos critérios desalinhamento_comando_grandeza e fuga_habilidade_alvo no schema."""
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

