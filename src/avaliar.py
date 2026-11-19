"""Roda as perguntas de teste nas três configurações e monta o placar.

Uso (de dentro da pasta ia/):
    python -m src.avaliar                 # todas as configurações
    python -m src.avaliar --config rag    # só uma
    python -m src.avaliar --placar        # só recalcula o placar a partir dos resultados salvos

Os resultados são gravados linha a linha em avaliacao/resultados_<config>.jsonl:
se a execução cair, rodar de novo continua de onde parou.
"""
import argparse
import json
import time
import unicodedata

import pandas as pd

from . import config
from .busca import Indice
from .pipelines import CONFIGURACOES


def carregar_perguntas() -> list[dict]:
    linhas = (config.AVALIACAO / "perguntas.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(l) for l in linhas if l.strip()]


def norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(c) != "Mn")


def classificar(p: dict, r: dict) -> str:
    """acerto | alucinacao | recusa_indevida | recusa_segura | erro_json"""
    if not r.get("json_valido", False):
        return "erro_json"
    consta = bool(r.get("consta"))
    if p["tipo"] == "nao_consta":
        return "acerto" if not consta else "alucinacao"
    if p["tipo"] == "dinamica":
        if not consta:
            return "recusa_segura"  # não inventou, mas também não respondeu
        fonte = r.get("fonte", "")
        return "acerto" if fonte.startswith(("open-meteo", "api:")) else "alucinacao"
    # tipo base
    if not consta:
        return "recusa_indevida"
    texto = norm(r.get("resposta", ""))
    ok = all(any(norm(k) in texto for k in grupo) for grupo in p["chaves"])
    return "acerto" if ok else "alucinacao"


def citacao_correta(p: dict, r: dict) -> bool | None:
    if p["tipo"] != "base" or not r.get("consta"):
        return None
    return r.get("fonte") in p["trechos"]


def rodar(nome: str, perguntas: list[dict], indice: Indice | None):
    arq = config.AVALIACAO / f"resultados_{nome}.jsonl"
    feitos = set()
    if arq.exists():
        feitos = {json.loads(l)["id"] for l in arq.read_text(encoding="utf-8").splitlines() if l.strip()}
    fn = CONFIGURACOES[nome]
    with arq.open("a", encoding="utf-8") as f:
        for p in perguntas:
            if p["id"] in feitos:
                continue
            r = None
            for espera in (0, 30, 120):  # falha de infraestrutura (ex.: memória) não vira resultado falso
                time.sleep(espera)
                try:
                    r = fn(p["pergunta"]) if nome == "sem_contexto" else fn(p["pergunta"], indice)
                    break
                except Exception as e:
                    print(f"[{nome}] {p['id']} falhou ({e!r:.120}); tentando de novo", flush=True)
            if r is None:
                print(f"[{nome}] {p['id']} PULADA: rode de novo para completar", flush=True)
                continue
            r.update({"id": p["id"], "config": nome, "pergunta": p["pergunta"], "tipo": p["tipo"]})
            r["classe"] = classificar(p, r)
            r["citacao_correta"] = citacao_correta(p, r)
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            print(f"[{nome}] {p['id']} -> {r['classe']:16s} ({r.get('latencia_s', '?')} s)", flush=True)


def placar() -> pd.DataFrame:
    perguntas = {p["id"]: p for p in carregar_perguntas()}
    linhas = []
    for nome in CONFIGURACOES:
        arq = config.AVALIACAO / f"resultados_{nome}.jsonl"
        if not arq.exists():
            continue
        rs = [json.loads(l) for l in arq.read_text(encoding="utf-8").splitlines() if l.strip()]
        for r in rs:  # reclassifica: permite ajustar o gabarito sem rodar o LLM de novo
            r["classe"] = classificar(perguntas[r["id"]], r)
            r["citacao_correta"] = citacao_correta(perguntas[r["id"]], r)
        df = pd.DataFrame(rs)
        base, nc, din = df[df.tipo == "base"], df[df.tipo == "nao_consta"], df[df.tipo == "dinamica"]
        cit = base["citacao_correta"].dropna()
        linhas.append({
            "configuracao": nome,
            "perguntas": len(df),
            "acerto_total_%": round(100 * (df.classe == "acerto").mean(), 1),
            "alucinacao_%": round(100 * (df.classe == "alucinacao").mean(), 1),
            "acerto_base_%": round(100 * (base.classe == "acerto").mean(), 1),
            "recusa_correta_nao_consta_%": round(100 * (nc.classe == "acerto").mean(), 1),
            "acerto_dinamicas_%": round(100 * (din.classe == "acerto").mean(), 1),
            "citacao_correta_%": round(100 * cit.mean(), 1) if len(cit) else 0.0,
            "json_valido_%": round(100 * df.json_valido.mean(), 1),
            "latencia_media_s": round(df.latencia_s.mean(), 2) if "latencia_s" in df else None,
        })
    tab = pd.DataFrame(linhas)
    tab.to_csv(config.AVALIACAO / "placar.csv", index=False)
    (config.AVALIACAO / "placar.md").write_text(tab.to_markdown(index=False), encoding="utf-8")
    return tab


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", choices=list(CONFIGURACOES), action="append")
    ap.add_argument("--placar", action="store_true")
    a = ap.parse_args()
    if not a.placar:
        perguntas = carregar_perguntas()
        indice = Indice()
        indice.pre_calcular([p['pergunta'] for p in perguntas])  # vetoriza tudo de uma vez
        for nome in a.config or list(CONFIGURACOES):
            rodar(nome, perguntas, indice)
    print(placar().to_string(index=False))


if __name__ == "__main__":
    main()
