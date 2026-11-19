"""Configuração central. Tudo pode ser trocado por variável de ambiente (nada de segredo no código)."""
import json
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BASE = RAIZ / "base"
AVALIACAO = RAIZ / "avaliacao"

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
MODELO_LLM = os.getenv("MODELO_LLM", "qwen2.5:3b")
MODELO_EMB = os.getenv("MODELO_EMB", "bge-m3")
MVP_URL = os.getenv("MVP_URL", "http://127.0.0.1:8000")  # API do CicloAlerta (ou o mock do repo rpa)
TIMEOUT_LLM = int(os.getenv("TIMEOUT_LLM", "180"))
TOP_K = 3

# Coordenadas e caixas aproximadas das ciclovias da área piloto
CICLOVIAS = {
    "paulista": {"nome": "Av. Paulista", "lat": -23.5614, "lon": -46.6559,
                 "caixa": (-23.5720, -23.5530, -46.6650, -46.6420)},
    "faria lima": {"nome": "Av. Brigadeiro Faria Lima", "lat": -23.5786, "lon": -46.6869,
                   "caixa": (-23.5980, -23.5650, -46.6950, -46.6730)},
}


def limiar_busca() -> float:
    """Limiar de similaridade escolhido no notebook 01 (salvo em avaliacao/limiar.json)."""
    arq = AVALIACAO / "limiar.json"
    if arq.exists():
        return float(json.loads(arq.read_text(encoding="utf-8"))["limiar"])
    return 0.50
