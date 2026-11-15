"""
Experimento 1 — Fase 4: tabela de resultados dos modelos avaliadores.

Cruza as avaliações oficiais (data/experimento1/avaliacoes/rtx4090__*.jsonl) com a chave
(base_experimento_chave.csv) e calcula, por modelo:

- Acurácia nas autênticas: a alternativa a que o modelo chegou é o gabarito oficial.
- Detecção de questões com erro: a classe positiva é "defeituosa" e a predição positiva é "reprovada".
  Daí saem precisão, recall, F1 e o falso positivo (autênticas reprovadas).
- Recall por tipo de erro e tempo médio por avaliação.
- Comparação estatística: teste de McNemar (exato), pareado item a item, entre o modelo de maior F1
  e cada um dos outros, sobre o acerto do veredito.

Falhas técnicas (resposta vazia ou JSON inválido do modelo, erro do servidor) não são veredito:
ficam fora da detecção e são contadas à parte. Na acurácia, contam como questão não resolvida.

Uso:
    python scripts/experimento1/analisar_resultados.py
Saída: data/experimento1/resultados/tabela_experimento1.md e .csv
"""
import os
import csv
import glob
import json
import statistics
from typing import Dict, List

from scipy.stats import binomtest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DIR_EXP = os.path.join(ROOT, "data", "experimento1")
DIR_SAIDA = os.path.join(DIR_EXP, "resultados")
TIPOS = ["GABARITO", "CALCULO", "AMBIGUIDADE", "CONTRADICAO"]
ROTULOS_TIPO = {"GABARITO": "Gabarito", "CALCULO": "Cálculo", "AMBIGUIDADE": "Ambiguidade", "CONTRADICAO": "Contradição"}
NOMES = {
    "qwen2.5_7b-instruct-q4_K_M": "Qwen2.5 7B",
    "qwen3_8b-q4_K_M_nothink": "Qwen3 8B",
    "llama3.1_8b-instruct-q4_K_M": "Llama 3.1 8B",
    "deepseek-r1_8b_think": "DeepSeek-R1 8B",
}


def falha_tecnica(r: dict) -> bool:
    return bool(r.get("erro_execucao")) or str(r.get("motivo_falha") or "").startswith("Falha n")


def carregar() -> Dict[str, Dict[str, dict]]:
    modelos = {}
    for caminho in sorted(glob.glob(os.path.join(DIR_EXP, "avaliacoes", "rtx4090__*.jsonl"))):
        chave = os.path.basename(caminho)[len("rtx4090__"):-len(".jsonl")]
        registros = {}
        with open(caminho, encoding="utf-8") as f:
            for linha in f:
                if linha.strip():
                    r = json.loads(linha)
                    registros[r["item_id"]] = r  # o último registro do item vale
        modelos[NOMES.get(chave, chave)] = registros
    return modelos


def pct(a: int, b: int) -> str:
    return br(100 * a / b, 1) + "%" if b else "-"


def br(valor: float, casas: int) -> str:
    return f"{valor:.{casas}f}".replace(".", ",")


def formatar_p(p: float) -> str:
    return "< 0,001" if p < 0.001 else f"{p:.3f}".replace(".", ",")


