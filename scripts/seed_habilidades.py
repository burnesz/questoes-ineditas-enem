import os
import sys
import logging
from typing import Optional
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db.session import SessionLocal
from app.db.base import Base
from app.db.session import engine
from app.db.models.habilidade import HabilidadeEnem

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_habilidades")

HABILIDADES_MAT = [
    {"codigo": "H01", "competencia": 1, "descricao": "Reconhecer, no contexto social, diferentes significados e representações dos números e operações.", "eixo_tematico": "Números e Operações"},
    {"codigo": "H02", "competencia": 1, "descricao": "Identificar padrões numéricos ou princípios de contagem.", "eixo_tematico": "Números e Operações"},
    {"codigo": "H03", "competencia": 1, "descricao": "Resolver situação-problema envolvendo conhecimentos numéricos.", "eixo_tematico": "Números e Operações"},
    {"codigo": "H04", "competencia": 1, "descricao": "Avaliar a razoabilidade de um resultado numérico na construção de argumentos sobre afirmações quantitativas.", "eixo_tematico": "Números e Operações"},
    {"codigo": "H05", "competencia": 1, "descricao": "Avaliar propostas de intervenção na realidade envolvendo conhecimentos numéricos.", "eixo_tematico": "Números e Operações"},

    {"codigo": "H06", "competencia": 2, "descricao": "Interpretar a localização e a movimentação de pessoas/objetos em representações bidimensionais (mapas, croquis etc.).", "eixo_tematico": "Geometria"},
    {"codigo": "H07", "competencia": 2, "descricao": "Identificar características de figuras planas ou espaciais.", "eixo_tematico": "Geometria"},
    {"codigo": "H08", "competencia": 2, "descricao": "Resolver situação-problema que envolva conhecimentos geométricos de espaço e forma.", "eixo_tematico": "Geometria"},
    {"codigo": "H09", "competencia": 2, "descricao": "Utilizar conhecimentos geométricos de espaço e forma na seleção de argumentos propostos como solução de problemas do cotidiano.", "eixo_tematico": "Geometria"},

    {"codigo": "H10", "competencia": 3, "descricao": "Identificar relações entre grandezas e unidades de medida.", "eixo_tematico": "Grandezas e Medidas"},
    {"codigo": "H11", "competencia": 3, "descricao": "Utilizar a noção de escalas na leitura de representação de situação do cotidiano.", "eixo_tematico": "Grandezas e Medidas"},
    {"codigo": "H12", "competencia": 3, "descricao": "Resolver situação-problema que envolva medidas de grandezas.", "eixo_tematico": "Grandezas e Medidas"},
    {"codigo": "H13", "competencia": 3, "descricao": "Avaliar o resultado de uma medição na construção de um argumento consistente.", "eixo_tematico": "Grandezas e Medidas"},
    {"codigo": "H14", "competencia": 3, "descricao": "Avaliar proposta de intervenção na realidade envolvendo grandezas e medidas.", "eixo_tematico": "Grandezas e Medidas"},

    {"codigo": "H15", "competencia": 4, "descricao": "Identificar a relação de dependência entre grandezas.", "eixo_tematico": "Proporcionalidade"},
    {"codigo": "H16", "competencia": 4, "descricao": "Resolver situação-problema envolvendo a variação de grandezas, direta ou inversamente proporcionais.", "eixo_tematico": "Proporcionalidade"},
    {"codigo": "H17", "competencia": 4, "descricao": "Analisar informações envolvendo a variação de grandezas como recurso para a construção de argumentação.", "eixo_tematico": "Proporcionalidade"},
    {"codigo": "H18", "competencia": 4, "descricao": "Avaliar propostas de intervenção na realidade envolvendo variação de grandezas.", "eixo_tematico": "Proporcionalidade"},

    {"codigo": "H19", "competencia": 5, "descricao": "Identificar representações algébricas que expressem a relação entre grandezas.", "eixo_tematico": "Álgebra e Funções"},
    {"codigo": "H20", "competencia": 5, "descricao": "Interpretar gráfico cartesiano que represente relações entre grandezas.", "eixo_tematico": "Álgebra e Funções"},
    {"codigo": "H21", "competencia": 5, "descricao": "Resolver situação-problema cuja modelagem envolva conhecimentos algébricos.", "eixo_tematico": "Álgebra e Funções"},
    {"codigo": "H22", "competencia": 5, "descricao": "Utilizar conhecimentos algébricos/geométricos como recurso para a construção de argumentação.", "eixo_tematico": "Álgebra e Funções"},
    {"codigo": "H23", "competencia": 5, "descricao": "Avaliar propostas de intervenção na realidade envolvendo conhecimentos algébricos.", "eixo_tematico": "Álgebra e Funções"},

    {"codigo": "H24", "competencia": 6, "descricao": "Utilizar informações expressas em gráficos ou tabelas para fazer inferências.", "eixo_tematico": "Estatística e Gráficos"},
    {"codigo": "H25", "competencia": 6, "descricao": "Resolver problema com dados apresentados em tabelas ou gráficos.", "eixo_tematico": "Estatística e Gráficos"},
    {"codigo": "H26", "competencia": 6, "descricao": "Analisar informações de tabelas ou gráficos como recurso para a construção de argumentos.", "eixo_tematico": "Estatística e Gráficos"},

    {"codigo": "H27", "competencia": 7, "descricao": "Calcular medidas de tendência central ou de dispersão de um conjunto de dados.", "eixo_tematico": "Probabilidade e Estatística"},
    {"codigo": "H28", "competencia": 7, "descricao": "Resolver situação-problema que envolva conhecimentos de estatística e probabilidade.", "eixo_tematico": "Probabilidade e Estatística"},
    {"codigo": "H29", "competencia": 7, "descricao": "Utilizar conhecimentos de estatística e probabilidade como recurso para a construção de argumentação.", "eixo_tematico": "Probabilidade e Estatística"},
    {"codigo": "H30", "competencia": 7, "descricao": "Avaliar propostas de intervenção na realidade envolvendo conhecimentos de estatística e probabilidade.", "eixo_tematico": "Probabilidade e Estatística"}
]


def seed_habilidades(db: Optional[Session] = None) -> int:
    should_close = False
    if db is None:
        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
        should_close = True
    try:
        count = 0
        for item in HABILIDADES_MAT:
            habilidade = db.get(HabilidadeEnem, item["codigo"])
            if habilidade:
                habilidade.competencia = item["competencia"]
                habilidade.descricao = item["descricao"]
                habilidade.eixo_tematico = item["eixo_tematico"]
            else:
                db.add(HabilidadeEnem(**item))
            count += 1
        db.commit()
        logger.info(f"Sucesso: {count} habilidades processadas.")
        return count
    finally:
        if should_close:
            db.close()


if __name__ == "__main__":
    seed_habilidades()
