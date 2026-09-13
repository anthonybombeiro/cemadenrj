"""
Conector para a API/site público do INMET (Instituto Nacional de Meteorologia).

Endpoints/páginas confirmados manualmente em setembro/2026:
  - GET https://apitempo.inmet.gov.br/estacoes/T (sem autenticação)
    Lista todas as estações automáticas do país. Usado para popular
    `Station`. Campo "SG_ESTADO" filtra por UF.

  - GET https://apitempo.inmet.gov.br/token/estacao/{inicio}/{fim}/{codigo}/{token}
    Série horária oficial via API — precisa de um token que não tem
    cadastro de autoatendimento (ver docs/fontes-de-dados.md e
    docs/email-inmet-rascunho.md). Usado automaticamente se
    `INMET_API_TOKEN` estiver configurado.

  - https://tempo.inmet.gov.br/TabelaEstacoes/{codigo} (página pública, sem
    login) — mostra a mesma tabela horária (temperatura, umidade, pressão,
    vento, radiação, chuva) só que renderizada em HTML. Solução TEMPORÁRIA
    enquanto não há token: renderiza a página com um Chrome real via
    Selenium e faz parsing da tabela — mesma técnica que o usuário já usa
    em produção para consultar vento. Funciona porque a validação
    anti-robô da página (reCAPTCHA Enterprise invisível, confirmado nesta
    sessão inspecionando as chamadas de rede) roda no JS da própria
    página: um navegador de verdade carregando a página normalmente já
    resolve isso sozinho, sem nenhuma ação nossa de contornar captcha —
    não é diferente de um humano abrindo a página no Chrome.

    IMPORTANTE — limitação conhecida: isso exige Google Chrome instalado
    na máquina que roda a ingestão. NÃO funciona no plano compartilhado do
    HostGator (sem root para instalar Chrome) — só em desenvolvimento
    local ou num futuro VPS/servidor com Chrome headless instalado. Ver
    docs/fontes-de-dados.md.
"""

from __future__ import annotations

import datetime as dt
import logging
import math
import re
import unicodedata
from io import StringIO

import requests
from django.conf import settings

from core.models import Reading, Station

from .base import BaseConnector

logger = logging.getLogger("ingestion")

STATIONS_URL = "https://apitempo.inmet.gov.br/estacoes/T"
READINGS_URL_TEMPLATE = "https://apitempo.inmet.gov.br/token/estacao/{inicio}/{fim}/{codigo}/{token}"
TABELA_URL_TEMPLATE = "https://tempo.inmet.gov.br/TabelaEstacoes/{codigo}"

UF_ALVO = "RJ"


