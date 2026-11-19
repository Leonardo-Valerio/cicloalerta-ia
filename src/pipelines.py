"""As três configurações comparadas no placar.

1. sem_contexto : o mesmo LLM, só com a pergunta (linha de base).
2. rag          : busca top-3 + limiar de recusa + geração em JSON citando o trecho.
3. agente       : decide a ferramenta (base, clima, relatos, alertas), gera e VERIFICA a resposta
                  (fonte precisa ser uma evidência recebida e todo número citado precisa estar nela).
"""
import json
import re
import time
import unicodedata

from . import config, ferramentas, ollama_cliente
from .busca import Indice
from .esquema import gerar_validado, recusa

FORMATO = ('Responda SOMENTE com um JSON no formato '
           '{"resposta": "<até 3 frases, português simples>", "fonte": "<id da fonte>", "consta": true|false}.')

SISTEMA_SEM_CONTEXTO = (
    "Você é o assistente do CicloAlerta, que orienta ciclistas e entregadores de São Paulo. "
    "Responda à pergunta com o que você sabe. Se não souber, use consta=false. "
    "Em 'fonte', escreva de onde vem a informação. " + FORMATO)

SISTEMA_RAG = (
    "Você é o assistente do CicloAlerta, que orienta ciclistas e entregadores de São Paulo. "
    "Use APENAS as evidências fornecidas. Não use conhecimento próprio. "
    "Se as evidências não respondem à pergunta, devolva consta=false e fonte vazia. "
    "Se respondem, devolva consta=true e em 'fonte' o id EXATO da evidência usada (ex.: ctb-art201). "
    "Copie números e valores exatamente como aparecem na evidência. " + FORMATO)

SISTEMA_ROTEADOR = (
    "Você decide qual ferramenta responde a pergunta de um ciclista. Ferramentas:\n"
    '- "base": leis de trânsito, bicicleta elétrica, como pedir conserto (SP156), regras e privacidade do CicloAlerta.\n'
    '- "clima": chuva agora ou nas próximas horas em uma ciclovia.\n'
    '- "relatos": quantos buracos/perigos estão reportados em uma ciclovia.\n'
    '- "alertas": alertas ativos de trechos perigosos com chuva.\n'
    'Responda SOMENTE com JSON: {"ferramenta": "base|clima|relatos|alertas", "local": "paulista|faria lima|null"}.\n'
    'Exemplos: "vai chover na Paulista?" -> {"ferramenta": "clima", "local": "paulista"}; '
    '"bicicleta elétrica precisa de placa?" -> {"ferramenta": "base", "local": null}; '
    '"tem buraco reportado na Faria Lima?" -> {"ferramenta": "relatos", "local": "faria lima"}; '
    '"como o CicloAlerta decide um alerta crítico?" -> {"ferramenta": "base", "local": null}.')


def _evidencias_texto(evid: list[dict]) -> str:
    return "\n".join(f"[{e['id']}] {e['texto']}" for e in evid)


def _resultado(saida: dict | None, tentativas: int, inicio: float, extra: dict) -> dict:
    json_ok = saida is not None
    if saida is None:
        saida = recusa("json_invalido")
    saida.update({"json_valido": json_ok, "tentativas_json": tentativas,
                  "latencia_s": round(time.perf_counter() - inicio, 2)}, **extra)
    return saida


# ---------------------------------------------------------------- 1. sem contexto
def sem_contexto(pergunta: str) -> dict:
    t0 = time.perf_counter()
    saida, n, _ = gerar_validado(SISTEMA_SEM_CONTEXTO, f"Pergunta: {pergunta}")
    return _resultado(saida, n, t0, {"evidencias": []})


