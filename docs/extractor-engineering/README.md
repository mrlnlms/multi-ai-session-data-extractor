# Extractor engineering

Documentacao tecnica da captura: descoberta empirica, comportamento upstream,
reconciliacao, parser e validacao entre plataformas. Nao e leitura necessaria
para operar o projeto normalmente; para isso, use [SETUP.md](../SETUP.md) e
[operations/pipeline.md](../operations/pipeline.md).

Antes de alterar uma fonte, leia `AGENTS.md`, o `state.md` da plataforma e o
schema em `src/schema/models.py`. Codigo e dados observaveis prevalecem sobre
registros historicos.

## Documentos desta familia

- [platforms/README.md](platforms/README.md) — indice tecnico de cada fonte.
- [cross-platform-findings.md](cross-platform-findings.md) — padroes e
  decisoes que se aplicam a mais de uma fonte.
- [cross-platform-validation.md](cross-platform-validation.md) — matriz viva
  de validacao de features entre plataformas.
- [known-limitations.md](known-limitations.md) — limites upstream, cobertura
  pendente e limites de validacao conhecidos.
- [glossary.md](glossary.md) — termos de captura, reconciliacao e parser.
- [adding-a-platform.md](adding-a-platform.md) — roteiro para introduzir ou
  promover uma fonte.

## Padrao por plataforma

```text
platforms/
├── web/<platform>/
│   ├── state.md             # estado atual e ponto de entrada
│   ├── discovery.md         # evidencia e investigacao tecnica detalhada
│   ├── server-behavior.md   # fatos upstream validados empiricamente
│   └── incident-*.md        # incidente grande, autocontido e datado
└── cli/<platform>/
    └── state.md             # estado atual, captura e recovery local
```

`state.md` e o documento canonico para toda fonte. Em fontes web,
`discovery.md` guarda schema, endpoints, probes e decisoes tecnicas, enquanto
`server-behavior.md` guarda o que foi observado no servidor ou UI. Uma CLI nao
ganha esses arquivos artificialmente: seu `state.md` concentra a evidencia que
ela realmente possui.

Evite separar arquivos por costume historico: junte documentos que repetem a
mesma evidencia, mas nao descarte detalhes de probe que ainda expliquem uma
decisao no codigo. Fatos de uma unica fonte pertencem ao diretorio dela;
padroes que realmente atravessam fontes pertencem aos documentos
cross-platform.

## Onde registrar trabalho novo

- Endpoint, schema, fixture ou edge case de uma fonte: `discovery.md`.
- Efeito observado de CRUD, listagem, login ou API: `server-behavior.md`.
- Gap confirmado ou limite de plano/conta: `known-limitations.md`.
- Feature comparada entre fontes: `cross-platform-validation.md`.
- Padrao reutilizavel de extractor, reconciler ou parser:
  `cross-platform-findings.md`.

O procedimento de coleta web fica em
[operations/web-collection.md](../operations/web-collection.md); handoffs
datados pertencem ao historico privado.

O guia [adding-a-platform.md](adding-a-platform.md) concentra o procedimento e
as licoes recorrentes de implementacao; este README apenas indica onde cada
tipo de evidencia deve viver.
