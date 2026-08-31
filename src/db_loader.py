"""Grava DataFrames no banco de dados usando SQLAlchemy + pandas.to_sql.

Modos de carga:
  substituir -> TRUNCATE na tabela e INSERT (mantem a estrutura existente)
  recriar    -> DROP + CREATE (estrutura inferida a partir do DataFrame)
  anexar     -> apenas INSERT (acumula os dados)
"""

import logging

import pandas as pd
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

MODOS_VALIDOS = {"substituir", "recriar", "anexar"}


def criar_engine(connection_string: str) -> Engine:
    """Cria a engine de conexao.

    fast_executemany acelera muito o INSERT em SQL Server via pyodbc.
    Para outros bancos (Postgres, Oracle...) o parametro e ignorado.
    """
    kwargs = {}
    if connection_string.startswith("mssql+pyodbc"):
        kwargs["fast_executemany"] = True
    return create_engine(connection_string, **kwargs)


def normalizar_colunas(df: pd.DataFrame) -> pd.DataFrame:
    """Padroniza os nomes das colunas para nomes amigaveis ao banco."""
    df = df.copy()
    df.columns = (
        df.columns.astype(str)
        .str.strip()
        .str.lower()
        .str.normalize("NFKD")
        .str.encode("ascii", errors="ignore")
        .str.decode("ascii")
        .str.replace(r"[^\w]+", "_", regex=True)
        .str.strip("_")
    )
    return df


def carregar_dataframe(
    engine: Engine,
    df: pd.DataFrame,
    tabela: str,
    schema: str | None = None,
    modo: str = "substituir",
    chunksize: int = 5_000,
) -> int:
    """Grava o DataFrame na tabela de destino e retorna o total de linhas."""
    modo = modo.strip().lower()
    if modo not in MODOS_VALIDOS:
        raise ValueError(f"Modo de carga invalido: '{modo}'. Use um de: {sorted(MODOS_VALIDOS)}")

    df = normalizar_colunas(df)
    nome_completo = f"{schema}.{tabela}" if schema else tabela

    if modo == "recriar":
        if_exists = "replace"
    else:
        if_exists = "append"
        if modo == "substituir":
            _truncar_tabela(engine, tabela, schema)

    logger.info(
        "Gravando %d linhas em %s (modo=%s)...", len(df), nome_completo, modo
    )
    df.to_sql(
        name=tabela,
        con=engine,
        schema=schema,
        if_exists=if_exists,
        index=False,
        chunksize=chunksize,
    )
    logger.info("Carga concluida em %s.", nome_completo)
    return len(df)


def _truncar_tabela(engine: Engine, tabela: str, schema: str | None) -> None:
    nome_completo = f"{schema}.{tabela}" if schema else tabela
    if not inspect(engine).has_table(tabela, schema=schema):
        logger.info(
            "Tabela %s ainda nao existe; sera criada automaticamente.",
            nome_completo,
        )
        return

    # SQLite (usado em testes) nao possui TRUNCATE
    comando = (
        f"DELETE FROM {nome_completo}"
        if engine.dialect.name == "sqlite"
        else f"TRUNCATE TABLE {nome_completo}"
    )
    with engine.begin() as conexao:
        conexao.execute(text(comando))
    logger.info("Tabela %s truncada.", nome_completo)
