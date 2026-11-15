"""
Experimento 1 — Fase 3: avalia os itens da base com a Etapa 4 do VERA usando um modelo local.

Para cada item de data/experimento1/base_experimento.jsonl (só os campos que o avaliador
pode ver), chama QuestionService.evaluate_item(perfil="enem") com o modelo indicado e grava
uma linha por item em data/experimento1/avaliacoes/<modelo>.jsonl. A chave com os rótulos
nunca é lida aqui.

A execução é retomável: itens já gravados no arquivo do modelo são pulados, então basta
rodar o mesmo comando de novo depois de uma interrupção.

Uso:
    python scripts/experimento1/avaliar_base.py --modelo qwen2.5:7b-instruct-q4_K_M [--limite 5]
    python scripts/experimento1/avaliar_base.py --modelo qwen3:8b-q4_K_M --think false
    python scripts/experimento1/avaliar_base.py --modelo qwen2.5:7b-instruct-q4_K_M --base data/experimento1/calibracao.jsonl
    python scripts/experimento1/avaliar_base.py --modelo deepseek-r1:8b --think true --rotulo rtx4090
"""
import os
import re
import sys
import json
import time
import argparse
import datetime
from typing import Dict, Optional

import httpx

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)  # o QuestionService resolve data/habilidades_queries.json a partir da raiz

from app.core.config import settings  # noqa: E402
from app.services.llm_client import LLMClient  # noqa: E402
from app.services.question_service import QuestionService  # noqa: E402

DIR_EXP = os.path.join(ROOT, "data", "experimento1")
DEFAULT_BASE = os.path.join(DIR_EXP, "base_experimento.jsonl")
DIR_AVALIACOES = os.path.join(DIR_EXP, "avaliacoes")
MAX_ERROS_SEGUIDOS = 3  # provável queda de conexão com o Ollama: parar em vez de marcar a base inteira como erro


def nome_arquivo(modelo: str, think: Optional[bool], base: str = DEFAULT_BASE, rotulo: str = "") -> str:
    """
    Arquivo de saída por modelo. Avaliações de outra base (ex.: calibração) ganham o nome da base como prefixo,
    e um rótulo (ex.: o hardware, "rtx4090") separa rodadas do mesmo modelo feitas em ambientes diferentes.
    """
    nome = re.sub(r"[^A-Za-z0-9._-]+", "_", modelo)
    sufixo = "" if think is None else ("_think" if think else "_nothink")
    prefixo = "" if os.path.abspath(base) == DEFAULT_BASE else os.path.splitext(os.path.basename(base))[0] + "__"
    prefixo_rotulo = f"{rotulo}__" if rotulo else ""
    return os.path.join(DIR_AVALIACOES, f"{prefixo_rotulo}{prefixo}{nome}{sufixo}.jsonl")


def versao_ollama() -> str:
    resposta = httpx.get(f"{settings.LLM_ENDPOINT_URL.rstrip('/')}/api/version", timeout=10.0)
    resposta.raise_for_status()
    return resposta.json().get("version", "")


def digest_modelo(modelo: str) -> str:
    """ID do modelo no Ollama (primeiros 12 caracteres do digest), para registrar a versão exata."""
    resposta = httpx.get(f"{settings.LLM_ENDPOINT_URL.rstrip('/')}/api/tags", timeout=10.0)
    resposta.raise_for_status()
    for m in resposta.json().get("models", []):
        if m.get("name") == modelo:
            return m.get("digest", "")[:12]
    raise SystemExit(f"Modelo '{modelo}' não encontrado no Ollama (rode 'ollama pull {modelo}').")


def ja_avaliados(caminho: str) -> Dict[str, dict]:
    if not os.path.exists(caminho):
        return {}
    with open(caminho, encoding="utf-8") as f:
        return {r["item_id"]: r for r in (json.loads(l) for l in f if l.strip())}