# ---------------------------------------------------------------- 2. RAG simples
def rag(pergunta: str, indice: Indice, limiar: float | None = None) -> dict:
    t0 = time.perf_counter()
    limiar = config.limiar_busca() if limiar is None else limiar
    achados = indice.buscar(pergunta)
    ids = [(t["id"], round(s, 3)) for t, s in achados]
    if achados[0][1] < limiar:  # abaixo do corte: recusa sem chamar o LLM
        return _resultado(recusa("abaixo_do_limiar"), 0, t0, {"evidencias": ids, "json_valido": True})
    evid = [{"id": t["id"], "texto": f"({t['fonte']}) {t['texto']}"} for t, _ in achados]
    usuario = f"Evidências:\n{_evidencias_texto(evid)}\n\nPergunta: {pergunta}"
    saida, n, _ = gerar_validado(SISTEMA_RAG, usuario)
    return _resultado(saida, n, t0, {"evidencias": ids})


# ---------------------------------------------------------------- 3. agente
def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def rotear(pergunta: str) -> dict:
    try:
        d = json.loads(ollama_cliente.conversar(SISTEMA_ROTEADOR, pergunta))
        if d.get("ferramenta") in ("base", "clima", "relatos", "alertas"):
            local = d.get("local")
            return {"ferramenta": d["ferramenta"], "local": None if local in (None, "null", "") else local}
    except (json.JSONDecodeError, AttributeError):
        pass
    return {"ferramenta": "base", "local": None}  # na dúvida, a opção mais segura


NUMERO = re.compile(r"\d+(?:[.,]\d+)?")


def numeros_sem_apoio(resposta: str, evid: list[dict]) -> list[str]:
    """Números citados na resposta que não aparecem em nenhuma evidência (sinal de alucinação)."""
    base = " ".join(e["texto"] for e in evid)
    base_norm = {n.replace(",", ".") for n in NUMERO.findall(base)}
    return [n for n in NUMERO.findall(resposta) if n.replace(",", ".") not in base_norm]


def agente(pergunta: str, indice: Indice, limiar: float | None = None) -> dict:
    t0 = time.perf_counter()
    return _executar_rota(pergunta, indice, limiar, rotear(pergunta), t0)


def _executar_rota(pergunta: str, indice: Indice, limiar: float | None, rota: dict, t0: float) -> dict:
    """Busca/ferramenta -> geração -> verificação (caminho comum ao agente v1 e v2)."""
    limiar = config.limiar_busca() if limiar is None else limiar
    passos = [f"roteador -> {rota['ferramenta']} ({rota['local']})"]

    if rota["ferramenta"] == "base":
        achados = indice.buscar(pergunta)
        ids = [(t["id"], round(s, 3)) for t, s in achados]
        if achados[0][1] < limiar:
            return _resultado(recusa("abaixo_do_limiar"), 0, t0,
                              {"evidencias": ids, "json_valido": True, "passos": passos + ["recusa: abaixo do limiar"]})
        evid = [{"id": t["id"], "texto": f"({t['fonte']}) {t['texto']}"} for t, _ in achados]
    else:
        evid = ferramentas.FERRAMENTAS[rota["ferramenta"]](rota["local"])
        ids = [(e["id"], None) for e in evid]
        if not evid:
            return _resultado(recusa("ferramenta_indisponivel"), 0, t0,
                              {"evidencias": ids, "json_valido": True, "passos": passos + ["recusa: serviço fora do ar"]})

    usuario = f"Evidências:\n{_evidencias_texto(evid)}\n\nPergunta: {pergunta}"
    total = 0
    for rodada in range(2):  # gera, verifica e, se falhar, tenta uma vez com instrução corretiva
        saida, n, _ = gerar_validado(SISTEMA_RAG, usuario)
        total += n
        if saida is None:
            return _resultado(None, total, t0, {"evidencias": ids, "passos": passos})
        if not saida["consta"]:
            passos.append("modelo recusou")
            break
        problemas = []
        validos = {e["id"] for e in evid}
        if saida["fonte"] not in validos:
            # aceita fonte com texto extra, ex.: "[ctb-art201]" ou "ctb-art201 (CTB)"
            candidata = next((v for v in validos if v in saida["fonte"]), None)
            if candidata:
                saida["fonte"] = candidata
            else:
                problemas.append(f"fonte '{saida['fonte']}' não está nas evidências")
        soltos = numeros_sem_apoio(saida["resposta"], evid)
        if soltos:
            problemas.append(f"números sem apoio na evidência: {soltos}")
        if not problemas:
            passos.append("verificação ok")
            break
        passos.append("verificação falhou: " + "; ".join(problemas))
        if rodada == 0:
            usuario += ("\n\nCORREÇÃO: " + "; ".join(problemas) +
                        ". Use somente o que está escrito nas evidências e cite o id exato.")
        else:
            saida = recusa("verificacao_falhou")
    return _resultado(saida, total, t0, {"evidencias": ids, "passos": passos})


