"""Gravacao dos dados no DWH Oracle.

Segue o padrao do script de carga ja validado em producao (Scrip_carga_banco):
- driver cx_Oracle ou python-oracledb;
- credenciais lidas da planilha DB_acess.xlsx (colunas user_dw2/pass_dw2);
- cria a tabela de destino caso ainda nao exista;
- DELETE + INSERT em lotes com bind variables, na mesma transacao;
- commit somente apos a reconciliacao (contagem das linhas gravadas);
- retentativa quando a conexao de gravacao cai no meio da carga;
- coleta de estatisticas (DBMS_STATS) ao final, sem falhar a carga.
"""

from __future__ import annotations

import logging
import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd

try:
    import cx_Oracle as oracle

    DRIVER_ORACLE = "cx_Oracle"
except ImportError:
    try:
        import oracledb as oracle

        DRIVER_ORACLE = "python-oracledb"
    except ImportError as exc:
        raise RuntimeError(
            "Instale cx_Oracle ou python-oracledb antes de executar a carga."
        ) from exc

logger = logging.getLogger(__name__)

MODOS_VALIDOS = {"substituir", "recriar", "anexar"}
TAMANHO_LOTE = 10_000
TENTATIVAS_GRAVACAO = 2
COLETAR_ESTATISTICAS_AO_FINAL = True


# =============================================================================
# Validacao de identificadores (mesmas regras do Scrip_carga_banco)
# =============================================================================

def validar_identificador(valor: str, nome_configuracao: str) -> str:
    """Valida nomes usados diretamente em DDL/DML."""
    valor = valor.strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9_$#]{0,29}", valor):
        raise ValueError(f"{nome_configuracao} inválido: {valor!r}")
    return valor


def validar_schema(valor: str, nome_configuracao: str) -> str:
    """Aceita schema Oracle convencional ou composto somente por números."""
    valor = valor.strip().upper()
    if re.fullmatch(r"[A-Z][A-Z0-9_$#]{0,29}", valor):
        return valor
    if re.fullmatch(r"[0-9]{1,30}", valor):
        return valor
    raise ValueError(f"{nome_configuracao} inválido: {valor!r}")


def schema_em_sql(schema: str) -> str:
    """Coloca aspas em schemas numéricos, como 93314735."""
    schema = validar_schema(schema, "schema")
    return f'"{schema}"' if schema.isdigit() else schema


def nome_qualificado(schema: str | None, tabela: str) -> str:
    tabela = validar_identificador(tabela, "tabela")
    if schema is None:
        return tabela
    return f"{schema_em_sql(schema)}.{tabela}"


# =============================================================================
# Credenciais (planilha DB_acess.xlsx, como no Scrip_carga_banco)
# =============================================================================

def ler_credenciais(
    arquivo: Path,
    aba: str,
    coluna_usuario: str,
    coluna_senha: str,
) -> tuple[str, str]:
    if not arquivo.exists():
        raise FileNotFoundError(f"Arquivo de credenciais não encontrado: {arquivo}")

    credenciais = pd.read_excel(arquivo, sheet_name=aba, dtype=str)
    credenciais.columns = [str(c).strip() for c in credenciais.columns]

    faltantes = {coluna_usuario, coluna_senha}.difference(credenciais.columns)
    if faltantes:
        raise KeyError(
            "Colunas ausentes no arquivo de credenciais: "
            + ", ".join(sorted(faltantes))
        )

    validas = credenciais.dropna(subset=[coluna_usuario, coluna_senha])
    if validas.empty:
        raise ValueError("Não há uma linha de credenciais preenchida na planilha.")

    linha = validas.iloc[0]
    usuario = str(linha[coluna_usuario]).strip()
    senha = str(linha[coluna_senha]).strip()
    if not usuario or not senha:
        raise ValueError("Há usuário ou senha vazios na planilha de credenciais.")
    return usuario, senha


# =============================================================================
# Preparacao do DataFrame
# =============================================================================

def normalizar_colunas(df: pd.DataFrame) -> pd.DataFrame:
    """Padroniza os nomes das colunas para identificadores Oracle (maiusculas,
    sem acento, '_' no lugar de simbolos, no maximo 30 caracteres)."""
    df = df.copy()
    novas, usadas = [], set()
    for coluna in df.columns:
        nome = unicodedata.normalize("NFKD", str(coluna).strip())
        nome = nome.encode("ascii", errors="ignore").decode("ascii")
        nome = re.sub(r"[^\w]+", "_", nome).strip("_").upper() or "COLUNA"
        if not nome[0].isalpha():
            nome = f"C_{nome}"
        nome = nome[:30]
        base = nome
        contador = 2
        while nome in usadas:
            sufixo = f"_{contador}"
            nome = base[: 30 - len(sufixo)] + sufixo
            contador += 1
        usadas.add(nome)
        novas.append(nome)
    df.columns = novas
    return df


