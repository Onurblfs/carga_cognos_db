# -*- coding: utf-8 -*-
from __future__ import annotations
"""
Automacao de download das bases do IBM Planning Analytics (Cognos)
para atualizacao do Power BI "Orcamento e Forecast Gerencial".

Fluxo (replica o processo manual do documento de atualizacao):
  1. Abre o site do Planning Analytics.
  2. Aguarda o login (manual ou automatico via SSO).
  3. Para cada exportacao do config.json:
       - pesquisa o nome da view na pasta Compartilhado;
       - abre a view de exportacao;
       - exporta para Excel;
       - move o arquivo baixado para a pasta de rede de destino
         (fazendo backup local do arquivo anterior).

Uso:
  python baixar_cognos.py                     -> executa todas as exportacoes
  python baixar_cognos.py --somente IRAT.950  -> executa so as que contem o texto no nome
  python baixar_cognos.py --sem-mover         -> baixa mas nao copia para a rede (teste)
"""

import argparse
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

# Copia local do Selenium (pasta vendor/). A rede da Claro bloqueia o pypi.org,
# entao o projeto nao depende de pip install selenium.
_VENDOR = Path(__file__).resolve().parent / "vendor"
if _VENDOR.is_dir() and str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

from selenium import webdriver
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from painel_status import ESTIMATIVA_PADRAO_SEG, PainelAcompanhamento

BASE_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Seletores da interface do Planning Analytics Workspace (Claro).
# O campo "Pesquisar" so aparece DEPOIS de abrir a pasta Compartilhado
# (sidebar esquerda). Cada entrada e uma lista de alternativas em ordem.
# ---------------------------------------------------------------------------
SELETORES = {
    # Debug Claro: botao id=com.ibm.bi.glass.common.navmenu, aria-label="Início".
    "menu_hamburguer": [
        (By.CSS_SELECTOR, "#com\\.ibm\\.bi\\.glass\\.common\\.navmenu"),
        (By.CSS_SELECTOR, "button[data-id='com.ibm.bi.glass.common.navmenu']"),
        (By.CSS_SELECTOR, "[walkme-data-id='com.ibm.bi.glass.common.navmenu'] button"),
        (By.CSS_SELECTOR, "button.ba-carbon-nav-menu"),
        (By.CSS_SELECTOR, "button[data-tid='buc-OverflowMenu']"),
        (By.XPATH, "//button[@id='com.ibm.bi.glass.common.navmenu']"),
    ],
    "link_compartilhado": [
        (By.XPATH, "//*[self::a or self::button or self::span or self::div][normalize-space(.)='Compartilhado']"),
        (By.XPATH, "//*[contains(@aria-label,'Compartilhado')]"),
        (By.XPATH, "//*[contains(@class,'create-menu-link')][contains(.,'Compartilhado')]"),
        (By.XPATH, "//*[contains(.,'Conteúdo compartilhado') or contains(.,'Conteudo compartilhado')]"),
        (By.XPATH, "//*[contains(.,'Pasta compartilhada') or contains(.,'Arquivos compartilhados')]"),
        (By.XPATH, "//*[self::a or self::button or self::span][normalize-space(.)='Shared']"),
        (By.XPATH, "//*[contains(text(),'Compartilhado') or contains(text(),'Shared')]"),
    ],
    "card_aplicativos": [
        (By.XPATH, "//*[contains(.,'Aplicativos e planos')]"),
        (By.XPATH, "//*[contains(.,'Apps and plans')]"),
    ],
    "aba_favoritos": [
        (By.CSS_SELECTOR, "#tab-favorites"),
        (By.XPATH, "//*[@role='tab' and (normalize-space(.)='Favoritos' or @title='Favoritos')]"),
        (By.XPATH, "//button[normalize-space(.)='Favoritos' or @id='tab-favorites']"),
        (By.XPATH, "//*[@title='Favoritos']"),
    ],
    "aba_recentes": [
        (By.CSS_SELECTOR, "#tab-recents, #tab-recent"),
        (By.XPATH, "//*[@role='tab' and (normalize-space(.)='Recentes' or @title='Recentes')]"),
        (By.XPATH, "//button[normalize-space(.)='Recentes']"),
        (By.XPATH, "//*[@title='Recentes']"),
    ],
    "campo_pesquisa": [
        # Campo da sidebar Compartilhado (screenshot: placeholder "Pesquisar")
        (By.XPATH, "//input[contains(@placeholder,'Pesquisar') or contains(@placeholder,'esquis')]"),
        (By.CSS_SELECTOR, "input[placeholder*='Pesquisar']"),
        (By.CSS_SELECTOR, "input[placeholder*='esquis']"),
        (By.CSS_SELECTOR, "input[placeholder*='Search']"),
        (By.CSS_SELECTOR, "input[type='search']"),
        (By.CSS_SELECTOR, "input[role='searchbox']"),
        (By.XPATH, "//aside//input | //nav//input | //*[contains(@class,'search')]//input"),
    ],
    "home_carregada": [
        (By.XPATH, "//*[contains(.,'Início rápido') or contains(.,'Inicio rapido') or contains(.,'Quick start')]"),
        (By.XPATH, "//*[contains(.,'Meus aplicativos') or contains(.,'My applications')]"),
        (By.XPATH, "//*[contains(.,'IBM Planning Analytics')]"),
        (By.CSS_SELECTOR, "#com\\.ibm\\.bi\\.glass\\.common\\.navmenu"),
    ],
    "campo_usuario": [
        (By.CSS_SELECTOR, "input[name='username']"),
        (By.CSS_SELECTOR, "input#username"),
        (By.CSS_SELECTOR, "input[name='CAMUsername']"),
        (By.CSS_SELECTOR, "input#CAMUsername"),
        (By.CSS_SELECTOR, "input[autocomplete='username']"),
        (By.XPATH, "//input[@type='text' or @type='email'][contains(@name,'ser') or contains(@id,'ser') or contains(@placeholder,'suário') or contains(@placeholder,'ser')]"),
        (By.XPATH, "//label[contains(.,'suário') or contains(.,'User')]/following::input[1]"),
    ],
    "campo_senha": [
        (By.CSS_SELECTOR, "input[type='password']"),
        (By.CSS_SELECTOR, "input[name='password']"),
        (By.CSS_SELECTOR, "input#password"),
        (By.CSS_SELECTOR, "input[name='CAMPassword']"),
        (By.CSS_SELECTOR, "input#CAMPassword"),
    ],
    "botao_login": [
        (By.XPATH, "//button[@type='submit']"),
        (By.XPATH, "//input[@type='submit']"),
        (By.XPATH, "//button[contains(.,'Entrar') or contains(.,'Login') or contains(.,'Sign in') or contains(.,'Log in')]"),
        (By.XPATH, "//input[@value='Entrar' or @value='Login' or @value='Sign in']"),
        (By.CSS_SELECTOR, "button.login, #loginButton, .signInBtn"),
    ],
    # Toolbar PA: data-id=exportAction, aria-label="Exportar" (#common-download).
    # O tooltip visual pode dizer "Exportar para planilha", mas no DOM e so "Exportar".
    "botao_exportar_planilha": [
        (By.CSS_SELECTOR, "button[data-id='exportAction']"),
        (By.CSS_SELECTOR, "button[walkme-data-id='exportAction']"),
        (By.XPATH, "//button[@aria-label='Exportar' or @aria-label='Export']"),
        (By.XPATH, "//*[@aria-label='Exportar para planilha' or @title='Exportar para planilha']"),
        (By.XPATH, "//*[@aria-label='Export to spreadsheet' or @title='Export to spreadsheet']"),
        (By.XPATH, "//button[.//span[contains(@class,'assistive') and (normalize-space(.)='Exportar' or contains(.,'Exportar para planilha'))]]"),
    ],
    "opcao_exportar_planilha": [
        (By.XPATH, "//*[self::button or self::a or self::li or self::div or self::span][normalize-space(.)='Exportar para planilha' or normalize-space(.)='Export to spreadsheet']"),
        (By.XPATH, "//*[contains(@aria-label,'Exportar para planilha') or contains(@title,'Exportar para planilha')]"),
        (By.XPATH, "//*[contains(@aria-label,'Export to spreadsheet') or contains(@title,'Export to spreadsheet')]"),
        (By.XPATH, "//*[@role='menuitem' or @role='option'][contains(.,'planilha') or contains(.,'spreadsheet') or contains(.,'Excel')]"),
    ],
    "toggle_editar": [
        (By.CSS_SELECTOR, "input[id*='editToggleButton']"),
        (By.XPATH, "//input[contains(@id,'editToggleButton')]"),
    ],
    "widget_cubo": [
        (By.XPATH, "//*[contains(@aria-label,'Visualização do cubo') or contains(@aria-label,'Visualizacao do cubo')]"),
        (By.XPATH, "//*[contains(@aria-label,'Cube view') or contains(@aria-label,'cube view')]"),
        (By.CSS_SELECTOR, "[aria-label*='IRAT.'], [aria-label*='FIS.'], [aria-label*='REV.'], [aria-label*='CTS.']"),
    ],
    "menu_exportar": [
        (By.XPATH, "//*[self::button or self::span or self::a or self::li or self::div][normalize-space(.)='Exportar' or normalize-space(.)='Export']"),
        (By.XPATH, "//*[contains(@aria-label,'Exportar') or contains(@aria-label,'Export')]"),
        (By.XPATH, "//*[contains(@title,'Exportar') or contains(@title,'Export')]"),
        (By.CSS_SELECTOR, "button[aria-label*='xport']"),
    ],
    "opcao_excel": [
        (By.XPATH, "//*[self::button or self::span or self::a or self::li or self::div][contains(.,'Excel') or contains(.,'xlsx')]"),
        (By.XPATH, "//*[contains(@aria-label,'Excel') or contains(@title,'Excel')]"),
        (By.XPATH, "//*[contains(text(), 'Excel')]"),
        (By.XPATH, "//*[contains(text(), 'xlsx')]"),
    ],
    "confirmar_exportacao": [
        (By.XPATH, "//div[contains(@id,'ExportExcelDialog') or contains(@class,'ExportView') or @role='dialog']//button[contains(.,'Exportar') or contains(.,'Export') or contains(.,'OK')]"),
        (By.XPATH, "//*[@role='dialog']//button[normalize-space(.)='Exportar' or normalize-space(.)='Export' or normalize-space(.)='OK']"),
        (By.XPATH, "//button[@type='submit' and (contains(.,'Exportar') or contains(.,'Export'))]"),
    ],
    "grade_cubo": [
        (By.CSS_SELECTOR, "[class*='TM1MDV']"),
        (By.CSS_SELECTOR, "[class*='cubeViewer'], [class*='CubeViewer']"),
        (By.CSS_SELECTOR, "[class*='exploration'], [class*='Exploration']"),
        (By.XPATH, "//*[contains(@class,'grid') or contains(@class,'tigre')]"),
        (By.CSS_SELECTOR, "canvas"),
    ],
}

