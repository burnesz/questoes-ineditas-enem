#!/usr/bin/env python3
"""
Ponto de entrada da CLI Unificada — Gerador de Questões Inéditas ENEM.
"""

import sys
import os

# Garante que a raiz do projeto esteja no sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.cli import main

if __name__ == "__main__":
    sys.exit(main())
