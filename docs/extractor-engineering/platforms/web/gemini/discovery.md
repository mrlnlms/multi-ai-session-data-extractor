# Gemini — discovery e contrato de captura

Evidencia tecnica do protocolo `batchexecute` usado pelo extractor. O estado
atual e os efeitos observados de CRUD ficam em [state.md](state.md) e
[server-behavior.md](server-behavior.md).

## Decisao de transporte

O extractor usa a API interna em vez de um scraper de DOM. O protocolo
`batchexecute` foi mais rapido e menos dependente da estrutura visual da UI;
os RPC IDs devem continuar sendo revalidados quando a plataforma mudar.

```text
POST /_/BardChatUi/data/batchexecute
  ?rpcids=<id>&bl=<build>&f.sid=<session>&hl=en&rt=c&_reqid=<N>
```

O corpo usa `f.req=<JSON>&at=<XSRF_TOKEN>`, com
`Content-Type: application/x-www-form-urlencoded;charset=UTF-8` e
`X-Same-Domain: 1`. Serializar o JSON sem espacos entre separadores; o
servidor rejeita alguns payloads formatados de outra forma.

`at`, `bl` e `f.sid` sao obtidos do HTML autenticado (`SNlM0e`, `cfb2h` e
`FdrFJe`) e renovados quando necessario. A resposta inicia com `)]}'` e vem
em blocos de tamanho prefixado; o payload interno e uma string JSON escapada
dentro de `wrb.fr`.

## RPCs de conteudo

| RPC | Uso | Observacao |
|---|---|---|
| `MaZiqc` | listar conversas | inclui ID, titulo, pin e timestamp da listagem |
| `hNvQHb` | buscar arvore completa | retorna turns, respostas alternativas e URLs de imagem |

RPCs de banners, perfil, upsell, modelos e feature flags nao pertencem a
captura normal. Campos posicionais devem ser documentados com o indice e a
amostra que os comprovou; nao inferir significado pelo nome na UI.

## Sessao, imagens e contas

Cada conta usa um perfil Playwright proprio em `.storage/gemini-profile-{N}/`;
nao ha troca de conta na mesma sessao. URLs de imagens em
`lh3.googleusercontent.com/gg/` sao preassinadas e expiram, portanto devem
ser baixadas logo apos a captura. Favicons, logos de produto e fontes devem
ser filtrados antes do download.

## Limites de descoberta

`created_at` nao e um substituto confiavel para ultima atualizacao: rename e
mensagens novas podem exigir os guardrails documentados no reconciler. A
estrutura de respostas alternativas existe, mas so deve ser promovida a
branches quando houver amostras representativas e testes que a cubram.
