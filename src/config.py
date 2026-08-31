"""Carrega as configuracoes do .env e do config/fontes.yaml."""

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

RAIZ_PROJETO = Path(__file__).resolve().parent.parent

load_dotenv(RAIZ_PROJETO / ".env")


@dataclass
class Fonte:
    """Uma exportacao do Planning Analytics e sua tabela de destino.

    O campo 'nome' deve ser IGUAL ao campo 'nome' da exportacao no
    config.json do att_cognos_pbi (ex.: "Receitas (IRAT.950)").
    """

    nome: str
    tabela: str
    schema: str | None = None
    modo_carga: str = "substituir"
    aba: str | int = 0          # nome ou indice da aba do Excel
    linhas_pular: int = 0       # linhas de cabecalho/contexto a pular


@dataclass
class Config:
    pasta_att: Path
    db_connection_string: str
    db_schema: str | None
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

    pasta_att = Path(_obrigatoria("ATT_COGNOS_DIR"))
    if not pasta_att.exists():
        raise SystemExit(
            f"Pasta da automacao att_cognos_pbi nao encontrada: {pasta_att}. "
            "Ajuste a variavel ATT_COGNOS_DIR no .env."
        )

    return Config(
        pasta_att=pasta_att,
        db_connection_string=_obrigatoria("DB_CONNECTION_STRING"),
        db_schema=os.getenv("DB_SCHEMA", "").strip() or None,
        fontes=fontes,
    )
