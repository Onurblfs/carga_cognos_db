# carga_cognos_db

Projeto **autossuficiente**: baixa as bases do Cognos (IBM Planning Analytics)
e grava no DWH Oracle. Nao depende de nenhum outro repositorio.

```
PLAY ME.bat
  1. Login no Planning Analytics (Selenium + Edge)
  2. Exporta cada view para Excel (pasta downloads\ deste projeto)
  3. Le o Excel e grava na tabela BI_FT_* correspondente
```

## Estrutura

```
carga_cognos_db/
├── PLAY ME.bat            # duplo clique: verifica bibliotecas e roda o fluxo
├── baixar_cognos.py       # automacao Selenium do download
├── painel_status.py       # painel de acompanhamento das exportacoes
├── painel.ps1
├── config.json            # as 6 exportacoes do Cognos (store/view/arquivo)
├── config/
│   └── fontes.yaml        # exportacao -> tabela BI_FT_* do DWH
├── src/
│   ├── att_cognos.py      # chama o download local e localiza os Excel
│   ├── config.py          # leitura do .env e do fontes.yaml
│   ├── db_loader.py       # gravacao no DWH Oracle
│   └── main.py            # orquestrador (download + carga)
├── .env.example           # modelo das variaveis de ambiente
└── requirements.txt
```

## Como usar

### Jeito facil: duplo clique no `PLAY ME.bat`

O `PLAY ME.bat` faz tudo sozinho, sem perguntas:

1. localiza o Python da maquina e ativa o Anaconda;
2. verifica as bibliotecas e **so instala se faltar alguma**;
3. na primeira execucao, cria o `.env` a partir do modelo e abre no Bloco de
   Notas para voce conferir DSN, schema e o caminho do `DB_acess.xlsx`;
4. executa direto as duas etapas: **baixa os arquivos do Cognos e grava no DWH**.
   Os Excel ficam na pasta `downloads/` deste projeto.

### Jeito manual

```powershell
python -m src.main                                  # baixa e grava
python -m src.main --fonte "Receitas (IRAT.950)"    # apenas uma fonte
python -m src.main --sem-baixar                     # so grava Excel ja baixados
```

O `.env` precisa de:

- `DSN_ORACLE` — DSN/TNS do DWH (ex.: `P00DW1`);
- `SCHEMA_DESTINO` — schema das tabelas `BI_FT_*` (ex.: `U93314735`);
- `ARQUIVO_CREDENCIAIS` — planilha `DB_acess.xlsx` com `user_dw2`/`pass_dw2`.

O login do Cognos usa o arquivo apontado em `config.json`
(`arquivo_credenciais`), o mesmo da automacao original.

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

- Cada tabela recebe duas colunas de auditoria: `DT_CARGA` e `ARQUIVO_ORIGEM`.
- A gravacao segue o padrao do `Scrip_carga_banco`: cria a tabela se nao
  existir, `DELETE` + `INSERT` em lotes de 10.000 com bind variables, commit
  so apos reconciliacao, retentativa em queda de conexao e `DBMS_STATS` ao final.
- Nomes de colunas normalizados para identificadores Oracle (MAIUSCULAS, sem
  acento, ate 30 caracteres).
- Se o Excel tiver linhas de titulo antes do cabecalho, ajuste `linhas_pular`
  na fonte correspondente do `fontes.yaml`.
