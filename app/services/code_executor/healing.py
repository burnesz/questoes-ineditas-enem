"""
Módulo de formatação numérica, deduplicação e auto-cura de alternativas de questões.
"""

import logging
from typing import Any, List, Set

logger = logging.getLogger(__name__)


def format_number(val: Any) -> str:
    """Formata valores numéricos para padrão brasileiro limpo (vírgula decimal, até 2 casas)."""
    try:
        num = float(val)
    except (ValueError, TypeError):
        return str(val).strip()

    if num.is_integer():
        return str(int(num))

    formatted = f"{num:.2f}".rstrip("0").rstrip(".")
    return formatted.replace(".", ",")


def _normalize_five_distractors(correta_val: Any, distratores_vals: List[Any]) -> List[Any]:
    """Descarta elemento duplicado quando o solver retorna 5 distratores incluindo a resposta correta."""
    if len(distratores_vals) != 5:
        return list(distratores_vals)

    correta_str = format_number(correta_val)
    filtered: List[Any] = []
    removed_one = False
    for d in distratores_vals:
        if not removed_one and format_number(d) == correta_str:
            removed_one = True
            continue
        filtered.append(d)

    if len(filtered) == 4:
        logger.info("Solver retornou 5 distratores com 1 igual à correta; duplicata descartada.")
        return filtered

    dedup: List[Any] = []
    seen_strs: Set[str] = set()
    for d in distratores_vals:
        d_str = format_number(d)
        if d_str not in seen_strs:
            seen_strs.add(d_str)
            dedup.append(d)
    if len(dedup) >= 4:
        return dedup[:4]

    return list(distratores_vals)[:4]


def auto_heal_distractors(
    correta_val: Any,
    distratores_vals: List[Any]
) -> List[str]:
    """Gera distratores substitutos plausíveis e únicos quando ocorrem colisões entre alternativas."""
    correta_str = format_number(correta_val)
    seen: Set[str] = {correta_str}
    accepted: List[str] = []

    for d in distratores_vals:
        d_str = format_number(d)
        if d_str not in seen:
            seen.add(d_str)
            accepted.append(d_str)

    if len(accepted) == 4:
        return accepted

    try:
        c_num = float(correta_val)
        all_nums: List[float] = [c_num]
        for d in distratores_vals:
            try:
                all_nums.append(float(d))
            except (ValueError, TypeError):
                pass

        is_int = c_num.is_integer() and all(n.is_integer() for n in all_nums)
        unique_floats = sorted(list(set(all_nums)))

        if len(unique_floats) >= 2:
            diffs = [
                unique_floats[i + 1] - unique_floats[i]
                for i in range(len(unique_floats) - 1)
                if unique_floats[i + 1] - unique_floats[i] > 1e-4
            ]
            delta = min(diffs) if diffs else 1.0
        else:
            base = abs(c_num) if abs(c_num) > 0 else 1.0
            delta = max(1.0, round(base * 0.2)) if is_int else round(base * 0.2, 2)
            if delta == 0:
                delta = 1.0

        if is_int and delta < 1.0:
            delta = 1.0

        min_val = min(unique_floats)
        max_val = max(unique_floats)
        all_non_negative = all(x >= 0 for x in unique_floats)

        candidates: List[float] = []

        for k in range(1, 25):
            candidates.append(max_val + k * delta)
            cand_below = min_val - k * delta
            if not all_non_negative or cand_below >= 0:
                candidates.append(cand_below)

            candidates.append(c_num + k * delta)
            cand_c_below = c_num - k * delta
            if not all_non_negative or cand_c_below >= 0:
                candidates.append(cand_c_below)

        if c_num != 0:
            candidates.append(c_num * 2.0)
            candidates.append(c_num * 1.5)
            candidates.append(c_num * 0.5)
            if is_int:
                candidates.append(c_num + 1.0)
                if not all_non_negative or c_num - 1.0 >= 0:
                    candidates.append(c_num - 1.0)
                candidates.append(c_num + 2.0)
                if not all_non_negative or c_num - 2.0 >= 0:
                    candidates.append(c_num - 2.0)
            if abs(c_num) >= 10:
                candidates.append(c_num * 10.0)
                candidates.append(c_num / 10.0)

        for cand in candidates:
            if is_int:
                cand = round(cand)
            cand_str = format_number(cand)
            if cand_str not in seen:
                seen.add(cand_str)
                accepted.append(cand_str)
                if len(accepted) == 4:
                    break

    except (ValueError, TypeError):
        pass

    suffix_idx = 1
    while len(accepted) < 4:
        cand_str = f"{correta_str} (Opção {suffix_idx})"
        if cand_str not in seen:
            seen.add(cand_str)
            accepted.append(cand_str)
        suffix_idx += 1

    return accepted
