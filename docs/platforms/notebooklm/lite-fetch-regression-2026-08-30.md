# NotebookLM — resolução da regressão de lite-fetch (2026-08-30)

## Resumo

Um sync incremental do NotebookLM classificou um número muito alto de
notebooks como candidatos a captura completa. Isso poderia parecer criação
massiva de notebooks, mas não era: o discovery continuava pequeno e estável,
enquanto a comparação leve encontrava diferenças em respostas que o servidor
regenera.

O problema foi resolvido sem limpeza de raw/merged e sem suprimir mudanças
reais. A correção foi validada em ambos os perfis vivos.

## Sintoma e risco

- O discovery listava 129 notebooks na conta 1, enquanto o raw acumulado tinha
  256 JSONs históricos. Essa diferença inclui registros preservados e schemas
  legados; não é critério para remoção.
- A classificação lite fazia muitos `fetch` apesar de não haver evidência de
  criação ou edição equivalente na interface.
- Rebaixar todos os notebooks seria caro, alteraria a ordem visual por acesso
  e aumentaria a chance de propagar instabilidade de upstream.

## Como o diagnóstico foi conduzido

1. Preservamos raw e merged existentes e não rodamos parser até sync/reconcile
   bem-sucedido.
2. Comparamos o raw anterior com os três RPCs usados pela classificação:
   `rLM1Ne` (metadata), `cFji9` (notes) e `gArtLc` (artifacts).
3. Fizemos repetições imediatas sem interação na interface para separar um
   campo regenerado de uma alteração que permanece no servidor.
4. Usamos uma conta controlada com um notebook de teste para relacionar os
   RPCs à interface: `VfAZjd` é o guia/overview, `khqZz` é conversa,
   `cFji9` são notas e `gArtLc` são outputs de estúdio.

## Causa raiz confirmada

O payload leve de metadata `rLM1Ne`, em cada fonte, pode regenerar:

- uma URL de download/presignada;
- dois campos de texto derivados pelo servidor.

Esses valores mudavam sem mudança visível feita pelo usuário. A comparação
estrita os tratava como alteração do notebook e disparava `fetch` completo.
Havia também uma fragilidade no normalizador: uma fonte curta ou com formato
incompleto podia interromper a normalização das fontes seguintes do mesmo
notebook.

O `update_time` do listing já era conhecido como volátil: ele pode mudar por
reindexação e ao simplesmente abrir um notebook, o que também muda sua ordem
na interface. Ele não participa da decisão de incrementalidade.

## Correção implementada

`src/extractors/notebooklm/orchestrator.py::_lite_metadata_equal` agora:

1. copia os corpos antes de comparar;
2. mascara apenas a URL e os dois textos derivados observados dentro de cada
   fonte de metadata;
3. trata cada fonte isoladamente, de modo que uma entrada incompleta não afeta
   as demais;
4. usa `_eq_lenient` para a comparação final.

O escopo é deliberadamente só o classificador lite. O reconciliador continua
comparando corpos completos e preservando registros ausentes como
`preserved_missing`.

**Não mascarar sem novo experimento controlado:** identidade/título da fonte,
notas (`cFji9`), artifacts (`gArtLc`), conteúdo capturado ou qualquer outro
campo de metadata. Esses podem representar uma alteração real.

Também foi corrigido `scripts/notebooklm-sync.py` para que erros de download
de assets não sejam sobrescritos ao combinar as estatísticas de assets, notas
e text artifacts.

## Validação observada

| Cenário | Resultado |
|---|---|
| Conta 2, repetição sem UI | 53 notebooks: `0 fetch`, `53 copy`; reconcile: `0 updated`, `53 copied`, `2 preserved_missing` |
| Conta 1, após capturar 30 diferenças em notas | Repetição imediata sem UI: 129 notebooks: `0 fetch`, `129 copy`; reconcile: `0 updated`, `129 copied`, `1 preserved_missing` |
| Testes focados | Passaram, incluindo URL/texto volátil, mudança real de identidade e fonte curta antes de fonte normal |
| Dados derivados | parser e `unify-parquets.py` concluíram; o unified ficou mais novo que todos os parquets de entrada |

As 30 diferenças de notas da conta 1 foram preservadas como atualizações; a
repetição estável mostra apenas que elas não eram um falso positivo recorrente
do comparador. Assets que retornaram HTTP upstream ficaram registrados no log;
nenhum arquivo existente foi removido ou sobrescrito.

## Se o comportamento mudar

1. Pare somente o NotebookLM se uma execução sem UI voltar a produzir muitos
   `fetch` inesperados.
2. Preserve raw/merged e logs; não limpe arquivos para alinhar discovery.
3. Compare uma amostra pequena dos três RPCs com o raw imediatamente anterior
   e uma segunda resposta lite imediata.
4. Identifique o caminho estrutural que diverge antes de adicionar qualquer
   máscara. Uma máscara precisa ser estreita, justificada e coberta por teste.
5. Rode testes focados, valide um sync incremental das duas contas vivas,
   execute parse apenas após reconcile saudável e então regenere o unified.

## Referências

- [state.md](state.md) — estado operacional e contagens da coleta.
- [server-behavior.md](server-behavior.md) — comportamento upstream conhecido.
- [WEB_COLLECTION_HANDOFF.md](../../WEB_COLLECTION_HANDOFF.md) — sequência
  operacional para a próxima coleta web.
