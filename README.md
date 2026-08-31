# carga_cognos_db

Fluxo de dados que **baixa as bases do Cognos (IBM Planning Analytics) e grava em banco de dados**.

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
├── config/
│   └── fontes.yaml        # exportacao do att_cognos_pbi -> tabela do banco
├── src/
│   ├── att_cognos.py      # integra com o att_cognos_pbi (roda o download, acha os arquivos)
│   ├── config.py          # leitura do .env e do fontes.yaml
│   ├── db_loader.py       # gravacao no banco (pandas + SQLAlchemy)
│   └── main.py            # orquestrador do fluxo
├── .env.example           # modelo das variaveis de ambiente
└── requirements.txt
```

## Como usar

### 1. Instalar dependencias

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

> Para SQL Server e necessario o **ODBC Driver 17 (ou 18) for SQL Server** na maquina.

### 2. Configurar

Copie `.env.example` para `.env` e preencha:

- `ATT_COGNOS_DIR` — pasta onde o `att_cognos_pbi` esta clonado;
- `DB_CONNECTION_STRING` — string de conexao do banco de destino (exemplos no arquivo).

As 6 exportacoes ja estao cadastradas em `config/fontes.yaml` com os mesmos
nomes do `config.json` do `att_cognos_pbi`; ajuste apenas os nomes das tabelas
se quiser outros.

### 3. Executar

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

### 4. Agendar (opcional)

No Agendador de Tarefas do Windows, aponte para:

```
C:\caminho\do\carga_cognos_db\.venv\Scripts\python.exe -m src.main
```

com "Iniciar em" = pasta do projeto.

## Detalhes da carga

- **Cada extracao vira uma tabela no DWH** (mapeamento no `config/fontes.yaml`):

| Extracao | Tabela |
|---|---|
| Receitas (IRAT.950) | `tb_irat950_receita` |
| Fisicos (FIS.900) | `tb_fis900_fisico` |
| Custos (IRAT.950 Custo) | `tb_irat950_custo` |
| Abertura da Receita / Waterfall (REV.900) | `tb_rev900_receita_abertura` |
| Pre-Pago Parte 1 (CTS.100) | `tb_cts100_prepago` |
| Pre-Pago Parte 2 (REV.420) | `tb_rev420_prepago` |

- Cada tabela recebe duas colunas de auditoria: `dt_carga` (data/hora da
  carga) e `arquivo_origem` (nome do Excel de origem).
- Os nomes das colunas sao normalizados (minusculas, sem acento, `_` no lugar
  de espacos) para ficarem amigaveis ao banco.
- Linhas e colunas totalmente vazias do Excel sao descartadas.
- Se o Excel exportado tiver linhas de titulo antes do cabecalho, ajuste
  `linhas_pular` na fonte correspondente do `fontes.yaml`.
- Modos de carga por fonte: `substituir` (TRUNCATE + INSERT), `recriar`
  (DROP + CREATE) e `anexar` (INSERT acumulando historico).
- Em SQL Server a gravacao usa `fast_executemany` (insercao em lote rapida).
