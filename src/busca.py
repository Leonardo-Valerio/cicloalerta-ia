"""Busca semântica na base de conhecimento (embeddings bge-m3 + similaridade de cosseno).

Com 32 trechos, uma busca exata em numpy é instantânea e mais transparente que um índice
aproximado (FAISS/Chroma). Os vetores ficam em cache em base/embeddings.npy.
"""
import hashlib
import json

import numpy as np

from . import config, ollama_cliente


def carregar_trechos() -> list[dict]:
    linhas = (config.BASE / "trechos.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(l) for l in linhas if l.strip()]


def texto_indexado(t: dict) -> str:
    # A fonte entra no texto indexado: ajuda perguntas como "o que diz o art. 201?"
    return f"{t['fonte']}. {t['texto']}"


class Indice:
    def __init__(self):
        self.trechos = carregar_trechos()
        textos = [texto_indexado(t) for t in self.trechos]
        assinatura = hashlib.sha256((config.MODELO_EMB + "".join(textos)).encode()).hexdigest()[:16]
        cache = config.BASE / f"embeddings_{assinatura}.npy"
        if cache.exists():
            self.vetores = np.load(cache)
        else:
            self.vetores = ollama_cliente.embed(textos)
            np.save(cache, self.vetores)
        self.por_id = {t["id"]: t for t in self.trechos}
        # Cache das perguntas já vetorizadas: evita recarregar o modelo de embeddings a cada
        # pergunta (em máquina com 8 GB, embeddings e LLM não cabem juntos na memória).
        self._arq_cache = config.BASE / f"cache_consultas_{config.MODELO_EMB.replace(':', '_')}.json"
        self._cache = json.loads(self._arq_cache.read_text(encoding="utf-8")) if self._arq_cache.exists() else {}

    def pre_calcular(self, perguntas: list[str]):
        novas = [p for p in dict.fromkeys(perguntas) if p not in self._cache]
        if novas:
            for p, v in zip(novas, ollama_cliente.embed(novas)):
                self._cache[p] = v.round(6).tolist()
            self._arq_cache.write_text(json.dumps(self._cache), encoding="utf-8")

    def vetor(self, pergunta: str) -> np.ndarray:
        if pergunta in self._cache:
            return np.array(self._cache[pergunta], dtype=np.float32)
        return ollama_cliente.embed([pergunta])[0]

    def buscar(self, pergunta: str, k: int = config.TOP_K) -> list[tuple[dict, float]]:
        q = self.vetor(pergunta)
        notas = self.vetores @ q
        ordem = np.argsort(-notas)[:k]
        return [(self.trechos[i], float(notas[i])) for i in ordem]
