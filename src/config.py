"""Carrega as configuracoes do .env e do config/fontes.yaml."""

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

RAIZ_PROJETO = Path(__file__).resolve().parent.parent


def _carregar_env(caminho: Path) -> None:
    """Le o arquivo .env sem depender da biblioteca python-dotenv
    (que nao vem com o Anaconda e pode nao instalar em rede restrita)."""
    if not caminho.exists():
        return
    for linha in caminho.read_text(encoding="utf-8-sig").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        chave = chave.strip()
        valor = valor.strip().strip('"').strip("'")
        if chave:
            os.environ.setdefault(chave, valor)


_carregar_env(RAIZ_PROJETO / ".env")


@dataclass
class Fonte:
    """Uma exportacao do Planning Analytics e sua tabela de destino no DWH.

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
    dsn_oracle: str
    schema_destino: str | None
    arquivo_credenciais: Path
    aba_credenciais: str
    coluna_usuario: str
    coluna_senha: str
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
        dsn_oracle=_obrigatoria("DSN_ORACLE"),
        schema_destino=os.getenv("SCHEMA_DESTINO", "").strip() or None,
        arquivo_credenciais=Path(_obrigatoria("ARQUIVO_CREDENCIAIS")),
        aba_credenciais=os.getenv("ABA_CREDENCIAIS", "Plan1").strip() or "Plan1",
        coluna_usuario=os.getenv("COLUNA_USUARIO", "user_dw2").strip() or "user_dw2",
        coluna_senha=os.getenv("COLUNA_SENHA", "pass_dw2").strip() or "pass_dw2",
        fontes=fontes,
    )
