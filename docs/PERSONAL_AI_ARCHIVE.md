# Personal AI Archive — desenho de produto

**Status:** visão de produto validada em conversa; não é especificação nem
plano de implementação.

**Data:** 2026-08-31

## 1. Decisão de produto

Este projeto evolui de um extractor com dashboard operacional para um **arquivo
pessoal de interações com IA** (*Personal AI Archive*). O produto reúne em uma
mesma aplicação três frentes distintas, mas conectadas:

1. **Operação e saúde:** cadastrar contas, realizar login/relogin, executar
   syncs e acompanhar a saúde de extractors, parsers e outputs.
2. **Arquivo e leitor:** buscar, abrir e ler as conversas e seus artefatos — o
   valor central que os dados preservados, dashboards e relatórios atuais ainda
   não oferecem diretamente.
3. **Curadoria assistida:** organizar milhares de chats progressivamente por
   meio de títulos pessoais, tags, classificações, trechos, workspaces,
   relações, detectores e visualizações de apoio.

Essas frentes podem ser tratadas como subprojetos próprios. Operação e leitor
têm responsabilidades mais delimitadas; a curadoria é a frente mais complexa e
deliberadamente iterativa. Ferramentas curatoriais podem aparecer dentro do
leitor, onde existe contexto para usá-las, sem transformar a renderização do
chat e a curadoria no mesmo componente ou domínio.

A próxima frente de exploração do produto é o **arquivo e leitor**. A coleta e
a análise já possuem infraestrutura utilizável, mas ainda falta a superfície
que permita inspecionar diretamente o principal dado preservado: a conversa.
Essa prioridade não congela uma ordem definitiva de implementação das três
frentes; ela ataca o gap de uso e visibilidade mais evidente no estado atual.

O arquivo substitui a necessidade de consultar o histórico diretamente em cada
plataforma, sem substituir a preservação: chats removidos upstream continuam
acessíveis localmente. A aplicação é *local-first*; uma futura implantação web
privada e protegida por autenticação é uma decisão de distribuição, não uma
premissa do produto atual.

O produto é para uma única pessoa, mas preserva múltiplas contas como
identidades de origem duráveis — inclusive contas pessoais, profissionais ou
desativadas que já não podem ser sincronizadas. Conta é procedência e
configuração operacional, não a estrutura principal de navegação do arquivo.

## 2. Princípios

1. **Preservar, nunca reescrever a origem.** `raw`, `merged`, `processed` e
   `unified` continuam canônicos para captura e análise. Nenhuma ação da
   interface altera título, projeto, path ou outro fato capturado.
2. **Tornar o arquivo realmente acessível.** Estatísticas não substituem a
   capacidade de encontrar, abrir e ler uma conversa preservada.
3. **Separar leitura de curadoria.** O leitor apresenta fielmente o conteúdo e
   os metadados disponíveis. Controles de curadoria podem ser integrados à
   experiência, mas gravam somente uma camada própria e mutável.
4. **Trabalhar com o melhor estado atual.** Organização, tags e relações podem
   ser revistas, substituídas ou removidas conforme a leitura evolui. Não há
   requisito de histórico detalhado das edições curatoriais.
5. **Assistir sem decidir silenciosamente.** Detectores e regras podem sugerir
   ou herdar classificações, desde que o resultado permaneça visível como novo
   ou não revisado até a confirmação humana.
6. **Começar amplo e refinar.** O sistema deve facilitar colocar milhares de
   chats em caixas úteis, observar o conjunto e então dividir, combinar ou
   relacionar essas caixas ao longo do tempo.
7. **Manter a análise exploratória aberta.** Quarto/notebooks continuam sendo
   o ambiente para formular perguntas e testar interpretações. O produto
   melhora os dados que essas análises consomem, sem tentar predeterminar seus
   métodos.

## 3. Camadas de dados

```text
captura imutável                 estado operacional/curado          leituras derivadas
raw → merged → processed → unified  → operação e curadoria       → busca, relatórios, RAG futuro
```

### 3.1 Arquivo canônico

Os Parquets unificados permanecem a fonte de leitura analítica e reprodução.
São adequados para scans, DuckDB, DVC, Quarto e contratos com consumidores. Não
são a superfície de escrita de ações pontuais da interface.

### 3.2 Estado operacional e curado

Uma camada própria, separada dos Parquets, armazena o estado mutável do
produto, incluindo:

- fontes, contas e sua situação operacional;
- execuções, fila de sync, saúde e erros;
- títulos pessoais e outros enriquecimentos manuais;
- tags, classificações, anotações e notas;
- trechos anotados de conversas;
- workspaces, memberships e regras de composição;
- relações explícitas entre chats, mensagens, trechos, artefatos e workspaces;
- candidatos produzidos por detectores ou regras, com seu estado de revisão; e
- decisões de apresentação de metadados ambíguos.

