# Cross-platform extractor findings

Padroes de engenharia que se repetem entre fontes. Evidencia de endpoint,
schema e comportamento de uma unica plataforma pertence ao seu diretorio em
`platforms/`.

## Reconciliacao deve propagar enriquecimento sem reescrever tudo

O reconciler compara o raw atual com o merged anterior. Usar apenas
`update_time` perde campos semanticos adicionados localmente pelo extractor,
como projeto, archive ou recuperacao de truncamento. Por outro lado, comparar
todo campo `_` indiscriminadamente reescreve registros a cada captura.

A regra reutilizavel e:

1. comparar `update_time` e campos `_` semanticos;
2. excluir somente campos operacionais que variam em toda execucao, como
   `_last_seen_in_server`, duracao ou contadores de retry;
3. testar separadamente enriquecimento novo, enriquecimento igual e diferenca
   apenas operacional.

Prefira blacklist de campos operacionais a whitelist de campos semanticos:
novos campos devem propagar por padrao, salvo quando houver evidencia de que
sao ruido de execucao.

## Discovery e incremental sao contratos distintos

Uma listagem geralmente precisa percorrer o universo da fonte; a busca de
corpos pode ser incremental. O raw final continua completo: registros nao
refetchados sao reaproveitados da captura anterior com o estado de observacao
atualizado.

Cada plataforma define seu sinal de mudanca e seu guardrail. `update_time`
pode ser suficiente, volatil ou inexistente; nao transfira a heuristica de uma
fonte para outra sem probe. `--full` serve como verificacao deliberada, nao
como forma de apagar a base incremental.

Quando discovery estiver parcial, preserve o raw/merged existente e use o
fallback documentado da plataforma, como `refetch_known`, antes de aceitar a
observacao como base nova.

## Autenticacao e transporte

Perfis Playwright persistentes em `.storage/` guardam a sessao usada pela
captura. Alguns extractors chamam a API com token Bearer derivado da sessao;
outros dependem diretamente de cookies e contexto de navegador. Login e sempre
interativo; a estrategia de captura posterior (headed ou headless) pertence ao
`state.md` de cada fonte.

Nao tente contornar uma sessao expirada extraindo ou reutilizando credenciais
fora do fluxo documentado. Reautentique a plataforma e valide uma requisicao
minima antes de confiar em uma captura.

## Assets e disponibilidade upstream

URLs preassinadas expiram e arquivos antigos podem ser removidos pelo
servidor. Downloaders devem ser idempotentes, preservar o que ja foi baixado e
registrar falhas upstream no manifest. Uma falha de asset nao autoriza apagar
a conversa, o registro merged ou os binarios ja preservados.

## Como usar estas descobertas

Ao criar ou corrigir uma fonte, aplique estes principios junto do roteiro em
[adding-a-platform.md](adding-a-platform.md). Registre a evidencia especifica
no `discovery.md` ou `server-behavior.md` da plataforma; registre limites
confirmados em [known-limitations.md](known-limitations.md).
