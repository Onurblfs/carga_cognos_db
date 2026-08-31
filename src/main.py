"""Orquestrador do fluxo: baixa as fontes do Cognos e grava no banco.

Uso:
    python -m src.main                     # processa todas as fontes
    python -m src.main --fonte nome_fonte  # processa apenas uma fonte
"""

import argparse
import io
import logging
import sys
from datetime import datetime

import pandas as pd

from src.cognos_client import CognosClient
from src.config import Fonte, carregar_config
from src.db_loader import carregar_dataframe, criar_engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def ler_arquivo_para_dataframe(conteudo: bytes, formato: str) -> pd.DataFrame:
    """Converte os bytes baixados do Cognos em DataFrame."""
    if formato.strip().upper() == "CSV":
        # O Cognos costuma exportar CSV em UTF-16 com tabulacao;
        # tentamos as combinacoes mais comuns.
        for codificacao, separador in (
            ("utf-16", "\t"),
            ("utf-8-sig", ","),
            ("utf-8-sig", ";"),
            ("latin-1", ";"),
        ):
            try:
                df = pd.read_csv(
                    io.BytesIO(conteudo), encoding=codificacao, sep=separador
                )
                if len(df.columns) > 1 or len(df) > 0:
                    return df
            except (UnicodeError, pd.errors.ParserError):
                continue
        raise RuntimeError("Nao foi possivel interpretar o CSV baixado do Cognos.")
    return pd.read_excel(io.BytesIO(conteudo))


def processar_fonte(fonte: Fonte, cognos: CognosClient, engine, config) -> int:
    """Baixa uma fonte do Cognos, salva copia local e grava no banco."""
    logger.info("=== Fonte: %s ===", fonte.nome)

    conteudo = cognos.baixar_relatorio(
        store_id=fonte.store_id,
        formato=fonte.formato,
        parametros=fonte.parametros,
    )

    # Copia local para conferencia/auditoria
    extensao = CognosClient.extensao_do_formato(fonte.formato)
    carimbo = datetime.now().strftime("%Y%m%d_%H%M%S")
    caminho_arquivo = config.pasta_downloads / f"{fonte.nome}_{carimbo}{extensao}"
    caminho_arquivo.write_bytes(conteudo)
    logger.info("Arquivo salvo em %s", caminho_arquivo)

    df = ler_arquivo_para_dataframe(conteudo, fonte.formato)
    logger.info("Linhas lidas: %d | Colunas: %d", len(df), len(df.columns))

    linhas = carregar_dataframe(
        engine=engine,
        df=df,
        tabela=fonte.tabela,
        schema=fonte.schema or config.db_schema,
        modo=fonte.modo_carga,
    )
    return linhas


def main() -> int:
    parser = argparse.ArgumentParser(description="Carga Cognos -> Banco de dados")
    parser.add_argument("--fonte", help="Processa apenas a fonte com este nome")
    parser.add_argument(
        "--config", default=None, help="Caminho alternativo do fontes.yaml"
    )
    args = parser.parse_args()

    config = carregar_config(args.config)

    fontes = config.fontes
    if args.fonte:
        fontes = [f for f in fontes if f.nome == args.fonte]
        if not fontes:
            logger.error("Fonte '%s' nao encontrada no fontes.yaml.", args.fonte)
            return 1

    engine = criar_engine(config.db_connection_string)

    sucesso, falhas = 0, []
    with CognosClient(
        config.cognos_url,
        config.cognos_namespace,
        config.cognos_usuario,
        config.cognos_senha,
    ) as cognos:
        for fonte in fontes:
            try:
                processar_fonte(fonte, cognos, engine, config)
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
