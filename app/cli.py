"""
Interface de Linha de Comando (CLI) para o Gerador de Questões Inéditas do ENEM.
Construída com argparse e sem dependências externas adicionais de console.
"""

import argparse
import json
import logging
import os
import sys
import time
import uuid
from typing import Dict, List, Optional

from app.core.config import settings
from app.db.base import Base
from app.db.init_db import init_db
from app.db.models.habilidade import HabilidadeEnem
from app.db.models.questao_enem import QuestaoEnem
from app.db.models.questao_inedita import QuestaoInedita
from app.db.session import engine, SessionLocal
from app.services.llm_client import LLMClient
from app.services.question_service import QuestionService
from app.services.vectorstore import ChromaVectorStore, EmbeddingService
from scripts.seed_chroma import seed_chroma
from scripts.seed_habilidades import seed_habilidades
from scripts.seed_questoes import parse_csv_rows, seed_questoes

logger = logging.getLogger("questoes_ineditas.cli")


def cmd_seed(args: argparse.Namespace) -> int:
    """Executa o povoamento do banco relacional e/ou do banco vetorial ChromaDB."""
    print("=" * 80)
    print(" VERA / ENEM — POVOAMENTO DO AMBIENTE (SEED)")
    print("=" * 80)
    print(f"Alvo selecionado: {args.target}")
    print(f"Arquivo CSV:      {args.csv}")

    if not os.path.exists(args.csv):
        print(f"[ERRO] Arquivo CSV não encontrado: {args.csv}")
        return 1

    db = SessionLocal()
    try:
        if args.target in ("all", "db"):
            print("\n[*] Semeando habilidades e acervo histórico no banco relacional...")
            inserted, updated = seed_questoes(csv_path=args.csv, db=db)
            print(f"[OK] Banco relacional atualizado: {inserted} inseridos, {updated} atualizados.")

        if args.target in ("all", "chroma"):
            print("\n[*] Semeando acervo histórico no banco vetorial ChromaDB...")
            if args.mock_embeddings:
                print("[!] Modo mock de embeddings ativado.")
            total_vec = seed_chroma(
                csv_path=args.csv,
                batch_size=args.batch_size,
                mock_embeddings=args.mock_embeddings
            )
            print(f"[OK] ChromaDB indexado com sucesso: {total_vec} itens processados.")

        print("\n" + "=" * 80)
        print(" SEED CONCLUÍDO COM SUCESSO!")
        print("=" * 80)
        return 0
    except Exception as e:
        print(f"\n[ERRO] Falha durante o seed: {e}")
        return 1
    finally:
        db.close()


