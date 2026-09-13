#!/usr/bin/env python
"""
Script standalone (sem Django) para rodar no GitHub Actions: raspa a tabela
pública do INMET com um Chrome real (Selenium) e envia as leituras prontas
para o endpoint /api/ingest/readings/ do backend hospedado no HostGator.

Existe como arquivo separado — em vez de reusar o management command do
Django — porque este script roda numa máquina que NÃO tem acesso ao banco
de dados de produção (só à internet pública). Ele fala com o backend só
via a API HTTP, nunca direto com o banco.

Variáveis de ambiente esperadas:
  INGEST_URL            ex: https://cemaden.preservess.com.br/api/ingest/readings/
  INGEST_SHARED_SECRET  mesmo valor configurado em Django (INGEST_SHARED_SECRET)

Uso: python scrape_inmet_and_push.py
"""

from __future__ import annotations

import datetime as dt
import math
import os
import re
import sys
import unicodedata
from io import StringIO

import requests

STATIONS_URL = "https://apitempo.inmet.gov.br/estacoes/T"
TABELA_URL_TEMPLATE = "https://tempo.inmet.gov.br/TabelaEstacoes/{codigo}"
UF_ALVO = "RJ"


def buscar_estacoes_rj() -> list[dict]:
    resp = requests.get(STATIONS_URL, timeout=30)
    resp.raise_for_status()
    return [item for item in resp.json() if item.get("SG_ESTADO") == UF_ALVO]


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return sem_acento.upper()


def _achar_coluna(colunas, tokens_obrigatorios: list[str]) -> str | None:
    for c in colunas:
        if all(tok in _normalizar(str(c)) for tok in tokens_obrigatorios):
            return c
    return None


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


def _parse_data_hora(data_val, hora_val) -> dt.datetime | None:
    import pandas as pd

    if data_val is None or hora_val is None:
        return None
    if (isinstance(data_val, float) and math.isnan(data_val)) or pd.isna(data_val):
        return None
    if (isinstance(hora_val, float) and math.isnan(hora_val)) or pd.isna(hora_val):
        return None
    data_str = re.sub(r"\s+", "", str(data_val))
    try:
        hora_num = int(float(str(hora_val).strip()))
    except (TypeError, ValueError):
        return None
    try:
        naive = dt.datetime.strptime(f"{data_str} {hora_num:04d}", "%d/%m/%Y %H%M")
    except ValueError:
        return None
    return naive.replace(tzinfo=dt.timezone.utc)


def _dismiss_alert_if_any(driver) -> None:
    try:
        driver.switch_to.alert.dismiss()
    except Exception:  # noqa: BLE001
        pass


def consultar_estacao(driver, codigo: str) -> dict | None:
    import pandas as pd
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    driver.get(TABELA_URL_TEMPLATE.format(codigo=codigo))
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
        df.columns = [" ".join(str(x) for x in c if str(x) != "nan").strip() for c in df.columns]
    df.columns = [str(c).strip() for c in df.columns]

    col_data = _achar_coluna(df.columns, ["DATA"])
    col_hora = _achar_coluna(df.columns, ["HORA"])
    if col_data is None or col_hora is None:
        return None

    colunas_variaveis = {
        "temperatura_c": _achar_coluna(df.columns, ["TEMPERATURA", "INST"]),
        "umidade_pct": _achar_coluna(df.columns, ["UMIDADE", "INST"]),
        "vento_ms": _achar_coluna(df.columns, ["VENTO", "VEL"]),
        "vento_rajada_ms": _achar_coluna(df.columns, ["VENTO", "RAJ"]),
        "vento_dir_graus": _achar_coluna(df.columns, ["VENTO", "DIR"]),
        "chuva_mm": _achar_coluna(df.columns, ["CHUVA"]),
    }

    melhor = None
    melhor_ts = None
    for _, row in df.iterrows():
        timestamp = _parse_data_hora(row.get(col_data), row.get(col_hora))
        if timestamp is None:
            continue
        valores = {chave: (_to_float(row.get(col)) if col else None) for chave, col in colunas_variaveis.items()}
        if not any(v is not None for v in valores.values()):
            continue
        if melhor_ts is None or timestamp > melhor_ts:
            melhor_ts = timestamp
            melhor = {"timestamp": timestamp, **valores}
    return melhor


def montar_readings(codigo: str, linha: dict) -> list[dict]:
    timestamp = linha["timestamp"].isoformat()
    out = []
    for chave in ("temperatura_c", "umidade_pct", "vento_ms", "vento_rajada_ms", "vento_dir_graus", "chuva_mm"):
        valor = linha.get(chave)
        if valor is None:
            continue
        out.append({"external_id": codigo, "reading_type": chave, "value": valor, "timestamp": timestamp})
    return out


def main() -> int:
    ingest_url = os.environ.get("INGEST_URL", "").strip()
    ingest_secret = os.environ.get("INGEST_SHARED_SECRET", "").strip()
    if not ingest_url or not ingest_secret:
        print("Defina INGEST_URL e INGEST_SHARED_SECRET nas variáveis de ambiente.", file=sys.stderr)
        return 1

    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1280,1024")
    options.add_argument("--log-level=3")
    options.set_capability("unhandledPromptBehavior", "dismiss")

    estacoes = buscar_estacoes_rj()
    print(f"{len(estacoes)} estações do INMET no RJ.")

    readings: list[dict] = []
    driver = webdriver.Chrome(options=options)
    try:
        for item in estacoes:
            codigo = item["CD_ESTACAO"]
            try:
                linha = consultar_estacao(driver, codigo)
            except Exception as exc:  # noqa: BLE001
                print(f"  {codigo}: falhou ({exc})")
                _dismiss_alert_if_any(driver)
                continue
            if linha is None:
                print(f"  {codigo}: sem dados válidos")
                continue
            novas = montar_readings(codigo, linha)
            readings.extend(novas)
            print(f"  {codigo}: {len(novas)} leituras")
    finally:
        driver.quit()

    if not readings:
        print("Nenhuma leitura coletada — nada para enviar.")
        return 0

    resp = requests.post(
        ingest_url,
        json={"source_slug": "inmet", "readings": readings},
        headers={"X-Ingest-Secret": ingest_secret},
        timeout=60,
    )
    print(f"POST {ingest_url} -> {resp.status_code}: {resp.text[:500]}")
    resp.raise_for_status()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
