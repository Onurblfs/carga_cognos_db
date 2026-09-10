"""Download das exportacoes do IBM Planning Analytics (Cognos).

Toda a automacao Selenium vive DENTRO deste projeto (baixar_cognos.py,
painel_status.py, config.json). Nao depende de outro repositorio.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

from src.config import RAIZ_PROJETO

logger = logging.getLogger(__name__)

EXTENSOES_VALIDAS = {".xlsx", ".xls", ".csv"}
CONFIG_COGNOS = RAIZ_PROJETO / "config.json"
SCRIPT_DOWNLOAD = RAIZ_PROJETO / "baixar_cognos.py"


def carregar_config_cognos() -> dict:
    if not CONFIG_COGNOS.exists():
        raise SystemExit(
            f"config.json da automacao Cognos nao encontrado em {CONFIG_COGNOS}."
        )
    with open(CONFIG_COGNOS, encoding="utf-8") as arq:
        return json.load(arq)


def buscar_job(config_cognos: dict, nome: str) -> dict:
    """Encontra a exportacao do config.json pelo nome."""
    for job in config_cognos.get("exportacoes", []):
        if job.get("nome") == nome:
            return job
    nomes = [j.get("nome") for j in config_cognos.get("exportacoes", [])]
    raise SystemExit(
        f"Exportacao '{nome}' nao existe no config.json. "
        f"Nomes disponiveis: {nomes}"
    )


def nome_arquivo_do_job(job: dict) -> str:
    """Nome final do Excel gerado (mesma regra do baixar_cognos.py)."""
    configurado = job.get("nome_arquivo_destino")
    if configurado:
        return configurado
    base = (job.get("nome_busca") or job.get("nome", "")).strip()
    if Path(base).suffix.lower() in EXTENSOES_VALIDAS:
        return base
    return f"{base}.xlsx"


def executar_download(
    somente: list[str] | None = None,
    sem_mover: bool = True,
) -> int:
    """Roda o baixar_cognos.py deste proprio projeto. Retorna o codigo de saida."""
    if not SCRIPT_DOWNLOAD.exists():
        raise SystemExit(f"baixar_cognos.py nao encontrado em {RAIZ_PROJETO}.")

    comando = [sys.executable, str(SCRIPT_DOWNLOAD)]
    # So filtra quando o usuario pediu uma fonte especifica. Juntar todos os
    # nomes com virgula quebra no Windows por causa dos parenteses (IRAT.950).
    if somente and len(somente) == 1:
        comando += ["--somente", somente[0]]
    if sem_mover:
        comando.append("--sem-mover")

    logger.info("Executando download do Planning Analytics: %s", " ".join(comando))
    resultado = subprocess.run(comando, cwd=str(RAIZ_PROJETO))
    if resultado.returncode != 0:
        logger.warning(
            "baixar_cognos.py terminou com erro (codigo %d).",
            resultado.returncode,
        )
    return resultado.returncode


def localizar_arquivo(config_cognos: dict, job: dict) -> Path:
    """Localiza o Excel de uma exportacao na pasta downloads/ deste projeto."""
    nome_arquivo = nome_arquivo_do_job(job)
    pasta_downloads = RAIZ_PROJETO / config_cognos.get("pasta_downloads", "downloads")
    local = pasta_downloads / nome_arquivo
    if local.exists():
        logger.info("Arquivo localizado: %s", local)
        return local

    raise FileNotFoundError(
        f"Arquivo '{nome_arquivo}' nao encontrado em {pasta_downloads}. "
        "O download do Cognos precisa ter gerado este arquivo."
    )
