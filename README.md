# Geração de Questões Inéditas de Matemática no ENEM (PoT + ChromaDB)

Projeto autônomo e local para elaboração, validação e persistência de **questões inéditas de Matemática alinhadas à Matriz de Referência do ENEM** (Competências `C1` a `C7`, Habilidades `H01` a `H30`).

---

## 🚀 Arquitetura e Diferenciais Técnicos

1. **Program-Aided Generation (PoT)**:
   - O LLM local (**Qwen 2.5 7B** via Ollama) elabora o planejamento, situação-problema e a função Python `def resolver():`.
   - Um interpretador isolado (`CodeExecutor`) executa os cálculos em subprocesso com timeout de 5 segundos, garantindo **100% de precisão aritmética**.
2. **Segurança Estática via AST**:
   - Bloqueio estático de chamadas e módulos de rede, sistema operacional e reflexão dinâmica (`os`, `sys`, `subprocess`, `eval`, `open`, etc.).
3. **Nexo Numérico Estrito (*Groundedness*) via Backward Slicing**:
   - Todo número usado no cálculo do gabarito deve constar explicitamente no enunciado ou na tabela, com suporte a numerais por extenso e conversões percentuais.
4. **Auto-Healing Algorítmico & Shuffling A–E**:
   - Cura determinística em 0ms para até 1 distrator colidente e embaralhamento com random seed das alternativas A a E (o LLM nunca escolhe a letra do gabarito).
5. **Validação Cega em 3 Etapas contra Viés de Confirmação (*Sycophancy*)**:
   - **Etapa 1**: Resolução Cega Pura (o LLM resolve a questão sem alternativas e sem gabarito, reportando premissas implícitas e dados ociosos).
   - **Etapa 2**: Confronto Direto de Equivalência com *Early Exit*.
   - **Etapa 3**: Auditoria Semântica e Pedagógica com critérios objetivos (B3).
6. **Acervo Histórico e ChromaDB Local**:
   - Acompanha o dataset bruto `data/itens_prova_2009_2024_enriquecido.csv` com mais de 400 questões históricas do ENEM (2009–2024).
   - Banco vetorial local **ChromaDB** persistido em disco (`./chroma_db`), indexado com o modelo `intfloat/multilingual-e5-large`.

---

## 📁 Estrutura de Diretórios

```
questoes-ineditas-enem/
├── app/
│   ├── api/                     # Rotas FastAPI (/health, /questoes/ineditas)
│   ├── core/                    # Configurações Pydantic, prompts PoT e sanitizadores
│   ├── db/                      # Modelos SQLAlchemy 2.0 (Habilidade, Inedita, Enem)
│   ├── schemas/                 # Schemas tipados Pydantic v2 e JSON Schemas Ollama
│   ├── services/                # CodeExecutor, QuestionService, LLMClient, ChromaVectorStore
│   └── main.py                  # Ponto de entrada da aplicação FastAPI
├── data/
│   ├── habilidades_queries.json                # 30 habilidades com queries expandidas e tipologias
│   └── itens_prova_2009_2024_enriquecido.csv   # Dataset raw de questões históricas do ENEM
├── scripts/
│   ├── seed_habilidades.py           # Popula H01 a H30 no banco
│   ├── seed_questoes.py              # Popula acervo histórico no banco relacional
│   ├── seed_chroma.py                # Indexa o CSV histórico no ChromaDB local
│   └── populate_questoes_ineditas.py # CLI para geração e povoamento em lote
├── tests/                       # Suíte completa de testes unitários e de integração
├── requirements.txt             # Dependências do projeto
├── pytest.ini                   # Configurações do Pytest
└── README.md
```

---

## 🛠️ Instalação e Configuração

### 1. Criar e Ativar o Ambiente Virtual

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Configurar o Arquivo `.env`

Copie o template de variáveis de ambiente:
```bash
cp .env.example .env
```

Por padrão, o projeto utiliza SQLite local (`sqlite:///./questoes_ineditas.db`) e ChromaDB em `./chroma_db`, sem necessidade de banco externo ou chaves de API.

---

## 📊 Povoamento e Indexação

### 1. Cadastrar as Habilidades e o Acervo Histórico no SQLite

```bash
python scripts/seed_questoes.py
```

### 2. Indexar as Questões no ChromaDB Local

Gera os embeddings de alta fidelidade das mais de 400 questões históricas no ChromaDB:
```bash
python scripts/seed_chroma.py
```
*(Para indexar rapidamente em modo simulação/testes, adicione a flag `--mock-embeddings`).*

---

## 💻 Uso via CLI (Geração em Lote)

Gere questões inéditas diretamente pelo terminal:

```bash
# Gerar 1 questão para uma habilidade específica (ex: H01):
python scripts/populate_questoes_ineditas.py --habilidades H01

# Gerar para múltiplas habilidades:
python scripts/populate_questoes_ineditas.py --habilidades H01,H02,H03 --count 2

# Gerar 1 questão para todas as 30 habilidades do ENEM (H01 a H30):
python scripts/populate_questoes_ineditas.py --habilidades all

# Modo simulação (sem necessidade de GPU/Ollama ativo):
python scripts/populate_questoes_ineditas.py --habilidades H01 --mock
```

---

## 🌐 Executando a API Web

Inicie o servidor FastAPI:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Acesse a documentação interativa:
- Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
- Health Check: [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health)

---

## 🧪 Executando os Testes Automatizados

A suíte cobre execução de subprocesso, AST de segurança, backward slicing, auto-healing de distratores, validação cega em 3 etapas, busca vetorial no ChromaDB e endpoints da API:

```bash
pytest
```