def inferir_ddl_colunas(df: pd.DataFrame) -> str:
    """Monta o bloco de colunas do CREATE TABLE a partir dos tipos do DataFrame."""
    definicoes = []
    for coluna in df.columns:
        serie = df[coluna]
        if pd.api.types.is_datetime64_any_dtype(serie):
            tipo = "DATE"
        elif pd.api.types.is_numeric_dtype(serie):
            tipo = "NUMBER"
        else:
            maior = int(serie.dropna().astype(str).str.len().max() or 0)
            # Arredonda para cima em multiplos de 50, limite do VARCHAR2
            tamanho = min(4000, max(50, -(-maior // 50) * 50))
            tipo = f"VARCHAR2({tamanho} CHAR)"
        definicoes.append(f"    {coluna} {tipo}")
    return "(\n" + ",\n".join(definicoes) + "\n)"


def preparar_linhas(df: pd.DataFrame) -> list[tuple]:
    """Converte o DataFrame em tuplas com None no lugar de NaN, prontas
    para o executemany com bind variables."""
    df = df.copy()
    for coluna in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[coluna]):
            df[coluna] = df[coluna].dt.to_pydatetime()
    df = df.astype(object).where(pd.notna(df), None)
    return list(df.itertuples(index=False, name=None))


def montar_sql_insert(tabela_sql: str, colunas: list[str]) -> str:
    nomes = ", ".join(colunas)
    binds = ", ".join(f":{i}" for i in range(1, len(colunas) + 1))
    return f"INSERT INTO {tabela_sql} ({nomes}) VALUES ({binds})"


def erro_de_conexao(exc: Exception) -> bool:
    """Identifica erros Oracle/DPI que permitem repetir a gravação."""
    mensagem = str(exc).upper()
    marcadores = (
        "DPI-1010",
        "DPI-1080",
        "ORA-01012",
        "ORA-03113",
        "ORA-03114",
        "ORA-03135",
        "ORA-12537",
        "ORA-12547",
        "ORA-12570",
        "ORA-12571",
    )
    return any(marcador in mensagem for marcador in marcadores)


def _rollback_silencioso(conexao) -> None:
    if conexao is None:
        return
    try:
        conexao.rollback()
    except Exception:
        pass


def _fechar_silencioso(recurso) -> None:
    if recurso is None:
        return
    try:
        recurso.close()
    except Exception:
        pass


# =============================================================================
# Carga
# =============================================================================

class CargaOracle:
    """Grava DataFrames no DWH Oracle no padrao do Scrip_carga_banco."""

    def __init__(self, dsn: str, usuario: str, senha: str):
        self.dsn = dsn
        self.usuario = usuario
        self.senha = senha

    def _conectar(self):
        return oracle.connect(user=self.usuario, password=self.senha, dsn=self.dsn)

    # ------------------------------------------------------------------
    def carregar(
        self,
        df: pd.DataFrame,
        tabela: str,
        schema: str | None = None,
        modo: str = "substituir",
    ) -> int:
        modo = modo.strip().lower()
        if modo not in MODOS_VALIDOS:
            raise ValueError(
                f"Modo de carga inválido: {modo!r}. Use um de: {sorted(MODOS_VALIDOS)}"
            )

        df = normalizar_colunas(df)
        tabela = validar_identificador(tabela, "tabela")
        schema = validar_schema(schema, "schema") if schema else None
        tabela_sql = nome_qualificado(schema, tabela)

        linhas = preparar_linhas(df)
        lotes = [
            linhas[i : i + TAMANHO_LOTE] for i in range(0, len(linhas), TAMANHO_LOTE)
        ]
        sql_insert = montar_sql_insert(tabela_sql, list(df.columns))

        owner = self._preparar_estrutura(df, tabela_sql, tabela, schema, modo)

        for tentativa in range(1, TENTATIVAS_GRAVACAO + 1):
            conexao = None
            cursor = None
            try:
                conexao = self._conectar()
                cursor = conexao.cursor()

                removidos = 0
                if modo in ("substituir", "recriar"):
                    cursor.execute(f"DELETE FROM {tabela_sql}")
                    removidos = max(cursor.rowcount, 0)
                    antes = 0
                else:
                    cursor.execute(f"SELECT COUNT(*) FROM {tabela_sql}")
                    antes = int(cursor.fetchone()[0])

                inseridos = 0
                for numero_lote, lote in enumerate(lotes, start=1):
                    cursor.executemany(sql_insert, lote)
                    inseridos += len(lote)
                    logger.info(
                        "%s | lote gravado=%d | transferidos=%s",
                        tabela_sql, numero_lote, f"{inseridos:,}",
                    )

                cursor.execute(f"SELECT COUNT(*) FROM {tabela_sql}")
                total = int(cursor.fetchone()[0])
                if total != antes + inseridos:
                    raise RuntimeError(
                        f"Reconciliação de linhas falhou em {tabela_sql}: "
                        f"esperado={antes + inseridos}, gravadas={total}."
                    )

                # DELETE e INSERT são confirmados juntos, só após reconciliar.
                conexao.commit()
                logger.info(
                    "%s | removidos=%s | inseridos=%s | total na tabela=%s",
                    tabela_sql, f"{removidos:,}", f"{inseridos:,}", f"{total:,}",
                )
                self._coletar_estatisticas(cursor, owner, tabela)
                return inseridos

            except Exception as exc:
                _rollback_silencioso(conexao)
                pode_repetir = (
                    tentativa < TENTATIVAS_GRAVACAO and erro_de_conexao(exc)
                )
                if pode_repetir:
                    logger.warning(
                        "%s | conexão de gravação perdida; nova tentativa %d/%d...",
                        tabela_sql, tentativa + 1, TENTATIVAS_GRAVACAO,
                    )
                else:
                    logger.error(
                        "Falha na carga de %s; transação não confirmada.", tabela_sql
                    )
                    raise
            finally:
                _fechar_silencioso(cursor)
                _fechar_silencioso(conexao)

        raise RuntimeError(f"Carga de {tabela_sql} não concluída.")

    # ------------------------------------------------------------------
    def _preparar_estrutura(
        self,
        df: pd.DataFrame,
        tabela_sql: str,
        tabela: str,
        schema: str | None,
        modo: str,
    ) -> str:
        """Conexão curta apenas para criar/validar a tabela de destino."""
        conexao = None
        cursor = None
        try:
            conexao = self._conectar()
            cursor = conexao.cursor()

            if schema is None:
                cursor.execute("SELECT USER FROM DUAL")
                owner = str(cursor.fetchone()[0]).upper()
            else:
                owner = schema

            existe = self._tabela_existe(cursor, owner, tabela)

            if modo == "recriar" and existe:
                cursor.execute(f"DROP TABLE {tabela_sql}")
                logger.info("Tabela %s descartada (modo=recriar).", tabela_sql)
                existe = False

            if not existe:
                ddl = f"CREATE TABLE {tabela_sql} {inferir_ddl_colunas(df)}"
                cursor.execute(ddl)
                logger.info("Tabela criada: %s", tabela_sql)
            else:
                self._validar_estrutura(cursor, owner, tabela, list(df.columns))

            conexao.commit()
            return owner
        finally:
            _fechar_silencioso(cursor)
            _fechar_silencioso(conexao)

    @staticmethod
    def _tabela_existe(cursor, owner: str, tabela: str) -> bool:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM ALL_TABLES
            WHERE OWNER = :owner
              AND TABLE_NAME = :tabela
            """,
            owner=owner,
            tabela=tabela,
        )
        return int(cursor.fetchone()[0]) > 0

    @staticmethod
    def _validar_estrutura(cursor, owner: str, tabela: str, colunas: list[str]) -> None:
        cursor.execute(
            """
            SELECT COLUMN_NAME
            FROM ALL_TAB_COLUMNS
            WHERE OWNER = :owner
              AND TABLE_NAME = :tabela
            """,
            owner=owner,
            tabela=tabela,
        )
        existentes = {linha[0] for linha in cursor.fetchall()}
        faltantes = set(colunas).difference(existentes)
        if faltantes:
            raise RuntimeError(
                f"A tabela {owner}.{tabela} existe, mas faltam as colunas: "
                + ", ".join(sorted(faltantes))
                + ". Use modo_carga: recriar para recriá-la com a estrutura nova."
            )

    @staticmethod
    def _coletar_estatisticas(cursor, owner: str, tabela: str) -> None:
        if not COLETAR_ESTATISTICAS_AO_FINAL:
            return
        try:
            cursor.execute(
                """
                BEGIN
                    DBMS_STATS.GATHER_TABLE_STATS(
                        ownname       => :owner,
                        tabname       => :tabela,
                        cascade       => TRUE,
                        no_invalidate => FALSE
                    );
                END;
                """,
                owner=owner,
                tabela=tabela,
            )
            logger.info("Estatísticas de %s.%s atualizadas.", owner, tabela)
        except oracle.DatabaseError as exc:
            logger.warning(
                "Não foi possível executar DBMS_STATS (carga concluída). Detalhe: %s",
                exc,
            )