class InmetConnector(BaseConnector):
    slug = "inmet"
    name = "INMET — Instituto Nacional de Meteorologia"
    website = "https://portal.inmet.gov.br"
    description = "Estações meteorológicas automáticas do INMET no estado do RJ."

    def fetch_stations(self) -> list[dict]:
        resp = requests.get(STATIONS_URL, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        stations = []
        for item in data:
            if item.get("SG_ESTADO") != UF_ALVO:
                continue
            try:
                lat = float(item["VL_LATITUDE"])
                lon = float(item["VL_LONGITUDE"])
            except (TypeError, ValueError, KeyError):
                logger.warning("Estação INMET %s sem lat/lon válidos, ignorada.", item.get("CD_ESTACAO"))
                continue

            situacao = (item.get("CD_SITUACAO") or "").strip().lower()
            status = Station.Status.ATIVA if situacao == "operante" else Station.Status.INATIVA

            nome = item.get("DC_NOME") or item.get("CD_ESTACAO")
            municipio = nome.split(" - ")[0].title() if nome else ""

            altitude = None
            if item.get("VL_ALTITUDE") not in (None, ""):
                try:
                    altitude = float(item["VL_ALTITUDE"])
                except (TypeError, ValueError):
                    altitude = None

            stations.append(
                {
                    "external_id": item["CD_ESTACAO"],
                    "name": nome,
                    "municipality": municipio,
                    "station_type": Station.StationType.METEOROLOGICA,
                    "status": status,
                    "latitude": lat,
                    "longitude": lon,
                    "altitude_m": altitude,
                    "raw_metadata": item,
                }
            )
        return stations

    def fetch_readings(self, stations: list[dict]) -> list[dict]:
        token = getattr(settings, "INMET_API_TOKEN", "")
        if token:
            try:
                return self._fetch_readings_via_token(stations, token)
            except Exception:  # noqa: BLE001
                logger.exception("Falha usando o token da API do INMET, tentando scraping como fallback.")

        if not getattr(settings, "INMET_SCRAPE_ENABLED", True):
            logger.info("INMET: sem token e scraping desabilitado (INMET_SCRAPE_ENABLED=False) — pulando leituras.")
            return []

        try:
            return self._fetch_readings_via_scraping(stations)
        except Exception:  # noqa: BLE001
            logger.exception("Falha no scraping do INMET (Selenium/Chrome). Verifique se o Chrome está instalado.")
            return []

    # -- Método 1: API oficial (precisa de token) -----------------------------

    def _fetch_readings_via_token(self, stations: list[dict], token: str) -> list[dict]:
        hoje = dt.date.today()
        ontem = hoje - dt.timedelta(days=1)
        readings: list[dict] = []

        for st in stations:
            codigo = st["external_id"]
            url = READINGS_URL_TEMPLATE.format(inicio=ontem.isoformat(), fim=hoje.isoformat(), codigo=codigo, token=token)
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
            if not isinstance(payload, list):
                logger.warning("Resposta inesperada do INMET (token) para %s: %r", codigo, payload)
                continue

            for row in payload:
                timestamp = _parse_timestamp_api(row)
                if timestamp is None:
                    continue
                for campo_origem, reading_type in (
                    ("CHUVA", Reading.ReadingType.CHUVA_MM),
                    ("TEM_INS", Reading.ReadingType.TEMPERATURA_C),
                    ("UMD_INS", Reading.ReadingType.UMIDADE_PCT),
                    ("VEN_VEL", Reading.ReadingType.VENTO_MS),
                    ("VEN_RAJ", Reading.ReadingType.VENTO_RAJADA_MS),
                    ("VEN_DIR", Reading.ReadingType.VENTO_DIR_GRAUS),
                ):
                    valor = _to_float(row.get(campo_origem))
                    if valor is None:
                        continue
                    readings.append(
                        {
                            "external_id": codigo,
                            "reading_type": reading_type,
                            "value": valor,
                            "timestamp": timestamp,
                            "raw_payload": row,
                        }
                    )
        return readings

    # -- Método 2: scraping da tabela pública via Selenium (temporário) ------

    def _fetch_readings_via_scraping(self, stations: list[dict]) -> list[dict]:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        options = Options()
        if getattr(settings, "INMET_SCRAPE_HEADLESS", True):
            options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--window-size=1280,1024")
        options.add_argument("--log-level=3")
        # Algumas estações disparam um alert() JS quando um widget lateral da
        # página (ex.: lista de estações próximas) falha ao carregar. Sem
        # isso, o alert trava a navegação seguinte com
        # UnexpectedAlertPresentException.
        options.set_capability("unhandledPromptBehavior", "dismiss")

        readings: list[dict] = []
        driver = webdriver.Chrome(options=options)
        try:
            for st in stations:
                codigo = st["external_id"]
                nome = st["name"]
                try:
                    linha = _consultar_estacao(driver, codigo, WebDriverWait, EC, By)
                except Exception:  # noqa: BLE001
                    logger.exception("Falha ao raspar tabela do INMET para %s (%s)", codigo, nome)
                    _dismiss_alert_if_any(driver)
                    continue
                if linha is None:
                    continue
                readings.extend(_linha_para_readings(codigo, linha))
        finally:
            driver.quit()
        return readings


# ---------------------------------------------------------------------------
# Scraping: replica a técnica já usada pelo usuário para consultar vento,
# generalizada para também capturar chuva/temperatura/umidade da mesma
# tabela (todas as variáveis vêm juntas na mesma página/linha).
# ---------------------------------------------------------------------------


def _consultar_estacao(driver, codigo: str, WebDriverWait, EC, By) -> dict | None:
    import pandas as pd

    url = TABELA_URL_TEMPLATE.format(codigo=codigo)
    driver.get(url)

    try:
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "table")))
    except Exception:  # noqa: BLE001
        return None

    tabelas = driver.find_elements(By.TAG_NAME, "table")
    if not tabelas:
        return None

    tabela = next((t for t in tabelas if "VENTO" in _normalizar(t.text)), tabelas[0])
    html = tabela.get_attribute("outerHTML")

    try:
        tabelas_df = pd.read_html(StringIO(html), decimal=",", thousands=".")
    except ValueError:
        return None
    if not tabelas_df:
        return None

    df = tabelas_df[0]
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [
            " ".join(str(x) for x in coluna if str(x) != "nan").strip() for coluna in df.columns
        ]
    df.columns = [str(c).strip() for c in df.columns]

    col_data = _achar_coluna(df.columns, ["DATA"])
    col_hora = _achar_coluna(df.columns, ["HORA"])
    if col_data is None or col_hora is None:
        return None

    col_temp = _achar_coluna(df.columns, ["TEMPERATURA", "INST"])
    col_umid = _achar_coluna(df.columns, ["UMIDADE", "INST"])
    col_vento_vel = _achar_coluna(df.columns, ["VENTO", "VEL"])
    col_vento_raj = _achar_coluna(df.columns, ["VENTO", "RAJ"])
    col_vento_dir = _achar_coluna(df.columns, ["VENTO", "DIR"])
    col_chuva = _achar_coluna(df.columns, ["CHUVA"])

    melhor_linha = None
    melhor_timestamp = None
    for _, row in df.iterrows():
        timestamp = _parse_data_hora_tabela(row.get(col_data), row.get(col_hora))
        if timestamp is None:
            continue
        valores = {
            "temperatura_c": _to_float(row.get(col_temp)) if col_temp else None,
            "umidade_pct": _to_float(row.get(col_umid)) if col_umid else None,
            "vento_ms": _to_float(row.get(col_vento_vel)) if col_vento_vel else None,
            "vento_rajada_ms": _to_float(row.get(col_vento_raj)) if col_vento_raj else None,
            "vento_dir_graus": _to_float(row.get(col_vento_dir)) if col_vento_dir else None,
            "chuva_mm": _to_float(row.get(col_chuva)) if col_chuva else None,
        }
        if not any(v is not None for v in valores.values()):
            continue
        if melhor_timestamp is None or timestamp > melhor_timestamp:
            melhor_timestamp = timestamp
            melhor_linha = {"timestamp": timestamp, **valores}

    return melhor_linha


