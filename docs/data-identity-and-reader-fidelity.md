# Identidade dos dados e fidelidade do leitor

**Status:** registro técnico para orientar decisões futuras; não é schema novo,
spec de implementação nem plano de migração.

**Última auditoria:** 2026-08-31.

## 1. Por que este registro existe

O arquivo já unifica conversas de fontes com modelos muito diferentes: chats
lineares, árvores com alternativas, notebooks, sessões de terminal e trajetórias
de agentes com ferramentas. A futura interface de leitura e a camada de
curadoria precisarão referenciar esses dados sem assumir que todos os IDs têm a
mesma origem ou estabilidade.

O leitor também expõe aspectos que hoje ficam difíceis de perceber em tabelas e
dashboards. Uma ligação ausente pode ser uma limitação real de captura, uma
decisão do parser ou apenas um evento que nunca correspondeu a uma mensagem
canônica. A interface precisa distinguir esses casos antes que eles sejam
tratados como erro ou ocultados.

## 2. Identidade canônica atual

O unificador já define chaves compostas porque IDs fornecidos pelas plataformas
podem ser locais à conversa ou reutilizados em sessões relacionadas:

| Entidade | Identidade canônica |
|---|---|
| Conversa | `(source, conversation_id)` |
| Mensagem | `(source, conversation_id, message_id)` |
| Tool event | `(source, conversation_id, event_id)` |
| Branch | `(source, conversation_id, branch_id)` |

O campo `account` registra procedência e localização operacional. Ele não faz
parte da identidade canônica atual e não deve substituir `source` na resolução
de referências.

Consequências para consumidores futuros:

- nunca persistir somente `conversation_id` ou `message_id` numa classificação;
- preservar `source` mesmo quando não houver colisão observada;
- tratar `sequence` como ordenação observada, não como identidade universal; e
- não presumir que campos chamados `message_id` sejam automaticamente foreign
  keys para a tabela canônica de mensagens.

## 3. Retrato empírico do conjunto unificado

A auditoria de 2026-08-31 encontrou:

| Verificação | Resultado |
|---|---:|
| Conversas | 8.248 |
| Mensagens | 328.112 |
| Tool events | 188.498 |
| Chaves compostas duplicadas nas quatro tabelas canônicas | 0 |
| IDs canônicos vazios | 0 |
| Mensagens sem conversa correspondente | 0 |
| `message_id` reutilizados em conversas diferentes da mesma fonte | 10.465 |
| Tool events cujo `message_id` não resolve para mensagem canônica | 9.590 |
| Branch roots sem mensagem canônica correspondente | 1.269 |
| Branch leaves sem mensagem canônica correspondente | 30 |

Também não foram encontradas duplicidades de chaves compostas ao reunir os
arquivos de `data/processed/`, antes da deduplicação do unificador. A suíte
direcionada de parsers com testes de idempotência e do unificador passou com 91
testes.

Esses resultados não indicam um arquivo quebrado. A reutilização de
`message_id` confirma por que a chave composta é necessária. As referências que
não resolvem concentram semânticas diferentes:

- Codex cria uma âncora própria para tool calls, não uma mensagem de chat;
- Antigravity pode produzir eventos para passos de trajetória sem mensagem;
- ChatGPT preserva IDs de nós brutos de branch que podem ser filtrados da
  tabela canônica de mensagens; e
- Perplexity possui alguns eventos associados a entries ou assets.

Portanto, integridade de conversa e integridade de mensagem são contratos
distintos. Toda mensagem pertence a uma conversa; nem todo evento ou nó bruto
precisa pertencer a uma mensagem canônica.

## 4. Origem e estabilidade dos IDs

### 4.1 Nativos ou derivados de IDs nativos

ChatGPT, Claude.ai, Qwen, DeepSeek, Grok e Kimi usam predominantemente IDs
fornecidos pela origem. Perplexity deriva mensagens do UUID da entry quando ele
está disponível. Claude Code e Gemini CLI também preservam IDs nativos na maior
parte de suas mensagens e eventos. NotebookLM usa IDs nativos para turns quando
presentes e IDs derivados para elementos sintéticos conhecidos.

Esses IDs são os melhores candidatos a âncoras duráveis, mas continuam sendo
usados com `source` e `conversation_id`. Fallbacks e mudanças upstream ainda
podem existir.

### 4.2 Sintéticos e posicionais

Alguns parsers precisam construir identidade a partir da estrutura observada:

