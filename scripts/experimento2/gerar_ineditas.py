"""
Experimento 2 — geração de questões inéditas com vários modelos, para comparação posterior.

Roda a pipeline completa (Etapas 1 a 5, perfil 'gerada') com o modelo indicado e persiste tudo no
SQLite do projeto (ciclos_geracao, tentativas_geracao, questoes_ineditas), como a CLI faz. Além disso,
grava um manifesto por modelo em data/experimento2/ciclos/, com uma linha por ciclo: é por ele que a
análise separa os ciclos deste experimento das gerações comuns e sabe com qual 'think' cada um rodou
(a tabela tentativas_geracao só guarda o nome do modelo).

Desenho:
- A unidade é o CICLO (até --max-attempts tentativas), não a questão aprovada: cada modelo recebe o
  mesmo número de ciclos por habilidade, e a taxa de sucesso por ciclo é comparável entre modelos.
- As habilidades são percorridas em rodízio (uma rodada = 1 ciclo de cada habilidade ativa), numa
  ordem embaralhada com semente fixa (--semente-ordem), igual para todos os modelos: se o --prazo cortar
  uma rodada no meio, as habilidades que ficam de fora são sorteadas, e não sempre as últimas (H25-H30).
- A barreira anti-saturação olha só as questões do próprio modelo (saturacao_por_modelo=True).
- Retomável: ciclos já gravados no manifesto contam; --por-habilidade é o total acumulado desejado.
- Queda de conexão com o Ollama (ou timeout) não vira ciclo reprovado: o ciclo é marcado como
  'interrompido_infra' (excluir da análise) e refeito; após 3 quedas seguidas o script sai com código 2.

Uso:
    python scripts/experimento2/gerar_ineditas.py --modelo qwen2.5:7b-instruct-q4_K_M --por-habilidade 1
    python scripts/experimento2/gerar_ineditas.py --modelo qwen3:8b-q4_K_M --think false --por-habilidade 2
    python scripts/experimento2/gerar_ineditas.py --modelo deepseek-r1:8b --think true --rotulo rtx4090 --prazo "2026-11-13 07:00"
"""
import os
import re
import sys
import json
import time
import uuid
import random
import argparse
import datetime
from typing import Dict, List, Optional, Set

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts", "experimento1"))
os.chdir(ROOT)  # o QuestionService resolve data/habilidades_queries.json a partir da raiz

from app.core.config import settings  # noqa: E402
from app.db.init_db import init_db  # noqa: E402
from app.db.models.ciclo_geracao import CicloGeracao  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.schemas.question import HABILIDADES_DESABILITADAS  # noqa: E402
from app.services.llm_client import LLMClient, LLMConnectionError, LLMTimeoutError  # noqa: E402
from app.services.question_service import QuestionService  # noqa: E402
from app.services.vectorstore import ChromaVectorStore, EmbeddingService  # noqa: E402
from avaliar_base import digest_modelo, parse_bool, versao_ollama  # noqa: E402

DIR_EXP = os.path.join(ROOT, "data", "experimento2")
DIR_CICLOS = os.path.join(DIR_EXP, "ciclos")
MAX_QUEDAS_SEGUIDAS = 3
HABILIDADES_ATIVAS = [f"H{i:02d}" for i in range(1, 31) if f"H{i:02d}" not in HABILIDADES_DESABILITADAS]


def nome_manifesto(modelo: str, think: Optional[bool], rotulo: str = "") -> str:
    nome = re.sub(r"[^A-Za-z0-9._-]+", "_", modelo)
    sufixo = "" if think is None else ("_think" if think else "_nothink")
    prefixo = f"{rotulo}__" if rotulo else ""
    return os.path.join(DIR_CICLOS, f"{prefixo}{nome}{sufixo}.jsonl")