EXTENSOES_VALIDAS = {".xlsx", ".xls", ".csv"}


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def carregar_config(caminho: Path) -> dict:
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def criar_driver(pasta_downloads: Path) -> webdriver.Edge:
    opcoes = webdriver.EdgeOptions()
    opcoes.set_capability("acceptInsecureCerts", True)  # certificado corporativo autoassinado
    opcoes.add_experimental_option("prefs", {
        "download.default_directory": str(pasta_downloads),
        "download.prompt_for_download": False,
        "safebrowsing.enabled": True,
    })
    opcoes.add_argument("--start-maximized")
    return webdriver.Edge(options=opcoes)


def achar_elemento(driver, chave_seletor: str, timeout: int = 20, clicavel: bool = True):
    """Tenta as alternativas de seletor em ordem ate encontrar um elemento."""
    condicao = EC.element_to_be_clickable if clicavel else EC.presence_of_element_located
    fim = time.time() + timeout
    while time.time() < fim:
        for by, seletor in SELETORES[chave_seletor]:
            try:
                el = WebDriverWait(driver, 2).until(condicao((by, seletor)))
                return el
            except TimeoutException:
                continue
    raise TimeoutException(
        f"Nao encontrei o elemento '{chave_seletor}'. "
        "Os seletores em SELETORES provavelmente precisam de ajuste para esta versao do PA."
    )


def clicar(driver, elemento) -> None:
    """Clica com scroll + fallback via JavaScript (PA às vezes bloqueia click nativo)."""
    try:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elemento)
        time.sleep(0.3)
        elemento.click()
    except Exception:
        driver.execute_script("arguments[0].click();", elemento)


def listar_inputs_visiveis(driver) -> list:
    """Lista inputs na pagina (inclui shadow DOM). Util para debug."""
    script = """
    const out = [];
    function walk(root, path) {
      root.querySelectorAll('input, textarea').forEach((el, i) => {
        out.push({
          path: path + '/' + el.tagName.toLowerCase() + '[' + i + ']',
          type: el.type || '',
          placeholder: el.placeholder || '',
          aria: el.getAttribute('aria-label') || '',
          name: el.name || '',
          id: el.id || '',
          visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
        });
      });
      root.querySelectorAll('*').forEach((el) => {
        if (el.shadowRoot) walk(el.shadowRoot, path + '/' + (el.tagName || 'shadow'));
      });
    }
    walk(document, 'doc');
    return out;
    """
    try:
        return driver.execute_script(script) or []
    except Exception:
        return []


def achar_input_por_js(driver, textos=("pesquisar", "search", "esquis")):
    """Encontra input pelo placeholder/aria, inclusive dentro de shadow DOM."""
    script = """
    const textos = arguments[0].map(t => t.toLowerCase());
    function match(el) {
      const p = (el.placeholder || '').toLowerCase();
      const a = (el.getAttribute('aria-label') || '').toLowerCase();
      const t = (el.type || '').toLowerCase();
      if (t === 'hidden') return false;
      return textos.some(x => p.includes(x) || a.includes(x)) || t === 'search';
    }
    function walk(root) {
      const inputs = root.querySelectorAll('input, textarea');
      for (const el of inputs) {
        if (match(el)) return el;
      }
      for (const el of root.querySelectorAll('*')) {
        if (el.shadowRoot) {
          const found = walk(el.shadowRoot);
          if (found) return found;
        }
      }
      return null;
    }
    return walk(document);
    """
    return driver.execute_script(script, list(textos))