def main() -> None:
    with open(os.path.join(DIR_EXP, "base_experimento_chave.csv"), encoding="utf-8-sig") as f:
        chave = {r["item_id"]: r for r in csv.DictReader(f)}
    with open(os.path.join(DIR_EXP, "base_experimento.jsonl"), encoding="utf-8") as f:
        gabaritos = {r["item_id"]: r["gabarito"] for r in (json.loads(l) for l in f if l.strip())}

    modelos = carregar()
    linhas: List[dict] = []
    acertos_veredito: Dict[str, Dict[str, bool]] = {}

    for nome, regs in modelos.items():
        assert len(regs) == len(chave), f"{nome}: {len(regs)} itens avaliados, esperado {len(chave)}"
        vp = fp = fn = vn = tecnicas = acertos_aut = 0
        por_tipo = {t: [0, 0] for t in TIPOS}  # [reprovadas, válidas]
        acertos_veredito[nome] = {}
        for item_id, r in regs.items():
            defeituosa = chave[item_id]["rotulo"] == "defeituosa"
            if not defeituosa and r.get("letras_mapeadas") == [gabaritos[item_id]]:
                acertos_aut += 1
            if falha_tecnica(r):
                tecnicas += 1
                continue
            reprovada = not r.get("aprovada")
            acertos_veredito[nome][item_id] = reprovada == defeituosa
            if defeituosa:
                tipo = chave[item_id]["tipo_erro"]
                por_tipo[tipo][1] += 1
                por_tipo[tipo][0] += reprovada
                vp += reprovada
                fn += not reprovada
            else:
                fp += reprovada
                vn += not reprovada
        precisao = vp / (vp + fp) if vp + fp else 0.0
        recall = vp / (vp + fn) if vp + fn else 0.0
        f1 = 2 * precisao * recall / (precisao + recall) if precisao + recall else 0.0
        tempos = [float(r["duracao_s"]) for r in regs.values() if r.get("duracao_s") is not None]
        n_aut = sum(1 for k in chave.values() if k["rotulo"] != "defeituosa")
        linhas.append({
            "modelo": nome,
            "acuracia_autenticas": acertos_aut / n_aut,
            "acertos_autenticas": acertos_aut, "n_autenticas": n_aut,
            "precisao": precisao, "recall": recall, "f1": f1,
            "falso_positivo": fp / (fp + vn) if fp + vn else 0.0,
            "vp": vp, "fp": fp, "fn": fn, "vn": vn,
            "falhas_tecnicas": tecnicas,
            "tempo_medio_s": statistics.mean(tempos), "tempo_mediano_s": statistics.median(tempos),
            **{f"recall_{t.lower()}": (por_tipo[t][0] / por_tipo[t][1] if por_tipo[t][1] else 0.0) for t in TIPOS},
            **{f"n_{t.lower()}": por_tipo[t][1] for t in TIPOS},
        })

    linhas.sort(key=lambda l: -l["f1"])
    melhor = linhas[0]["modelo"]

    # McNemar exato: itens em que um modelo acerta o veredito e o outro erra
    comparacoes = []
    for l in linhas[1:]:
        outro = l["modelo"]
        comuns = acertos_veredito[melhor].keys() & acertos_veredito[outro].keys()
        b = sum(1 for i in comuns if acertos_veredito[melhor][i] and not acertos_veredito[outro][i])
        c = sum(1 for i in comuns if not acertos_veredito[melhor][i] and acertos_veredito[outro][i])
        p = binomtest(b, b + c, 0.5).pvalue if b + c else 1.0
        comparacoes.append({"outro": outro, "itens": len(comuns), "so_melhor": b, "so_outro": c, "p": p})

    os.makedirs(DIR_SAIDA, exist_ok=True)
    with open(os.path.join(DIR_SAIDA, "tabela_experimento1.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0].keys()))
        w.writeheader()
        for l in linhas:
            w.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in l.items()})

    md = ["# Experimento 1: resultados dos modelos avaliadores", "",
          f"Base: {len(chave)} questões ({linhas[0]['n_autenticas']} autênticas e "
          f"{len(chave) - linhas[0]['n_autenticas']} com erro). Modelos ordenados pelo F1.", "",
          "## Tabela principal", "",
          "| Modelo | Acurácia nas autênticas | Precisão | Recall | F1 | Falso positivo | Tempo médio | Falhas técnicas |",
          "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for l in linhas:
        md.append(f"| {l['modelo']} | {pct(l['acertos_autenticas'], l['n_autenticas'])} | {br(l['precisao'], 3)} | "
                  f"{br(l['recall'], 3)} | **{br(l['f1'], 3)}** | {br(100 * l['falso_positivo'], 1)}% | "
                  f"{br(l['tempo_medio_s'], 1)} s | {l['falhas_tecnicas']} |")
    md += ["", "## Recall por tipo de erro", "",
           "| Modelo | " + " | ".join(ROTULOS_TIPO[t] for t in TIPOS) + " |",
           "| :--- | " + " | ".join("---:" for _ in TIPOS) + " |"]
    for l in linhas:
        md.append(f"| {l['modelo']} | " + " | ".join(
            pct(round(l[f'recall_{t.lower()}'] * l[f'n_{t.lower()}']), l[f'n_{t.lower()}']) for t in TIPOS) + " |")
    md += ["", f"## Comparação estatística (McNemar exato, {melhor} contra os demais)", "",
           f"| Comparação | Itens comparados | Só {melhor} acertou | Só o outro acertou | p-valor |",
           "| :--- | ---: | ---: | ---: | ---: |"]
    for c in comparacoes:
        md.append(f"| {melhor} × {c['outro']} | {c['itens']} | {c['so_melhor']} | {c['so_outro']} | "
                  f"{formatar_p(c['p'])} |")
    md += ["", "## Como ler", "",
           "- **Acurácia nas autênticas**: % das 140 questões autênticas em que o modelo chegou à alternativa do gabarito oficial.",
           "- **Precisão**: das questões que o modelo reprovou, quantas tinham erro de fato.",
           "- **Recall**: das questões com erro, quantas o modelo reprovou.",
           "- **F1**: média harmônica entre precisão e recall.",
           "- **Falso positivo**: % das autênticas que o modelo reprovou sem motivo.",
           "- **Falhas técnicas**: respostas vazias ou malformadas do modelo. Ficam fora da precisão e do recall e "
           "contam como não resolvidas na acurácia.",
           "- **McNemar**: compara os dois modelos nos mesmos itens. p-valor < 0,05 indica diferença estatisticamente significativa.", ""]
    with open(os.path.join(DIR_SAIDA, "tabela_experimento1.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print("\n".join(md))


if __name__ == "__main__":
    main()
