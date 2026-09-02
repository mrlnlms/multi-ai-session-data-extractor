# Perplexity — discovery e contratos de captura

Auditoria iniciada em 2026-04-29 para mapear entidades alem da listagem comum
de threads. O estado atual de cobertura e comportamento fica em
[state.md](state.md); limites de plano e upstream ficam em
[known-limitations.md](../../../known-limitations.md#perplexity).

## Entidades descobertas

- **Threads:** a listagem normal e a de pinados se sobrepoem; a fusao deve
  preservar flags como `is_pinned`, em vez de descartar a segunda observacao.
- **Spaces:** a UI chama collections. Capturar a collection, suas threads,
  arquivos e skills com os endpoints observados durante navegacao autenticada.
- **Pages e artigos:** slugs nao aparecem no DOM inicial da SPA; a navegacao
  controlada revela a URL e permite buscar a pagina correspondente.
- **Assets e anexos:** URLs antigas podem ter sido removidas do S3 upstream.
  Registre `failed_upstream_deleted` no manifest e preserve a referencia.

## Observacoes de probe

UI e API usam nomes diferentes (`Spaces`/collections, `Pages`/articles,
`Artifacts`/assets). Nao deduzir rotas a partir do texto visivel: use network
tap e uma acao real da UI para confirmar endpoint, payload e paginacao.

O archive de threads e limitado pelo plano: requests podem responder sem que o
estado se torne observavel. Voice tambem e comportamento upstream — o servidor
transcreve e descarta o sinal de origem. Ambos sao limites, nao lacunas de
parser.

## Reconciliacao

Uma thread pode sumir de todas as listagens ou continuar referenciada dentro
de um space depois de ter sido removida globalmente. Os dois casos precisam
virar preservacao local, para evitar que um orphan reintroduza uma conversa
considerada apagada.

Os planos de implementacao e baterias de UI que acompanhavam a auditoria foram
concluidos. A cobertura atual esta no `state.md`; qualquer nova evidencia de
endpoint ou schema deve ser adicionada aqui.