def parse_bool(valor: str) -> Optional[bool]:
    return {"true": True, "false": False, "padrao": None}[valor.lower()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Fase 3 do Experimento 1: avaliação da base com um modelo local.")
    parser.add_argument("--modelo", required=True, help="Tag do modelo no Ollama.")
    parser.add_argument("--think", type=parse_bool, default=None,
                        help="true/false liga ou desliga o raciocínio (qwen3); 'padrao' não envia o parâmetro.")
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--limite", type=int, help="Avalia no máximo N itens novos (teste).")
    parser.add_argument("--refazer-erros", action="store_true",
                        help="Avalia de novo os itens que terminaram em erro de execução (o registro mais recente prevalece).")
    parser.add_argument("--rotulo", default="", help="Prefixo do arquivo de saída que identifica o hardware (ex.: rtx4090).")
    args = parser.parse_args()

    digest = digest_modelo(args.modelo)
    ollama = versao_ollama()
    saida = nome_arquivo(args.modelo, args.think, args.base, args.rotulo)
    os.makedirs(DIR_AVALIACOES, exist_ok=True)
    feitos = ja_avaliados(saida)

    with open(args.base, encoding="utf-8") as f:
        itens = [json.loads(l) for l in f if l.strip()]
    if args.refazer_erros:
        feitos = {k: v for k, v in feitos.items() if v.get("erro_execucao") is None}
    pendentes = [i for i in itens if i["item_id"] not in feitos]
    if args.limite:
        pendentes = pendentes[:args.limite]
    print(f"{args.modelo} ({digest}) | Ollama {ollama} em {settings.LLM_ENDPOINT_URL} | think={args.think} | já avaliados: {len(feitos)} | nesta execução: {len(pendentes)}")

    servico = QuestionService(llm_client=LLMClient(model_name=args.modelo, think=args.think))
    duracoes = []
    erros_seguidos = 0
    for n, item in enumerate(pendentes, start=1):
        inicio = time.time()
        registro = {"item_id": item["item_id"], "modelo": args.modelo, "modelo_digest": digest, "think": args.think,
                    "ollama_versao": ollama, "rotulo": args.rotulo or None}
        try:
            resultado = servico.evaluate_item(
                enunciado=item["enunciado"], alternativas=item["alternativas"], gabarito=item["gabarito"],
                habilidade_codigo=item["habilidade_codigo"], perfil="enem",
            )
            registro.update(json.loads(resultado.model_dump_json()), erro_execucao=None)
        except Exception as e:  # falha de infraestrutura (Ollama fora do ar etc.), não veredito
            registro.update(aprovada=None, erro_execucao=f"{type(e).__name__}: {e}")
        registro["duracao_s"] = round(time.time() - inicio, 1)
        registro["avaliado_em"] = datetime.datetime.now().isoformat(timespec="seconds")

        with open(saida, "a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")

        erros_seguidos = erros_seguidos + 1 if registro["aprovada"] is None else 0
        if erros_seguidos >= MAX_ERROS_SEGUIDOS:
            print(f"{erros_seguidos} erros de execução seguidos ({registro['erro_execucao']}); interrompendo. "
                  f"Rode de novo com --refazer-erros quando o Ollama voltar.", flush=True)
            sys.exit(2)

        duracoes.append(registro["duracao_s"])
        media = sum(duracoes) / len(duracoes)
        restantes = len(itens) - len(feitos) - n
        veredito = "ERRO" if registro["aprovada"] is None else ("aprovada" if registro["aprovada"] else f"reprovada {registro.get('etapa_falha')}")
        print(f"[{n}/{len(pendentes)}] {item['item_id']} {veredito} ({registro['duracao_s']}s) | "
              f"média {media:.0f}s → faltam ~{restantes * media / 3600:.1f} h para a base inteira", flush=True)

    print(f"Gravado em {os.path.relpath(saida, ROOT)}")


if __name__ == "__main__":
    main()
