"""
Validador estrutural e de integridade para questões inéditas geradas por LLM.
Implementa as regras RN-Q01 (validação estrutural de unicidade) e RN-Q02 (conformidade com schema).
"""

import json
import re
import logging
from typing import Union, Dict, Any, List, Optional, Tuple
from pydantic import ValidationError

from app.schemas.question import QuestaoIneditaLLMOutput

logger = logging.getLogger(__name__)


def extract_json_from_text(text: str) -> str:
    """
    Localiza e extrai o bloco de JSON dentro de uma string de resposta do modelo,
    mesmo que o modelo tenha incluído marcações markdown ```json ... ``` ou texto ao redor.
    """
    text = text.strip()
    # 1. Procura bloco delimitado por ```json ... ```
    match_md = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if match_md:
        return match_md.group(1).strip()

    # 2. Procura pelo primeiro '{' e último '}'
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        return text[first_brace:last_brace + 1].strip()

    return text


def sanitize_latex_json_text(text: str) -> str:
    r"""
    Sanitiza strings de JSON contendo expressões matemáticas em LaTeX antes do json.loads().
    Resolve os seguintes problemas comuns gerados por LLMs:
    1. Formfeed corrompido: '\f' no JSON vira \x0c, deixando 'rac{a}{b}' em vez de '\frac{a}{b}'.
    2. Comandos LaTeX iniciados por caracteres válidos de escape JSON (\frac, \times, \right, \neq, \bar).
    3. Qualquer barra simples antes de comandos LaTeX (\sqrt, \cdot, etc.) que seja escape inválido em JSON.
    """
    if not text:
        return text

    # 1. Trata o caractere de controle form feed (chr(12) / \x0c) e resíduos literais
    text = text.replace("\x0crac", "\\\\frac")
    text = text.replace("\x0c", " ")
    text = text.replace(r"\x0crac", "\\\\frac")
    text = text.replace(r"\x0c", " ")

    # 2. Comandos LaTeX específicos que começam com letras de escape do JSON (\f, \t, \r, \n, \b)
    # Convertemos para barra dupla antes de qualquer outra operação:
    text = re.sub(r"(?<!\\)\\frac", r"\\\\frac", text)
    text = re.sub(r"(?<!\\)\\times", r"\\\\times", text)
    text = re.sub(r"(?<!\\)\\right", r"\\\\right", text)
    text = re.sub(r"(?<!\\)\\neq", r"\\\\neq", text)
    text = re.sub(r"(?<!\\)\\bar", r"\\\\bar", text)
    text = re.sub(r"(?<!\\)\\beta", r"\\\\beta", text)

    # 3. Qualquer barra simples não duplicada que não seja um escape válido de JSON:
    # No JSON, os escapes válidos são: \" \\ \/ \b \f \n \r \t \uXXXX
    text = re.sub(r'\\(?!["\\/bfnrt]|u[0-9a-fA-F]{4})', r"\\\\", text)

    # 4. Corrige ocorrências de 'rac{' órfãs causadas por escape prévio de form feed
    text = re.sub(r"(?<![\\a-zA-Z])rac\{", r"\\frac{", text)

    return text