Essa camada representa o estado atual da curadoria. Justificativas, comentários
e trechos de evidência são opcionais e só precisam ser registrados quando
forem úteis para a decisão.

Registros curatoriais nunca usam um `conversation_id` ou `message_id` isolado
como identidade global. Conversas são ancoradas por `(source,
conversation_id)`; mensagens, por `(source, conversation_id, message_id)`.
Anotações de mensagens ou trechos também preservam sinais redundantes de
recuperação, como papel, timestamp, sequência observada e impressão do conteúdo,
para que uma melhoria futura de parser não solte silenciosamente a curadoria do
material ao qual ela se referia.

### 3.3 Índices derivados

Busca, snippets, filtros e futuros embeddings são derivados e reconstruíveis.
A arquitetura preserva granularidade de mensagem e trecho, mesmo quando a
interface apresenta resultados agrupados por conversa.

### 3.4 Artefatos

Arquivos enviados, imagens, áudio, HTML, fontes do NotebookLM e saídas geradas
são recursos ligados a chats ou mensagens. A aplicação usa um modelo genérico
de recurso, com renderizadores específicos quando disponíveis. Não há, por
ora, ingestão livre de documentos externos sem vínculo com uma interação
capturada; isso seria outro produto.

## 4. Frente 1 — operação e saúde

Esta frente incorpora e supera o papel operacional do dashboard Streamlit
atual. Ela concentra:

- cadastro e identificação de fontes e contas;
- contas ativas, desativadas ou apenas históricas;
- fluxo de login/relogin sem expor credenciais nos dados;
- fila para sincronizar uma conta/fonte, um conjunto selecionado ou todas as
  fontes;
- histórico e progresso das execuções operacionais;
- erros, credenciais expiradas, discovery parcial, outputs desatualizados e
  necessidade de intervenção;
- diagnóstico que diferencie falhas transitórias de sinais de que um extractor
  ou parser precisa ser revisto após mudança upstream;
- frescor de `raw`, `merged`, `processed`, `unified` e índices; e
- acesso a logs, validações e ações de retry apropriadas.

O histórico desta frente é histórico de execução do pipeline, necessário para
diagnóstico. Ele não implica manter histórico das decisões curatoriais.

## 5. Frente 2 — arquivo, busca e leitor

### 5.1 Descoberta do acervo

O arquivo oferece busca global e navegação direta por chats. O mesmo chat pode
ser alcançado por busca, fonte/conta, contêiner nativo, workspace, artefato ou
relação. Conta aparece como metadado e filtro secundário, não como a árvore
principal da biblioteca.

Resultados podem ser apresentados como cards de conversa com título, fonte,
conta, data e snippets expansíveis das mensagens que deram match. Abrir o
resultado leva à mensagem ou trecho exato na timeline.

Busca e filtros devem cobrir progressivamente: título original e pessoal,
texto das mensagens, datas, fonte, conta, contêiner nativo, contexto técnico,
workspaces, tags, relações e artefatos.

### 5.2 Timeline de chat

O leitor usa uma apresentação genérica com identidade própria, não cópias
visuais das plataformas. Blocos especiais aparecem quando existem dados:

- HTML e outros artefatos gerados pelo Claude;
- áudio e transcrição do ChatGPT;
- fontes, notas, outputs e citações do NotebookLM;
- anexos enviados;
- tool events, thinking e memórias persistentes de CLIs; e
- ramificações, citações e metadados de origem.

Todo metadado disponível deve ser acessível, inclusive URL de origem quando
existir. O leitor local é a interface primária, mas “abrir na plataforma de
origem” continua útil para verificação e refinamento da captura.

### 5.3 Fronteira com a curadoria

A timeline é essencialmente uma leitura estável do arquivo canônico. Ações como
taguear, relacionar ou incluir em workspace podem aparecer ao lado do conteúdo,
porque dependem dele para fazer sentido, mas pertencem à frente de curadoria e
escrevem somente em sua camada própria.

### 5.4 Leitor como inspeção de fidelidade

O leitor também é uma ferramenta de validação do próprio arquivo. Parquets,
dashboards e contagens permitem detectar muitos problemas estruturais, mas não
mostram com clareza quando uma conversa perdeu contexto, quando um tool event
ficou sem mensagem canônica, quando uma branch referencia um nó filtrado ou
quando uma sessão CLI possui etapas que não cabem no modelo visual de chat
convencional.

A timeline deve tornar acessíveis, sem fingir que são todos o mesmo tipo de
objeto:

- mensagens canônicas de usuário, assistente e sistema;
- thinking/reasoning, tool calls e tool results;
- nós e alternativas de branches;
- passos de trajetória de agentes que não geraram uma mensagem;
- anexos, assets, citações, outputs e memórias; e
- metadados de captura, identidade e procedência.

Esses elementos podem ser recolhidos ou apresentados como detalhes para manter
a leitura fluida, mas não devem desaparecer do produto. Quando a visualização
revelar ausência, ligação ambígua ou representação inadequada, o refinamento
volta ao schema, extractor ou parser correspondente. Isso é diferente de uma
classificação curatorial: correções de fidelidade melhoram o arquivo canônico;
tags, relações e interpretações continuam na camada derivada.

O registro técnico de identidade, vínculos e requisitos de fidelidade do leitor
está em [data-identity-and-reader-fidelity.md](data-identity-and-reader-fidelity.md).

## 6. Frente 3 — curadoria assistida

### 6.1 Espírito da curadoria

A curadoria é uma bancada para transformar um acervo de milhares de chats em
conjuntos progressivamente compreensíveis. O fluxo conceitual é:

```text
sinais amplos → caixas iniciais → leitura do conjunto → divisão/combinação
              → relações e classificações mais precisas → nova leitura
```

Não se espera acertar uma taxonomia final de uma vez. O produto deve permitir
que ferramentas, regras e visualizações sejam ajustadas enquanto a organização
amadurece.

### 6.2 Ações no contexto da leitura

No nível adequado, o usuário pode:

- definir um título pessoal sem substituir o título original;
- adicionar tags ou classificações livres;
- anotar a conversa inteira, uma mensagem ou um intervalo de mensagens;
- criar notas;
- adicionar ou remover chats de workspaces; e
- criar relações explícitas.

Uma anotação de trecho aponta para um intervalo explícito da timeline. Isso
permite registrar mudanças de assunto dentro da mesma conversa sem fragmentar
ou duplicar o chat original.

### 6.3 Proveniência e organização

Três conceitos não devem ser confundidos:

| Conceito | Significado | Exemplos |
|---|---|---|
| Contêiner nativo | Associação explícita fornecida pela origem | projeto ChatGPT/Claude; notebook Gemini/NotebookLM |
| Contexto técnico | Informação observada durante a captura, sem afirmar semântica | path/diretório de uma sessão CLI |
| Workspace curado | Organização posterior e cross-platform | Obsidian Qualia Coding; Open Source Projects |

Paths de CLI são metadados de execução. Podem ser pesquisados e filtrados, mas
não são automaticamente apresentados como projetos: uma sessão aberta no
diretório deste projeto pode tratar de limpeza do sistema, por exemplo. Um path
só ganha uma lente destacada quando o usuário confirmar que o contexto é útil.

Na navegação, três estados não devem ser colapsados sob o nome “órfão”:

| Estado | Significado |
|---|---|
| Sem contêiner nativo | A plataforma oferece contêineres, mas o chat não pertencia a nenhum |
| Contêiner nativo não aplicável | A origem não oferece esse conceito para a interação |
| Sem workspace | O chat ainda não recebeu organização curada |

Um contexto técnico considerado ambíguo pode ser retirado da visão padrão sem
apagar o fato capturado; uma opção explícita continua permitindo revelá-lo.

### 6.4 Workspaces e composição progressiva

Workspaces reúnem conversas, artefatos, notas, tags e relações de várias fontes
e contas. Uma conversa pode participar de vários workspaces; membership é uma
conexão curada, não uma mudança de localização do chat.

Projetos ou contêineres nativos também podem compor um workspace. Por exemplo,
projetos do ChatGPT e do Claude podem alimentar juntos `Obsidian Qualia
Coding`, acompanhados de chats avulsos. Essa composição pode funcionar como
regra contínua para novos chats do contêiner. Os novos itens entram visíveis no
workspace, mas sinalizados como posteriores à última categorização ou ainda não
revisados; não devem desaparecer do fluxo nem parecer silenciosamente
confirmados.

Um workspace tem uma home ou dossiê com:

- descrição, notas e objetivos próprios;
- chats relacionados, com suas fontes e contas;
- contêineres nativos que o compõem;
- recursos de entrada e artefatos de saída;
- tags e anotações recorrentes;
- relações com outros chats e workspaces; e
- timeline da atividade e da trajetória.

Workspaces-contêineres são uma relação de **organização**. Por exemplo,
`Obsidian Qualia Coding` pode estar em `Open Source Projects`. Essa relação não
equivale a **derivação**: um trabalho pode levar a outro sem pertencer a ele.

### 6.5 Relações

Relações são independentes de tags. São arestas explícitas e tipadas entre
chats, trechos, artefatos ou workspaces, como:

- `deriva de` / `levou a`;
- `continua`;
- `contrasta com`;
- `compara resposta de`; e
- `relacionado a`.

O tipo `deriva de` tende a formar uma linhagem temporal sem ciclos. Outras
relações, como `contrasta com`, podem ser recíprocas; o grafo inteiro não deve
ser forçado a uma árvore ou DAG.

### 6.6 Detectores e visualizações como ferramentas

A assistência automática identifica possibilidades, não decisões finais. Pode
incluir:

- prompts idênticos ou semelhantes enviados em plataformas diferentes;
- possíveis episódios comparativos, como os hoje representados por
  `episode_id`;
- recorrências ou agrupamentos que ajudem a revisar grandes conjuntos; e
- novos chats abrangidos por uma regra de composição de workspace.

Os resultados entram como candidatos ou memberships herdadas visíveis até a
confirmação. Limiares, estados e microinterações serão refinados durante o uso;
não precisam ser fechados nesta visão.

Sankeys, grafos, timelines e outras visualizações podem fazer parte do produto
quando ajudam a observar o estado da organização, detectar incoerências e
voltar aos chats para ajustar a curadoria. Elas são ferramentas interativas de
classificação, não apenas relatórios finais.

### 6.7 Referência do `AI Interaction Analysis`

O projeto `AI Interaction Analysis` é referência e primeiro ponto de partida
para esta frente. Ele contém enriquecimentos de títulos, modelos e contas,
`project_group` cross-platform, topics e hierarquias, memberships múltiplas,
`episode_id`, classificação de voice mode e visualizações usadas durante a
curadoria.

Esses dados formam um estado inicial útil, mas não final: podem ser alterados ou
revogados quando o trabalho continuar no produto. Métodos e ferramentas que se
mostrarem úteis podem inspirar funcionalidades nativas. Isso não exige copiar
integralmente os notebooks nem manter o projeto antigo como consumidor
paralelo.

## 7. Análise exploratória com Quarto

Depois da curadoria, os dados organizados ficam disponíveis para análises em
Quarto/notebooks neste repositório, como já ocorre hoje aqui e no projeto de
referência. A análise não é uma quarta área fechada da aplicação.

A fronteira é funcional:

| Quando a visualização... | Lugar natural |
|---|---|
| ajuda a organizar, revisar ou corrigir o acervo | produto de curadoria |
| investiga uma pergunta analítica aberta | Quarto/notebook |

Uma mesma técnica, como Sankey ou grafo, pode aparecer nos dois ambientes com
propósitos diferentes. Quando uma análise exigir uma unidade única por
conversa, uma vista derivada pode consolidar memberships sem apagar a camada
qualitativa mais rica.

## 8. RAG futuro

RAG é uma fase posterior possível, apoiada pela padronização e curadoria que já
existem. Não substitui busca, leitura ou organização. Para ser útil, deverá
recuperar trechos com contexto de chat, filtros de fonte, conta e workspace,
artefatos e anotações, sempre citando mensagens ou trechos navegáveis no
arquivo.

Pré-requisitos conceituais:

- estratégia de segmentação que respeite conversas e turns;
- índice textual e, se adotado, índice de embeddings;
- filtros e escopo de recuperação claros;
- tratamento explícito de conteúdo preservado, tombstones e dados pessoais; e
- resposta com proveniência, não apenas síntese sem referência.

## 9. Decisões deliberadamente abertas

Estas decisões são importantes, mas não bloqueiam a visão de produto:

1. Banco ou formato exato da camada operacional mutável e da busca.
2. Estratégia de atualização e reconstrução dos índices.
3. Vocabulário inicial e governança dos tipos de relação.
4. Hierarquia de workspaces: memberships múltiplas são permitidas; a interface
   de contêineres e a necessidade de parent(s) seguem para exploração.
5. Estratégia para trazer o estado curado existente do `AI Interaction
   Analysis` e priorizar ferramentas que devem virar funcionalidades nativas.
6. Limiares, estados e microinterações de revisão para regras e detectores.
7. Autenticação e topologia de uma implantação privada futura.
8. Escopo, modelos e controles de um RAG futuro.
9. Formato exato das âncoras redundantes e da resolução de referências após
   mudanças legítimas de IDs sintéticos.

## 10. Fora de escopo atual

- Publicar o acervo pessoal em backend público.
- Reescrever ou excluir dados capturados pela interface.
- Tratar sugestões automáticas como decisões curatoriais silenciosas e finais.
- Manter histórico detalhado de cada edição curatorial.
- Transformar o arquivo em vault genérico por importação livre de documentos
  externos não vinculados a interações de IA.
- Substituir a exploração aberta de Quarto/notebooks por um módulo analítico
  fechado antes de os métodos se estabilizarem.