# ---------------------------------------------------------------- 4. agente v2 (correções dos erros 2 e 4)
# Erro 2: o roteador copiou o molde do prompt como valor ("paulista|faria lima|null") e mandou
#         "quais ciclovias o CicloAlerta cobre hoje?" para a ferramenta de alertas.
#         Correção: saída restrita por JSON Schema com enum + exemplos de perguntas estáticas com "hoje".
# Erro 4: com a evidência "7 alertas críticos", o modelo de 3B respondeu "não há alertas críticos".
#         Correção: clima, relatos e alertas são dados numéricos; a resposta é montada por template, sem LLM.

ESQUEMA_ROTA = {
    "type": "object",
    "properties": {
        "ferramenta": {"type": "string", "enum": ["base", "clima", "relatos", "alertas"]},
        "local": {"type": "string", "enum": ["paulista", "faria lima", "nenhum"]},
    },
    "required": ["ferramenta", "local"],
}

SISTEMA_ROTEADOR_V2 = (
    "Você decide qual ferramenta responde a pergunta de um ciclista.\n"
    '- "base": leis de trânsito, bicicleta elétrica, como pedir conserto (SP156), regras, cobertura e privacidade '
    "do CicloAlerta. Tudo que é regra fixa, MESMO que a pergunta diga 'hoje' ou 'agora'.\n"
    '- "clima": chuva agora ou nas próximas horas.\n'
    '- "relatos": quantos buracos ou perigos estão reportados em uma ciclovia.\n'
    '- "alertas": SÓ para saber se existem alertas ativos neste momento. Como o alerta funciona é "base".\n'
    'Em "local", use "paulista" ou "faria lima" se a pergunta citar a avenida; senão, "nenhum".\n'
    "Exemplos (escritos para o roteador; nenhum deles está no conjunto de teste):\n"
    '"preciso de capa de chuva pra ir pela Paulista agora?" -> {"ferramenta": "clima", "local": "paulista"}\n'
    '"patinete elétrico pode andar na ciclovia?" -> {"ferramenta": "base", "local": "nenhum"}\n'
    '"o CicloAlerta já funciona na zona leste hoje?" -> {"ferramenta": "base", "local": "nenhum"}\n'
    '"o que significa a faixa vermelha que aparece no mapa?" -> {"ferramenta": "base", "local": "nenhum"}\n'
    '"o que fazer hoje se eu vir um buraco?" -> {"ferramenta": "base", "local": "nenhum"}\n'
    '"quantos problemas o pessoal já marcou na Paulista?" -> {"ferramenta": "relatos", "local": "paulista"}\n'
    '"existe aviso de perigo no mapa neste momento?" -> {"ferramenta": "alertas", "local": "nenhum"}')


def rotear_v2(pergunta: str) -> dict:
    try:
        d = json.loads(ollama_cliente.conversar(SISTEMA_ROTEADOR_V2, pergunta, esquema=ESQUEMA_ROTA))
        if d.get("ferramenta") in ("base", "clima", "relatos", "alertas"):
            local = d.get("local")
            return {"ferramenta": d["ferramenta"], "local": local if local in ("paulista", "faria lima") else None}
    except (json.JSONDecodeError, AttributeError):
        pass
    return {"ferramenta": "base", "local": None}


def _plural(n: int, um: str, varios: str) -> str:
    return f"{n} {um if n == 1 else varios}"


