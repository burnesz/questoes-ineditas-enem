"""
Experimento 2 — seleção do modelo gerador.

Cada gerador produz questões com UMA tentativa por pedido (sem retry), passando pelas Etapas 1 a 3.
As que passam da Etapa 3 ficam gravadas como pendentes; depois, o avaliador escolhido no Experimento 1
faz a Etapa 4 (perfil 'gerada') de todas elas. Separar as fases evita trocar de modelo a cada
tentativa, o que é o que mais custa numa GPU pequena.

Tudo fica no SQLite do projeto (ciclos_geracao, tentativas_geracao, questoes_ineditas). Os manifestos
em data/experimento2/ dizem quais registros são deste experimento e guardam os tempos de cada fase:
    geracoes.jsonl     uma linha por pedido de geração
    avaliacoes.jsonl   uma linha por avaliação

Os comandos são retomáveis: o que já está no manifesto é pulado. Com --prazo, nenhum pedido novo começa
depois do horário indicado, então dá para rodar em noites de 8 h.

Uso:
    python scripts/experimento2/experimento2.py gerar --modelo qwen2.5:7b-instruct-q4_K_M --prazo "2026-11-16 07:00"
    python scripts/experimento2/experimento2.py gerar --modelo qwen3:8b-q4_K_M --think false
    python scripts/experimento2/experimento2.py gerar --modelo llama3.1:8b-instruct-q4_K_M
    python scripts/experimento2/experimento2.py avaliar --avaliador qwen3:8b-q4_K_M --think false
    python scripts/experimento2/experimento2.py resumo
"""
import os
import sys
import json
import time
import uuid
import random
import argparse
import datetime
import statistics
from collections import Counter, defaultdict
from typing import Dict, List, Optional

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts", "experimento1"))
os.chdir(ROOT)  # o QuestionService resolve data/habilidades_queries.json a partir da raiz

from app.core.config import settings  # noqa: E402
from app.db.init_db import init_db  # noqa: E402
from app.db.models.questao_inedita import QuestaoInedita  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.schemas.question import HABILIDADES_DESABILITADAS  # noqa: E402
from app.services.llm_client import LLMClient, LLMConnectionError, LLMTimeoutError  # noqa: E402
from app.services.question_service import ETAPA_PENDENTE_AVALIACAO, QuestionService  # noqa: E402
from app.services.vectorstore import ChromaVectorStore, EmbeddingService  # noqa: E402
from avaliar_base import digest_modelo, parse_bool, versao_ollama  # noqa: E402

DIR_EXP = os.path.join(ROOT, "data", "experimento2")
MANIFESTO_GERACOES = os.path.join(DIR_EXP, "geracoes.jsonl")
MANIFESTO_AVALIACOES = os.path.join(DIR_EXP, "avaliacoes.jsonl")
DIR_RESULTADOS = os.path.join(DIR_EXP, "resultados")
HABILIDADES_ATIVAS = [f"H{i:02d}" for i in range(1, 31) if f"H{i:02d}" not in HABILIDADES_DESABILITADAS]
MAX_QUEDAS_SEGUIDAS = 3
ESPERA_APOS_QUEDA_S = 30


