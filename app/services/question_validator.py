"""
Validador estrutural e de integridade para questões inéditas do ENEM.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)


def extract_json_from_text(text: str) -> str:
    """Extrai o bloco JSON de uma resposta textual, suportando blocos markdown."""
    text = text.strip()
    match_md = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if match_md:
        return match_md.group(1).strip()

    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        return text[first_brace:last_brace + 1].strip()

    return text


def sanitize_latex_json_text(text: str) -> str:
    r"""
    Sanitiza expressões matemáticas em LaTeX no JSON bruto antes do json.loads().
    Normaliza formfeed (\x0c), escapes válidos do JSON e comandos comuns do LaTeX.
    """
    if not text:
        return text

    text = text.replace("\x0crac", "\\\\frac")
    text = text.replace("\x0c", " ")
    text = text.replace(r"\x0crac", "\\\\frac")
    text = text.replace(r"\x0c", " ")

    text = re.sub(r"(?<!\\)\\frac", r"\\\\frac", text)
    text = re.sub(r"(?<!\\)\\times", r"\\\\times", text)
    text = re.sub(r"(?<!\\)\\right", r"\\\\right", text)
    text = re.sub(r"(?<!\\)\\neq", r"\\\\neq", text)
    text = re.sub(r"(?<!\\)\\bar", r"\\\\bar", text)
    text = re.sub(r"(?<!\\)\\beta", r"\\\\beta", text)

    text = re.sub(r'\\(?!["\\/bfnrt]|u[0-9a-fA-F]{4})', r"\\\\", text)
    text = re.sub(r"(?<![\\a-zA-Z])rac\{", r"\\frac{", text)

    return text


def sanitize_parsed_dict_values(data: Any) -> Any:
    """Limpa resíduos de form feed e normaliza comandos LaTeX em estruturas decodificadas."""
    if isinstance(data, str):
        val = data.replace("\x0crac", r"\frac")
        val = val.replace("\x0c", " ")
        return re.sub(r"(?<![\\a-zA-Z])rac\{", r"\\frac{", val)
    if isinstance(data, dict):
        return {k: sanitize_parsed_dict_values(v) for k, v in data.items()}
    if isinstance(data, list):
        return [sanitize_parsed_dict_values(v) for v in data]
    return data




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
    """Verifica se enunciados que anunciam uma tabela possuem formatação tabular Markdown."""
    clean_text = enunciado.lower()
    announces_table = any(re.search(pat, clean_text) for pat in TABLE_INDICATOR_PATTERNS)
    if not announces_table:
        return True, None

    lines = [line.strip() for line in enunciado.split("\n") if line.strip()]
    pipe_lines = [l for l in lines if "|" in l]
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
    """Converte lista de dicionários em tabela Markdown e anexa ao enunciado se ainda não presente."""
    if not tabela_dados or not isinstance(tabela_dados, list) or len(tabela_dados) == 0:
        return enunciado

    keys = list(tabela_dados[0].keys())
    md_table = "\n\n| " + " | ".join(keys) + " |\n"
    md_table += "| " + " | ".join(["---"] * len(keys)) + " |\n"
    for row in tabela_dados:
        md_table += "| " + " | ".join([str(row.get(k, "")) for k in keys]) + " |\n"

    if re.search(r"\|(?:\s*:?-+:?\s*\|)+", enunciado):
        return enunciado

    clean_enunciado = re.sub(
        r"(?:\n\s*(?:Tabela|Quadro)[^\n:]*:\s*\n(?:[ \t]*[-*•|].*(?:\n|$))+)",
        "\n",
        enunciado,
        flags=re.IGNORECASE
    ).strip()

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
            if len(candidate) > 30:
                clean_enunciado = candidate

    return clean_enunciado + md_table




def check_prohibited_terms(text: str) -> Tuple[bool, Optional[str]]:
    """Detecta vazamento de termos técnicos internos no enunciado da questão."""
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
    """Verifica se o enunciado duplicou a estrutura da tabela quando tabela_dados é fornecida."""
    if not tabela_dados or not enunciado:
        return True, None
    if "|" in enunciado:
        return False, "TABELA_INVALIDA: O texto do enunciado contém estrutura de tabela bruta (pipes '|'). Os dados devem residir exclusivamente em 'tabela_dados'."
    return True, None


def validate_tabela_dados(tabela_dados: Optional[List[Dict[str, Any]]]) -> Tuple[bool, Optional[str]]:
    """Valida que tabela_dados possui até 6 linhas e colunas uniformes em todas as linhas."""
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
