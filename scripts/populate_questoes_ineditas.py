#!/usr/bin/env python3
"""
Script CLI para Povoamento da Tabela questoes_ineditas no PostgreSQL.
Executa o pipeline RAG/few-shot determinístico utilizando o LLM local (Ollama Qwen 2.5),
conforme Seção 8 do pré-projeto VERA / AGENTS.md.

Uso:
    # Gerar 1 questão para cada uma das 30 habilidades oficiais (H01 a H30):
    python scripts/populate_questoes_ineditas.py --habilidades all

    # Gerar para habilidades específicas:
    python scripts/populate_questoes_ineditas.py --habilidades H01,H02,H03

    # Modo simulação/mock para testes instantâneos:
    python scripts/populate_questoes_ineditas.py --habilidades H01 --mock
"""

import sys
import os
import time
import argparse
import logging
from typing import Dict, List

# Adiciona o diretório raiz ao PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db.session import SessionLocal
from app.db.init_db import init_db
from app.db.models.questao_inedita import QuestaoInedita
from app.services.llm_client import LLMClient
from app.services.vectorstore import ChromaVectorStore, EmbeddingService
from app.services.question_service import QuestionService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("vera.populate")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Povoamento da tabela questoes_ineditas usando pipeline RAG no Pinecone e LLM local via Ollama."
    )
    parser.add_argument(
        "--habilidades",
        type=str,
        default="all",
        help="Códigos das habilidades separados por vírgula (ex: 'H01,H02,H03') ou 'all' para todas as 30."
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="Quantidade de questões inéditas a gerar por habilidade (padrão: 1)."
    )
    parser.add_argument(
        "--few-shot-k",
        type=int,
        default=2,
        help="Quantidade de exemplos históricos recuperados via RAG (Pinecone) para o prompt (padrão: 2)."
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Executa em modo mock (respostas simuladas pré-formatadas) para testes rápidos."
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Pula habilidades que já possuam a quantidade solicitada de questões no banco."
    )
    parser.add_argument(
        "--tema",
        type=str,
        default=None,
        help="Fixa um tema contextual específico (se omitido, sorteia aleatoriamente a cada questão)."
    )
    parser.add_argument(
        "--abertura",
        type=str,
        default=None,
        help="Fixa um estilo de abertura narrativa específico (se omitido, sorteia aleatoriamente a cada questão)."
    )
    return parser.parse_args()