def cmd_generate(args: argparse.Namespace) -> int:
    """Gera questões inéditas através da pipeline PoT com validação em 3 etapas."""
    print("=" * 80)
    print(" VERA / ENEM — GERAÇÃO DE QUESTÕES INÉDITAS (PoT + VALIDAÇÃO EM 3 ETAPAS)")
    print("=" * 80)

    llm_client = LLMClient(mock_mode=args.mock)
    if not args.mock:
        print(f"[*] Verificando disponibilidade do LLM no Ollama ({llm_client.endpoint_url})...")
        health = llm_client.health_check()
        if not health.get("healthy"):
            print(f"[ERRO] Servidor Ollama inacessível em {llm_client.endpoint_url}. Inicie o serviço antes de continuar.")
            return 1
        if not health.get("model_available"):
            print(f"[AVISO] O modelo configurado '{llm_client.model_name}' não foi localizado no catálogo do Ollama.")
            print(f"        Modelos disponíveis: {health.get('available_models')}")
        else:
            print(f"[OK] Ollama ativo. Modelo verificado: '{llm_client.model_name}'")
    else:
        print("[!] Modo MOCK ativado — inferência real do LLM desabilitada.")

    if args.habilidades.strip().lower() == "all":
        habilidades_list = [f"H{i:02d}" for i in range(1, 31)]
    else:
        habilidades_list = [h.strip().upper() for h in args.habilidades.split(",") if h.strip()]

    print(f"[*] Total de habilidades a processar: {len(habilidades_list)}")
    print(f"[*] Questões por habilidade: {args.count}")
    print(f"[*] Exemplos few-shot por item: {args.few_shot_k}")
    print(f"[*] Total estimado a gerar: {len(habilidades_list) * args.count}")
    print("-" * 80)

    db = SessionLocal()
    init_db(db)
    emb_service = EmbeddingService(mock_mode=args.mock)
    vector_store = ChromaVectorStore(embedding_service=emb_service)
    question_service = QuestionService(llm_client=llm_client, vector_store=vector_store)

    inicio_geral = time.time()
    sucessos = 0
    falhas = 0

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
                print("\nTodas as metas de questões por habilidade foram concluídas com sucesso!")
                break

            total_itens_rodada = sum(habs_para_processar.values())
            if rodada > 1:
                print("\n" + "=" * 80)
                print(f" RE-TENTATIVAS: INICIANDO RODADA {rodada} PARA HABILIDADES PENDENTES")
                print(f" Habilidades Pendentes: {len(habs_para_processar)} | Questões Restantes: {total_itens_rodada}")
                print("=" * 80)

            for idx, (hab_code, needed_in_round) in enumerate(habs_para_processar.items(), 1):
                print(f"\n>>> [{idx}/{len(habs_para_processar)}] Habilidade: {hab_code} ({needed_in_round} pendente(s))")

                for q_idx in range(1, needed_in_round + 1):
                    t0 = time.time()
                    try:
                        questao = question_service.generate_single_questao_inedita(
                            db=db,
                            habilidade_codigo=hab_code,
                            num_few_shot=args.few_shot_k,
                            max_attempts=args.max_attempts,
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

            pendencias_finais = {hab: qtd for hab, qtd in metas_restantes.items() if qtd > 0}
            if not pendencias_finais:
                break

            total_restante = sum(pendencias_finais.values())
            print("\n" + "=" * 80)
            print(" RELATÓRIO DE PENDÊNCIAS / FALHAS DA RODADA")
            print("=" * 80)
            for hab, qtd_faltando in pendencias_finais.items():
                meta_orig = metas_originais[hab]
                geradas = meta_orig - qtd_faltando
                print(f"  * {hab}: {geradas} de {meta_orig} gerada(s) ({qtd_faltando} pendente(s))")
            print(f"\nTotal restante: {total_restante} questão(ões) em {len(pendencias_finais)} habilidade(s).")
            print("-" * 80)

            if args.non_interactive or not sys.stdin.isatty():
                print("[*] Modo não-interativo ativo. Encerrando sem nova rodada.")
                break

            try:
                pergunta = f"\nDeseja iniciar uma nova rodada para as {len(pendencias_finais)} habilidades pendentes? (s/N): "
                resposta = input(pergunta).strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nExecução interrompida pelo usuário.")
                break

            if resposta in ["s", "sim", "y", "yes"]:
                rodada += 1
                continue
            else:
                break

        total_no_banco = db.query(QuestaoInedita).count()
    finally:
        db.close()

    tempo_total = time.time() - inicio_geral
    print("\n" + "=" * 80)
    print(" RELATÓRIO FINAL DE GERAÇÃO")
    print("=" * 80)
    print(f"Tempo Total: {tempo_total:.1f} segundos ({tempo_total / 60:.1f} minutos)")
    print(f"Habilidades Solicitadas: {len(habilidades_list)}")
    print(f"Questões Geradas com Sucesso: {sucessos}")
    print(f"Falhas Acumuladas: {falhas}")
    print(f"Total Acumulado de Questões Inéditas no Banco: {total_no_banco}")
    print("=" * 80)
    return 0 if falhas == 0 else (0 if sucessos > 0 else 1)


def cmd_list(args: argparse.Namespace) -> int:
    """Lista questões inéditas cadastradas no banco relacional."""
    db = SessionLocal()
    try:
        service = QuestionService()
        questoes = service.list_questoes_ineditas(
            db=db,
            habilidade_codigo=args.habilidade,
            skip=args.skip,
            limit=args.limit
        )

        total_count = db.query(QuestaoInedita)
        if args.habilidade:
            total_count = total_count.filter(QuestaoInedita.habilidade_codigo == args.habilidade.strip().upper())
        total_items = total_count.count()

        print("=" * 115)
        print(f" VERA / ENEM — QUESTÕES INÉDITAS CADASTRADAS (Total no banco: {total_items})")
        if args.habilidade:
            print(f" Filtro: Habilidade {args.habilidade.strip().upper()}")
        print("=" * 115)

        if not questoes:
            print("Nenhuma questão inédita encontrada com os filtros especificados.")
            print("=" * 115)
            return 0

        header = f"{'ID':<36} | {'HAB':<4} | {'GAB':<3} | {'DATA (UTC)':<19} | {'ENUNCIADO RESUMIDO'}"
        print(header)
        print("-" * 115)

        for q in questoes:
            dt_str = q.created_at.strftime("%Y-%m-%d %H:%M:%S") if q.created_at else "N/A"
            enun_clean = " ".join(q.enunciado.split())
            if len(enun_clean) > 45:
                enun_resumo = enun_clean[:42] + "..."
            else:
                enun_resumo = enun_clean

            print(f"{str(q.id):<36} | {q.habilidade_codigo:<4} | {q.gabarito:<3} | {dt_str:<19} | {enun_resumo}")

        print("=" * 115)
        print(f"Exibindo {len(questoes)} item(ns) (skip={args.skip}, limit={args.limit}).")
        return 0
    finally:
        db.close()


def cmd_show(args: argparse.Namespace) -> int:
    """Exibe os detalhes completos de uma questão inédita específica."""
    try:
        qid = uuid.UUID(args.id.strip())
    except ValueError:
        print(f"[ERRO] ID inválido: '{args.id}'. Forneça um UUID válido.")
        return 1

    db = SessionLocal()
    try:
        service = QuestionService()
        q = service.get_questao_inedita_by_id(db=db, questao_id=qid)
        if not q:
            print(f"[ERRO] Questão inédita com ID '{qid}' não encontrada.")
            return 1

        if args.json:
            payload = {
                "id": str(q.id),
                "habilidade_codigo": q.habilidade_codigo,
                "enunciado": q.enunciado,
                "alternativas": q.alternativas,
                "gabarito": q.gabarito,
                "justificativa": q.justificativa,
                "is_validated": q.is_validated,
                "created_at": q.created_at.isoformat() if q.created_at else None
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0

        dt_str = q.created_at.strftime("%Y-%m-%d %H:%M:%S") if q.created_at else "N/A"
        print("=" * 80)
        print(f"QUESTÃO INÉDITA: {q.id}")
        print("=" * 80)
        print(f"Habilidade:        {q.habilidade_codigo}")
        print(f"Data de Criação:   {dt_str}")
        print(f"Validada no PoT:   {'Sim' if q.is_validated else 'Não'}")
        print("-" * 80)
        print("ENUNCIADO:")
        print(q.enunciado)
        print("-" * 80)
        print("ALTERNATIVAS:")
        for letra in ["A", "B", "C", "D", "E"]:
            texto_alt = q.alternativas.get(letra, "")
            marcador = " [GABARITO]" if letra == q.gabarito else ""
            print(f"  ({letra}) {texto_alt}{marcador}")
        print("-" * 80)
        print("JUSTIFICATIVA / CÓDIGO RESOLVER:")
        print(q.justificativa)
        print("=" * 80)
        return 0
    finally:
        db.close()


def cmd_stats(args: argparse.Namespace) -> int:
    """Exibe estatísticas consolidadas do ambiente e dos bancos relacional e vetorial."""
    print("=" * 80)
    print(" VERA / ENEM — ESTATÍSTICAS E STATUS DO SISTEMA")
    print("=" * 80)

    print(f"Projeto:           {settings.PROJECT_NAME} (v{settings.VERSION})")
    print(f"Banco Relacional:  {settings.DATABASE_URL}")
    print(f"ChromaDB Diretório:{settings.CHROMA_PERSIST_DIRECTORY}")
    print(f"LLM Endpoint:      {settings.LLM_ENDPOINT_URL} (Modelo: {settings.LLM_MODEL})")

    llm_client = LLMClient()
    health = llm_client.health_check()
    if health.get("healthy"):
        print(f"Status Ollama:     ONLINE (Modelo no catálogo: {'Sim' if health.get('model_available') else 'Não'})")
    else:
        print("Status Ollama:     OFFLINE (Não conectado)")

    db = SessionLocal()
    try:
        init_db(db)
        total_hab = db.query(HabilidadeEnem).count()
        total_enem = db.query(QuestaoEnem).count()
        total_ineditas = db.query(QuestaoInedita).count()

        print("-" * 80)
        print("ACERVO NO BANCO RELACIONAL:")
        print(f"  • Habilidades cadastradas:      {total_hab} / 30")
        print(f"  • Questões históricas do ENEM:  {total_enem}")
        print(f"  • Questões inéditas geradas:    {total_ineditas}")

        if total_ineditas > 0:
            print("\n  Distribuição de Questões Inéditas por Habilidade:")
            from sqlalchemy import func
            counts = (
                db.query(QuestaoInedita.habilidade_codigo, func.count(QuestaoInedita.id))
                .group_by(QuestaoInedita.habilidade_codigo)
                .order_by(QuestaoInedita.habilidade_codigo)
                .all()
            )
            for hab_code, count in counts:
                print(f"    - {hab_code}: {count} questão(ões)")

        print("-" * 80)
        try:
            emb_service = EmbeddingService(mock_mode=True)
            vstore = ChromaVectorStore(embedding_service=emb_service)
            collection = vstore.get_or_create_collection()
            chroma_count = collection.count()
            print(f"BANCO VETORIAL (ChromaDB): {chroma_count} documentos na coleção '{settings.CHROMA_COLLECTION_QUESTOES}'.")
        except Exception as e:
            print(f"BANCO VETORIAL (ChromaDB): Não foi possível consultar ({e}).")

        print("=" * 80)
        return 0
    finally:
        db.close()


def cmd_export(args: argparse.Namespace) -> int:
    """Exporta questões inéditas do banco para arquivo JSON ou Markdown."""
    output_path = args.output.strip()
    fmt = args.format
    if not fmt:
        if output_path.lower().endswith(".md") or output_path.lower().endswith(".markdown"):
            fmt = "markdown"
        else:
            fmt = "json"

    db = SessionLocal()
    try:
        query = db.query(QuestaoInedita)
        if args.habilidade:
            query = query.filter(QuestaoInedita.habilidade_codigo == args.habilidade.strip().upper())
        questoes = query.order_by(QuestaoInedita.created_at.asc()).all()

        if not questoes:
            print("[AVISO] Nenhuma questão inédita encontrada para exportar.")
            return 0

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        if fmt == "json":
            data = []
            for q in questoes:
                data.append({
                    "id": str(q.id),
                    "habilidade_codigo": q.habilidade_codigo,
                    "enunciado": q.enunciado,
                    "alternativas": q.alternativas,
                    "gabarito": q.gabarito,
                    "justificativa": q.justificativa,
                    "is_validated": q.is_validated,
                    "created_at": q.created_at.isoformat() if q.created_at else None
                })
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        else:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write("# Caderno de Questões Inéditas de Matemática — ENEM\n\n")
                for idx, q in enumerate(questoes, 1):
                    f.write(f"## Questão {idx:02d} — Habilidade {q.habilidade_codigo}\n\n")
                    f.write(f"**ID:** `{q.id}`  \n\n")
                    f.write(f"{q.enunciado}\n\n")
                    for letra in ["A", "B", "C", "D", "E"]:
                        alt_text = q.alternativas.get(letra, "")
                        f.write(f"- **({letra})** {alt_text}\n")
                    f.write("\n<details>\n<summary><b>Gabarito e Resolução</b></summary>\n\n")
                    f.write(f"**Gabarito Oficial:** **{q.gabarito}**\n\n")
                    f.write(f"```python\n{q.justificativa}\n```\n")
                    f.write("\n</details>\n\n---\n\n")

        print(f"[OK] {len(questoes)} questão(ões) exportada(s) com sucesso para '{output_path}' ({fmt.upper()}).")
        return 0
    except Exception as e:
        print(f"[ERRO] Falha ao exportar questões: {e}")
        return 1
    finally:
        db.close()


def create_parser() -> argparse.ArgumentParser:
    """Cria e configura o parser de argumentos para a CLI."""
    parser = argparse.ArgumentParser(
        prog="enem",
        description="CLI VERA — Sistema Autônomo de Geração e Gestão de Questões Inéditas do ENEM (PoT + ChromaDB).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos de uso:
  # Povoar banco relacional e ChromaDB com dados históricos:
  python cli.py seed

  # Gerar 1 questão inédita para a habilidade H01 (modo simulação/mock):
  python cli.py generate --habilidades H01 --mock

  # Gerar questões para múltiplas habilidades com LLM local:
  python cli.py generate --habilidades H01,H02,H03 --count 2

  # Listar questões geradas:
  python cli.py list --habilidade H01

  # Exibir detalhes de uma questão pelo ID:
  python cli.py show 123e4567-e89b-12d3-a456-426614174000

  # Visualizar estatísticas do acervo e status dos serviços:
  python cli.py stats

  # Exportar questões para Markdown ou JSON:
  python cli.py export -o caderno_questoes.md
"""
    )

    subparsers = parser.add_subparsers(dest="subcommand", title="Subcomandos Disponíveis")

    p_seed = subparsers.add_parser("seed", help="Povoa habilidades, acervo histórico no banco relacional e ChromaDB.")
    p_seed.add_argument("-t", "--target", choices=["all", "db", "chroma"], default="all",
                        help="Alvo do povoamento: 'all' (ambos), 'db' (relacional) ou 'chroma' (vetorial). Padrão: all.")
    p_seed.add_argument("--csv", default="data/itens_prova_2009_2024_enriquecido.csv",
                        help="Caminho do CSV com o acervo histórico do ENEM.")
    p_seed.add_argument("--batch-size", type=int, default=50,
                        help="Tamanho do lote para indexação no ChromaDB. Padrão: 50.")
    p_seed.add_argument("--mock-embeddings", action="store_true",
                        help="Usa gerador mock de embeddings sem carregar modelo neural pesado.")
    p_seed.set_defaults(func=cmd_seed)

    p_gen = subparsers.add_parser("generate", help="Gera questões inéditas através de Program-Aided Generation (PoT).")
    p_gen.add_argument("--habilidades", type=str, default="all",
                       help="Códigos das habilidades separados por vírgula (ex: 'H01,H02') ou 'all'. Padrão: all.")
    p_gen.add_argument("--count", type=int, default=1,
                       help="Quantidade de questões por habilidade a gerar. Padrão: 1.")
    p_gen.add_argument("--few-shot-k", type=int, default=2,
                       help="Exemplos históricos recuperados via RAG para o prompt. Padrão: 2.")
    p_gen.add_argument("--mock", action="store_true",
                       help="Executa em modo mock simulado para testes rápidos.")
    p_gen.add_argument("--skip-existing", action="store_true",
                       help="Pula habilidades que já possuam a quantidade solicitada no banco.")
    p_gen.add_argument("--tema", type=str, default=None,
                       help="Tema contextual fixo (se omitido, sorteia aleatoriamente).")
    p_gen.add_argument("--abertura", type=str, default=None,
                       help="Estilo de abertura narrativa fixo (se omitido, sorteia aleatoriamente).")
    p_gen.add_argument("--max-attempts", type=int, default=5,
                       help="Tentativas máximas por questão na pipeline PoT. Padrão: 5.")
    p_gen.add_argument("--non-interactive", action="store_true",
                       help="Não solicita confirmação interativa para retentativas de falhas.")
    p_gen.set_defaults(func=cmd_generate)

    p_list = subparsers.add_parser("list", help="Lista questões inéditas persistidas no banco relacional.")
    p_list.add_argument("--habilidade", type=str, default=None,
                        help="Filtra listagem por código de habilidade (ex: 'H01').")
    p_list.add_argument("--limit", type=int, default=20,
                        help="Número máximo de itens retornados. Padrão: 20.")
    p_list.add_argument("--skip", type=int, default=0,
                        help="Número de itens a pular para paginação. Padrão: 0.")
    p_list.set_defaults(func=cmd_list)

    p_show = subparsers.add_parser("show", help="Exibe os dados detalhados de uma questão inédita por ID.")
    p_show.add_argument("id", type=str, help="UUID identificador da questão inédita.")
    p_show.add_argument("--json", action="store_true", help="Exibe os dados em formato JSON estrito.")
    p_show.set_defaults(func=cmd_show)

    p_stats = subparsers.add_parser("stats", help="Exibe status das conexões e estatísticas do acervo.")
    p_stats.set_defaults(func=cmd_stats)

    p_export = subparsers.add_parser("export", help="Exporta questões inéditas para JSON ou Markdown.")
    p_export.add_argument("-o", "--output", type=str, required=True,
                          help="Caminho do arquivo de saída (ex: questoes.json ou caderno.md).")
    p_export.add_argument("--habilidade", type=str, default=None,
                          help="Filtra questões por código de habilidade (ex: 'H01').")
    p_export.add_argument("--format", choices=["json", "markdown"], default=None,
                          help="Formato de exportação: 'json' ou 'markdown' (auto-detectado se omitido).")
    p_export.set_defaults(func=cmd_export)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """Ponto de entrada de execução da CLI."""
    parser = create_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)

    if not hasattr(args, "func"):
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
