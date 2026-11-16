"""
Pares de questões (VERA × baseline zero-shot) para a avaliação cega por especialista.

- VERA: questões APROVADAS do gerador escolhido no Experimento 2 (Qwen2.5 7B), uma por habilidade, sorteadas com
  semente fixa entre as habilidades disponíveis.
- Baseline: o mesmo modelo gera uma questão para a mesma habilidade, com o mesmo tema, abertura e tipologia da
  tentativa da VERA, sem RAG, sem few-shot, sem PoT e sem validação (app/services/baseline_service.py).

Grava data/avaliacao_especialista/pares_questoes.jsonl (retomável: pares já gravados são pulados) e manifest.json.

Uso:
    python scripts/avaliacao_especialista/gerar_pares_questoes.py [--n 10] [--semente 2026]
"""
import os
import sys
import json
import uuid
import random
import argparse
import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts", "experimento1"))
os.chdir(ROOT)

from app.core.config import settings  # noqa: E402
from app.db.models.habilidade import HabilidadeEnem  # noqa: E402
from app.db.models.questao_inedita import QuestaoInedita  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services.baseline_service import BaselineQuestaoService  # noqa: E402
from app.services.llm_client import LLMClient  # noqa: E402
from avaliar_base import digest_modelo, versao_ollama  # noqa: E402

GERADOR = "qwen2.5:7b-instruct-q4_K_M"
QUESTOES_EXP2 = os.path.join(ROOT, "data", "experimento2", "questoes_geradas.jsonl")
DIR_SAIDA = os.path.join(ROOT, "data", "avaliacao_especialista")
SAIDA = os.path.join(DIR_SAIDA, "pares_questoes.jsonl")


def sortear_aprovadas(n, rng):
    with open(QUESTOES_EXP2, encoding="utf-8") as f:
        aprovadas = [q for q in (json.loads(l) for l in f if l.strip()) if q["is_validated"] and q["modelo"] == GERADOR]
    por_hab = {}
    for q in sorted(aprovadas, key=lambda q: q["id"]):
        por_hab.setdefault(q["habilidade_codigo"], []).append(q)
    habs = sorted(por_hab)
    rng.shuffle(habs)
    return [rng.choice(por_hab[h]) for h in habs[:n]]


def main():
    parser = argparse.ArgumentParser(description="Gera os pares de questões VERA × baseline.")
    parser.add_argument("--n", type=int, default=10)
    parser.add_argument("--semente", type=int, default=2026)
    args = parser.parse_args()

    os.makedirs(DIR_SAIDA, exist_ok=True)
    feitos = set()
    if os.path.exists(SAIDA):
        with open(SAIDA, encoding="utf-8") as f:
            feitos = {json.loads(l)["vera"]["questao_id"] for l in f if l.strip()}
    with open(os.path.join(DIR_SAIDA, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"criado_em": datetime.datetime.now().isoformat(timespec="seconds"), "gerador": GERADOR,
                   "gerador_digest": digest_modelo(GERADOR), "ollama_versao": versao_ollama(),
                   "endpoint": settings.LLM_ENDPOINT_URL, "n_pares": args.n, "semente": args.semente,
                   "vera": "questões aprovadas do Experimento 2 (Etapas 1 a 4, uma tentativa)",
                   "baseline": "BaselineQuestaoService: mesmo prompt da Fase 2A sem RAG, few-shot, PoT e validação"},
                  f, ensure_ascii=False, indent=2)

    servico = BaselineQuestaoService(llm_client=LLMClient(model_name=GERADOR))
    db = SessionLocal()
    try:
        for n, q in enumerate(sortear_aprovadas(args.n, random.Random(args.semente)), start=1):
            if q["id"] in feitos:
                continue
            questao = db.get(QuestaoInedita, uuid.UUID(q["id"]))
            tentativa = questao.tentativa
            habilidade = db.get(HabilidadeEnem, q["habilidade_codigo"])
            base = servico.gerar_questao(habilidade, tema=tentativa.tema, abertura=tentativa.abertura,
                                         tipologia=tentativa.tipologia, seed=args.semente + n)
            registro = {
                "id": f"Q{n:02d}", "habilidade": habilidade.codigo, "habilidade_descricao": habilidade.descricao,
                "insumo": {"tema": tentativa.tema, "abertura": tentativa.abertura, "tipologia": tentativa.tipologia},
                "vera": {"questao_id": q["id"], "enunciado": q["enunciado"], "alternativas": q["alternativas"],
                         "gabarito": q["gabarito"]},
                "baseline": base,
            }
            with open(SAIDA, "a", encoding="utf-8") as f:
                f.write(json.dumps(registro, ensure_ascii=False) + "\n")
            print(f"[questões] {registro['id']} {habilidade.codigo}: baseline em {base['tempo_s']}s "
                  f"(falhas de formato: {len(base['falhas_formato'])})", flush=True)
    finally:
        db.close()
    print(f"Pares gravados em {os.path.relpath(SAIDA, ROOT)}", flush=True)


if __name__ == "__main__":
    main()
