"""Ferramentas que o agente pode chamar além da base: chuva (Open-Meteo) e dados do MVP.

Cada ferramenta devolve uma lista de evidências {"id", "texto"}. O id vira a `fonte` citada.
Se o serviço estiver fora do ar, a ferramenta devolve lista vazia e o agente recusa (sem inventar).
"""
from collections import Counter

import requests

from . import config

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"


def _ciclovia(local: str | None) -> list[str]:
    if local:
        l = local.lower()
        achadas = [k for k in config.CICLOVIAS if k in l or k.split()[0] in l]
        if achadas:
            return achadas
    return list(config.CICLOVIAS)


def clima(local: str | None) -> list[dict]:
    evid = []
    for chave in _ciclovia(local):
        c = config.CICLOVIAS[chave]
        try:
            r = requests.get(OPEN_METEO, timeout=10, params={
                "latitude": c["lat"], "longitude": c["lon"], "timezone": "America/Sao_Paulo",
                "current": "precipitation,rain", "hourly": "precipitation,precipitation_probability",
                "forecast_hours": 3})
            r.raise_for_status()
            d = r.json()
        except requests.RequestException:
            continue
        agora = d["current"]["precipitation"]
        horas = d["hourly"]["time"]
        prec = d["hourly"]["precipitation"]
        prob = d["hourly"]["precipitation_probability"]
        prox = "; ".join(f"{h[11:16]}: {p} mm ({pp}% de chance)" for h, p, pp in zip(horas, prec, prob))
        evid.append({"id": f"open-meteo:{chave}",
                     "texto": f"Open-Meteo, {c['nome']}, consulta de {d['current']['time']}: "
                              f"precipitação agora {agora} mm. Próximas horas: {prox}.",
                     "dados": {"ciclovia": c["nome"], "agora_mm": agora,
                               "horas": [(h[11:16], p, pp) for h, p, pp in zip(horas, prec, prob)]}})
    return evid


def _dentro(rel: dict, caixa) -> bool:
    lat, lon = rel.get("lat"), rel.get("lon")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return False  # relato sem coordenada (o bot de RPA põe esses em quarentena)
    lat_min, lat_max, lon_min, lon_max = caixa
    return lat_min <= lat <= lat_max and lon_min <= lon <= lon_max


def relatos(local: str | None) -> list[dict]:
    try:
        r = requests.get(f"{config.MVP_URL}/api/relatos", timeout=10)
        r.raise_for_status()
        todos = r.json()
    except requests.RequestException:
        return []
    evid = []
    for chave in _ciclovia(local):
        c = config.CICLOVIAS[chave]
        dentro = [x for x in todos if _dentro(x, c["caixa"])]
        tipos = Counter(x.get("tipo", "?") for x in dentro)
        sev = Counter(x.get("severidade", "?") for x in dentro)
        evid.append({"id": f"api:relatos:{chave}",
                     "texto": f"API do CicloAlerta, ciclovia {c['nome']}: {len(dentro)} perigos reportados. "
                              f"Por tipo: {dict(tipos)}. Por severidade: {dict(sev)}.",
                     "dados": {"ciclovia": c["nome"], "total": len(dentro), "tipos": dict(tipos),
                               "severidades": dict(sev)}})
    return evid


def alertas(local: str | None = None) -> list[dict]:
    try:
        r = requests.get(f"{config.MVP_URL}/api/alertas", timeout=10)
        r.raise_for_status()
        ativos = r.json()
    except requests.RequestException:
        return []
    criticos = [a for a in ativos if a.get("nivel") == "critico"]
    atencao = [a for a in ativos if a.get("nivel") == "atencao"]
    exemplos = "; ".join(f"{a.get('tipo','?')} em {a.get('ciclovia','?')} ({a.get('chuva_mm','?')} mm previstos)"
                         for a in criticos[:3])
    return [{"id": "api:alertas",
             "texto": f"API do CicloAlerta: {len(criticos)} alertas críticos e {len(atencao)} alertas de atenção ativos."
                      + (f" Críticos: {exemplos}." if exemplos else ""),
             "dados": {"criticos": criticos, "atencao": atencao}}]


FERRAMENTAS = {"clima": clima, "relatos": relatos, "alertas": alertas}