def main():
    args = parse_args()
    print("=" * 80)
    print(" VERA — PIPELINE DE GERAÇÃO E POVOAMENTO DE QUESTÕES INÉDITAS (ENEM)")
    print("=" * 80)

    # 1. Configuração do cliente LLM
    llm_client = LLMClient(mock_mode=args.mock)
    if not args.mock:
        print(f"[*] Verificando disponibilidade do LLM no Ollama ({llm_client.endpoint_url})...")
        health = llm_client.health_check()
        if not health.get("healthy"):
            print(f"[!] ERRO: Servidor Ollama inacessível em {llm_client.endpoint_url}. Inicie o serviço antes de continuar.")
            sys.exit(1)
        if not health.get("model_available"):
            print(f"[!] AVISO: O modelo configurado '{llm_client.model_name}' não foi localizado no catálogo do Ollama.")
            print(f"    Modelos disponíveis: {health.get('available_models')}")
        else:
            print(f"[OK] Ollama ativo. Modelo verificado: '{llm_client.model_name}'")
    else:
        print("[!] Modo MOCK ativado — inferência real do LLM desabilitada.")

    # 2. Resolução das habilidades-alvo
    if args.habilidades.strip().lower() == "all":
        habilidades_list = [f"H{i:02d}" for i in range(1, 31)]
    else:
        habilidades_list = [h.strip().upper() for h in args.habilidades.split(",") if h.strip()]

    print(f"[*] Total de habilidades a processar: {len(habilidades_list)}")
    print(f"[*] Questões por habilidade: {args.count}")
    print("[*] Modo de Arquitetura: Program-Aided Generation (PoT: Python Solver + Justificativa)")
    print(f"[*] Exemplos few-shot por item: {args.few_shot_k}")
    print(f"[*] Total estimado de questões inéditas a gerar: {len(habilidades_list) * args.count}")
    print("-" * 80)

    db = SessionLocal()
    init_db(db)
    emb_service = EmbeddingService(mock_mode=args.mock)
    vector_store = ChromaVectorStore(embedding_service=emb_service)
    question_service = QuestionService(llm_client=llm_client, vector_store=vector_store)

    inicio_geral = time.time()
    sucessos = 0
    falhas = 0

    # Inicializa o mapa de metas por habilidade (quantas questões ainda faltam gerar)
    metas_originais: Dict[str, int] = {}
    metas_restantes: Dict[str, int] = {}

    for hab_code in habilidades_list:
        needed = args.count
        if args.skip_existing:
            existing_count = db.query(QuestaoInedita).filter(QuestaoInedita.habilidade_codigo == hab_code).count()
            needed = max(0, args.count - existing_count)
        metas_originais[hab_code] = needed
        metas_restantes[hab_code] = needed

    rodada = 1

    try:
        while True:
            habs_para_processar = {hab: qtd for hab, qtd in metas_restantes.items() if qtd > 0}
            if not habs_para_processar:
                print("\n🎉 Todas as metas de questões por habilidade foram concluídas com sucesso!")
                break

            total_itens_rodada = sum(habs_para_processar.values())
            if rodada > 1:
                print("\n" + "=" * 80)
                print(f" 🔄 INICIANDO RODADA {rodada} DE RE-TENTATIVAS PARA HABILIDADES PENDENTES")
                print(f" Habilidades Pendentes: {len(habs_para_processar)} | Questões Restantes: {total_itens_rodada}")
                print("=" * 80)

            for idx, (hab_code, needed_in_round) in enumerate(habs_para_processar.items(), 1):
                print(f"\n>>> [{idx}/{len(habs_para_processar)}] Processando Habilidade: {hab_code} ({needed_in_round} pendente(s))")

                for q_idx in range(1, needed_in_round + 1):
                    t0 = time.time()
                    try:
                        questao = question_service.generate_single_questao_inedita(
                            db=db,
                            habilidade_codigo=hab_code,
                            num_few_shot=args.few_shot_k,
                            max_attempts=5,
                            tema=args.tema,
                            abertura=args.abertura
                        )
                        tempo_gasto = time.time() - t0
                        sucessos += 1
                        metas_restantes[hab_code] -= 1
                        enunciado_resumo = (questao.enunciado[:90] + "...") if len(questao.enunciado) > 90 else questao.enunciado
                        print(f"    [SUCESSO] Questão {q_idx}/{needed_in_round} gerada e validada em {tempo_gasto:.1f}s!")
                        print(f"    - ID: {questao.id}")
                        print(f"    - Gabarito: {questao.gabarito}")
                        print(f"    - Enunciado: {enunciado_resumo}")
                    except Exception as e:
                        tempo_gasto = time.time() - t0
                        falhas += 1
                        print(f"    [FALHA] Não foi possível gerar para {hab_code} após {tempo_gasto:.1f}s: {e}")

            # Verifica pendências remanescentes após a rodada
            pendencias_finais = {hab: qtd for hab, qtd in metas_restantes.items() if qtd > 0}
            if not pendencias_finais:
                print("\nTodas as questões solicitadas foram concluídas com sucesso!")
                break

            total_restante = sum(pendencias_finais.values())
            print("\n" + "=" * 80)
            print(" ⚠️  RELATÓRIO DE PENDÊNCIAS / FALHAS DA RODADA")
            print("=" * 80)
            print("As seguintes habilidades não concluíram todas as questões solicitadas:")
            for hab, qtd_faltando in pendencias_finais.items():
                meta_orig = metas_originais[hab]
                geradas = meta_orig - qtd_faltando
                print(f"  • {hab}: {geradas} de {meta_orig} gerada(s) ({qtd_faltando} pendente(s))")
            print(f"\nTotal restante: {total_restante} questão(ões) em {len(pendencias_finais)} habilidade(s).")
            print("-" * 80)

            # Verifica se o terminal é interativo para aguardar resposta do usuário
            if not sys.stdin.isatty():
                print("[*] Terminal não-interativo detectado. Finalizando sem repetições.")
                break

            try:
                pergunta = f"\nDeseja iniciar um novo fluxo somente com essas {len(pendencias_finais)} habilidades pendentes? (s/N): "
                resposta = input(pergunta).strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n\nExecução interrompida pelo usuário.")
                break

            if resposta in ["s", "sim", "y", "yes"]:
                rodada += 1
                continue
            else:
                print("\nFluxo de re-tentativas recusado. Finalizando processo...")
                break

        # Contagem total consolidada no banco de dados
        total_no_banco = db.query(QuestaoInedita).count()

    finally:
        db.close()

    tempo_total = time.time() - inicio_geral
    print("\n" + "=" * 80)
    print(" RELATÓRIO FINAL DE POVOAMENTO")
    print("=" * 80)
    print(f"Tempo Total de Execução: {tempo_total:.1f} segundos ({tempo_total / 60:.1f} minutos)")
    print(f"Habilidades Processadas: {len(habilidades_list)}")
    print(f"Questões Geradas com Sucesso: {sucessos}")
    print(f"Falhas: {falhas}")
    print(f"Total Acumulado de Questões Inéditas no Banco: {total_no_banco}")
    print("=" * 80)


if __name__ == "__main__":
    main()
