"""
Módulo de execução segura, validação e auto-cura de solvers em código Python para geração de questões.
Exporta a interface pública e utilitários de análise estática e matemática.
"""

from app.services.code_executor.safety import (
    BLOCKED_MODULES,
    BLOCKED_CALLS,
    ALLOWED_BUILTINS,
    check_free_variables,
    check_code_safety,
)
from app.services.code_executor.runner import (
    sanitize_solver_code,
    execute_solver_code,
)
from app.services.code_executor.healing import (
    format_number,
    auto_heal_distractors,
)
from app.services.code_executor.analyzer import (
    ALLOWED_NUMERIC_CONSTANTS,
    _WORDS_TO_NUMBERS,
    validate_solver_complexity,
    validate_no_degenerate_ties,
)
from app.services.code_executor.assembly import (
    validate_solver_consistency,
    assemble_alternatives_and_gabarito,
)

__all__ = [
    "BLOCKED_MODULES",
    "BLOCKED_CALLS",
    "ALLOWED_BUILTINS",
    "ALLOWED_NUMERIC_CONSTANTS",
    "_WORDS_TO_NUMBERS",
    "check_free_variables",
    "check_code_safety",
    "sanitize_solver_code",
    "execute_solver_code",
    "format_number",
    "auto_heal_distractors",
    "validate_solver_complexity",
    "validate_no_degenerate_ties",
    "validate_solver_consistency",
    "assemble_alternatives_and_gabarito",
]
