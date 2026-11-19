# Fontes da base de conhecimento

A base fica em [`trechos.jsonl`](trechos.jsonl): um trecho por linha, com `id`, `fonte`, `url`, `tema` e `texto`.
Os trechos legais foram copiados do texto oficial, sem paráfrase; `(...)` marca incisos omitidos por não tratarem de bicicletas.

| Fonte | Formato de origem | Licença / uso | Nº de trechos |
| --- | --- | --- | --- |
| Código de Trânsito Brasileiro, Lei nº 9.503/1997 (texto compilado, Planalto) | HTML | Ato oficial, não protegido por direito autoral (Lei 9.610/1998, art. 8º, IV) | 14 |
| Resolução Contran nº 996/2023 | HTML | Ato oficial, não protegido por direito autoral (Lei 9.610/1998, art. 8º, IV) | 9 |
| Prefeitura de São Paulo, páginas das Subprefeituras Ipiranga e Sapopemba sobre Tapa-Buraco / SP156 | HTML | Informação pública de órgão municipal, citada com fonte | 3 |
| FAQ CicloAlerta (escrito pela equipe) | Markdown | CC BY 4.0, autoria da equipe | 6 |
| **Total** | | | **32** |

## Como os trechos foram feitos

1. O HTML oficial foi baixado e convertido para texto (tags removidas, texto revogado `<strike>` descartado).
2. Cada trecho corresponde a **um dispositivo legal** (artigo, parágrafo ou inciso) ou a **um assunto** do FAQ, para que a citação aponte exatamente de onde a resposta veio.
3. Trechos curtos (até ~120 palavras) deixam a busca mais precisa e cabem no contexto de um modelo de 3B.

## FAQ CicloAlerta

Os trechos `faq-*` descrevem as regras do próprio produto (como reportar, quando um alerta é emitido, o que é guardado).
As regras de alerta são as mesmas usadas pelo bot de triagem do componente de Automação (repositório `rpa`), para que o assistente e o bot nunca se contradigam.
