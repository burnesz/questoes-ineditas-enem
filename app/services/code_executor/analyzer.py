"""
Módulo de análise de complexidade determinística, backward slicing e verificação de empates no solver.
"""

import ast
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from app.schemas.question import PipelineErrorCode, PipelineValidationError
from app.services.code_executor.runner import sanitize_solver_code
from app.services.code_executor.healing import format_number

ALLOWED_NUMERIC_CONSTANTS: Set[float] = {
    0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 10.0, 12.0, 24.0, 60.0, 100.0, 180.0, 360.0, 1000.0,
    0.5, 0.1, 0.01, 3.14, 3.1415, 3.1416
}

_WORDS_TO_NUMBERS: Dict[str, float] = {
    "zero": 0.0,
    "um": 1.0, "uma": 1.0, "unico": 1.0, "único": 1.0, "unica": 1.0, "única": 1.0,
    "dois": 2.0, "duas": 2.0, "ambos": 2.0, "ambas": 2.0, "par": 2.0, "dobro": 2.0, "duplo": 2.0, "bimestre": 2.0, "bimestral": 2.0,
    "tres": 3.0, "três": 3.0, "triplo": 3.0, "trimestre": 3.0, "trimestral": 3.0,
    "quatro": 4.0, "quadruplo": 4.0, "quádruplo": 4.0, "quadrimestre": 4.0,
    "cinco": 5.0, "quintuplo": 5.0, "quíntuplo": 5.0,
    "seis": 6.0, "semestre": 6.0, "semestral": 6.0, "meia": 6.0,
    "sete": 7.0,
    "oito": 8.0,
    "nove": 9.0,
    "dez": 10.0, "dezena": 10.0, "decada": 10.0, "década": 10.0,
    "onze": 11.0,
    "doze": 12.0, "duzia": 12.0, "dúzia": 12.0,
    "treze": 13.0,
    "quatorze": 14.0, "catorze": 14.0,
    "quinze": 15.0, "quinzena": 15.0,
    "dezesseis": 16.0,
    "dezessete": 17.0,
    "dezoito": 18.0,
    "dezenove": 19.0,
    "vinte": 20.0,
    "trinta": 30.0,
    "quarenta": 40.0,
    "cinquenta": 50.0,
    "sessenta": 60.0,
    "setenta": 70.0,
    "oitenta": 80.0,
    "noventa": 90.0,
    "cem": 100.0, "cento": 100.0, "centena": 100.0,
    "duzentos": 200.0, "duzentas": 200.0,
    "trezentos": 300.0, "trezentas": 300.0,
    "quatrocentos": 400.0, "quatrocentas": 400.0,
    "quinhentos": 500.0, "quinhentas": 500.0,
    "seiscentos": 600.0, "seiscentas": 600.0,
    "setecentos": 700.0, "setecentas": 700.0,
    "oitocentos": 800.0, "oitocentas": 800.0,
    "novecentos": 900.0, "novecentas": 900.0,
    "mil": 1000.0,
    "meio": 0.5, "metade": 0.5,
    "terco": 3.0, "terço": 3.0, "terca": 3.0, "terça": 3.0,
    "quarto": 4.0, "quarta": 4.0,
    "quinto": 5.0, "quinta": 5.0,
}


def _extract_numeric_literals_from_ast(node: ast.AST) -> Set[float]:
    """Extrai todos os literais numéricos presentes em uma subárvore AST."""
    nums: Set[float] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, (int, float)) and not isinstance(child.value, bool):
            nums.add(float(child.value))
    return nums


def _extract_loaded_names_from_ast(node: ast.AST) -> Set[str]:
    """Extrai identificadores lidos (ctx=Load) em uma subárvore AST."""
    return {
        child.id
        for child in ast.walk(node)
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)
    }


def _extract_stored_names_from_ast(node: ast.AST) -> Set[str]:
    """Extrai identificadores escritos (ctx=Store) em um alvo de atribuição AST."""
    return {
        child.id
        for child in ast.walk(node)
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store)
    }


