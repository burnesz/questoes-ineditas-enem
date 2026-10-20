#!/usr/bin/env python3
"""
Wrapper de compatibilidade para o comando de geração via CLI VERA.
Delega a execução para a CLI unificada em `app.cli`.
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.cli import main

if __name__ == "__main__":
    # Injeta o subcomando 'generate' caso não esteja explícito
    args = sys.argv[1:]
    if not args or args[0] != "generate":
        args = ["generate"] + args
    sys.exit(main(args))
