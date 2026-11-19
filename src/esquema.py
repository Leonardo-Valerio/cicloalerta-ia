"""Formato de saída obrigatório do assistente e validação com Pydantic."""
import json

from pydantic import BaseModel, ValidationError

from . import ollama_cliente

RECUSA = "Não consta na base de conhecimento do CicloAlerta."


class Resposta(BaseModel):
    resposta: str
    fonte: str
    consta: bool


def recusa(motivo: str = "") -> dict:
    return {"resposta": RECUSA, "fonte": "", "consta": False, "motivo": motivo}


def gerar_validado(sistema: str, usuario: str, tentativas: int = 2) -> tuple[dict | None, int, str]:
    """Chama o LLM e valida o JSON. Repete uma vez se vier inválido.

    Devolve (resposta_validada_ou_None, nº de tentativas usadas, texto bruto da última tentativa).
    """
    bruto = ""
    for n in range(1, tentativas + 1):
        bruto = ollama_cliente.conversar(sistema, usuario)
        try:
            return Resposta.model_validate(json.loads(bruto)).model_dump(), n, bruto
        except (json.JSONDecodeError, ValidationError):
            usuario = (usuario + "\n\nATENÇÃO: sua resposta anterior não era um JSON válido. "
                       'Responda SOMENTE com {"resposta": str, "fonte": str, "consta": bool}.')
    return None, tentativas, bruto
