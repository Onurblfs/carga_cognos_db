"""Integracao com a automacao existente do repositorio att_cognos_pbi.

O att_cognos_pbi (Selenium + Edge) baixa as exportacoes do IBM Planning
Analytics para a pasta downloads/ e depois copia cada arquivo para a pasta
de rede configurada no config.json dele.

Este modulo:
  - le o config.json do att_cognos_pbi para descobrir os arquivos gerados;
  - executa o baixar_cognos.py como subprocesso (etapa de download);
  - localiza o Excel de cada exportacao (em downloads/ ou na pasta de rede).
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

EXTENSOES_VALIDAS = {".xlsx", ".xls", ".csv"}


def carregar_config_att(pasta_att: Path) -> dict:
    caminho = pasta_att / "config.json"
    if not caminho.exists():
        raise SystemExit(
            f"config.json da automacao nao encontrado em {caminho}. "
            "Confira a variavel ATT_COGNOS_DIR no .env."
        )
    with open(caminho, encoding="utf-8") as arq:
        return json.load(arq)


def buscar_job(config_att: dict, nome: str) -> dict:
    """Encontra a exportacao do config.json do att_cognos_pbi pelo nome."""
    for job in config_att.get("exportacoes", []):
        if job.get("nome") == nome:
            return job
    nomes = [j.get("nome") for j in config_att.get("exportacoes", [])]
    raise SystemExit(
        f"Exportacao '{nome}' nao existe no config.json do att_cognos_pbi. "
        f"Nomes disponiveis: {nomes}"
    )


def nome_arquivo_do_job(job: dict) -> str:
    """Replica a regra de nome do baixar_cognos.py (nome_arquivo_final)."""
    configurado = job.get("nome_arquivo_destino")
    if configurado:
        return configurado
    base = (job.get("nome_busca") or job.get("nome", "")).strip()
    if Path(base).suffix.lower() in EXTENSOES_VALIDAS:
        return base
    return f"{base}.xlsx"


def executar_download(
    pasta_att: Path,
    somente: list[str] | None = None,
    sem_mover: bool = False,
) -> None:
    """Roda o baixar_cognos.py do att_cognos_pbi como subprocesso."""
    script = pasta_att / "baixar_cognos.py"
    if not script.exists():
        raise SystemExit(f"baixar_cognos.py nao encontrado em {pasta_att}.")

    comando = [sys.executable, str(script)]
    if somente:
        comando += ["--somente", ",".join(somente)]
    if sem_mover:
        comando.append("--sem-mover")

    logger.info("Executando download do Planning Analytics: %s", " ".join(comando))
    resultado = subprocess.run(comando, cwd=pasta_att)
    if resultado.returncode != 0:
        # O baixar_cognos.py retorna 1 quando alguma exportacao falha,
        # mas as demais podem ter baixado; seguimos e carregamos o que houver.
        logger.warning(
            "baixar_cognos.py terminou com erro (codigo %d). "
            "Tentando carregar os arquivos que foram baixados.",
            resultado.returncode,
        )


def localizar_arquivo(pasta_att: Path, config_att: dict, job: dict) -> Path:
    """Localiza o Excel de uma exportacao.

    Procura na pasta downloads/ do att_cognos_pbi e na pasta de rede de
    destino; se existir nos dois lugares, usa o mais recente.
    """
    nome_arquivo = nome_arquivo_do_job(job)
    candidatos = []

    pasta_downloads = pasta_att / config_att.get("pasta_downloads", "downloads")
    local = pasta_downloads / nome_arquivo
    if local.exists():
        candidatos.append(local)

    pasta_destino = job.get("pasta_destino")
    if pasta_destino:
        rede = Path(pasta_destino) / nome_arquivo
        try:
            if rede.exists():
                candidatos.append(rede)
        except OSError:
            logger.warning("Pasta de rede inacessivel: %s", pasta_destino)

    if not candidatos:
        raise FileNotFoundError(
            f"Arquivo '{nome_arquivo}' nao encontrado nem em {pasta_downloads} "
            f"nem em {pasta_destino}. Execute o download primeiro."
        )

    arquivo = max(candidatos, key=lambda p: p.stat().st_mtime)
    logger.info("Arquivo localizado: %s", arquivo)
    return arquivo
