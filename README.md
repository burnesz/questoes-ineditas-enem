# Geração de Questões Inéditas de Matemática no ENEM (PoT + ChromaDB)

Projeto local para elaboração, validação e persistência de **questões inéditas de Matemática alinhadas à Matriz de Referência do ENEM** (Competências `C1` a `C7`, Habilidades `H01` a `H30`, com **28 habilidades ativas** para geração).

> **Aviso sobre Escopo de Habilidades (`H06` e `H20`)**: As habilidades **H06** (localização/movimentação em mapas e croquis) e **H20** (interpretação de gráficos cartesianos) foram desabilitadas para geração e removidas do acervo histórico (`questoes_enem` e ChromaDB). Como a grande maioria das questões dessas duas habilidades exige interpretação puramente visual e a raspagem dos microdados do ENEM resultou em apenas cinco itens sem imagem ao todo, a amostragem foi considerada insuficiente para contextualização RAG. Dada a delimitação técnica deste projeto para LLMs locais estritamente textuais (Qwen 2.5 7B), o sistema conta com uma proteção estática que rejeita imediatamente qualquer tentativa de geração para H06 ou H20 (`HabilidadeDesabilitadaError`).

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
│   ├── cli.py                   # Implementação da CLI tradicional (argparse puro)
│   ├── core/                    # Configurações Pydantic, prompts PoT e sanitizadores
│   ├── db/                      # Modelos SQLAlchemy 2.0 (Habilidade, Inedita, Enem)
│   ├── schemas/                 # Schemas tipados Pydantic v2 e JSON Schemas Ollama
│   └── services/                # CodeExecutor, QuestionService, LLMClient, ChromaVectorStore
├── data/
│   ├── habilidades_queries.json                # 30 habilidades com queries expandidas e tipologias
│   └── itens_prova_2009_2024_enriquecido.csv   # Dataset raw de questões históricas do ENEM
├── scripts/
│   ├── seed_habilidades.py           # Popula H01 a H30 no banco
│   ├── seed_questoes.py              # Popula acervo histórico no banco relacional
│   ├── seed_chroma.py                # Indexa o CSV histórico no ChromaDB local
│   └── populate_questoes_ineditas.py # Wrapper compatível para geração em lote
├── tests/                       # Suíte completa de testes unitários e de integração
├── cli.py                       # Ponto de entrada executável da CLI unificada
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

## 💻 Uso da CLI

O projeto é operado inteiramente via linha de comando tradicional (`argparse` padrão do Python, sem dependências externas de formatação).

### 1. Povoamento do Ambiente (`seed`)

Popule o banco relacional SQLite e o ChromaDB com as mais de 400 questões históricas do ENEM:
```bash
# Povoar banco relacional e ChromaDB (completo):
python cli.py seed

# Apenas banco relacional:
python cli.py seed --target db

# Apenas ChromaDB (com embeddings simulados para testes rápidos):
python cli.py seed --target chroma --mock-embeddings
```

### 2. Geração de Questões Inéditas (`generate`)

Execute a pipeline autônoma PoT com validação em 3 etapas:
```bash
# Gerar 1 questão para a habilidade H01 (modo simulação/mock, sem precisar do Ollama ativo):
python cli.py generate --habilidades H01 --mock

# Gerar para uma habilidade com o LLM local (Qwen 2.5 via Ollama):
python cli.py generate --habilidades H01

# Gerar para múltiplas habilidades com 2 questões por habilidade:
python cli.py generate --habilidades H01,H02,H03 --count 2

# Gerar para as 28 habilidades ativas do ENEM (H06 e H20 são ignoradas automaticamente):
python cli.py generate --habilidades all
```

### 3. Consulta e Inspeção (`list` e `show`)

```bash
# Listar questões geradas no banco:
python cli.py list

# Filtrar listagem por habilidade específica:
python cli.py list --habilidade H01

# Exibir detalhes completos de uma questão pelo ID:
python cli.py show <UUID_DA_QUESTAO>

# Exibir os dados da questão em JSON estrito:
python cli.py show <UUID_DA_QUESTAO> --json
```

### 4. Status e Métricas do Sistema (`stats`)

Consulte a saúde da conexão com o LLM local, acervo de questões e contagem do banco vetorial:
```bash
python cli.py stats
```

### 5. Exportação de Cadernos (`export`)

Exporte o acervo gerado para impressão ou arquivamento:
```bash
# Exportar caderno pronto em Markdown:
python cli.py export -o caderno_questoes.md

# Exportar em formato JSON estruturado:
python cli.py export -o questoes.json --habilidade H01
```
