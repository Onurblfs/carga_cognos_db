"""Carrega as configuracoes do .env e do config/fontes.yaml."""

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

RAIZ_PROJETO = Path(__file__).resolve().parent.parent

load_dotenv(RAIZ_PROJETO / ".env")


@dataclass
class Fonte:
    """Uma fonte de dados do Cognos e sua tabela de destino."""

    nome: str
    store_id: str
    tabela: str
    formato: str = "CSV"
    schema: str | None = None
    modo_carga: str = "substituir"
    parametros: dict = field(default_factory=dict)


@dataclass
class Config:
    cognos_url: str
    cognos_namespace: str
    cognos_usuario: str
    cognos_senha: str
    db_connection_string: str
    db_schema: str
    pasta_downloads: Path
    fontes: list[Fonte]


def _obrigatoria(nome_var: str) -> str:
    valor = os.getenv(nome_var, "").strip()
    if not valor:
        raise SystemExit(
            f"Variavel de ambiente obrigatoria nao definida: {nome_var}. "
            "Copie o .env.example para .env e preencha os valores."
        )
    return valor


def carregar_config(caminho_fontes: str | Path | None = None) -> Config:
    caminho_fontes = Path(caminho_fontes or RAIZ_PROJETO / "config" / "fontes.yaml")

    with open(caminho_fontes, encoding="utf-8") as arq:
        dados = yaml.safe_load(arq) or {}

    fontes = [Fonte(**item) for item in dados.get("fontes", [])]
    if not fontes:
        raise SystemExit(f"Nenhuma fonte cadastrada em {caminho_fontes}.")

    pasta_downloads = RAIZ_PROJETO / os.getenv("PASTA_DOWNLOADS", "downloads")
    pasta_downloads.mkdir(parents=True, exist_ok=True)

    return Config(
        cognos_url=_obrigatoria("COGNOS_URL").rstrip("/"),
        cognos_namespace=_obrigatoria("COGNOS_NAMESPACE"),
        cognos_usuario=_obrigatoria("COGNOS_USUARIO"),
        cognos_senha=_obrigatoria("COGNOS_SENHA"),
        db_connection_string=_obrigatoria("DB_CONNECTION_STRING"),
        db_schema=os.getenv("DB_SCHEMA", "dbo"),
        pasta_downloads=pasta_downloads,
        fontes=fontes,
    )
