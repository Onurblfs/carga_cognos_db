# carga_cognos_db

Fluxo de dados que **baixa as fontes de dados do IBM Cognos Analytics e grava em banco de dados**.

O fluxo funciona em 3 etapas para cada fonte cadastrada:

1. **Download** — autentica no Cognos e executa o relatorio, baixando o resultado em CSV ou Excel (`src/cognos_client.py`);
2. **Leitura** — converte o arquivo baixado em DataFrame do pandas (`src/main.py`);
3. **Carga** — grava o DataFrame na tabela de destino do banco (`src/db_loader.py`).

## Estrutura

```
carga_cognos_db/
├── config/
│   └── fontes.yaml        # cadastro das fontes do Cognos e tabelas de destino
├── src/
│   ├── config.py          # leitura do .env e do fontes.yaml
│   ├── cognos_client.py   # login e download dos relatorios do Cognos
│   ├── db_loader.py       # gravacao dos dados no banco (pandas + SQLAlchemy)
│   └── main.py            # orquestrador do fluxo
├── .env.example           # modelo das variaveis de ambiente (credenciais)
└── requirements.txt
```

## Como usar

### 1. Instalar dependencias

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

> Para SQL Server e necessario ter o **ODBC Driver 17 (ou 18) for SQL Server** instalado na maquina.

### 2. Configurar credenciais

Copie `.env.example` para `.env` e preencha:

- `COGNOS_URL`, `COGNOS_NAMESPACE`, `COGNOS_USUARIO`, `COGNOS_SENHA` — acesso ao Cognos;
- `DB_CONNECTION_STRING` — string de conexao SQLAlchemy do banco de destino (exemplos no proprio arquivo, incluindo SQL Server com autenticacao Windows).

### 3. Cadastrar as fontes

Edite `config/fontes.yaml` e cadastre cada relatorio/fonte do Cognos com:

- `store_id` do relatorio (propriedades do relatorio no Cognos > Geral > ID);
- `tabela` e `schema` de destino no banco;
- `modo_carga`: `substituir` (TRUNCATE + INSERT), `recriar` (DROP + CREATE) ou `anexar` (INSERT acumulando historico).

### 4. Executar

```bash
python -m src.main                        # processa todas as fontes
python -m src.main --fonte nome_da_fonte  # processa apenas uma fonte
```

Cada execucao tambem salva uma copia do arquivo baixado na pasta `downloads/` (auditoria) e grava logs no console.

### 5. Agendar (opcional)

No Windows, agende pelo **Agendador de Tarefas** apontando para:

```
C:\caminho\do\projeto\.venv\Scripts\python.exe -m src.main
```

com "Iniciar em" = pasta do projeto.

## Integracao com automacoes existentes

- Se o download do Cognos ja e feito por outra automacao (ex.: repositorio `att_cognos_pbi`), basta substituir a classe `CognosClient` mantendo a mesma interface (`login()` + `baixar_relatorio()` retornando bytes) — o restante do fluxo nao muda. Alternativamente, aponte a automacao existente para salvar os arquivos na pasta `downloads/` e use apenas o `db_loader`.
- A gravacao no banco usa o padrao `pandas.to_sql` + SQLAlchemy com `fast_executemany` (SQL Server), em transacao, com truncamento opcional antes da carga.