| Fonte | Forma atual | Fragilidade principal |
|---|---|---|
| Gemini web | ID da conversa + índice do turn + papel | Inserção ou nova descoberta de turn anterior pode deslocar índices. |
| Codex | ID da sessão + sequência cronológica | Mudança no conjunto ou ordenação de eventos reconhecidos pode deslocar sequências. |
| Antigravity CLI | ID da conversa + índice do step | Recuperação ou reordenação de trajectory steps pode mudar a âncora. |

Esses IDs são determinísticos para a mesma interpretação do mesmo input, mas
não constituem uma promessa suficiente para anotações permanentes sem sinais
de recuperação adicionais.

### 4.3 Não determinísticos nas capturas manuais

Os parsers de clippings do Obsidian, copy/paste web e terminal Claude Code usam
`uuid4()` para mensagens; alguns fallbacks legados de NotebookLM também usam
UUID aleatório. Reprocessar o mesmo material pode, portanto, trocar os IDs.

No snapshot auditado, as capturas manuais representam cerca de 436 mensagens,
aproximadamente 0,13% do total. O impacto atual é pequeno, mas esses IDs devem
se tornar determinísticos antes de sustentar curadoria durável no nível de
mensagem ou trecho.

## 5. Âncoras para o estado curado

A camada curada permanece separada do arquivo canônico. Sua referência mínima
é a chave composta da entidade. Para mensagem ou intervalo, ela também deve
guardar sinais redundantes suficientes para localizar novamente o conteúdo se
um ID sintético mudar legitimamente:

- `source`, `conversation_id` e `message_id` observados;
- papel da mensagem;
- timestamp, quando disponível;
- sequência observada no momento da anotação; e
- impressão do conteúdo normalizado ou equivalente que não armazene uma
  segunda cópia desnecessária do texto.

Para um intervalo, as duas extremidades recebem âncoras próprias. O intervalo
não deve depender apenas de posições numéricas.

Essa redundância não cria histórico detalhado da curadoria. Ela serve para
resolver ou ao menos sinalizar referências que deixem de corresponder
exatamente após uma melhoria de parser. Um caso ambíguo deve permanecer visível
para revisão, nunca ser realocado silenciosamente.

## 6. Semântica de vínculos para o leitor

O modelo futuro precisa distinguir pelo menos:

- referência para mensagem canônica;
- referência para nó bruto de uma árvore;
- referência para step de trajetória;
- referência para asset, entry ou output; e
- evento associado apenas à conversa.

O formato exato ainda está aberto. O requisito é não obrigar todas essas
relações a caberem numa foreign key de mensagem. Uma possível evolução é manter
um vínculo canônico opcional e registrar separadamente o tipo e o ID da âncora
de origem.

No leitor, thinking, chamadas e resultados de ferramentas, branches, assets e
steps podem ficar recolhidos para preservar fluidez. Ainda assim, devem ser
inspecionáveis e não descartados por não terem representação de balão de chat.

## 7. Ciclo de fidelidade orientado pelo leitor

```text
captura → reconciliação → parser → unified → leitor
     ↑                                      │
     └──── gap observável e validado ───────┘
```

Ao visualizar conversas reais, um problema encontrado deve ser classificado
antes de qualquer mudança:

1. **Captura:** a informação existe upstream, mas não foi preservada.
2. **Parser/schema:** a informação foi capturada, mas foi perdida, ligada ou
   representada inadequadamente.
3. **Apresentação:** o dado está correto, porém invisível ou confuso no leitor.
4. **Curadoria:** o arquivo está fiel; falta uma interpretação pessoal, tag ou
   relação, que pertence à camada derivada.

Isso permite melhorar as treze fontes incrementalmente conforme casos reais
apareçam, sem exigir uma revisão completa de todos os parsers antes do leitor.

## 8. Contrato de regressão desejado

Antes de a curadoria no nível de mensagens depender desses vínculos, os testes
devem cobrir progressivamente:

- duas execuções sobre o mesmo fixture produzem as mesmas chaves;
- chaves compostas canônicas são não vazias e únicas;
- toda mensagem resolve para sua conversa;
- mudança de ID intencional é tratada como migração ou referência a revisar;
- eventos sem mensagem canônica declaram uma semântica válida; e
- fixtures de CLI exercitam thinking, ferramentas, steps e compactações.

Esse contrato não exige que plataformas diferentes ofereçam os mesmos dados.
Ele exige apenas que o que foi capturado seja identificado e apresentado de
forma consistente.

## 9. Limites deste documento

Este registro não escolhe banco, framework de UI, formato final das âncoras ou
migração de schema. Também não exige corrigir antecipadamente todas as
referências existentes. Essas decisões pertencem ao desenho posterior da
frente de arquivo e leitor e às correções empíricas reveladas por ela.
