"""API do assistente do CicloAlerta.

    uvicorn api.main:app --port 8001      (de dentro da pasta ia/)

POST /perguntar  {"pergunta": "...", "modo": "agente" | "rag"}
GET  /health

LGPD: a pergunta não é gravada em disco nem associada a IP ou usuário.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src import ollama_cliente
from src.busca import Indice
from src.esquema import RECUSA
from src.pipelines import agente_v2, rag

estado: dict = {}


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    try:
        estado["indice"] = Indice()
    except Exception:  # Ollama fora do ar na subida: a API sobe mesmo assim e responde 503
        estado["indice"] = None
    yield


app = FastAPI(title="CicloAlerta · Assistente", version="1.0", lifespan=ciclo_de_vida)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])


class Pergunta(BaseModel):
    pergunta: str = Field(min_length=3, max_length=300)
    modo: str = Field(default="agente", pattern="^(agente|rag)$")


@app.get("/health")
def health():
    return {"status": "ok", "llm": ollama_cliente.disponivel(), "indice": estado.get("indice") is not None}


@app.post("/perguntar")
def perguntar(p: Pergunta):
    if estado.get("indice") is None:
        try:
            estado["indice"] = Indice()
        except Exception:
            raise HTTPException(503, "Assistente indisponível no momento. Tente novamente em instantes.")
    indice = estado["indice"]
    try:
        r = (agente_v2 if p.modo == "agente" else rag)(p.pergunta, indice)
    except Exception:
        # Degradação elegante: sem LLM, devolve o trecho mais parecido para a pessoa ler.
        try:
            t, nota = indice.buscar(p.pergunta, k=1)[0]
        except Exception:
            raise HTTPException(503, "Assistente indisponível no momento. Tente novamente em instantes.")
        return {"resposta": f"O assistente está fora do ar. Trecho mais relevante: {t['texto']}" if nota >= 0.5 else RECUSA,
                "fonte": t["id"] if nota >= 0.5 else "", "consta": nota >= 0.5, "degradado": True}
    return {k: r[k] for k in ("resposta", "fonte", "consta")} | {"passos": r.get("passos", []), "degradado": False}
