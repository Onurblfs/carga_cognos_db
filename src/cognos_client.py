"""Cliente para autenticar no IBM Cognos Analytics e baixar relatorios.

Fluxo:
  1. login()            -> abre sessao via API REST (/api/v1/session)
  2. baixar_relatorio() -> executa o relatorio pela URL de "run" e
                           retorna o conteudo (CSV ou Excel) em bytes

Se a sua automacao do repositorio att_cognos_pbi ja faz o download de
outra forma (ex.: Selenium ou outra URL), basta substituir esta classe:
o restante do fluxo so precisa de um arquivo baixado por fonte.
"""

import logging
import time

import requests

logger = logging.getLogger(__name__)

# Mapeia o formato do fontes.yaml para o parametro do Cognos e a extensao
FORMATOS = {
    "CSV": ("CSV", ".csv"),
    "SPREADSHEETML": ("spreadsheetML", ".xlsx"),  # Excel
    "XLSX": ("spreadsheetML", ".xlsx"),
}


class CognosClient:
    def __init__(self, url_base: str, namespace: str, usuario: str, senha: str):
        self.url_base = url_base.rstrip("/")
        self.namespace = namespace
        self.usuario = usuario
        self.senha = senha
        self.sessao = requests.Session()

    # ------------------------------------------------------------------
    # Autenticacao
    # ------------------------------------------------------------------
    def login(self) -> None:
        """Abre a sessao no Cognos via API REST (gera o cookie CAM passport)."""
        url = f"{self.url_base}/api/v1/session"
        payload = {
            "parameters": [
                {"name": "CAMNamespace", "value": self.namespace},
                {"name": "CAMUsername", "value": self.usuario},
                {"name": "CAMPassword", "value": self.senha},
            ]
        }
        resposta = self.sessao.put(url, json=payload, timeout=60)
        resposta.raise_for_status()

        # O Cognos exige o token XSRF nas chamadas seguintes
        xsrf = self.sessao.cookies.get("XSRF-TOKEN")
        if xsrf:
            self.sessao.headers["X-XSRF-TOKEN"] = xsrf

        logger.info("Login no Cognos realizado com sucesso (usuario=%s).", self.usuario)

    def logout(self) -> None:
        try:
            self.sessao.delete(f"{self.url_base}/api/v1/session", timeout=30)
        except requests.RequestException:
            pass

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------
    def baixar_relatorio(
        self,
        store_id: str,
        formato: str = "CSV",
        parametros: dict | None = None,
        tentativas: int = 3,
    ) -> bytes:
        """Executa o relatorio e retorna o conteudo do arquivo em bytes.

        Usa a interface de execucao por URL (cognosViewer), que devolve o
        arquivo pronto no formato pedido.
        """
        formato_chave = formato.strip().upper()
        if formato_chave not in FORMATOS:
            raise ValueError(
                f"Formato '{formato}' nao suportado. Use um de: {sorted(FORMATOS)}"
            )
        formato_cognos, _ = FORMATOS[formato_chave]

        url = f"{self.url_base}/bi/v1/disp"
        params = {
            "b_action": "cognosViewer",
            "ui.action": "run",
            "ui.object": f'storeID("{store_id}")',
            "run.outputFormat": formato_cognos,
            "run.prompt": "false",
        }
        # Prompts/parametros do relatorio (p_nome=valor)
        for chave, valor in (parametros or {}).items():
            params[chave] = valor

        ultimo_erro: Exception | None = None
        for tentativa in range(1, tentativas + 1):
            try:
                resposta = self.sessao.get(url, params=params, timeout=600)
                resposta.raise_for_status()

                # Se voltou HTML, normalmente e tela de erro/prompt do Cognos
                content_type = resposta.headers.get("Content-Type", "")
                if "text/html" in content_type and formato_chave == "CSV":
                    raise RuntimeError(
                        "O Cognos retornou HTML em vez do arquivo. Verifique o "
                        "store_id, permissoes do usuario e se o relatorio possui "
                        "prompts obrigatorios (informe-os em 'parametros')."
                    )
                return resposta.content
            except (requests.RequestException, RuntimeError) as erro:
                ultimo_erro = erro
                logger.warning(
                    "Falha ao baixar relatorio %s (tentativa %d/%d): %s",
                    store_id, tentativa, tentativas, erro,
                )
                time.sleep(5 * tentativa)

        raise RuntimeError(
            f"Nao foi possivel baixar o relatorio {store_id} apos "
            f"{tentativas} tentativas."
        ) from ultimo_erro

    @staticmethod
    def extensao_do_formato(formato: str) -> str:
        return FORMATOS[formato.strip().upper()][1]

    # Suporte a "with CognosClient(...) as cognos:"
    def __enter__(self) -> "CognosClient":
        self.login()
        return self

    def __exit__(self, *args) -> None:
        self.logout()
