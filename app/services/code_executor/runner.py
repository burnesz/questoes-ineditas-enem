"""
Módulo de instrumentação AST e execução isolada em subprocesso do código do solver.
"""

import ast
import json
import logging
import re
import subprocess
import sys
from typing import Any, Dict, List, Set

from app.schemas.question import PipelineErrorCode, PipelineValidationError
from app.services.code_executor.safety import check_code_safety
from app.services.code_executor.healing import format_number

logger = logging.getLogger(__name__)


def sanitize_solver_code(code: str) -> str:
    """Remove marcações de bloco markdown de código Python e espaços residuais."""
    code = code.strip()
    match = re.search(r"```(?:python)?\s*(.*?)\s*```", code, re.DOTALL | re.IGNORECASE)
    if match:
        code = match.group(1).strip()
    return code


class _ResolverLocalsTransformer(ast.NodeTransformer):
    """Transforma a função resolver() para retornar locals(), preservando retornos explícitos."""

    def __init__(self) -> None:
        super().__init__()
        self._in_resolver = False

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        if node.name == "resolver" and not self._in_resolver:
            self._in_resolver = True
            new_body = []
            for stmt in node.body:
                visited = self.visit(stmt)
                if isinstance(visited, list):
                    new_body.extend(visited)
                elif visited is not None:
                    new_body.append(visited)
            ret_locals = ast.Return(
                value=ast.Call(
                    func=ast.Name(id="locals", ctx=ast.Load()),
                    args=[],
                    keywords=[]
                )
            )
            new_body.append(ret_locals)
            node.body = new_body
            self._in_resolver = False
            return node
        return node

    def visit_Return(self, node: ast.Return) -> Any:
        if not self._in_resolver:
            return node
        assign_ret = ast.Assign(
            targets=[ast.Name(id="__explicit_return__", ctx=ast.Store())],
            value=node.value if node.value is not None else ast.Constant(value=None)
        )
        ret_locals = ast.Return(
            value=ast.Call(
                func=ast.Name(id="locals", ctx=ast.Load()),
                args=[],
                keywords=[]
            )
        )
        return [assign_ret, ret_locals]


def _instrument_resolver_ast(clean_code: str) -> str:
    """Instrumenta a AST de resolver() para capturar variáveis locais ao término."""
    tree = ast.parse(clean_code)
    has_resolver = any(
        isinstance(node, ast.FunctionDef) and node.name == "resolver"
        for node in tree.body
    )
    if not has_resolver:
        raise ValueError("O código fornecido não define a função obrigatória 'def resolver()'.")
    transformer = _ResolverLocalsTransformer()
    tree = transformer.visit(tree)
    ast.fix_missing_locations(tree)
    return ast.unparse(tree)