def _slice_correta_and_validate_distractors(
    code: str,
    enun_floats: Set[float]
) -> Set[float]:
    """
    Executa backward slicing na AST de resolver():
    - Extrai os literais numéricos da fatia que computa 'correta'.
    - Garante que cada distrator 'erro_*' dependa de variáveis fundamentadas no problema.
    """
    clean_code = sanitize_solver_code(code)
    try:
        tree = ast.parse(clean_code)
    except SyntaxError:
        code_before_return = clean_code.split("return")[0] if "return" in clean_code else clean_code
        code_no_comments = re.sub(r"#.*", "", code_before_return)
        return {float(n) for n in re.findall(r"\b\d+(?:\.\d+)?\b", code_no_comments)}

    target_body: List[ast.stmt] = tree.body
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "resolver":
            target_body = node.body
            break

    assign_records: List[Tuple[Set[str], Set[str], Set[float], ast.AST]] = []
    return_correta_expr: Optional[ast.AST] = None

    for stmt in target_body:
        for sub in ast.walk(stmt):
            if isinstance(sub, ast.Assign) and sub.value is not None:
                targets: Set[str] = set()
                for t in sub.targets:
                    targets |= _extract_stored_names_from_ast(t)
                used = _extract_loaded_names_from_ast(sub.value)
                lits = _extract_numeric_literals_from_ast(sub.value)
                assign_records.append((targets, used, lits, sub.value))
            elif isinstance(sub, ast.AnnAssign) and sub.value is not None:
                targets = _extract_stored_names_from_ast(sub.target)
                used = _extract_loaded_names_from_ast(sub.value)
                lits = _extract_numeric_literals_from_ast(sub.value)
                assign_records.append((targets, used, lits, sub.value))
            elif isinstance(sub, ast.AugAssign) and sub.value is not None:
                targets = _extract_stored_names_from_ast(sub.target)
                used = _extract_loaded_names_from_ast(sub.value) | targets
                lits = _extract_numeric_literals_from_ast(sub.value)
                assign_records.append((targets, used, lits, sub.value))
            elif isinstance(sub, ast.Return) and isinstance(sub.value, ast.Dict):
                for k_node, v_node in zip(sub.value.keys, sub.value.values):
                    if isinstance(k_node, ast.Constant) and k_node.value == "correta" and v_node is not None:
                        return_correta_expr = v_node

    has_correta_var = any("correta" in rec[0] for rec in assign_records)
    if not has_correta_var and return_correta_expr is not None:
        ret_lits = (
            set()
            if isinstance(return_correta_expr, ast.Constant)
            else _extract_numeric_literals_from_ast(return_correta_expr)
        )
        assign_records.append((
            {"correta"},
            _extract_loaded_names_from_ast(return_correta_expr),
            ret_lits,
            return_correta_expr
        ))

    slice_vars: Set[str] = {"correta"}
    changed = True
    while changed:
        changed = False
        for targets, used, _, _ in reversed(assign_records):
            if targets & slice_vars:
                new_vars = used - slice_vars
                if new_vars:
                    slice_vars |= new_vars
                    changed = True

    correta_floats: Set[float] = set()
    for targets, _, lits, _ in assign_records:
        if targets & slice_vars:
            correta_floats |= lits

    all_assigned_vars = {v for targets, _, _, _ in assign_records for v in targets}
    grounded_vars: Set[str] = {
        v for v in (slice_vars & all_assigned_vars)
        if not v.startswith("erro_")
    }
    changed = True
    while changed:
        changed = False
        for targets, used, lits, _ in assign_records:
            non_erro_targets = {t for t in targets if not t.startswith("erro_")}
            if not non_erro_targets or non_erro_targets.issubset(grounded_vars):
                continue
            lits_ok = all(n in enun_floats or n in ALLOWED_NUMERIC_CONSTANTS for n in lits)
            has_enun_lit = any(n in enun_floats for n in lits)
            has_grounded_dep = bool(used & grounded_vars)
            if lits_ok and (has_enun_lit or has_grounded_dep):
                grounded_vars |= non_erro_targets
                changed = True

    var_direct_deps: Dict[str, Set[str]] = {}
    erro_vars: List[str] = []
    for targets, used, _, _ in assign_records:
        for t in targets:
            var_direct_deps.setdefault(t, set()).update(used)
            if t.startswith("erro_") and t not in erro_vars:
                erro_vars.append(t)

    for erro_var in erro_vars:
        deps: Set[str] = set(var_direct_deps.get(erro_var, set()))
        worklist = list(deps)
        while worklist:
            curr = worklist.pop()
            for nxt in var_direct_deps.get(curr, set()):
                if nxt not in deps:
                    deps.add(nxt)
                    worklist.append(nxt)
        if not (deps & grounded_vars):
            raise PipelineValidationError(
                PipelineErrorCode.NEXO_NUMERICO,
                f"Distrator '{erro_var}' não depende de nenhuma variável fundamentada no enunciado/tabela "
                f"(literais soltos só são aceitos quando combinados com variáveis fundamentadas)."
            )

    return correta_floats


