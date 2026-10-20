"""
Módulo de validação de consistência matemática, nexo numérico e montagem de alternativas.
"""

import json
import logging
import random
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from app.schemas.question import PipelineErrorCode, PipelineValidationError
from app.services.code_executor.healing import (
    format_number,
    _normalize_five_distractors,
    auto_heal_distractors
)
from app.services.code_executor.analyzer import (
    ALLOWED_NUMERIC_CONSTANTS,
    _WORDS_TO_NUMBERS,
    _slice_correta_and_validate_distractors,
    validate_no_degenerate_ties
)

logger = logging.getLogger(__name__)


def validate_solver_consistency(
    enunciado: str,
    code: str,
    result: Dict[str, Any],
    tabela_dados: Optional[List[Dict[str, Any]]] = None
) -> List[str]:
    """
    Valida a consistência matemática e o nexo entre o código do solver e o texto do enunciado.
    Garante unicidade estrita das alternativas e conformidade dos números usados no cálculo.
    """
    validate_no_degenerate_ties(enunciado=enunciado, code=code, result=result)

    correta_val = result["correta"]
    distratores_vals = list(result["distratores"])

    if len(distratores_vals) == 5:
        distratores_vals = _normalize_five_distractors(correta_val, distratores_vals)

    correta_str = format_number(correta_val)
    dist_strs = [format_number(d) for d in distratores_vals]
    all_values = [correta_str] + dist_strs

    unique_valid_distractors = {d for d in dist_strs if d != correta_str}
    num_collisions = 4 - len(unique_valid_distractors)

    if num_collisions > 1:
        raise PipelineValidationError(
            PipelineErrorCode.COLISAO,
            f"Colisão excessiva de alternativas no solver ({num_collisions} colisões em {all_values}). "
            f"O solver deve produzir pelo menos 3 distratores únicos distintos do gabarito."
        )
    elif num_collisions == 1 or len(set(all_values)) != 5:
        logger.warning(
            f"Auto-Healing: 1 colisão de alternativa detectada no solver ({all_values}). "
            f"Acionando auto-cura algorítmica para 1 distrator..."
        )
        dist_strs = auto_heal_distractors(
            correta_val=correta_val,
            distratores_vals=distratores_vals
        )
        all_values = [correta_str] + dist_strs
        logger.info(f"Auto-Healing: Alternativas curadas com sucesso: {all_values}")

    if len(set(all_values)) != 5:
        duplicates = [v for v in all_values if all_values.count(v) > 1]
        raise PipelineValidationError(
            PipelineErrorCode.COLISAO,
            f"Alternativas duplicadas geradas pelo solver mesmo após auto-healing: {all_values}. Valores repetidos: {set(duplicates)}."
        )

    combined_source = enunciado
    if tabela_dados:
        combined_source = f"{enunciado}\n{json.dumps(tabela_dados, ensure_ascii=False)}"

    enun_floats: Set[float] = set()

    for match in re.finditer(r"\b\d{1,3}(?:\.\d{3})+(?:,\d+)?\b", combined_source):
        raw_val = match.group(0).replace(".", "").replace(",", ".")
        try:
            enun_floats.add(float(raw_val))
        except ValueError:
            pass

    raw_enun_matches = re.findall(r"\b\d+(?:[\.,]\d+)?\b", combined_source)
    for n in raw_enun_matches:
        try:
            enun_floats.add(float(n.replace(",", ".")))
        except ValueError:
            pass

    for word in re.findall(r"[a-zA-ZÀ-ÿ]+", combined_source.lower()):
        if word in _WORDS_TO_NUMBERS:
            enun_floats.add(_WORDS_TO_NUMBERS[word])

    has_pct_context = bool(
        re.search(r"(%|percentua(?:l|is)|porcentagen(?:s)?|porcentagem)", combined_source, re.IGNORECASE)
    )
    if has_pct_context:
        for val_pct in list(enun_floats):
            if 0 < val_pct <= 100:
                enun_floats.add(round(val_pct / 100.0, 6))
                enun_floats.add(round((100.0 - val_pct) / 100.0, 6))
                if val_pct < 100:
                    enun_floats.add(round(100.0 - val_pct, 6))
                    enun_floats.add(round((100.0 + val_pct) / 100.0, 6))

    code_floats = _slice_correta_and_validate_distractors(code, enun_floats)

    pi_approximations = {n for n in code_floats if abs(n - 3.14159265) < 0.005}
    if pi_approximations and not (pi_approximations & enun_floats):
        raise PipelineValidationError(
            PipelineErrorCode.USO_PI,
            "Aproximação de π não declarada no enunciado: se usar π, escreva 'considere π = 3,14' no enunciado e use 3.14 no solver"
        )

    missing_numbers = {
        n for n in code_floats
        if n not in enun_floats and n not in ALLOWED_NUMERIC_CONSTANTS
    }

    if missing_numbers:
        missing_fmt = sorted([int(x) if x.is_integer() else x for x in missing_numbers])
        raise PipelineValidationError(
            PipelineErrorCode.NEXO_NUMERICO,
            f"Números utilizados na lógica do solver ausentes no enunciado da questão: {missing_fmt}. "
            f"O enunciado e o solver devem utilizar os mesmos dados numéricos."
        )

    return all_values


def assemble_alternatives_and_gabarito(
    formatted_values: List[str]
) -> Tuple[Dict[str, str], str]:
    """Embaralha as 5 alternativas de forma determinística e define o gabarito oficial."""
    correta = formatted_values[0]
    shuffled = list(formatted_values)
    random.shuffle(shuffled)

    letras = ["A", "B", "C", "D", "E"]
    alternativas = {letra: valor for letra, valor in zip(letras, shuffled)}
    gabarito = letras[shuffled.index(correta)]

    return alternativas, gabarito
