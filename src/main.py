"""Fluxo completo: baixa as bases do Cognos (Planning Analytics) e grava no DWH.

Uso:
    python -m src.main                        # baixa tudo e grava no banco
    python -m src.main --fonte "Receitas (IRAT.950)"   # apenas uma fonte
    python -m src.main --sem-baixar           # so grava arquivos ja baixados
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime

import pandas as pd

from src.att_cognos import (
    buscar_job,
    carregar_config_cognos,
    executar_download,
    localizar_arquivo,
)
from src.config import Fonte, carregar_config
from src.db_loader import DRIVER_ORACLE, CargaOracle, ler_credenciais

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def ler_excel(caminho, fonte: Fonte) -> pd.DataFrame:
    """Le o arquivo exportado do Planning Analytics em DataFrame."""
    if caminho.suffix.lower() == ".csv":
        df = pd.read_csv(caminho, skiprows=fonte.linhas_pular)
    else:
        df = pd.read_excel(
            caminho, sheet_name=fonte.aba, skiprows=fonte.linhas_pular
        )
    # Remove linhas e colunas totalmente vazias (comuns em exportacao de cubo)
    df = df.dropna(how="all").dropna(axis=1, how="all")
    return df


def processar_fonte(fonte: Fonte, config, config_cognos, carga: CargaOracle) -> int:
    logger.info("=== Fonte: %s ===", fonte.nome)

    job = buscar_job(config_cognos, fonte.nome)
    arquivo = localizar_arquivo(config_cognos, job)

    df = ler_excel(arquivo, fonte)
    logger.info("Linhas lidas: %d | Colunas: %d", len(df), len(df.columns))
    if df.empty:
        raise RuntimeError(f"O arquivo {arquivo.name} nao contem dados.")

    # Colunas de auditoria da carga no DWH
    df["DT_CARGA"] = datetime.now()
    df["ARQUIVO_ORIGEM"] = arquivo.name

    return carga.carregar(
        df=df,
        tabela=fonte.tabela,
        schema=fonte.schema or config.schema_destino,
        modo=fonte.modo_carga,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Carga das bases do Cognos/Planning Analytics em banco de dados"
    )
    parser.add_argument("--fonte", help="Processa apenas a fonte com este nome")
    parser.add_argument(
        "--sem-baixar",
        action="store_true",
        help="Nao executa o download; carrega os arquivos ja existentes",
    )
    parser.add_argument(
        "--config", default=None, help="Caminho alternativo do fontes.yaml"
    )
    args = parser.parse_args()

    config = carregar_config(args.config)
    config_cognos = carregar_config_cognos()

    fontes = config.fontes
    if args.fonte:
        fontes = [f for f in fontes if f.nome == args.fonte]
        if not fontes:
            logger.error("Fonte '%s' nao encontrada no fontes.yaml.", args.fonte)
            return 1

    # Valida o cadastro antes de gastar tempo com download
    for fonte in fontes:
        buscar_job(config_cognos, fonte.nome)

    if not args.sem_baixar:
        filtro = [f.nome for f in fontes] if args.fonte else None
        executar_download(somente=filtro, sem_mover=True)

    # Sem Excel, nao adianta abrir o Oracle
    prontas = []
    for fonte in fontes:
        job = buscar_job(config_cognos, fonte.nome)
        try:
            localizar_arquivo(config_cognos, job)
            prontas.append(fonte)
        except FileNotFoundError as exc:
            logger.error("%s", exc)

    if not prontas:
        logger.error(
            "Nenhum Excel encontrado em downloads\\. "
            "A carga no DWH foi abortada."
        )
        return 1

    fontes = prontas

    usuario, senha = ler_credenciais(
        config.arquivo_credenciais,
        config.aba_credenciais,
        config.coluna_usuario,
        config.coluna_senha,
    )
    logger.info("Driver Oracle: %s | DSN: %s | Usuário de gravação: %s",
                DRIVER_ORACLE, config.dsn_oracle, usuario)
    carga = CargaOracle(config.dsn_oracle, usuario, senha)

    sucesso, falhas = 0, []
    for fonte in fontes:
        try:
            processar_fonte(fonte, config, config_cognos, carga)
            sucesso += 1
        except Exception:
            logger.exception("Falha ao processar a fonte '%s'.", fonte.nome)
            falhas.append(fonte.nome)

    logger.info(
        "Fluxo finalizado: %d fonte(s) com sucesso, %d falha(s).",
        sucesso, len(falhas),
    )
    if falhas:
        logger.error("Fontes com falha: %s", ", ".join(falhas))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
