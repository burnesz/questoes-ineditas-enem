"""
Módulo de análise estática e segurança AST para código de solvers.
"""

import ast
import builtins
from typing import List, Optional, Set

from app.schemas.question import PipelineErrorCode, PipelineValidationError

BLOCKED_MODULES: Set[str] = {
    "os", "sys", "subprocess", "socket", "shutil", "urllib", "requests",
    "http", "ftplib", "smtplib", "telnetlib", "pathlib", "posix", "nt",
    "pty", "commands", "builtin", "builtins", "_thread", "threading",
    "multiprocessing", "ctypes", "pickle", "shelve", "dbm", "sqlite3"
}

BLOCKED_CALLS: Set[str] = {
    "eval", "exec", "compile", "__import__", "open", "getattr", "setattr",
    "delattr", "input", "exit", "quit", "breakpoint"
}

ALLOWED_BUILTINS: Set[str] = set(dir(builtins)) | {"math", "json", "resolver"}


def _extract_store_names(node: ast.AST) -> Set[str]:
    """Extrai identificadores atribuídos (ctx=Store) em um nó AST."""
    names: Set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
            names.add(sub.id)
    return names


def _check_expr_free_vars(node: Optional[ast.AST], bound: Set[str]) -> Optional[str]:
    """Inspeciona recursivamente uma expressão AST buscando nomes livres."""
    if node is None:
        return None

    if isinstance(node, ast.Name):
        if isinstance(node.ctx, ast.Load) and node.id not in bound:
            return node.id
        return None

    if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
        comp_bound = set(bound)
        for gen in node.generators:
            free = _check_expr_free_vars(gen.iter, comp_bound)
            if free:
                return free
            comp_bound.update(_extract_store_names(gen.target))
            for if_clause in gen.ifs:
                free = _check_expr_free_vars(if_clause, comp_bound)
                if free:
                    return free
        if isinstance(node, ast.DictComp):
            free = _check_expr_free_vars(node.key, comp_bound)
            if free:
                return free
            return _check_expr_free_vars(node.value, comp_bound)
        return _check_expr_free_vars(node.elt, comp_bound)

    if isinstance(node, ast.Lambda):
        lam_bound = set(bound)
        for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs:
            lam_bound.add(arg.arg)
        if node.args.vararg:
            lam_bound.add(node.args.vararg.arg)
        if node.args.kwarg:
            lam_bound.add(node.args.kwarg.arg)
        return _check_expr_free_vars(node.body, lam_bound)

    if isinstance(node, ast.NamedExpr):
        free = _check_expr_free_vars(node.value, bound)
        if free:
            return free
        bound.update(_extract_store_names(node.target))
        return None

    for child in ast.iter_child_nodes(node):
        free = _check_expr_free_vars(child, bound)
        if free:
            return free
    return None


def _check_stmts_free_vars(stmts: List[ast.stmt], bound: Set[str]) -> Optional[str]:
    """Percorre instruções verificando variáveis livres antes de sua definição."""
    for stmt in stmts:
        if isinstance(stmt, ast.Assign):
            free = _check_expr_free_vars(stmt.value, bound)
            if free:
                return free
            for target in stmt.targets:
                if not isinstance(target, ast.Name):
                    for child in ast.iter_child_nodes(target):
                        free = _check_expr_free_vars(child, bound)
                        if free:
                            return free
                bound.update(_extract_store_names(target))
        elif isinstance(stmt, ast.AnnAssign):
            if stmt.value:
                free = _check_expr_free_vars(stmt.value, bound)
                if free:
                    return free
            bound.update(_extract_store_names(stmt.target))
        elif isinstance(stmt, ast.AugAssign):
            if isinstance(stmt.target, ast.Name) and stmt.target.id not in bound:
                return stmt.target.id
            free = _check_expr_free_vars(stmt.target, bound)
            if free:
                return free
            free = _check_expr_free_vars(stmt.value, bound)
            if free:
                return free
        elif isinstance(stmt, (ast.For, ast.AsyncFor)):
            free = _check_expr_free_vars(stmt.iter, bound)
            if free:
                return free
            bound.update(_extract_store_names(stmt.target))
            free = _check_stmts_free_vars(stmt.body, bound)
            if free:
                return free
            free = _check_stmts_free_vars(stmt.orelse, bound)
            if free:
                return free
        elif isinstance(stmt, (ast.While, ast.If)):
            free = _check_expr_free_vars(stmt.test, bound)
            if free:
                return free
            free = _check_stmts_free_vars(stmt.body, bound)
            if free:
                return free
            free = _check_stmts_free_vars(stmt.orelse, bound)
            if free:
                return free
        elif isinstance(stmt, ast.Import):
            for alias in stmt.names:
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(stmt, ast.ImportFrom):
            for alias in stmt.names:
                bound.add(alias.asname or alias.name)
        elif isinstance(stmt, ast.FunctionDef):
            bound.add(stmt.name)
            fn_bound = set(bound)
            for arg in stmt.args.posonlyargs + stmt.args.args + stmt.args.kwonlyargs:
                fn_bound.add(arg.arg)
            if stmt.args.vararg:
                fn_bound.add(stmt.args.vararg.arg)
            if stmt.args.kwarg:
                fn_bound.add(stmt.args.kwarg.arg)
            free = _check_stmts_free_vars(stmt.body, fn_bound)
            if free:
                return free
        else:
            for child in ast.iter_child_nodes(stmt):
                free = _check_expr_free_vars(child, bound)
                if free:
                    return free
    return None


def check_free_variables(tree: ast.Module) -> None:
    """Verifica variáveis não declaradas ou uso indevido de constantes matemáticas."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "pi":
            raise PipelineValidationError(
                PipelineErrorCode.USO_PI,
                "Uso de math.pi detectado: se usar π, escreva 'considere π = 3,14' no enunciado e use 3.14 no solver"
            )
        if isinstance(node, ast.ImportFrom) and node.module == "math":
            for alias in node.names:
                if alias.name == "pi":
                    raise PipelineValidationError(
                        PipelineErrorCode.USO_PI,
                        "Import de math.pi detectado: se usar π, escreva 'considere π = 3,14' no enunciado e use 3.14 no solver"
                    )

    bound: Set[str] = set(ALLOWED_BUILTINS)
    free = _check_stmts_free_vars(tree.body, bound)
    if free:
        if free.lower() in {"pi", "π"}:
            raise PipelineValidationError(
                PipelineErrorCode.USO_PI,
                "Variável 'pi' não declarada: se usar π, escreva 'considere π = 3,14' no enunciado e use 3.14 no solver"
            )
        raise PipelineValidationError(
            PipelineErrorCode.NOME_LIVRE,
            f"Variável externa/livre '{free}' não definida: "
            f"declare os valores como variáveis dentro de resolver(); não use variáveis externas"
        )


def check_code_safety(code: str) -> ast.Module:
    """Valida sintaxe, proíbe chamadas e imports inseguros e checa escopo de variáveis."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise PipelineValidationError(
            PipelineErrorCode.SINTAXE,
            f"Erro de sintaxe no código Python do solver: {e}"
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_pkg = alias.name.split(".")[0]
                if root_pkg in BLOCKED_MODULES:
                    raise PermissionError(f"Import não permitido no solver: '{alias.name}'")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root_pkg = node.module.split(".")[0]
                if root_pkg in BLOCKED_MODULES:
                    raise PermissionError(f"ImportFrom não permitido no solver: '{node.module}'")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_CALLS:
                raise PermissionError(f"Chamada de função não permitida no solver: '{node.func.id}()'")

    check_free_variables(tree)
    return tree