def com_iframes(driver, fn):
    """
    Executa fn(driver) no documento principal e em cada iframe.
    Retorna o primeiro resultado nao-nulo. Volta sempre ao default_content.
    """
    driver.switch_to.default_content()
    try:
        resultado = fn(driver)
        if resultado is not None:
            return resultado
    except Exception:
        pass

    iframes = driver.find_elements(By.TAG_NAME, "iframe")
    for idx, frame in enumerate(iframes):
        try:
            driver.switch_to.default_content()
            driver.switch_to.frame(frame)
            resultado = fn(driver)
            if resultado is not None:
                log(f"Elemento encontrado no iframe[{idx}].")
                return resultado
        except Exception:
            continue

    driver.switch_to.default_content()
    return None


def achar_campo_pesquisa(driver, timeout: int = 20):
    """Localiza o campo Pesquisar no PA (documento, iframes e shadow DOM)."""
    fim = time.time() + timeout
    while time.time() < fim:
        def tentar(_drv):
            try:
                return achar_elemento(_drv, "campo_pesquisa", timeout=2, clicavel=False)
            except TimeoutException:
                return achar_input_por_js(_drv)

        el = com_iframes(driver, tentar)
        if el is not None:
            return el
        time.sleep(1)
    raise TimeoutException(
        "Nao encontrei o elemento 'campo_pesquisa'. "
        "Os seletores em SELETORES provavelmente precisam de ajuste para esta versao do PA."
    )