def ler_manifesto(caminho: str) -> List[dict]:
    if not os.path.exists(caminho):
        return []
    with open(caminho, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def ciclos_da_habilidade(db, habilidade: str) -> Set[str]:
    return {str(i) for (i,) in db.query(CicloGeracao.id).filter(CicloGeracao.habilidade_codigo == habilidade).all()}


def ler_prazo(valor: Optional[str]) -> Optional[float]:
    if not valor:
        return None
    return datetime.datetime.strptime(valor, "%Y-%m-%d %H:%M").timestamp()


def main() -> None:
    parser = argparse.ArgumentParser(description="Experimento 2: geração de questões inéditas com um modelo.")
    parser.add_argument("--modelo", required=True, help="Tag do modelo no Ollama.")
    parser.add_argument("--think", type=parse_bool, default=None,
                        help="true/false liga/desliga o raciocínio (qwen3, deepseek-r1); 'padrao' não envia.")
    parser.add_argument("--por-habilidade", type=int, default=1,
                        help="Total acumulado de ciclos por habilidade (retomável).")
    parser.add_argument("--habilidades", default="all", help="'all' (28 ativas) ou lista separada por vírgula.")
    parser.add_argument("--max-attempts", type=int, default=5)
    parser.add_argument("--few-shot-k", type=int, default=2)
    parser.add_argument("--rotulo", default="", help="Hardware da rodada (ex.: 'rtx4090'); entra no nome do manifesto.")
    parser.add_argument("--semente-ordem", type=int, default=2026,
                        help="Semente da ordem das habilidades no rodízio (a mesma para todos os modelos).")
    parser.add_argument("--prazo", default=None,
                        help="'AAAA-MM-DD HH:MM' (hora local): não inicia ciclos depois disso.")
    args = parser.parse_args()

    habilidades = list(HABILIDADES_ATIVAS) if args.habilidades.lower() == "all" else [
        h.strip().upper() for h in args.habilidades.split(",") if h.strip()
    ]
    random.Random(args.semente_ordem).shuffle(habilidades)
    prazo = ler_prazo(args.prazo)
    digest = digest_modelo(args.modelo)
    ollama = versao_ollama()
    os.makedirs(DIR_CICLOS, exist_ok=True)
    manifesto = nome_manifesto(args.modelo, args.think, args.rotulo)

    feitos: Dict[str, int] = {h: 0 for h in habilidades}
    for r in ler_manifesto(manifesto):
        if r.get("status") != "interrompido_infra" and r.get("habilidade") in feitos:
            feitos[r["habilidade"]] += 1

    # Rodízio: rodada n = 1 ciclo de cada habilidade que ainda tem menos de n ciclos
    fila = [(n, h) for n in range(1, args.por_habilidade + 1) for h in habilidades if feitos[h] < n]
    print(f"{args.modelo} ({digest}) | Ollama {ollama} em {settings.LLM_ENDPOINT_URL} | think={args.think} | "
          f"meta {args.por_habilidade}/habilidade | já feitos: {sum(feitos.values())} | nesta execução: {len(fila)}"
          + (f" | prazo {args.prazo}" if args.prazo else ""), flush=True)
    if not fila:
        return

    llm = LLMClient(model_name=args.modelo, think=args.think)
    db = SessionLocal()
    init_db(db)
    servico = QuestionService(
        llm_client=llm,
        vector_store=ChromaVectorStore(embedding_service=EmbeddingService()),
        saturacao_por_modelo=True,
    )

    quedas_seguidas = 0
    tempos: List[float] = []
    try:
        idx = 0
        while idx < len(fila):
            if prazo and time.time() >= prazo:
                print(f"Prazo {args.prazo} atingido: {len(fila) - idx} ciclo(s) não iniciados.", flush=True)
                break
            rodada, hab = fila[idx]
            antes = ciclos_da_habilidade(db, hab)
            t0 = time.time()
            registro = {
                "modelo": args.modelo, "modelo_digest": digest, "think": args.think, "ollama_versao": ollama,
                "rotulo": args.rotulo, "habilidade": hab, "rodada": rodada, "max_attempts": args.max_attempts,
                "few_shot_k": args.few_shot_k, "inicio": datetime.datetime.now().isoformat(timespec="seconds"),
            }
            try:
                questao = servico.generate_single_questao_inedita(
                    db=db, habilidade_codigo=hab, num_few_shot=args.few_shot_k, max_attempts=args.max_attempts
                )
                registro.update(status="aprovada", sucesso=True, ciclo_id=str(questao.ciclo_id),
                                questao_id=str(questao.id))
            except (LLMConnectionError, LLMTimeoutError) as e:
                db.rollback()
                novos = sorted(ciclos_da_habilidade(db, hab) - antes)
                registro.update(status="interrompido_infra", sucesso=None, ciclo_id=novos[0] if novos else None,
                                erro=f"{type(e).__name__}: {e}"[:500])
                quedas_seguidas += 1
            except Exception as e:
                db.rollback()
                novos = sorted(ciclos_da_habilidade(db, hab) - antes)
                esgotou = str(e).startswith("RN-Q01")
                registro.update(status="reprovada" if esgotou else "erro_inesperado", sucesso=False,
                                ciclo_id=novos[0] if novos else None, erro=f"{type(e).__name__}: {e}"[:500])

            if registro.get("ciclo_id"):
                ciclo = db.get(CicloGeracao, uuid.UUID(registro["ciclo_id"]))
                if ciclo is not None:
                    registro["total_tentativas"] = ciclo.total_tentativas
            registro["tempo_s"] = round(time.time() - t0, 1)
            with open(manifesto, "a", encoding="utf-8") as f:
                f.write(json.dumps(registro, ensure_ascii=False) + "\n")

            if registro["status"] == "interrompido_infra":
                print(f"[{idx + 1}/{len(fila)}] {hab} rodada {rodada} INTERROMPIDO ({registro['erro'][:120]})", flush=True)
                if quedas_seguidas >= MAX_QUEDAS_SEGUIDAS:
                    print(f"{quedas_seguidas} quedas seguidas de conexão com o Ollama: parando para retomar depois.", flush=True)
                    sys.exit(2)
                time.sleep(30)
                continue  # refaz o mesmo ciclo
            quedas_seguidas = 0
            tempos.append(registro["tempo_s"])
            media = sum(tempos) / len(tempos)
            print(f"[{idx + 1}/{len(fila)}] {hab} rodada {rodada} {registro['status']} "
                  f"({registro.get('total_tentativas', '?')} tent., {registro['tempo_s']}s) | média {media:.0f}s "
                  f"→ faltam ~{media * (len(fila) - idx - 1) / 3600:.1f} h", flush=True)
            idx += 1
    finally:
        db.close()
    print(f"Manifesto em {os.path.relpath(manifesto, ROOT)}", flush=True)


if __name__ == "__main__":
    main()
