"""Cliente mínimo da API REST do Ollama (LLM e embeddings locais)."""
import time

import numpy as np
import requests

from . import config


def disponivel() -> bool:
    try:
        return requests.get(f"{config.OLLAMA_URL}/api/tags", timeout=3).ok
    except requests.RequestException:
        return False


def _post(rota: str, corpo: dict, tentativas: int = 3) -> dict:
    """POST com repetição: na primeira carga o Ollama pode devolver 500 enquanto troca de modelo."""
    for n in range(1, tentativas + 1):
        try:
            r = requests.post(f"{config.OLLAMA_URL}{rota}", json=corpo, timeout=config.TIMEOUT_LLM)
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            if n == tentativas:
                raise
            time.sleep(10 * n)


def embed(textos: list[str]) -> np.ndarray:
    """Devolve vetores normalizados (norma 1), então produto escalar = similaridade de cosseno."""
    d = _post("/api/embed", {"model": config.MODELO_EMB, "input": textos})
    v = np.array(d["embeddings"], dtype=np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def conversar(sistema: str, usuario: str, formato_json: bool = True, temperatura: float = 0.0,
              esquema: dict | None = None) -> str:
    """`esquema` (JSON Schema) restringe a saída do modelo; sem ele, `formato_json` pede só um JSON qualquer."""
    corpo = {
        "model": config.MODELO_LLM,
        "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}],
        "stream": False,
        "options": {"temperature": temperatura, "num_ctx": 4096, "seed": 42},
    }
    if esquema is not None:
        corpo["format"] = esquema
    elif formato_json:
        corpo["format"] = "json"
    return _post("/api/chat", corpo)["message"]["content"]