LIMIAR_CHUVA_MM = 1.0  # mesmo limiar do bot de RPA e do FAQ do produto


def _mm(v) -> str:
    return f"{v:.1f}".replace(".", ",") + " mm"


def resposta_template(ferramenta: str, evid: list[dict]) -> dict:
    """Resposta montada direto dos dados da API: não há como o modelo ler o número errado."""
    if ferramenta == "clima":
        partes = []
        for e in evid:
            d = e["dados"]
            agora = "está chovendo" if d["agora_mm"] > 0 else "não está chovendo"
            prox = "; ".join(f"{h}: {_mm(p)} ({pp}% de chance)" for h, p, pp in d["horas"])
            maximo = max((p for _, p, _ in d["horas"]), default=0)
            aviso = ("Há previsão de chuva de 1 mm ou mais nas próximas horas: atenção a poças que escondem buracos."
                     if maximo >= LIMIAR_CHUVA_MM else "Não há previsão de chuva de 1 mm ou mais nas próximas horas.")
            partes.append(f"Na {d['ciclovia']}, agora {agora} ({_mm(d['agora_mm'])}). Próximas horas: {prox}. {aviso}")
        return {"resposta": " ".join(partes), "fonte": evid[0]["id"] if len(evid) == 1 else "open-meteo", "consta": True}
    if ferramenta == "relatos":
        partes = []
        nomes = {"buraco": ("buraco", "buracos"), "desnivel": ("desnível", "desníveis"),
                 "poca": ("poça", "poças"), "obstaculo": ("obstáculo", "obstáculos")}
        for e in evid:
            d = e["dados"]
            alta = d["severidades"].get("alta", 0)
            tipos = ", ".join(_plural(v, *nomes.get(k, (k, k)))
                              for k, v in sorted(d["tipos"].items(), key=lambda x: -x[1]))
            partes.append(f"Na ciclovia da {d['ciclovia']} há {_plural(d['total'], 'perigo reportado', 'perigos reportados')}"
                          + (f" ({tipos}), sendo {_plural(alta, 'de severidade alta', 'de severidade alta')}" if d["total"] else "") + ".")
        return {"resposta": " ".join(partes), "fonte": evid[0]["id"] if len(evid) == 1 else "api:relatos", "consta": True}
    d = evid[0]["dados"]
    crit, aten = d["criticos"], d["atencao"]
    if not crit and not aten:
        texto = "Não há alertas ativos agora nas ciclovias da área piloto."
    else:
        texto = f"Há {_plural(len(crit), 'alerta crítico', 'alertas críticos')} e {_plural(len(aten), 'alerta de atenção', 'alertas de atenção')} ativos agora."
        vias = sorted({a.get("ciclovia", "?") for a in crit})
        if vias:
            texto += f" Os críticos estão em: {', '.join(vias)}. Reduza a velocidade nesses trechos."
    return {"resposta": texto, "fonte": evid[0]["id"], "consta": True}


def agente_v2(pergunta: str, indice: Indice, limiar: float | None = None) -> dict:
    t0 = time.perf_counter()
    rota = rotear_v2(pergunta)
    if rota["ferramenta"] in ("clima", "relatos", "alertas"):
        evid = ferramentas.FERRAMENTAS[rota["ferramenta"]](rota["local"])
        passos = [f"roteador -> {rota['ferramenta']} ({rota['local']})"]
        if not evid:
            return _resultado(recusa("ferramenta_indisponivel"), 0, t0,
                              {"evidencias": [], "json_valido": True, "passos": passos + ["recusa: serviço fora do ar"]})
        return _resultado(resposta_template(rota["ferramenta"], evid), 0, t0,
                          {"evidencias": [(e["id"], None) for e in evid], "json_valido": True,
                           "passos": passos + ["resposta por template (dados da API, sem LLM)"]})
    return _executar_rota(pergunta, indice, limiar, rota, t0)


CONFIGURACOES = {"sem_contexto": sem_contexto, "rag": rag, "agente": agente, "agente_v2": agente_v2}