_NON_MATH_HELPER_CALLS = {
    "round", "float", "int", "str", "list", "dict", "set", "tuple",
    "sorted", "range", "enumerate", "zip", "bool"
}


def validate_solver_complexity(
    code: str,
    min_operations: Optional[int] = None,
    min_operation_types: Optional[int] = None
) -> Dict[str, Any]:
    """Calcula a complexidade da fatia de 'correta', exigindo encadeamento mínimo de operações."""
    from app.core.config import settings

    min_ops = min_operations if min_operations is not None else getattr(settings, "POT_MIN_OPERATIONS", 3)
    min_types = min_operation_types if min_operation_types is not None else getattr(settings, "POT_MIN_OPERATION_TYPES", 2)

    clean_code = sanitize_solver_code(code)
    tree = ast.parse(clean_code)

    target_body: List[ast.stmt] = tree.body
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "resolver":
            target_body = node.body
            break

    assign_records: List[Tuple[Set[str], Set[str], ast.AST, Optional[ast.operator]]] = []
    return_correta_expr: Optional[ast.AST] = None

    for stmt in target_body:
        for sub in ast.walk(stmt):
            if isinstance(sub, ast.Assign) and sub.value is not None:
                targets: Set[str] = set()
                for t in sub.targets:
                    targets |= _extract_stored_names_from_ast(t)
                used = _extract_loaded_names_from_ast(sub.value)
                assign_records.append((targets, used, sub.value, None))
            elif isinstance(sub, ast.AnnAssign) and sub.value is not None:
                targets = _extract_stored_names_from_ast(sub.target)
                used = _extract_loaded_names_from_ast(sub.value)
                assign_records.append((targets, used, sub.value, None))
            elif isinstance(sub, ast.AugAssign) and sub.value is not None:
                targets = _extract_stored_names_from_ast(sub.target)
                used = _extract_loaded_names_from_ast(sub.value) | targets
                assign_records.append((targets, used, sub.value, sub.op))
            elif isinstance(sub, ast.Return) and isinstance(sub.value, ast.Dict):
                for k_node, v_node in zip(sub.value.keys, sub.value.values):
                    if isinstance(k_node, ast.Constant) and k_node.value == "correta" and v_node is not None:
                        return_correta_expr = v_node

    has_correta_var = any("correta" in rec[0] for rec in assign_records)
    if not has_correta_var and return_correta_expr is not None:
        if isinstance(return_correta_expr, ast.Constant):
            return {"num_operations": min_ops, "operation_types": ["StubA", "StubB"], "chained_assignments": 1}
        assign_records.append((
            {"correta"},
            _extract_loaded_names_from_ast(return_correta_expr),
            return_correta_expr,
            None
        ))

    slice_vars: Set[str] = {"correta"}
    changed = True
    while changed:
        changed = False
        for targets, used, _, _ in reversed(assign_records):
            if targets & slice_vars:
                new_vars = used - slice_vars
                if new_vars:
                    slice_vars |= new_vars
                    changed = True

    total_ops = 0
    op_types: Set[str] = set()
    chained_assignments = 0

    for targets, used, val_node, aug_op in assign_records:
        if not (targets & slice_vars):
            continue
        stmt_ops = 0
        if aug_op is not None:
            total_ops += 1
            stmt_ops += 1
            op_types.add(type(aug_op).__name__)

        for child in ast.walk(val_node):
            if isinstance(child, ast.BinOp):
                total_ops += 1
                stmt_ops += 1
                op_types.add(type(child.op).__name__)
            elif isinstance(child, ast.Call):
                func_name = ""
                if isinstance(child.func, ast.Name):
                    func_name = child.func.id
                elif isinstance(child.func, ast.Attribute):
                    func_name = child.func.attr
                if func_name and func_name not in _NON_MATH_HELPER_CALLS:
                    total_ops += 1
                    stmt_ops += 1
                    op_types.add(f"call:{func_name}")

        if stmt_ops > 0 or used:
            chained_assignments += 1

    if total_ops < min_ops or len(op_types) < min_types:
        raise PipelineValidationError(
            PipelineErrorCode.COMPLEXIDADE,
            f"Complexidade determinística insuficiente na fatia de 'correta': "
            f"{total_ops} operações (mínimo {min_ops}) e {len(op_types)} tipos de operação {sorted(op_types)} (mínimo {min_types}). "
            f"Exija pelo menos 2 etapas de raciocínio encadeadas."
        )

    return {
        "num_operations": total_ops,
        "operation_types": sorted(op_types),
        "chained_assignments": chained_assignments
    }