def execute_solver_code(code: str, timeout: int = 5) -> Dict[str, Any]:
    """Executa a função resolver() em subprocesso isolado com timeout estrito."""
    clean_code = sanitize_solver_code(code)
    check_code_safety(clean_code)

    if "def resolver" not in clean_code:
        raise ValueError("O código fornecido não define a função obrigatória 'def resolver()'.")

    instrumented_code = _instrument_resolver_ast(clean_code)

    runner_script = f"""
import json
import math
import types

{instrumented_code}

def _is_serializable_val(val):
    if val is None or isinstance(val, (bool, types.ModuleType, types.FunctionType, type)):
        return False
    return isinstance(val, (int, float, str, list, tuple, dict))

try:
    scope = resolver()
    if not isinstance(scope, dict):
        raise ValueError(f"Escopo inválido retornado por resolver(): {{type(scope).__name__}}")

    erro_vals = [
        v for k, v in scope.items()
        if k.startswith("erro_") and _is_serializable_val(v)
    ]
    locals_numeric = {{
        k: float(v) for k, v in scope.items()
        if not k.startswith("erro_")
        and k not in ("correta", "__explicit_return__")
        and isinstance(v, (int, float))
        and not isinstance(v, bool)
        and math.isfinite(float(v))
    }}

    if "correta" in scope and erro_vals:
        res = {{
            "correta": scope["correta"],
            "distratores": erro_vals,
            "_raw_erros_count": len(erro_vals),
            "_locals_numeric": locals_numeric
        }}
    elif "__explicit_return__" in scope and isinstance(scope["__explicit_return__"], dict):
        explicit = scope["__explicit_return__"]
        raw_d = explicit.get("distratores")
        res = {{
            "correta": explicit.get("correta"),
            "distratores": list(raw_d) if isinstance(raw_d, (list, tuple)) else raw_d,
            "_raw_erros_count": len(raw_d) if isinstance(raw_d, (list, tuple)) else 0,
            "_locals_numeric": locals_numeric
        }}
        if "correta" not in explicit or "distratores" not in explicit:
            res = explicit
    elif "correta" in scope:
        res = {{
            "correta": scope["correta"],
            "distratores": erro_vals,
            "_raw_erros_count": len(erro_vals),
            "_locals_numeric": locals_numeric
        }}
    else:
        raise ValueError("O dicionário retornado por resolver() deve conter as chaves 'correta' e 'distratores' (ou definir 'correta' e variáveis 'erro_*').")

    print("___RESULT_START___")
    print(json.dumps(res))
    print("___RESULT_END___")
except Exception as e:
    import sys
    sys.stderr.write(f"EXCECAO_SOLVER: {{type(e).__name__}}: {{str(e)}}")
    sys.exit(1)
"""

    try:
        proc = subprocess.run(
            [sys.executable, "-c", runner_script],
            capture_output=True,
            text=True,
            timeout=timeout
        )
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"O solver excedeu o tempo limite de execução ({timeout}s). Possível loop infinito.")

    if proc.returncode != 0:
        err_msg = proc.stderr.strip() or proc.stdout.strip()
        raise RuntimeError(f"Falha na execução do solver: {err_msg[:400]}")

    stdout = proc.stdout
    start_tag = "___RESULT_START___"
    end_tag = "___RESULT_END___"

    if start_tag not in stdout or end_tag not in stdout:
        raise ValueError(f"Saída do solver não formatada corretamente. Stdout: {stdout[:300]}")

    start_idx = stdout.find(start_tag) + len(start_tag)
    end_idx = stdout.find(end_tag)
    raw_json = stdout[start_idx:end_idx].strip()

    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as e:
        raise ValueError(f"Não foi possível decodificar o JSON retornado por resolver(): {e}. Raw: {raw_json}")

    if not isinstance(data, dict):
        raise ValueError(f"O retorno de resolver() deve ser um dicionário. Obtido: {type(data).__name__}")

    if "correta" not in data or "distratores" not in data:
        raise ValueError("O dicionário retornado por resolver() deve conter as chaves 'correta' e 'distratores'.")

    if not isinstance(data["distratores"], (list, tuple)):
        raise ValueError("A chave 'distratores' deve ser uma lista ou tupla.")

    raw_distratores = list(data["distratores"])
    raw_count = data.pop("_raw_erros_count", len(raw_distratores))

    if raw_count < 3:
        raise PipelineValidationError(
            PipelineErrorCode.DISTRATORES_INSUFICIENTES,
            f"Distratores insuficientes no solver: defina pelo menos 3 variáveis 'erro_*' (encontrado: {raw_count})."
        )

    correta_str = format_number(data["correta"])
    unique_distractors: List[Any] = []
    seen_strs: Set[str] = {correta_str}
    for d in raw_distratores:
        d_str = format_number(d)
        if d_str not in seen_strs:
            seen_strs.add(d_str)
            unique_distractors.append(d)

    if len(unique_distractors) < 3:
        num_collisions = max(4 - len(unique_distractors), raw_count - len(unique_distractors))
        raise PipelineValidationError(
            PipelineErrorCode.COLISAO,
            f"Colisão excessiva de alternativas no solver ({num_collisions} colisões). "
            f"O solver deve produzir pelo menos 3 distratores únicos distintos do gabarito."
        )

    data["distratores"] = unique_distractors[:4]
    return data