def salvar_debug(driver, pasta: Path, rotulo: str, erro: str | None = None) -> Path:
    """Salva screenshot + lista de inputs + HTML para diagnostico."""
    pasta.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Evita caracteres invalidos no Windows (ex.: parenteses no nome da exportacao).
    seguro = "".join(c if c.isalnum() or c in "-_." else "_" for c in rotulo)[:60]
    base = pasta / f"debug_{seguro}_{ts}"
    try:
        driver.switch_to.default_content()
        driver.save_screenshot(str(base.with_suffix(".png")))
    except Exception as e:
        log(f"Falha ao salvar screenshot: {e}")
    try:
        inputs = listar_inputs_visiveis(driver)
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        relatorio = {
            "url": driver.current_url,
            "title": driver.title,
            "iframes": len(iframes),
            "erro": erro,
            "inputs": inputs,
        }
        base.with_suffix(".json").write_text(
            json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log(f"Debug salvo em: {base.with_suffix('.json')} ({len(inputs)} inputs, {len(iframes)} iframes)")
    except Exception as e:
        log(f"Falha ao salvar debug JSON: {e}")
    try:
        base.with_suffix(".html").write_text(driver.page_source, encoding="utf-8")
    except Exception:
        pass
    return base


def carregar_credenciais(caminho: str | Path | None) -> tuple[str, str] | None:
    """
    Le arquivo de credenciais: 1a linha = login, 2a linha = senha.
    Nunca imprime a senha.
    """
    if not caminho:
        return None
    path = Path(caminho).expanduser()
    if not path.exists():
        log(f"Arquivo de credenciais nao encontrado: {path}")
        return None
    linhas = [
        ln.strip()
        for ln in path.read_text(encoding="utf-8-sig").splitlines()
        if ln.strip()
    ]
    if len(linhas) < 2:
        raise ValueError(
            f"Arquivo de credenciais invalido ({path}). "
            "Esperado: 1a linha login, 2a linha senha."
        )
    usuario, senha = linhas[0], linhas[1]
    log(f"Credenciais carregadas para usuario: {usuario}")
    return usuario, senha


def home_ja_carregada(driver) -> bool:
    for by, seletor in SELETORES["home_carregada"]:
        try:
            if driver.find_elements(by, seletor):
                return True
        except Exception:
            continue
    return False


def fazer_login(driver, usuario: str, senha: str, timeout: int = 60) -> bool:
    """Preenche usuario/senha na tela de login do PA, se ela aparecer."""
    fim = time.time() + timeout
    while time.time() < fim:
        if home_ja_carregada(driver):
            return True
        try:
            campo_user = achar_elemento(driver, "campo_usuario", timeout=3)
            campo_pass = achar_elemento(driver, "campo_senha", timeout=3)
        except TimeoutException:
            time.sleep(1)
            continue

        log("Tela de login detectada; preenchendo credenciais...")
        try:
            campo_user.clear()
        except Exception:
            pass
        campo_user.send_keys(usuario)
        time.sleep(0.3)
        try:
            campo_pass.clear()
        except Exception:
            pass
        campo_pass.send_keys(senha)
        time.sleep(0.3)
        try:
            botao = achar_elemento(driver, "botao_login", timeout=5)
            clicar(driver, botao)
        except TimeoutException:
            campo_pass.send_keys(Keys.ENTER)
        log("Credenciais enviadas; aguardando home carregar...")
        return True
    return False


def aguardar_login(
    driver,
    timeout: int,
    arquivo_credenciais: str | Path | None = None,
) -> None:
    """Faz login automatico (se houver arquivo) e espera a home carregar."""
    creds = carregar_credenciais(arquivo_credenciais)
    if creds:
        usuario, senha = creds
        if not fazer_login(driver, usuario, senha, timeout=min(60, timeout)):
            log("Formulario de login nao apareceu a tempo; seguindo aguardando home...")
    else:
        log("Aguardando login manual... Se aparecer a tela de login, entre com seu usuario.")

    fim = time.time() + timeout
    while time.time() < fim:
        try:
            if home_ja_carregada(driver):
                log("Login concluido, pagina inicial carregada.")
                time.sleep(3)
                return
        except Exception:
            pass
        time.sleep(2)
    raise TimeoutException("Tempo esgotado aguardando o login no Planning Analytics.")


def extrair_dashboard_id(url: str) -> str | None:
    """Extrai id=... da URL do dashboard, se houver."""
    if "id=" not in (url or ""):
        return None
    parte = url.split("id=", 1)[1]
    return parte.split("&", 1)[0].strip() or None


def trecho_distintivo(nome_busca: str) -> str:
    """Parte mais especifica do nome (ex.: CTS.100, REV.420, CUSTO, irat950)."""
    nome = (nome_busca or "").strip()
    if not nome:
        return ""
    primeiro = nome.split()[0]
    if "." in primeiro and len(primeiro) >= 5:
        return primeiro
    if "(" in nome and nome.endswith(")"):
        sufixo = nome[nome.rfind("(") + 1 : -1].strip()
        if sufixo.lower() not in {"power bi", "tableau", "cognos"} and len(sufixo) >= 3:
            return sufixo
    # Ultima palavra distintiva (ex.: CUSTO).
    partes = nome.replace("(", " ").replace(")", " ").split()
    for p in reversed(partes):
        if p.lower() not in {"power", "bi", "tableau", "dre", "receita", "v2"} and len(p) >= 3:
            return p
    return nome


def validar_dashboard_aberto(driver, nome_busca: str) -> None:
    """
    Confirma que a view aberta corresponde ao nome_busca.
    Evita exportar Tableau/outros tiles abertos por engano (caso Pre-Pago).
    """
    time.sleep(2)
    title = (driver.title or "").strip()
    url = driver.current_url or ""
    did = extrair_dashboard_id(url)
    if did:
        log(f"Dashboard aberto: title='{title}' id={did}")
    else:
        log(f"Dashboard aberto: title='{title}'")

    chave = trecho_distintivo(nome_busca).lower()
    blob = f"{title} {url}".lower()
    quer_pbi = "power bi" in nome_busca.lower()
    if quer_pbi and "tableau" in title.lower():
        raise TimeoutException(
            f"Abriu view Tableau por engano ('{title}'), esperado: '{nome_busca}'. "
            "Favorite a view correta ou informe o dashboard_id no config.json."
        )
    if chave and chave not in blob and chave not in title.lower():
        # Title as vezes trunca; aceita se URL ja e dashboard e nome_busca quase bate.
        if nome_busca.lower()[:20] not in title.lower() and chave not in title.lower():
            raise TimeoutException(
                f"View aberta nao confere. title='{title}' esperado conter '{chave}' "
                f"(nome_busca='{nome_busca}'). id={did or '-'}."
            )


def abrir_por_tile(driver, nome_busca: str) -> bool:
    """
    Tenta abrir a view pelo tile ja presente na home (Favoritos/Recentes).
    No HTML de debug da Claro esses tiles existem com:
      <div title="Receita DRE PowerBI V2 (irat950)" class="pa-tile-header ...">
    """
    literais = xpath_literal(nome_busca)
    xpaths = [
        f"//div[contains(@class,'pa-tile-header') and @title={literais}]",
        f"//*[@title={literais} and contains(@class,'pa-tile')]",
        f"//a[contains(@class,'pa-tile')][.//div[@title={literais}]]",
        f"//div[contains(@class,'click-area')][.//*[@title={literais}]]",
    ]

    # Tenta nas abas onde os tiles costumam aparecer.
    for aba in ("aba_favoritos", "aba_recentes"):
        try:
            el_aba = achar_elemento(driver, aba, timeout=3)
            clicar(driver, el_aba)
            time.sleep(2)
        except TimeoutException:
            pass

        for xp in xpaths:
            els = driver.find_elements(By.XPATH, xp)
            for el in els:
                try:
                    if not el.is_displayed():
                        continue
                    titulo = (el.get_attribute("title") or el.text or "").strip()
                    if "tableau" in titulo.lower() and "tableau" not in nome_busca.lower():
                        continue
                    log(f"Tile encontrado na home: {titulo or nome_busca}")
                    clicar(driver, el)
                    time.sleep(10)
                    return True
                except Exception:
                    continue
    return False


def abrir_compartilhado(driver, pasta_debug: Path | None = None) -> None:
    """Abre o menu de navegacao e entra em Compartilhado (campo Pesquisar)."""
    try:
        achar_campo_pesquisa(driver, timeout=3)
        log("Sidebar Compartilhado ja aberta.")
        return
    except TimeoutException:
        pass

    log("Abrindo menu de navegacao (navmenu)...")
    try:
        menu = achar_elemento(driver, "menu_hamburguer", timeout=15)
        clicar(driver, menu)
        time.sleep(2)
    except TimeoutException:
        if pasta_debug is not None:
            salvar_debug(driver, pasta_debug, "sem_navmenu")
        raise TimeoutException(
            "Nao encontrei o botao do menu (#com.ibm.bi.glass.common.navmenu)."
        )

    try:
        link = achar_elemento(driver, "link_compartilhado", timeout=20)
        clicar(driver, link)
        time.sleep(4)
    except TimeoutException:
        if pasta_debug is not None:
            salvar_debug(driver, pasta_debug, "sem_compartilhado")
        raise

    try:
        achar_campo_pesquisa(driver, timeout=20)
        log("Compartilhado aberto.")
    except TimeoutException:
        if pasta_debug is not None:
            salvar_debug(driver, pasta_debug, "sem_campo_pesquisa")
        raise


def abrir_por_dashboard_id(driver, base_url: str, dashboard_id: str, timeout: int = 90) -> bool:
    """Abre a view direto pela URL do dashboard (mais estavel que tile/pesquisa)."""
    if not dashboard_id:
        return False
    # Ex.: https://host:9443/?perspective=pa-home -> .../?perspective=dashboard&id=...
    root = base_url.split("?")[0].rstrip("/")
    url = f"{root}/?perspective=dashboard&id={dashboard_id}"
    log(f"Abrindo dashboard direto: {url}")
    driver.get(url)
    time.sleep(5)
    if "perspective=dashboard" not in driver.current_url:
        return False
    aguardar_dashboard_pronto(driver, timeout=timeout)
    return True


def aguardar_dashboard_pronto(driver, timeout: int = 90) -> None:
    """
    Espera o dashboard terminar de carregar (Custos demora mais que Receitas/Fisicos).
    Criterio: grade TM1 visivel + sem spinner/loading por alguns segundos seguidos.
    """
    log(f"Aguardando dashboard carregar por completo (ate {timeout}s)...")
    fim = time.time() + timeout
    estavel = 0
    while time.time() < fim:
        try:
            pronto = driver.execute_script(
                """
                const isVisible = (el) => {
                  if (!el) return false;
                  const r = el.getBoundingClientRect();
                  const st = window.getComputedStyle(el);
                  return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
                };
                const loaders = document.querySelectorAll(
                  '[class*="loading"], [class*="Loading"], [class*="spinner"], [class*="Spinner"],'
                  + '[class*="BusyIndicator"], [class*="busy"], .bx--loading, [aria-busy="true"]'
                );
                for (const el of loaders) {
                  if (isVisible(el)) return {ok:false, why:'loading'};
                }
                const grid = document.querySelector(
                  '[id*="TM1MDV"], [class*="CubeView"], [class*="pa--dimensionoverview"], [class*="TM1MDV"]'
                );
                if (!grid || !isVisible(grid)) return {ok:false, why:'sem-grade'};
                // Titulo da aba/dashboard ajuda a saber se a view certa montou.
                const title = (document.title || '').trim();
                return {ok:true, title: title};
                """
            )
        except Exception:
            pronto = {"ok": False, "why": "script"}
        if pronto and pronto.get("ok"):
            estavel += 1
            if estavel >= 4:  # ~4s estavel
                log(f"Dashboard pronto (title='{pronto.get('title') or driver.title}').")
                time.sleep(1.5)  # folga extra apos estabilizar
                return
        else:
            if estavel:
                log("Dashboard ainda oscilando (reload parcial); continuando a esperar...")
            estavel = 0
        time.sleep(1)
    log("Timeout aguardando dashboard estabilizar; seguindo com o que houver na tela.")


def pesquisar_e_abrir(
    driver,
    nome_busca: str,
    pasta_debug: Path | None = None,
    dashboard_id: str | None = None,
    base_url: str | None = None,
    timeout_dashboard: int = 90,
) -> None:
    """Abre a view: URL direta > tile na home > pesquisa no Compartilhado."""
    log(f"Abrindo view: {nome_busca}")

    if dashboard_id and base_url and abrir_por_dashboard_id(
        driver, base_url, dashboard_id, timeout=timeout_dashboard
    ):
        log("View aberta via dashboard_id.")
        validar_dashboard_aberto(driver, nome_busca)
        return

    if abrir_por_tile(driver, nome_busca):
        log("View aberta via tile da home.")
        aguardar_dashboard_pronto(driver, timeout=timeout_dashboard)
        validar_dashboard_aberto(driver, nome_busca)
        return

    log("Tile nao encontrado na home; indo para Compartilhado...")
    # Atalho: card "Aplicativos e planos" às vezes leva ao browser de conteudo.
    try:
        card = achar_elemento(driver, "card_aplicativos", timeout=5)
        clicar(driver, card)
        time.sleep(4)
    except TimeoutException:
        pass

    abrir_compartilhado(driver, pasta_debug=pasta_debug)

    log(f"Pesquisando: {nome_busca}")
    campo = achar_campo_pesquisa(driver, timeout=20)
    clicar(driver, campo)
    try:
        campo.send_keys(Keys.CONTROL, "a")
        campo.send_keys(Keys.BACKSPACE)
    except Exception:
        driver.execute_script(
            "arguments[0].value='';"
            "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));",
            campo,
        )
    time.sleep(0.3)
    campo.send_keys(nome_busca)
    time.sleep(1)
    campo.send_keys(Keys.ENTER)
    time.sleep(4)

    resultado = achar_resultado(driver, nome_busca, timeout=30)
    try:
        clicar_nativo(driver, resultado)
    except Exception:
        clicar(driver, resultado)
    log("View aberta via pesquisa no Compartilhado. Aguardando carregar...")
    aguardar_dashboard_pronto(driver, timeout=timeout_dashboard)
    validar_dashboard_aberto(driver, nome_busca)


def achar_resultado(driver, nome_busca: str, timeout: int = 30):
    """
    Localiza o resultado da pesquisa.
    A UI do PA trunca o texto (ex.: 'Receita DRE P... V2 (irat950)'),
    entao tenta match exato, title/aria-label e contains parcial.
    """
    literais = xpath_literal(nome_busca)
    # Trechos distintivos do nome (evita depender do texto truncado).
    # NAO usar sufixos genericos como "(Power BI)" — batem em varias views.
    trechos = [nome_busca]
    if "(" in nome_busca and nome_busca.endswith(")"):
        sufixo = nome_busca[nome_busca.rfind("(") :]
        if sufixo.lower() not in {"(power bi)", "(tableau)", "(cognos)"}:
            trechos.append(sufixo)  # ex.: (irat950)
    # Codigo do cubo no inicio do nome, se houver (CTS.100, REV.420, etc.).
    primeiro = nome_busca.split()[0]
    if "." in primeiro and len(primeiro) >= 5:
        trechos.append(primeiro)

    candidatos_xpath = [
        f"//*[@title={literais} or @aria-label={literais}]",
        f"//*[normalize-space(.)={literais}]",
    ]
    for trecho in trechos:
        lit = xpath_literal(trecho)
        candidatos_xpath.append(f"//*[contains(normalize-space(.), {lit})]")
        candidatos_xpath.append(f"//*[@title[contains(., {lit})] or @aria-label[contains(., {lit})]]")

    fim = time.time() + timeout
    rejeita_tableau = "tableau" not in nome_busca.lower()
    while time.time() < fim:
        for xp in candidatos_xpath:
            els = driver.find_elements(By.XPATH, xp)
            for el in els:
                try:
                    texto = (el.text or "").strip()
                    title = (el.get_attribute("title") or el.get_attribute("aria-label") or "").strip()
                    # Ignora o proprio campo de busca / labels genericos.
                    if el.tag_name.lower() in {"input", "textarea", "html", "body"}:
                        continue
                    combinado = f"{texto} {title}".lower()
                    if rejeita_tableau and "tableau" in combinado:
                        continue
                    if nome_busca.lower() in texto.lower() or nome_busca.lower() in title.lower():
                        if el.is_displayed():
                            log(f"Resultado encontrado: {texto or title}")
                            return el
                    # Match por trecho curto distintivo (ex.: (irat950) / CTS.100) quando truncado.
                    for trecho in trechos[1:]:
                        if trecho.lower() in texto.lower() or trecho.lower() in title.lower():
                            if el.is_displayed() and len(texto) > 3:
                                log(f"Resultado encontrado (parcial): {texto or title}")
                                return el
                except Exception:
                    continue
        time.sleep(1)
    raise TimeoutException(f"Nao encontrei o resultado da pesquisa para: {nome_busca}")


def xpath_literal(texto: str) -> str:
    """Gera literal XPath seguro para textos com aspas."""
    if "'" not in texto:
        return f"'{texto}'"
    if '"' not in texto:
        return f'"{texto}"'
    partes = texto.split("'")
    return "concat(" + ", \"'\", ".join(f"'{p}'" for p in partes) + ")"


def _clicar_item_menu_por_texto(driver, textos, timeout: int = 10) -> bool:
    """Clica no primeiro item de menu/contexto cujo texto contenha um dos textos."""
    fim = time.time() + timeout
    while time.time() < fim:
        for texto in textos:
            xp = (
                "//*[self::button or self::span or self::a or self::li or self::div]"
                f"[contains(translate(normalize-space(.),"
                f"'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), '{texto.lower()}')]"
            )
            for el in driver.find_elements(By.XPATH, xp):
                try:
                    if not el.is_displayed():
                        continue
                    t = (el.text or el.get_attribute("aria-label") or "").strip()
                    if not t:
                        continue
                    clicar(driver, el)
                    log(f"Clique em menu: {t}")
                    return True
                except Exception:
                    continue
        time.sleep(0.5)
    return False


def desligar_modo_editar(driver) -> None:
    """Preferivel Editar desligado; tenta desmarcar o toggle Carbon."""
    try:
        toggle = achar_elemento(driver, "toggle_editar", timeout=5, clicavel=False)
    except TimeoutException:
        return
    try:
        if not toggle.is_selected():
            return
        log("Desligando modo Editar...")
        tid = toggle.get_attribute("id") or ""
        # Label do Carbon e o alvo clicavel real.
        if tid:
            for lab in driver.find_elements(By.CSS_SELECTOR, f"label[for='{tid}']"):
                try:
                    if lab.is_displayed():
                        clicar_nativo(driver, lab)
                        time.sleep(2)
                        if not toggle.is_selected():
                            return
                except Exception:
                    continue
        # Clique no texto "Editar" ao lado do toggle.
        for lab in driver.find_elements(By.XPATH, "//*[normalize-space(.)='Editar']/ancestor::label[1] | //label[.//text()[contains(.,'Editar')]]"):
            try:
                if lab.is_displayed():
                    clicar_nativo(driver, lab)
                    time.sleep(2)
                    if not toggle.is_selected():
                        return
            except Exception:
                continue
        driver.execute_script(
            "arguments[0].click();"
            "arguments[0].checked=false;"
            "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));"
            "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));",
            toggle,
        )
        time.sleep(2)
    except Exception as e:
        log(f"Nao foi possivel desligar Editar: {e}")


def sair_tela_cheia(driver) -> None:
    """Sai de tela cheia com um unico Escape (sem clicar em icones)."""
    try:
        driver.switch_to.default_content()
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        time.sleep(0.8)
    except Exception:
        pass


def selecionar_cubo(driver) -> None:
    """
    Seleciona o widget do cubo para a toolbar de exploracao (Exportar) aparecer.
    No Custos o cabecalho 'Visualizacao do cubo' as vezes nao esta no DOM —
    cai para clique na grade TM1 / overview.
    """
    xpaths = [
        "//*[contains(@aria-label,'Visualização do cubo')]",
        "//*[contains(@aria-label,'Visualizacao do cubo')]",
        "//*[contains(@title,'Visualização do cubo')]",
        "//*[contains(@title,'Visualizacao do cubo')]",
        "//*[contains(normalize-space(.),'Visualização do cubo Banco de dados')]",
        "//*[contains(normalize-space(.),'Visualizacao do cubo Banco de dados')]",
        "//*[contains(normalize-space(.),'Banco de dados:') and contains(normalize-space(.),'Cubo:')]",
        "//*[contains(@class,'pa--dimensionoverview--content')]",
        "//*[contains(@id,'TM1MDVOverview')]",
        "//*[contains(@class,'CubeView') or contains(@class,'cubeView')]",
        "//*[contains(@id,'TM1MDV') and (@tabindex or contains(@class,'content'))]",
    ]
    for xp in xpaths:
        for el in driver.find_elements(By.XPATH, xp):
            try:
                if not el.is_displayed():
                    continue
                log(f"Selecionando cubo via: {xp[:60]}...")
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                time.sleep(0.2)
                try:
                    ActionChains(driver).move_to_element(el).pause(0.2).click().perform()
                except Exception:
                    try:
                        el.click()
                    except Exception:
                        driver.execute_script("arguments[0].click();", el)
                time.sleep(1.5)
                return
            except Exception:
                continue

    # Ultimo recurso: clique no centro da area de conteudo.
    try:
        log("Selecionando cubo via clique no centro do conteudo...")
        driver.execute_script(
            """
            const pane = document.querySelector('[aria-label*=\"contentViewPane\"], .contentViewPane, .dashboard-content, main')
                       || document.body;
            const r = pane.getBoundingClientRect();
            const x = r.left + r.width * 0.55;
            const y = r.top + r.height * 0.45;
            const el = document.elementFromPoint(x, y);
            if (el) el.click();
            """
        )
        time.sleep(1.5)
    except Exception:
        log("Titulo/grade do cubo nao encontrado para selecao.")


def achar_botao_exportar_planilha(driver, timeout: int = 12):
    """Botao da toolbar: data-id=exportAction / aria-label Exportar."""
    fim = time.time() + timeout
    while time.time() < fim:
        try:
            return achar_elemento(driver, "botao_exportar_planilha", timeout=2)
        except TimeoutException:
            el = driver.execute_script(
                """
                const byId = document.querySelector("button[data-id='exportAction'], button[walkme-data-id='exportAction']");
                if (byId) {
                  const r = byId.getBoundingClientRect();
                  if (r.width > 0 && r.height > 0) return byId;
                }
                const nodes = document.querySelectorAll('button, [role="button"]');
                for (const el of nodes) {
                  const aria = (el.getAttribute('aria-label') || '').trim().toLowerCase();
                  const assist = (el.querySelector('.bx--assistive-text')?.textContent || '').trim().toLowerCase();
                  const t = aria || assist;
                  if (t !== 'exportar' && t !== 'export' && !t.includes('exportar para planilha') && !t.includes('export to spreadsheet')) continue;
                  if (t.includes('tela cheia') || t.includes('fullscreen')) continue;
                  const r = el.getBoundingClientRect();
                  if (r.width > 0 && r.height > 0) return el;
                }
                return null;
                """
            )
            if el is not None:
                return el
        time.sleep(0.5)
    return None


def garantir_toolbar_exportacao(driver, tentativas: int = 6):
    """Desliga Editar, seleciona o cubo e espera o botao Exportar aparecer."""
    botao = None
    for i in range(1, tentativas + 1):
        try:
            desligar_modo_editar(driver)
            selecionar_cubo(driver)
            botao = achar_botao_exportar_planilha(driver, timeout=10)
            if botao is not None:
                return botao
        except StaleElementReferenceException:
            log("DOM regenerou durante selecao (stale); aguardando e tentando de novo...")
            time.sleep(2)
            continue
        log(f"Toolbar Exportar ainda ausente (tentativa {i}/{tentativas}); selecionando de novo...")
        # Clique extra na grade (Custos nao expoe o titulo do cubo).
        try:
            grade = driver.execute_script(
                """
                const cands = [
                  ...document.querySelectorAll('[id*="TM1MDV"]'),
                  ...document.querySelectorAll('[class*="CubeView"]'),
                  ...document.querySelectorAll('[class*="pa--dimensionoverview"]'),
                ];
                for (const el of cands) {
                  const r = el.getBoundingClientRect();
                  if (r.width > 80 && r.height > 40) return el;
                }
                return null;
                """
            )
            if grade is not None:
                ActionChains(driver).move_to_element(grade).pause(0.2).click().perform()
                time.sleep(1.5)
        except StaleElementReferenceException:
            time.sleep(2)
        except Exception:
            pass
    return botao


def clicar_opcao_menu_planilha(driver, timeout: int = 3) -> bool:
    """Se Exportar abrir menu, escolhe so a opcao explicita de planilha."""
    fim = time.time() + timeout
    while time.time() < fim:
        try:
            opcao = achar_elemento(driver, "opcao_exportar_planilha", timeout=1)
            label = (opcao.text or opcao.get_attribute("aria-label") or "").strip()
            log(f"Clicando opcao do menu: {label or 'Exportar para planilha'}")
            clicar_nativo(driver, opcao)
            time.sleep(1.5)
            return True
        except StaleElementReferenceException:
            time.sleep(0.5)
            continue
        except TimeoutException:
            el = driver.execute_script(
                """
                const want = ['exportar para planilha', 'export to spreadsheet'];
                const nodes = document.querySelectorAll('[role="menuitem"], [role="option"], li, button, a');
                for (const el of nodes) {
                  const t = ((el.getAttribute('aria-label')||'') + ' ' + (el.textContent||'')).trim().toLowerCase();
                  if (!want.some(w => t.includes(w))) continue;
                  if (t.length > 60) continue;
                  const r = el.getBoundingClientRect();
                  if (r.width > 0 && r.height > 0) return el;
                }
                return null;
                """
            )
            if el is not None:
                log("Clicando opcao do menu (nativo)...")
                try:
                    clicar_nativo(driver, el)
                    time.sleep(1.5)
                    return True
                except StaleElementReferenceException:
                    time.sleep(0.5)
        time.sleep(0.3)
    return False


def clicar_nativo(driver, elemento) -> None:
    """
    Clique real de mouse (ActionChains). O PA/Carbon ignora click() via JS
    em botoes icon-only da toolbar — o tooltip aparece, mas o download nao inicia.
    """
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", elemento)
    time.sleep(0.2)
    try:
        ActionChains(driver).move_to_element(elemento).pause(0.35).click().perform()
        return
    except Exception as e:
        log(f"ActionChains falhou ({e}); tentando click nativo...")
    try:
        elemento.click()
        return
    except Exception:
        pass
    try:
        elemento.send_keys(Keys.ENTER)
        return
    except Exception:
        pass
    driver.execute_script(
        """
        const el = arguments[0];
        el.focus();
        for (const type of ['pointerdown','mousedown','pointerup','mouseup','click']) {
          el.dispatchEvent(new MouseEvent(type, {bubbles:true, cancelable:true, view:window}));
        }
        """,
        elemento,
    )


def exportar_para_excel(driver) -> None:
    """
    Fluxo:
      1) Escape (sair tela cheia se houver)
      2) Esperar dashboard estabilizar (views lentas como CUSTO)
      3) Desligar Editar + selecionar cubo ate Exportar aparecer
      4) Re-localizar o botao e clique NATIVO (retry se stale)
      5) Menu/dialogo opcionais
    """
    log("Acionando exportacao para Excel (fluxo simples)...")
    driver.switch_to.default_content()
    sair_tela_cheia(driver)
    # Reforca espera: Custos pode ainda estar montando a toolbar.
    aguardar_dashboard_pronto(driver, timeout=60)

    ultimo_erro = None
    for tentativa in range(1, 6):
        try:
            botao = garantir_toolbar_exportacao(driver, tentativas=4)
            if botao is None:
                raise TimeoutException(
                    "Botao Exportar (exportAction) nao apareceu na toolbar apos selecionar o cubo."
                )
            # Re-busca imediatamente antes do clique (evita stale apos re-render).
            time.sleep(0.8)
            botao = achar_botao_exportar_planilha(driver, timeout=8) or botao
            label = (botao.get_attribute("aria-label") or botao.get_attribute("title") or "").strip()
            data_id = botao.get_attribute("data-id") or ""
            log(f"Clique nativo em: {label or 'Exportar'} (data-id={data_id or '-'}) [tentativa {tentativa}]")
            clicar_nativo(driver, botao)
            time.sleep(2)

            if clicar_opcao_menu_planilha(driver, timeout=2):
                time.sleep(1)

            try:
                confirmar = achar_elemento(driver, "confirmar_exportacao", timeout=4)
                if (confirmar.get_attribute("data-id") or "") != "exportAction":
                    log("Confirmando dialogo de exportacao...")
                    clicar_nativo(driver, confirmar)
                    time.sleep(1)
            except TimeoutException:
                pass

            log("Exportacao acionada; aguardando arquivo baixar.")
            return
        except StaleElementReferenceException as e:
            ultimo_erro = e
            log(f"Elemento stale na tentativa {tentativa}/5 (pagina ainda carregando). Esperando...")
            time.sleep(3)
            aguardar_dashboard_pronto(driver, timeout=45)
        except TimeoutException as e:
            ultimo_erro = e
            log(f"Exportar ainda nao disponivel (tentativa {tentativa}/5): {e}")
            time.sleep(2)
            aguardar_dashboard_pronto(driver, timeout=30)

    raise TimeoutException(
        f"Falha ao acionar Exportar apos retries. Ultimo erro: {ultimo_erro}"
    )


def aguardar_download(pasta: Path, arquivos_antes: set, timeout: int) -> Path:
    """Espera um arquivo novo terminar de baixar na pasta de downloads."""
    log(f"Aguardando download terminar (ate {timeout}s) em: {pasta}")
    fim = time.time() + timeout
    ultimo_ping = 0
    while time.time() < fim:
        atuais = {p for p in pasta.iterdir() if p.is_file()}
        novos = [
            p for p in atuais - arquivos_antes
            if p.suffix.lower() in EXTENSOES_VALIDAS
        ]
        baixando = [p for p in atuais if p.suffix in (".crdownload", ".tmp", ".partial")]
        if novos and not baixando:
            arquivo = max(novos, key=lambda p: p.stat().st_mtime)
            time.sleep(2)  # margem para o SO liberar o arquivo
            log(f"Download concluido: {arquivo.name}")
            return arquivo
        decorrido = int(timeout - (fim - time.time()))
        if decorrido - ultimo_ping >= 15:
            ultimo_ping = decorrido
            log(f"... ainda aguardando ({decorrido}s) — baixando={len(baixando)} novos={len(novos)}")
        time.sleep(2)
    raise TimeoutException(
        f"Tempo esgotado aguardando o download do arquivo em {pasta}. "
        "Verifique se o botao 'Exportar para planilha' realmente iniciou o download."
    )


def nome_arquivo_final(job: dict, arquivo: Path) -> str:
    """
    Nome final = nome da pasta compartilhada (nome_busca) + extensao.
    Ex.: 'Receita DRE PowerBI V2 (irat950).xlsx'
    """
    configurado = job.get("nome_arquivo_destino")
    if configurado:
        return configurado
    ext = arquivo.suffix.lower() if arquivo.suffix else ".xlsx"
    if ext not in EXTENSOES_VALIDAS:
        ext = ".xlsx"
    base = (job.get("nome_busca") or job.get("nome") or arquivo.stem).strip()
    # Remove extensao se ja vier no nome_busca.
    if Path(base).suffix.lower() in EXTENSOES_VALIDAS:
        return base
    return f"{base}{ext}"


def limpar_pasta_downloads(pasta: Path) -> None:
    """Apaga arquivos da pasta de downloads antes de iniciar as exportacoes."""
    pasta.mkdir(parents=True, exist_ok=True)
    removidos = 0
    for p in pasta.iterdir():
        try:
            if p.is_file():
                p.unlink()
                removidos += 1
            elif p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
                removidos += 1
        except Exception as e:
            log(f"Nao foi possivel apagar {p.name}: {e}")
    log(f"Pasta de downloads limpa ({removidos} item(ns) removido(s)): {pasta}")


def renomear_download(arquivo: Path, job: dict) -> Path:
    """Renomeia o arquivo baixado para o nome da view compartilhada."""
    nome = nome_arquivo_final(job, arquivo)
    destino = arquivo.with_name(nome)
    if destino.resolve() == arquivo.resolve():
        return arquivo
    if destino.exists():
        destino.unlink()
    arquivo.rename(destino)
    log(f"Arquivo renomeado para: {destino.name}")
    return destino


def mover_para_destino(arquivo: Path, job: dict, pasta_backup: Path) -> Path:
    """Move o arquivo baixado para a pasta de rede, com backup do anterior."""
    destino_dir = Path(job["pasta_destino"])
    if not destino_dir.exists():
        raise FileNotFoundError(
            f"Pasta de destino inacessivel: {destino_dir}\n"
            "Verifique a conexao com a rede corporativa (VPN).\n"
            f"O Excel JA FOI exportado e permanece em: {arquivo}"
        )

    nome_final = nome_arquivo_final(job, arquivo)
    destino = destino_dir / nome_final

    if destino.exists():
        backup_dir = pasta_backup / job["nome"].replace("/", "-")
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / f"{datetime.now():%Y%m%d_%H%M%S}_{nome_final}"
        shutil.copy2(destino, backup)
        log(f"Backup do arquivo anterior salvo em: {backup}")

    shutil.copy2(arquivo, destino)
    arquivo.unlink(missing_ok=True)
    log(f"Arquivo atualizado em: {destino}")
    return destino


def main() -> int:
    parser = argparse.ArgumentParser(description="Baixa as bases do Cognos/Planning Analytics.")
    parser.add_argument("--config", default=str(BASE_DIR / "config.json"))
    parser.add_argument("--somente", default=None,
                        help="Executa apenas exportacoes cujo nome contenha este texto. "
                             "Use virgula para varios: Receitas,Fisicos")
    parser.add_argument("--sem-mover", action="store_true",
                        help="Baixa os arquivos mas nao copia para a pasta de rede.")
    parser.add_argument("--debug", action="store_true",
                        help="Salva screenshot/HTML/inputs quando falhar e para no 1o erro.")
    parser.add_argument("--nao-limpar", action="store_true",
                        help="Nao limpa a pasta downloads antes de comecar.")
    args = parser.parse_args()

    cfg = carregar_config(Path(args.config))
    pasta_downloads = BASE_DIR / cfg["pasta_downloads"]
    pasta_backup = BASE_DIR / cfg["pasta_backup"]
    pasta_debug = BASE_DIR / "debug"
    pasta_downloads.mkdir(parents=True, exist_ok=True)

    jobs = cfg["exportacoes"]
    if args.somente:
        filtros = [f.strip().lower() for f in args.somente.split(",") if f.strip()]
        jobs = [
            j for j in jobs
            if any(
                f in j["nome"].lower() or f in j["nome_busca"].lower()
                for f in filtros
            )
        ]
        if not jobs:
            log(f"Nenhuma exportacao corresponde ao filtro '{args.somente}'.")
            return 1
        log(f"Filtro --somente: {', '.join(filtros)} -> {len(jobs)} job(s)")

    if not args.nao_limpar:
        limpar_pasta_downloads(pasta_downloads)
    else:
        log("Pasta de downloads NAO foi limpa (--nao-limpar).")

    estimativa = int(cfg.get("tempo_estimado_por_exportacao_segundos", ESTIMATIVA_PADRAO_SEG))
    painel = PainelAcompanhamento([j["nome"] for j in jobs], estimativa_padrao=estimativa)
    painel.set_fase("login", "Abrindo Planning Analytics / aguardando login...")

    log(f"Iniciando automacao: {len(jobs)} exportacao(oes).")
    driver = None
    resultados = []
    houve_erro = False
    try:
        driver = criar_driver(pasta_downloads)
        driver.get(cfg["url"])
        aguardar_login(
            driver,
            cfg["timeout_login_segundos"],
            arquivo_credenciais=cfg.get("arquivo_credenciais"),
        )
        painel.set_fase("exportando", "Login concluido. Iniciando exportacoes...")

        for idx, job in enumerate(jobs):
            log("=" * 60)
            log(f"Exportacao: {job['nome']}  (servidor {job['servidor']})")
            painel.iniciar_job(idx, f"Exportando: {job['nome']}")
            try:
                arquivos_antes = {p for p in pasta_downloads.iterdir() if p.is_file()}
                pesquisar_e_abrir(
                    driver,
                    job["nome_busca"],
                    pasta_debug=pasta_debug,
                    dashboard_id=job.get("dashboard_id"),
                    base_url=cfg["url"],
                    timeout_dashboard=int(cfg.get("timeout_dashboard_segundos", 90)),
                )
                exportar_para_excel(driver)
                arquivo = aguardar_download(
                    pasta_downloads, arquivos_antes, cfg["timeout_download_segundos"]
                )
                arquivo = renomear_download(arquivo, job)
                if args.sem_mover:
                    log(f"(--sem-mover) Arquivo mantido em: {arquivo}")
                    resultados.append((job["nome"], f"OK (download): {arquivo.name}"))
                    painel.concluir_job(idx, "OK", arquivo.name)
                else:
                    try:
                        mover_para_destino(arquivo, job, pasta_backup)
                        resultados.append((job["nome"], "OK"))
                        painel.concluir_job(idx, "OK", "copiado para rede")
                    except FileNotFoundError as e_rede:
                        # Exportacao OK; so a copia para a rede falhou.
                        log(f"EXPORTACAO OK, mas falha ao mover para a rede: {e_rede}")
                        resultados.append(
                            (job["nome"], f"OK download; ERRO rede: {arquivo.name}")
                        )
                        painel.concluir_job(idx, "OK_REDE", arquivo.name)
                        if args.debug:
                            salvar_debug(
                                driver,
                                pasta_debug,
                                job["nome"].replace("/", "-")[:40],
                                erro=str(e_rede),
                            )
                # Volta para a home para a proxima exportacao.
                driver.get(cfg["url"])
                time.sleep(6)
            except Exception as e:
                log(f"ERRO em '{job['nome']}': {e}")
                resultados.append((job["nome"], f"ERRO: {e}"))
                painel.concluir_job(idx, "ERRO", str(e)[:80])
                salvar_debug(
                    driver,
                    pasta_debug,
                    job["nome"].replace("/", "-")[:40],
                    erro=str(e),
                )
                if args.debug:
                    log("Modo --debug: navegador permanece aberto. Pressione ENTER neste terminal para encerrar.")
                    try:
                        input()
                    except EOFError:
                        time.sleep(60)
                    break
                # Volta para a home para tentar a proxima exportacao.
                driver.get(cfg["url"])
                time.sleep(8)
    except Exception as e:
        log(f"ERRO fatal: {e}")
        houve_erro = True
        painel.set_fase("erro", str(e)[:120])
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass

    log("=" * 60)
    log("Resumo:")
    for nome, status in resultados:
        log(f"  {nome}: {status}")
        if status.startswith("ERRO") or "ERRO rede" in status:
            houve_erro = True
    if pasta_downloads.exists():
        restantes = sorted(p.name for p in pasta_downloads.iterdir() if p.is_file())
        if restantes:
            log(f"Arquivos em downloads/: {', '.join(restantes)}")
    painel.finalizar("Concluido com erros" if houve_erro else "Concluido com sucesso")
    return 1 if houve_erro else 0


if __name__ == "__main__":
    sys.exit(main())
