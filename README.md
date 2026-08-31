# carga_cognos_db

Fluxo de dados que **baixa as bases do Cognos (IBM Planning Analytics) e grava no DWH Oracle**.

O download reaproveita a automacao ja existente do repositorio
[att_cognos_pbi](https://github.com/Onurblfs/att_cognos_pbi) (Selenium + Edge),
que exporta as views para Excel. Este projeto adiciona a etapa de **carga em banco**:

```
att_cognos_pbi (Selenium)          carga_cognos_db (este projeto)
┌──────────────────────────┐       ┌─────────────────────────────┐
│ 1. Login no Planning     │       │ 3. Localiza o Excel de cada │
│    Analytics             │  -->  │    exportacao               │
│ 2. Exporta cada view     │       │ 4. Le com pandas            │
│    para Excel            │       │ 5. Grava na tabela do banco │
└──────────────────────────┘       └─────────────────────────────┘
```

## Estrutura

```
carga_cognos_db/
├── PLAY ME.bat            # duplo clique: instala as bibliotecas e roda o fluxo
├── config/
│   └── fontes.yaml        # exportacao do att_cognos_pbi -> tabela do banco
├── src/
│   ├── att_cognos.py      # integra com o att_cognos_pbi (roda o download, acha os arquivos)
│   ├── config.py          # leitura do .env e do fontes.yaml
│   ├── db_loader.py       # gravacao no DWH Oracle (padrao do Scrip_carga_banco)
│   └── main.py            # orquestrador do fluxo
├── .env.example           # modelo das variaveis de ambiente
└── requirements.txt
```

## Como usar

### Jeito facil: duplo clique no `PLAY ME.bat`

O `PLAY ME.bat` faz tudo sozinho, sem perguntas:

1. localiza o Python da maquina e ativa o Anaconda (corrige o erro de SSL do pip);
2. verifica as bibliotecas e **so instala se faltar alguma** — em maquinas
   onde o `Scrip_carga_banco` ja roda, nada precisa ser instalado (pandas,
   PyYAML e openpyxl vem com o Anaconda; o driver Oracle ja esta presente);
3. na primeira execucao, cria o `.env` a partir do modelo e abre no Bloco de
   Notas para voce conferir os caminhos;
4. executa direto as duas etapas: **baixa os arquivos do Cognos e grava no
   DWH** (os Excel ficam na pasta `downloads/` do att_cognos_pbi; nada e
   copiado para a pasta de rede).

### Jeito manual

#### 1. Instalar dependencias

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

> O driver `python-oracledb` funciona em modo *thin* (nao precisa do Oracle
> Client instalado). Se a maquina ja tiver o `cx_Oracle`, ele tambem e aceito.

#### 2. Configurar

Copie `.env.example` para `.env` e preencha:

- `ATT_COGNOS_DIR` — pasta onde o `att_cognos_pbi` esta clonado;
- `DSN_ORACLE` — DSN/TNS do DWH (ex.: `P00DW1`);
- `SCHEMA_DESTINO` — schema onde as tabelas `BI_FT_*` serao gravadas (ex.: `U93314735`);
- `ARQUIVO_CREDENCIAIS` — planilha `DB_acess.xlsx` com as colunas
  `user_dw2`/`pass_dw2` (a mesma usada pelos outros scripts de carga).

As 6 exportacoes ja estao cadastradas em `config/fontes.yaml` com os mesmos
nomes do `config.json` do `att_cognos_pbi`; ajuste apenas os nomes das tabelas
se quiser outros.

#### 3. Executar

```powershell
# Fluxo completo: baixa do Planning Analytics e grava no banco
python -m src.main

# Apenas uma fonte
python -m src.main --fonte "Receitas (IRAT.950)"

# So gravar no banco arquivos ja baixados (sem abrir o navegador)
python -m src.main --sem-baixar

# Baixar sem copiar para a pasta de rede (teste)
python -m src.main --sem-mover
```

O download continua se comportando exatamente como no `att_cognos_pbi`
(mesmo painel de status, backup na rede etc.); a novidade e a gravacao das
tabelas no banco ao final.

### Agendar (opcional)

No Agendador de Tarefas do Windows, aponte para:

```
C:\caminho\do\carga_cognos_db\.venv\Scripts\python.exe -m src.main
```

com "Iniciar em" = pasta do projeto.

## Detalhes da carga

- **Cada extracao vira uma tabela no DWH** (mapeamento no `config/fontes.yaml`):

| Extracao | Tabela |
|---|---|
| Receitas (IRAT.950) | `BI_FT_IRAT950_RECEITA` |
| Fisicos (FIS.900) | `BI_FT_FIS900_FISICO` |
| Custos (IRAT.950 Custo) | `BI_FT_IRAT950_CUSTO` |
| Abertura da Receita / Waterfall (REV.900) | `BI_FT_REV900_RECEITA_ABERTURA` |
| Pre-Pago Parte 1 (CTS.100) | `BI_FT_CTS100_PREPAGO` |
| Pre-Pago Parte 2 (REV.420) | `BI_FT_REV420_PREPAGO` |

- Cada tabela recebe duas colunas de auditoria: `DT_CARGA` (data/hora da
  carga) e `ARQUIVO_ORIGEM` (nome do Excel de origem).
- A gravacao segue o padrao do `Scrip_carga_banco` ja validado em producao:
  - cria a tabela de destino caso ainda nao exista (tipos inferidos dos dados);
  - `DELETE` + `INSERT` em lotes de 10.000 linhas com bind variables,
    na mesma transacao;
  - o commit acontece somente apos a reconciliacao (contagem das linhas
    gravadas bater com o esperado);
  - retentativa automatica se a conexao de gravacao cair no meio da carga;
  - `DBMS_STATS.GATHER_TABLE_STATS` ao final (sem falhar a carga se nao der).
- Os nomes das colunas sao normalizados para identificadores Oracle
  (MAIUSCULAS, sem acento, `_` no lugar de simbolos, ate 30 caracteres).
- Linhas e colunas totalmente vazias do Excel sao descartadas.
- Se o Excel exportado tiver linhas de titulo antes do cabecalho, ajuste
  `linhas_pular` na fonte correspondente do `fontes.yaml`.
- Modos de carga por fonte: `substituir` (DELETE + INSERT, padrao), `recriar`
  (DROP + CREATE) e `anexar` (INSERT acumulando historico).