def ler_jsonl(caminho: str) -> List[dict]:
    if not os.path.exists(caminho):
        return []
    with open(caminho, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def gravar_jsonl(caminho: str, registro: dict) -> None:
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")


def ler_prazo(valor: Optional[str]) -> Optional[float]:
    return datetime.datetime.strptime(valor, "%Y-%m-%d %H:%M").timestamp() if valor else None


def agora() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def eta(tempos: List[float], restantes: int) -> str:
    media = sum(tempos) / len(tempos)
    return f"média {media:.0f}s → faltam ~{media * restantes / 3600:.1f} h"


def ids_questoes(db, habilidade: str) -> set:
    return {i for (i,) in db.query(QuestaoInedita.id).filter(QuestaoInedita.habilidade_codigo == habilidade).all()}


def novo_servico(modelo: str, think: Optional[bool]) -> QuestionService:
    return QuestionService(
        llm_client=LLMClient(model_name=modelo, think=think),
        vector_store=ChromaVectorStore(embedding_service=EmbeddingService()),
    )


def cmd_gerar(args: argparse.Namespace) -> None:
    habilidades = list(HABILIDADES_ATIVAS) if args.habilidades == "all" else [h.strip().upper() for h in args.habilidades.split(",")]
    random.Random(args.semente_ordem).shuffle(habilidades)  # mesma ordem para todos os geradores
    prazo = ler_prazo(args.prazo)
    digest, ollama = digest_modelo(args.modelo), versao_ollama()

    feitos: Dict[str, int] = Counter(
        r["habilidade"] for r in ler_jsonl(MANIFESTO_GERACOES)
        if r["modelo_gerador"] == args.modelo and r["think"] == args.think and r["status"] != "interrompido"
    )
    # Rodízio: rodada n = 1 pedido de cada habilidade; um corte pelo prazo deixa as habilidades equilibradas
    fila = [(n, h) for n in range(1, args.por_habilidade + 1) for h in habilidades if feitos[h] < n]
    print(f"GERAR {args.modelo} ({digest}) think={args.think} | Ollama {ollama} em {settings.LLM_ENDPOINT_URL} | "
          f"meta {args.por_habilidade}/habilidade | já feitos {sum(feitos.values())} | nesta execução {len(fila)}", flush=True)
    if not fila:
        return

    servico = novo_servico(args.modelo, args.think)
    db = SessionLocal()
    init_db(db)
    quedas, tempos, idx = 0, [], 0
    try:
        while idx < len(fila):
            if prazo and time.time() >= prazo:
                print(f"Prazo atingido: {len(fila) - idx} pedido(s) ficam para a próxima execução.", flush=True)
                break
            rodada, hab = fila[idx]
            antes = ids_questoes(db, hab)
            t0 = time.time()
            registro = {"modelo_gerador": args.modelo, "modelo_digest": digest, "think": args.think,
                        "ollama_versao": ollama, "hardware": args.hardware, "habilidade": hab, "rodada": rodada,
                        "inicio": agora()}
            try:
                questao = servico.generate_single_questao_inedita(
                    db=db, habilidade_codigo=hab, num_few_shot=args.few_shot_k, max_attempts=1, ate_etapa3=True
                )
                registro.update(status="passou_etapa3", questao_id=str(questao.id), ciclo_id=str(questao.ciclo_id))
            except (LLMConnectionError, LLMTimeoutError) as e:
                db.rollback()
                registro.update(status="interrompido", erro=f"{type(e).__name__}: {e}"[:300])
            except Exception as e:
                db.rollback()
                # a tentativa reprovada nas Etapas 2 ou 3 já foi gravada no banco por este pedido
                novas = ids_questoes(db, hab) - antes
                q = db.get(QuestaoInedita, next(iter(novas))) if len(novas) == 1 else None
                registro.update(status="reprovada_etapa2_3", questao_id=str(q.id) if q else None,
                                ciclo_id=str(q.ciclo_id) if q else None, etapa_falha=q.etapa_falha if q else None,
                                erro=f"{type(e).__name__}: {e}"[:300])
            registro["tempo_geracao_s"] = round(time.time() - t0, 1)
            gravar_jsonl(MANIFESTO_GERACOES, registro)

            if registro["status"] == "interrompido":
                quedas += 1
                print(f"[{idx + 1}/{len(fila)}] {hab} INTERROMPIDO ({registro['erro'][:100]})", flush=True)
                if quedas >= MAX_QUEDAS_SEGUIDAS:
                    sys.exit(f"{quedas} quedas seguidas de conexão com o Ollama: parando para retomar depois.")
                time.sleep(ESPERA_APOS_QUEDA_S)
                continue  # refaz o mesmo pedido
            quedas = 0
            tempos.append(registro["tempo_geracao_s"])
            idx += 1
            situacao = "passou na Etapa 3" if registro["status"] == "passou_etapa3" else registro.get("etapa_falha")
            print(f"[{idx}/{len(fila)}] {hab} rodada {rodada}: {situacao} ({registro['tempo_geracao_s']}s) | "
                  f"{eta(tempos, len(fila) - idx)}", flush=True)
    finally:
        db.close()


def cmd_avaliar(args: argparse.Namespace) -> None:
    prazo = ler_prazo(args.prazo)
    digest, ollama = digest_modelo(args.avaliador), versao_ollama()
    avaliadas = {r["questao_id"] for r in ler_jsonl(MANIFESTO_AVALIACOES) if r["status"] != "interrompido"}
    geracoes = {r["questao_id"]: r for r in ler_jsonl(MANIFESTO_GERACOES) if r["status"] == "passou_etapa3"}
    pendentes = [qid for qid in geracoes if qid not in avaliadas]
    print(f"AVALIAR com {args.avaliador} ({digest}) think={args.think} | Ollama {ollama} | "
          f"já avaliadas {len(avaliadas)} | pendentes {len(pendentes)}", flush=True)
    if not pendentes:
        return

    servico = novo_servico(args.avaliador, args.think)
    db = SessionLocal()
    init_db(db)
    quedas, tempos, idx = 0, [], 0
    try:
        while idx < len(pendentes):
            if prazo and time.time() >= prazo:
                print(f"Prazo atingido: {len(pendentes) - idx} avaliação(ões) ficam para a próxima execução.", flush=True)
                break
            qid = pendentes[idx]
            questao = db.get(QuestaoInedita, uuid.UUID(qid))
            t0 = time.time()
            registro = {"questao_id": qid, "modelo_gerador": geracoes[qid]["modelo_gerador"],
                        "habilidade": geracoes[qid]["habilidade"], "avaliador": args.avaliador,
                        "avaliador_digest": digest, "think": args.think, "ollama_versao": ollama,
                        "hardware": args.hardware, "inicio": agora()}
            try:
                if questao is None or questao.etapa_falha != ETAPA_PENDENTE_AVALIACAO:
                    raise ValueError("questão ausente do banco ou já avaliada")
                resultado = servico.avaliar_questao_pendente(db, questao)
                registro.update(status="aprovada" if resultado.aprovada else "reprovada",
                                etapa_falha=resultado.etapa_falha, codigo_erro=questao.codigo_erro)
            except (LLMConnectionError, LLMTimeoutError) as e:
                db.rollback()
                registro.update(status="interrompido", erro=f"{type(e).__name__}: {e}"[:300])
            except Exception as e:
                db.rollback()
                registro.update(status="erro", erro=f"{type(e).__name__}: {e}"[:300])
            registro["tempo_avaliacao_s"] = round(time.time() - t0, 1)
            gravar_jsonl(MANIFESTO_AVALIACOES, registro)

            if registro["status"] == "interrompido":
                quedas += 1
                print(f"[{idx + 1}/{len(pendentes)}] INTERROMPIDO ({registro['erro'][:100]})", flush=True)
                if quedas >= MAX_QUEDAS_SEGUIDAS:
                    sys.exit(f"{quedas} quedas seguidas de conexão com o Ollama: parando para retomar depois.")
                time.sleep(ESPERA_APOS_QUEDA_S)
                continue
            quedas = 0
            tempos.append(registro["tempo_avaliacao_s"])
            idx += 1
            print(f"[{idx}/{len(pendentes)}] {registro['habilidade']} ({registro['modelo_gerador']}): "
                  f"{registro['status']} {registro.get('etapa_falha') or ''} ({registro['tempo_avaliacao_s']}s) | "
                  f"{eta(tempos, len(pendentes) - idx)}", flush=True)
    finally:
        db.close()


def cmd_resumo(args: argparse.Namespace) -> None:
    from scipy.stats import chi2_contingency

    geracoes = [r for r in ler_jsonl(MANIFESTO_GERACOES) if r["status"] != "interrompido"]
    avaliacoes = {r["questao_id"]: r for r in ler_jsonl(MANIFESTO_AVALIACOES) if r["status"] in ("aprovada", "reprovada")}
    por_modelo: Dict[str, List[dict]] = defaultdict(list)
    for g in geracoes:
        por_modelo[g["modelo_gerador"]].append(g)

    linhas, contagem_erros, tabela_chi = [], {}, []
    for modelo, gs in sorted(por_modelo.items()):
        passou = [g for g in gs if g["status"] == "passou_etapa3"]
        avaliadas = [avaliacoes[g["questao_id"]] for g in passou if g["questao_id"] in avaliacoes]
        aprovadas = [a for a in avaliadas if a["status"] == "aprovada"]
        n_validos = (len(gs) - len(passou)) + len(avaliadas)  # pedidos com veredito final
        taxa = len(aprovadas) / n_validos if n_validos else 0.0
        # Tempo por questão aprovada: todo o tempo gasto (geração de todos os pedidos + avaliações) ÷ aprovadas
        tempo_total = sum(g["tempo_geracao_s"] for g in gs) + sum(a["tempo_avaliacao_s"] for a in avaliadas)
        erros = Counter(g.get("etapa_falha") or "?" for g in gs if g["status"] == "reprovada_etapa2_3")
        erros.update(a.get("etapa_falha") or "?" for a in avaliadas if a["status"] == "reprovada")
        contagem_erros[modelo] = erros
        tabela_chi.append([len(aprovadas), n_validos - len(aprovadas)])
        linhas.append({
            "modelo": modelo, "pedidos": len(gs), "passaram_etapa3": len(passou), "avaliadas": len(avaliadas),
            "pendentes": len(passou) - len(avaliadas), "aprovadas": len(aprovadas), "taxa": taxa,
            "tentativas_por_aprovada": (1 / taxa) if taxa else None,
            "tempo_por_aprovada_s": (tempo_total / len(aprovadas)) if aprovadas else None,
            "tempo_medio_geracao_s": statistics.mean(g["tempo_geracao_s"] for g in gs),
        })

    md = ["# Experimento 2: resultados dos modelos geradores", "",
          "Uma tentativa por pedido. Etapas 1 a 3 com o gerador; Etapa 4 com o avaliador escolhido no Experimento 1.", "",
          "| Gerador | Pedidos | Passaram na Etapa 3 | Aprovadas | % aprovadas | Tentativas por aprovada | "
          "Tempo por aprovada | Pendentes de avaliação |",
          "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for l in linhas:
        tent = f"{l['tentativas_por_aprovada']:.1f}".replace(".", ",") if l["tentativas_por_aprovada"] else "-"
        tempo = f"{l['tempo_por_aprovada_s'] / 60:.1f} min".replace(".", ",") if l["tempo_por_aprovada_s"] else "-"
        taxa = f"{100 * l['taxa']:.1f}%".replace(".", ",")
        md.append(f"| {l['modelo']} | {l['pedidos']} | {l['passaram_etapa3']} | {l['aprovadas']} | "
                  f"{taxa} | {tent} | {tempo} | {l['pendentes']} |")

    etapas = sorted({e for c in contagem_erros.values() for e in c})
    md += ["", "## Onde as tentativas foram reprovadas", "",
           "| Etapa | " + " | ".join(l["modelo"] for l in linhas) + " |",
           "| :--- | " + " | ".join("---:" for _ in linhas) + " |"]
    for e in etapas:
        md.append(f"| {e} | " + " | ".join(str(contagem_erros[l['modelo']].get(e, 0)) for l in linhas) + " |")

    if len(tabela_chi) >= 2 and all(sum(r) for r in tabela_chi) and any(r[0] for r in tabela_chi):
        chi2, p, _, _ = chi2_contingency(tabela_chi)
        p_txt = "< 0,001" if p < 0.001 else f"{p:.3f}".replace(".", ",")
        md += ["", "## Comparação estatística", "",
               f"Teste qui-quadrado da taxa de aprovação entre os geradores: χ² = {chi2:.2f}, p = {p_txt}. "
               "p < 0,05 indica que a taxa de aprovação difere entre os geradores."]
    md += ["", "## Como ler", "",
           "- **% aprovadas**: aprovadas ÷ pedidos com veredito final (os pendentes de avaliação ficam de fora).",
           "- **Tentativas por aprovada**: 1 ÷ taxa de aprovação; é o número médio de tentativas para obter uma questão aprovada.",
           "- **Tempo por aprovada**: todo o tempo de geração e avaliação gasto pelo gerador ÷ número de aprovadas.", ""]

    os.makedirs(DIR_RESULTADOS, exist_ok=True)
    with open(os.path.join(DIR_RESULTADOS, "tabela_experimento2.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print("\n".join(md))


def main() -> None:
    parser = argparse.ArgumentParser(description="Experimento 2: seleção do modelo gerador.")
    sub = parser.add_subparsers(dest="comando", required=True)

    p_ger = sub.add_parser("gerar", help="Gera questões (Etapas 1 a 3, uma tentativa por pedido).")
    p_ger.add_argument("--modelo", required=True, help="Tag do gerador no Ollama.")
    p_ger.add_argument("--think", type=parse_bool, default=None, help="true/false liga/desliga o raciocínio; 'padrao' não envia.")
    p_ger.add_argument("--por-habilidade", type=int, default=5, help="Total de pedidos por habilidade (acumulado).")
    p_ger.add_argument("--habilidades", default="all", help="'all' (28 ativas) ou lista separada por vírgula (para testes).")
    p_ger.add_argument("--few-shot-k", type=int, default=2)
    p_ger.add_argument("--semente-ordem", type=int, default=2026, help="Semente da ordem das habilidades no rodízio.")
    p_ger.add_argument("--hardware", default="", help="Descrição do hardware, gravada no manifesto.")
    p_ger.add_argument("--prazo", default=None, help="'AAAA-MM-DD HH:MM': não inicia pedidos depois disso.")
    p_ger.set_defaults(func=cmd_gerar)

    p_av = sub.add_parser("avaliar", help="Faz a Etapa 4 das questões pendentes com o avaliador.")
    p_av.add_argument("--avaliador", required=True, help="Tag do avaliador no Ollama.")
    p_av.add_argument("--think", type=parse_bool, default=None)
    p_av.add_argument("--hardware", default="")
    p_av.add_argument("--prazo", default=None)
    p_av.set_defaults(func=cmd_avaliar)

    p_res = sub.add_parser("resumo", help="Monta a tabela de resultados.")
    p_res.set_defaults(func=cmd_resumo)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