def _linha_para_readings(codigo: str, linha: dict) -> list[dict]:
    tipo_por_chave = {
        "temperatura_c": Reading.ReadingType.TEMPERATURA_C,
        "umidade_pct": Reading.ReadingType.UMIDADE_PCT,
        "vento_ms": Reading.ReadingType.VENTO_MS,
        "vento_rajada_ms": Reading.ReadingType.VENTO_RAJADA_MS,
        "vento_dir_graus": Reading.ReadingType.VENTO_DIR_GRAUS,
        "chuva_mm": Reading.ReadingType.CHUVA_MM,
    }
    timestamp = linha["timestamp"]
    out = []
    for chave, reading_type in tipo_por_chave.items():
        valor = linha.get(chave)
        if valor is None:
            continue
        out.append(
            {
                "external_id": codigo,
                "reading_type": reading_type,
                "value": valor,
                "timestamp": timestamp,
                "raw_payload": {"fonte": "scraping_tabela_estacoes", **{k: v for k, v in linha.items() if k != "timestamp"}},
            }
        )
    return out


def _dismiss_alert_if_any(driver) -> None:
    try:
        driver.switch_to.alert.dismiss()
    except Exception:  # noqa: BLE001
        pass


def _achar_coluna(colunas, tokens_obrigatorios: list[str]) -> str | None:
    for c in colunas:
        norm = _normalizar(str(c))
        if all(tok in norm for tok in tokens_obrigatorios):
            return c
    return None


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return sem_acento.upper()


def _to_float(valor) -> float | None:
    if valor is None:
        return None
    if isinstance(valor, float) and math.isnan(valor):
        return None

    texto = str(valor).strip()
    if texto in ("", "--", "-", "nan", "NaN", "None"):
        return None
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return None


def _parse_data_hora_tabela(data_val, hora_val) -> dt.datetime | None:
    if data_val is None or hora_val is None:
        return None
    if isinstance(data_val, float) and math.isnan(data_val):
        return None
    if isinstance(hora_val, float) and math.isnan(hora_val):
        return None

    data_str = re.sub(r"\s+", "", str(data_val))
    try:
        hora_num = int(float(str(hora_val).strip()))
    except (TypeError, ValueError):
        return None
    hora_str = f"{hora_num:04d}"

    try:
        naive = dt.datetime.strptime(f"{data_str} {hora_str}", "%d/%m/%Y %H%M")
    except ValueError:
        return None
    # A coluna "Hora" da tabela do INMET já é UTC (confirmado no cabeçalho da página).
    return naive.replace(tzinfo=dt.timezone.utc)


def _parse_timestamp_api(row: dict) -> dt.datetime | None:
    data = row.get("DT_MEDICAO")
    hora = row.get("HR_MEDICAO")
    if not data or hora is None:
        return None
    try:
        hora_str = str(hora).zfill(4)
        naive = dt.datetime.strptime(f"{data} {hora_str}", "%Y-%m-%d %H%M")
        return naive.replace(tzinfo=dt.timezone.utc)
    except ValueError:
        logger.warning("Timestamp INMET (API) inesperado: DT_MEDICAO=%r HR_MEDICAO=%r", data, hora)
        return None