def sanitize_parsed_dict_values(data: Any) -> Any:
    """
    Limpa recursivamente valores de strings no dicionário decodificado, garantindo que
    quaisquer resíduos de form feed (\x0c) ou comandos LaTeX incompletos sejam restaurados.
    """
    if isinstance(data, str):
        val = data.replace("\x0crac", r"\frac")
        val = val.replace("\x0c", " ")
        val = re.sub(r"(?<![\\a-zA-Z])rac\{", r"\\frac{", val)
        return val
    elif isinstance(data, dict):
        return {k: sanitize_parsed_dict_values(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [sanitize_parsed_dict_values(v) for v in data]
    return data


def check_command_gabarito_alignment(
    enunciado: str,
    alternativas: Dict[str, str],
    gabarito: str,
    justificativa: str,
    scratchpad: Optional[str] = None
) -> Tuple[bool, Optional[str]]:
    """
    Valida a consistência semântica entre o comando da questão e a alternativa indicada no gabarito:
    Detecta o erro clássico de 'Shortcut Reasoning' / parada em passo intermediário:
    Ex: se o enunciado pede 'valor total' ou 'ao todo', e a justificativa/scratchpad calcula um produto final
    (ex: N * unitário = total), o gabarito NÃO pode ser o valor unitário intermediário.
    """
    clean_enunciado = enunciado.lower()
    clean_just = justificativa.lower()
    clean_scratch = (scratchpad or "").lower()
    combined_reasoning = f"{clean_scratch}\n{clean_just}"

    alt_escolhida = alternativas.get(gabarito, "").strip()

    # Checagem de 'valor total' vs 'valor unitário':
    asks_for_total = any(k in clean_enunciado for k in ["valor total", "ao todo", "quantia total", "custo total", "total pago", "total arrecadado"])
    if asks_for_total:
        # Procura multiplicações do tipo N * X = Y ou N x X = Y no raciocínio
        mult_match = re.search(r"(\d+)\s*(?:[xX*×]|vezes)\s*(\d+(?:[\.,]\d+)?)\s*=\s*(\d+(?:[\.,]\d+)?)", combined_reasoning)
        if mult_match:
            qtd, unit, total_val = mult_match.groups()

            def norm_num(n_str: str) -> str:
                return re.sub(r"[^\d]", "", n_str.split(",")[0].split(".")[0])

            unit_norm = norm_num(unit)
            total_norm = norm_num(total_val)
            alt_norm = norm_num(alt_escolhida)

            if alt_norm and unit_norm and total_norm:
                if alt_norm == unit_norm and alt_norm != total_norm:
                    msg = (
                        f"Inconsistência semântica de comando (Shortcut Reasoning): O enunciado solicita o 'valor total' ({total_val}), "
                        f"mas o gabarito selecionado ({gabarito}) aponta para o valor unitário intermediário ({alt_escolhida})."
                    )
                    logger.warning(msg)
                    return False, msg

    return True, None


def _jaccard_similarity(text_a: str, text_b: str) -> float:
    """Calcula a similaridade de Jaccard com base nos conjuntos de palavras."""
    words_a = set(re.findall(r"\w+", text_a.lower()))
    words_b = set(re.findall(r"\w+", text_b.lower()))
    if not words_a or not words_b:
        return 0.0
    intersection = len(words_a.intersection(words_b))
    union = len(words_a.union(words_b))
    return intersection / union if union > 0 else 0.0


TABLE_INDICATOR_PATTERNS = [
    r"\btabela\s+a\s+seguir\b",
    r"\btabela\s+abaixo\b",
    r"\bquadro\s+a\s+seguir\b",
    r"\bquadro\s+abaixo\b",
    r"\bapresentados?\s+na\s+tabela\b",
    r"\bapresentadas?\s+na\s+tabela\b",
    r"\bconstam\s+na\s+tabela\b",
    r"\bconstam\s+no\s+quadro\b",
    r"\bdados\s+da\s+tabela\b",
    r"\bna\s+seguinte\s+tabela\b",
    r"\bno\s+seguinte\s+quadro\b",
    r"\bconforme\s+a\s+tabela\b",
    r"\bconforme\s+o\s+quadro\b",
    r"\bmostrad[oa]s?\s+na\s+tabela\b",
    r"\bmostrad[oa]s?\s+no\s+quadro\b",
    r"\bobservando\s+a\s+tabela\b",
    r"\bobservando\s+o\s+quadro\b",
    r"\bsegundo\s+a\s+tabela\b",
]


TABLE_INDICATOR_PATTERNS = [
    r"\btabela\s+a\s+seguir\b",
    r"\btabela\s+abaixo\b",
    r"\bquadro\s+a\s+seguir\b",
    r"\bquadro\s+abaixo\b",
    r"\bapresentados?\s+na\s+tabela\b",
    r"\bapresentadas?\s+na\s+tabela\b",
    r"\bconstam\s+na\s+tabela\b",
    r"\bconstam\s+no\s+quadro\b",
    r"\bdados\s+da\s+tabela\b",
    r"\bna\s+seguinte\s+tabela\b",
    r"\bno\s+seguinte\s+quadro\b",
    r"\bconforme\s+a\s+tabela\b",
    r"\bconforme\s+o\s+quadro\b",
    r"\bmostrad[oa]s?\s+na\s+tabela\b",
    r"\bmostrad[oa]s?\s+no\s+quadro\b",
    r"\bobservando\s+a\s+tabela\b",
    r"\bobservando\s+o\s+quadro\b",
    r"\bsegundo\s+a\s+tabela\b",
]


def check_table_markdown_structure(enunciado: str) -> Tuple[bool, Optional[str]]:
    """
    Verifica se enunciados que anunciam uma tabela possuem estrutura de tabela em Markdown válida.
    Evita que o LLM achate dados tabulares em texto corrido e confuso.
    """
    clean_text = enunciado.lower()
    announces_table = any(re.search(pat, clean_text) for pat in TABLE_INDICATOR_PATTERNS)
    if not announces_table:
        return True, None

    # Verifica linhas com pipes
    lines = [line.strip() for line in enunciado.split("\n") if line.strip()]
    pipe_lines = [l for l in lines if "|" in l]
    # Linha delimitadora clássica do Markdown: ex | --- | --- | ou |:---|:---:|
    has_delimiter = any(re.search(r"\|?\s*:?-{2,}:?\s*\|", l) for l in pipe_lines)

    if len(pipe_lines) >= 3 and has_delimiter:
        return True, None

    msg = (
        "Problema de formatação tabular: O enunciado menciona a apresentação de uma tabela "
        "(ex: 'tabela a seguir/abaixo'), mas não contém uma tabela estruturada em Markdown válida. "
        "Você DEVE OBRIGATORIAMENTE formatar os dados tabulares como uma tabela Markdown "
        "(com cabeçalho '| Col 1 | Col 2 |', delimitador '| :--- | :---: |' e linhas de dados separadas por '\\n')."
    )
    return False, msg


def format_enunciado_with_table(
    enunciado: str,
    tabela_dados: Optional[List[Dict[str, Any]]]
) -> str:
    """
    Converte tabela_dados em uma tabela Markdown e anexa ao enunciado de forma idempotente e limpa:
    1. Se tabela_dados for vazia ou None, retorna o enunciado inalterado.
    2. Se o enunciado já contiver uma tabela Markdown com delimitadores (| --- |), não duplica.
    3. Remove blocos redundantes de pseudo-tabelas ou listas introduzidas por 'Tabela ...:' que repetem os dados.
    4. Anexa a tabela Markdown formatada ao enunciado.
    """
    if not tabela_dados or not isinstance(tabela_dados, list) or len(tabela_dados) == 0:
        return enunciado

    # Monta a tabela Markdown canônica
    keys = list(tabela_dados[0].keys())
    md_table = "\n\n| " + " | ".join(keys) + " |\n"
    md_table += "| " + " | ".join(["---"] * len(keys)) + " |\n"
    for row in tabela_dados:
        md_table += "| " + " | ".join([str(row.get(k, "")) for k in keys]) + " |\n"

    # 1. Se já existe uma tabela Markdown com linha divisória (| --- |), não anexa outra
    if re.search(r"\|(?:\s*:?-+:?\s*\|)+", enunciado):
        return enunciado

    # 2. Higieniza eventuais pseudo-tabelas em texto simples ou listas de tópicos redundantes
    # Padrão: 'Tabela ...:' seguido de linhas com marcadores (- ou *) ou barras verticais (|)
    clean_enunciado = re.sub(
        r"(?:\n\s*(?:Tabela|Quadro)[^\n:]*:\s*\n(?:[ \t]*[-*•|].*(?:\n|$))+)",
        "\n",
        enunciado,
        flags=re.IGNORECASE
    ).strip()

    # Se após remoção ainda houver uma pseudo-tabela de pipes solta no final sem cabeçalho específico
    if "|" in clean_enunciado:
        lines = clean_enunciado.split("\n")
        non_pipe_lines = []
        trailing_pipe = True
        for line in reversed(lines):
            if trailing_pipe and ("|" in line or not line.strip()):
                continue
            trailing_pipe = False
            non_pipe_lines.append(line)
        if len(non_pipe_lines) < len(lines):
            candidate = "\n".join(reversed(non_pipe_lines)).strip()
            if len(candidate) > 30:  # preserva o enunciado principal
                clean_enunciado = candidate

    return clean_enunciado + md_table


def validate_questao_inedita(
    raw_output: Union[str, Dict[str, Any]],
    few_shot_exemplos: Optional[List[Dict[str, Any]]] = None
) -> Tuple[bool, Optional[str], Optional[QuestaoIneditaLLMOutput]]:
    """
    Realiza a validação estrutural e semântica obrigatória do item inédito antes de salvar no banco:
    1. Parsing e conformidade com o schema Pydantic QuestaoIneditaLLMOutput (RN-Q02).
    2. Sanitização de sintaxe LaTeX pré-parsing e pós-parsing.
    3. Existência de exatamente 5 alternativas (A, B, C, D, E) com textos não vazios.
    4. Gabarito válido e restrito a uma única letra ('A' a 'E').
    5. Unicidade estrita das alternativas (RN-Q01: ausência de alternativas duplicadas).
    6. Verificação de originalidade (não plagiar enunciados dos exemplos few-shot fornecidos).
    7. Validação semântica de alinhamento comando-gabarito (mitigação de shortcut reasoning).
    8. Validação estrutural de tabelas Markdown quando anunciadas.

    Retorna: (is_valid, error_message, parsed_model_or_none)
    """
    # 1. Extração, sanitização de LaTeX e decodificação do JSON
    if isinstance(raw_output, dict):
        data = sanitize_parsed_dict_values(raw_output)
    else:
        json_str = extract_json_from_text(raw_output)
        json_str = sanitize_latex_json_text(json_str)
        try:
            data = json.loads(json_str)
            data = sanitize_parsed_dict_values(data)
        except json.JSONDecodeError as e:
            msg = f"Falha ao decodificar JSON gerado pelo LLM: {str(e)}"
            logger.warning(msg)
            return False, msg, None

    if not isinstance(data, dict):
        msg = f"O retorno do LLM não é um objeto JSON/dicionário. Tipo obtido: {type(data).__name__}"
        logger.warning(msg)
        return False, msg, None

    # 2. Validação via Pydantic Schema (inclui validação de alternativas e unicidade - RN-Q01 e RN-Q02)
    try:
        validated_item = QuestaoIneditaLLMOutput.model_validate(data)
        
        if validated_item.tabela_dados:
            try:
                validated_item.enunciado = format_enunciado_with_table(
                    enunciado=validated_item.enunciado,
                    tabela_dados=validated_item.tabela_dados
                )
            except Exception as e:
                logger.warning(f"Aviso ao converter tabela_dados para Markdown no modo tradicional: {e}")
                
    except ValidationError as e:
        error_details = []
        for err in e.errors():
            loc = " -> ".join(str(l) for l in err.get("loc", []))
            msg = err.get("msg", "")
            error_details.append(f"[{loc}]: {msg}")
        msg = f"Erro de validação estrutural do item (RN-Q01/RN-Q02): {'; '.join(error_details)}"
        logger.warning(msg)
        return False, msg, None

    # 3. Verificação de anti-plágio com exemplos few-shot (não permitir cópia literal do banco)
    if few_shot_exemplos:
        enunciado_gerado = validated_item.enunciado
        for ex in few_shot_exemplos:
            ex_enunciado = ex.get("enunciado", "")
            if not ex_enunciado:
                continue
            sim = _jaccard_similarity(enunciado_gerado, ex_enunciado)
            if sim > 0.85:
                msg = f"Item gerado é excessivamente similar a um exemplo histórico de treino (similaridade Jaccard={sim:.2f}). Item descartado por ineditismo."
                logger.warning(msg)
                return False, msg, None

    # 4. Validação semântica de alinhamento comando-gabarito
    is_aligned, align_error = check_command_gabarito_alignment(
        enunciado=validated_item.enunciado,
        alternativas=validated_item.alternativas,
        gabarito=validated_item.gabarito,
        justificativa=validated_item.justificativa,
        scratchpad=validated_item.thought_scratchpad
    )
    if not is_aligned:
        return False, align_error, None

    # 5. Validação estrutural de tabelas Markdown quando anunciadas
    is_table_valid, table_error = check_table_markdown_structure(validated_item.enunciado)
    if not is_table_valid:
        logger.warning(table_error)
        return False, table_error, None

    return True, None, validated_item


def check_prohibited_terms(text: str) -> Tuple[bool, Optional[str]]:
    """
    Verifica deterministicamente via regex se o texto contém palavras de bastidores técnicos proibidas.
    Evita vazamento de termos como 'solver', 'python', 'código', 'algoritmo', 'distrator' e 'gabarito'.
    """
    if not text:
        return True, None

    prohibited_patterns = [
        (r"\bsolver\b", "solver"),
        (r"\bpython\b", "python"),
        (r"\bcódigo\b", "código"),
        (r"\bcodigo\b", "codigo"),
        (r"\balgoritmo\b", "algoritmo"),
        (r"\bdistrator(?:es)?\b", "distrator"),
        (r"\bgabarito\b", "gabarito"),
    ]
    for pattern, name in prohibited_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return False, f"Presença de termo técnico de bastidor proibido no enunciado: '{name}'"
    return True, None


def check_table_duplication(enunciado: str, tabela_dados: Optional[List[Dict[str, Any]]]) -> Tuple[bool, Optional[str]]:
    """
    Verifica se o enunciado duplicou dados da tabela em formato tabular Markdown cru (com pipes '|').
    No pipeline PoT, os dados residem exclusivamente em tabela_dados e são formatados pelo sistema.
    """
    if not tabela_dados or not enunciado:
        return True, None
    if "|" in enunciado:
        return False, "TABELA_INVALIDA: O texto do enunciado contém estrutura de tabela bruta (pipes '|'). Os dados devem residir exclusivamente em 'tabela_dados'."
    return True, None


def validate_tabela_dados(tabela_dados: Optional[List[Dict[str, Any]]]) -> Tuple[bool, Optional[str]]:
    """
    Valida a integridade estrutural de tabela_dados (A3):
    1. Máximo de 6 linhas.
    2. Todas as linhas devem ter exatamente as mesmas chaves.
    """
    if tabela_dados is None:
        return True, None
    if not isinstance(tabela_dados, list):
        return False, "TABELA_INVALIDA: 'tabela_dados' deve ser uma lista de dicionários."
    if len(tabela_dados) > 6:
        return False, f"TABELA_INVALIDA: 'tabela_dados' deve ter no máximo 6 linhas (encontrado: {len(tabela_dados)})."
    if len(tabela_dados) > 0:
        if not isinstance(tabela_dados[0], dict) or not tabela_dados[0]:
            return False, "TABELA_INVALIDA: as linhas de 'tabela_dados' não podem ser vazias."
        expected_keys = list(tabela_dados[0].keys())
        expected_set = set(expected_keys)
        for idx, row in enumerate(tabela_dados, 1):
            if not isinstance(row, dict) or set(row.keys()) != expected_set or len(row.keys()) != len(expected_keys):
                return False, (
                    f"TABELA_INVALIDA: todas as linhas de 'tabela_dados' devem ter exatamente as mesmas chaves. "
                    f"Esperado {expected_keys}, linha {idx} possui {list(row.keys()) if isinstance(row, dict) else type(row).__name__}."
                )
    return True, None