_COMPARATIVE_SUPERLATIVE_RE = re.compile(
    r"\b(mais\s+econ[oô]mic[oa]|mais\s+vantajos[oa]|mais\s+barat[oa]|mais\s+car[oa]"
    r"|menor\s+custo|maior\s+custo|menor\s+pre[cç]o|maior\s+pre[cç]o"
    r"|menor\s+valor|maior\s+valor|menor\s+tempo|maior\s+lucro"
    r"|[oa]\s+maior|[oa]\s+menor|melhor\s+op[cç][aã]o)\b",
    re.IGNORECASE,
)


def validate_no_degenerate_ties(
    enunciado: str,
    code: str,
    result: Dict[str, Any]
) -> None:
    """Verifica empates degenerados entre alternativas quando a pergunta pede valor extremo."""
    locals_numeric = result.get("_locals_numeric")
    if not isinstance(locals_numeric, dict):
        locals_numeric = {}

    clean_code = sanitize_solver_code(code)
    try:
        tree = ast.parse(clean_code)
    except SyntaxError:
        return

    resolver_node: Optional[ast.FunctionDef] = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "resolver":
            resolver_node = node
            break
    if resolver_node is None:
        return

    for node in ast.walk(resolver_node):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("min", "max"):
            func_name = node.func.id
            candidate_nodes: List[ast.AST] = []
            if len(node.args) >= 2:
                candidate_nodes = list(node.args)
            elif len(node.args) == 1 and isinstance(node.args[0], (ast.List, ast.Tuple, ast.Set)):
                candidate_nodes = list(node.args[0].elts)

            resolved_vals: List[float] = []
            for c_node in candidate_nodes:
                if isinstance(c_node, ast.Name) and c_node.id in locals_numeric:
                    resolved_vals.append(float(locals_numeric[c_node.id]))
                elif isinstance(c_node, ast.Constant) and isinstance(c_node.value, (int, float)) and not isinstance(c_node.value, bool):
                    resolved_vals.append(float(c_node.value))

            if len(resolved_vals) >= 2:
                ext_val = min(resolved_vals) if func_name == "min" else max(resolved_vals)
                tie_count = sum(1 for v in resolved_vals if abs(v - ext_val) < 1e-6)
                if tie_count >= 2:
                    raise PipelineValidationError(
                        PipelineErrorCode.CASO_DEGENERADO,
                        f"Empate degenerado detectado em {func_name}(): {tie_count} opções empatam no valor extremo ({format_number(ext_val)})."
                    )

    correta_val = result.get("correta")
    if (
        locals_numeric
        and isinstance(correta_val, (int, float))
        and not isinstance(correta_val, bool)
        and _COMPARATIVE_SUPERLATIVE_RE.search(enunciado or "")
    ):
        computed_vars: Set[str] = set()
        for stmt in resolver_node.body:
            if isinstance(stmt, ast.Assign) and any(isinstance(c, (ast.BinOp, ast.Call)) for c in ast.walk(stmt.value)):
                for target in stmt.targets:
                    for name in _extract_stored_names_from_ast(target):
                        if not name.startswith("erro_") and name != "correta":
                            computed_vars.add(name)

        prefix_groups: Dict[str, List[Tuple[str, float]]] = {}
        for var_name in computed_vars:
            if "_" in var_name and var_name in locals_numeric:
                prefix = var_name.rsplit("_", 1)[0]
                prefix_groups.setdefault(prefix, []).append((var_name, float(locals_numeric[var_name])))

        c_float = float(correta_val)
        for prefix, items in prefix_groups.items():
            if len(items) >= 2:
                tied_vars = [name for name, val in items if abs(val - c_float) < 1e-6]
                if len(tied_vars) >= 2:
                    raise PipelineValidationError(
                        PipelineErrorCode.CASO_DEGENERADO,
                        f"Empate degenerado entre opções comparadas ({', '.join(sorted(tied_vars))} = {format_number(c_float)}) "
                        f"para pergunta comparativa/superlativa."
                    )
