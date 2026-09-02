# Instancias de conta e arquitetura da aplicacao

**Status:** exploracao arquitetural pausada; nao e especificacao, decisao final
nem plano de implementacao.

**Data:** 2026-08-31

Documentos relacionados:

- [Personal AI Archive](product-vision.md) — visao de produto;
- [Identidade dos dados e fidelidade do leitor](reader-and-identity-contract.md)
  — contrato tecnico atual de identidade; e
- [DVC runbook](../operations/dvc-runbook.md) — preservacao e fronteira atual com o
  consumidor.

## 1. Por que este documento existe

Uma conversa sobre adicionar uma segunda conta do ChatGPT revelou um gap mais
amplo. O projeto ja captura varias contas em Gemini e NotebookLM e varios
extractors aceitam nomes alternativos de profile, mas a nocao de conta nao e
um conceito uniforme do pipeline. Em parte do codigo, conta e uma unidade
operacional; em outra, cada plataforma ainda e tratada como se tivesse uma
unica identidade autenticada.

Resolver apenas o ChatGPT repetindo o desenho atual do Gemini fecharia o caso
imediato, mas manteria listas fixas, convencoes locais e trabalho duplicado na
proxima plataforma. A conversa tambem mostrou que a decisao se relaciona com:

- a futura frente de operacao e saude do Personal AI Archive;
- o formato e a distribuicao de uma aplicacao local;
- o modelo de seguranca para perfis autenticados e outros segredos;
- a identidade canonica de conversas e contas;
- a migracao dos dados atuais; e
- a fronteira com o unico consumidor, `AI Interaction Analysis`.

Este documento preserva o que foi entendido, registra direcoes preferidas e
mantem as decisoes ainda abertas visiveis. Ele existe para que o trabalho possa
ser retomado sem transformar uma exploracao incompleta em implementacao
prematura.

## 2. Evidencia no estado atual

### 2.1 Plataformas web

Gemini e NotebookLM possuem profiles e arvores `raw`/`merged` por conta. O
codigo, porem, ainda conhece conjuntos particulares de contas, como `[1, 2]`,
e os relatorios individuais usam arquivos `*-acc-1.qmd`, `*-acc-2.qmd` etc.

ChatGPT, Claude.ai, Kimi, Qwen, DeepSeek, Grok e Perplexity possuem graus
diferentes de suporte a um profile selecionavel, mas seus caminhos cumulativos,
reconcilers ou parsers continuam assumindo uma unica conta. Trocar apenas o
profile sem isolar os dados pode:

- sobrescrever o raw da conta anterior;
- fazer o reconciler interpretar conversas de outra conta como removidas;
- misturar ou substituir assets, projetos, memorias e instrucoes; e
- produzir Parquets sem procedencia de conta confiavel.

Portanto, autenticacao separada e necessaria, mas nao suficiente.

### 2.2 CLIs

As quatro fontes CLI copiam sessoes de uma arvore local cumulativa. Uma troca
de conta no proprio programa pode continuar escrevendo no mesmo diretorio.

No Codex auditado, `session_meta` registra ID da sessao, `cwd`, provider do
modelo, origem e versao da CLI, mas nao registra e-mail, user ID ou account ID.
Nao existe evidencia segura para atribuir retroativamente cada JSONL a uma
conta. Inferir por data, modelo ou workspace seria fragil.

Direcao atual: o contrato de instancias de conta comeca pelas plataformas web.
Fontes CLI continuam com `account` nulo quando a sessao nao traz identidade
observavel. Se uma CLI futura passar a gravar uma identidade estavel por
sessao, o suporte pode ser adicionado com base nessa evidencia.

### 2.3 Consumidores e identidade atual

O unificador considera conversa por `(source, conversation_id)`; `account` e
procedencia, mas nao participa da chave canonica atual. Gemini evita colisoes
incluindo a conta em IDs derivados. Uma mudanca geral de contas precisa decidir
se preserva esse contrato por namespace ou se promove `account_id` a parte da
identidade composta.

O projeto `AI Interaction Analysis` consome `processed` e `unified` por DVC.
Como ele e o unico consumidor e ambos os projetos sao pessoais, existe uma
janela favoravel para revisar esse acoplamento antes de publicar um schema ou
uma identidade novos.

## 3. Distincao central

O modelo futuro deve separar dois conceitos:

```text
Plataforma/conector
  define API, login, discovery, fetch, reconcile, parser e capacidades

Instancia de conta
  define identidade de origem, vinculo de autenticacao, dados e execucoes
```

Uma nova plataforma, como uma hipotetica `Marlon-bot`, exige implementar um
novo conector. Uma nova conta do ChatGPT deve reutilizar integralmente o
conector ChatGPT e apenas registrar uma nova instancia.

```text
ChatGPT
├── conta A
├── conta B
└── conta N
```

A quantidade de contas nao deve ser codificada em listas fixas nem exigir
alteracao de parser, dashboard ou relatorio a cada adicao.

## 4. Acordos alcancados

Os pontos abaixo representam o entendimento atual, nao uma autorizacao para
implementacao:

1. A arquitetura deve possuir um nucleo comum de contas e adaptadores por
   plataforma, em vez de reproduzir regras independentes em cada script.
2. ChatGPT seria o primeiro novo adotante; Gemini e NotebookLM deveriam ser
   normalizados para remover limites fixos de contas.
3. CLI e interface grafica devem chamar o mesmo servico de dominio. Regras de
   conta nao devem morar em `argparse`, Streamlit, Electron ou Tauri.
4. O nome mostrado ao usuario e livre, editavel e pode repetir. Ele nunca e
   chave, path ou identidade.
5. A identidade interna da conta e imutavel e atribuida pelo sistema. UUID e a
   direcao atualmente preferida, mesmo que exija migracao do desenho numerico
   existente.
6. Um identificador estavel fornecido pela plataforma, quando disponivel, e um
   dado separado. Ele serve para detectar login na conta errada, nao para
   substituir automaticamente a identidade interna.
7. Ciclo de vida e autenticacao sao estados independentes. Uma conta pode estar
   ativa com login ausente ou expirado; ausencia de cookies nao a transforma em
   conta historica.
8. Depois de restaurar Git + DVC em outra maquina, o usuario deve poder escolher
   a mesma identidade de conta, autenticar novamente e continuar reconciliando
   com as conversas preservadas.
9. Credenciais nunca entram em Git, DVC, Parquet ou logs. Profiles continuam
   sendo estado local descartavel e recriavel por login.
10. Uma futura interface de contas e uma entrega separada, mas o nucleo deve ser
    desenhado desde o inicio para servi-la.
11. Antes de mudar IDs ou schema, deve existir uma baseline validada dos
    Parquets atualmente consumidos pelo `AI Interaction Analysis`.
12. Nenhum DVC push, commit ou publicacao faz parte desta exploracao.

## 5. Modelo de dominio candidato

Este modelo expressa responsabilidades. Nomes de campos, banco e formato ainda
nao estao decididos.

### 5.1 Identidade arquivavel da conta

```text
Account
  account_id             UUID imutavel gerado pelo sistema
  platform_id            chave estavel do conector
  display_name           nome livre, mutavel e nao unico
  upstream_subject       identificador upstream opcional
  lifecycle_status       active | disabled | historical
  created_at
  updated_at
```

Regras candidatas:

- renomear nao muda `account_id`, paths, relacoes ou dados;
- nomes iguais sao validos;
- `account_id` nunca e reutilizado;
- `upstream_subject` nao deve conter credencial e pode exigir tratamento como
  dado pessoal;
- `historical` e uma decisao explicita de preservacao sem novas capturas;
- `disabled` interrompe operacao sem apagar dados ou identidade.

### 5.2 Vinculo local de autenticacao

```text
AccountBinding
  account_id
  profile_locator
  auth_status            valid | expired | missing | unknown
  last_validated_at
  observed_subject       opcional
```

O vinculo e especifico da maquina. Depois de uma restauracao limpa, a conta
continua existindo, mas `auth_status=missing`. Um novo login deve vincular o
profile recriado ao `account_id` existente. Quando a plataforma expuser um
subject estavel, um subject diferente bloqueia o vinculo e evita mistura de
historicos.

### 5.3 Catalogo de plataformas

Um adaptador de plataforma poderia declarar, sem acoplar a interface ao
extractor:

```text
PlatformAdapter
  platform_id e capacidades
  registrar/abrir login
  validar autenticacao
  resolver paths da instancia
  capturar e baixar assets
  reconciliar
  expor status operacional
```

O parser continua sendo uma fronteira de dados. Ele consome todas as instancias
validas de uma plataforma e produz os Parquets da plataforma, com procedencia
de conta preservada.

## 6. Fluxo alvo candidato

```text
AccountService
  ├── catalogo de plataformas
  ├── identidades de conta
  ├── bindings locais de autenticacao
  └── execucoes por instancia
             │
             ▼
platform/account -> raw/account -> reconcile -> merged/account
                                              │
                                              ▼
                         parser da plataforma agrega instancias
                                              │
                                              ▼
                                    processed -> unified
                                              │
                         ┌────────────────────┴───────────────────┐
                         ▼                                        ▼
                 dashboard/relatorios                 snapshot para consumidor
```

Falhas, discovery baseline, logs e freshness devem ser avaliados por instancia
antes de serem agregados por plataforma. Uma falha em uma conta nao pode marcar
outra como removida. O pipeline nao deve declarar estado verde se `processed`
ou `unified` forem anteriores aos inputs modificados.

## 7. Interface operacional futura

A visao de produto ja preve cadastro de fontes e contas, login/relogin, estados
ativo/desativado/historico, sync seletivo, erros e freshness. A conversa atual
adicionou um requisito: registrar e sincronizar uma conta suportada deve ser uma
operacao normal do produto, nao uma tarefa que dependa de um agente de IA ou de
edicao de codigo.

Fluxo candidato:

1. Selecionar uma plataforma suportada.
2. Adicionar uma conta e escolher um nome livre.
3. O sistema gera a identidade imutavel.
4. Abrir o fluxo de login; senha e MFA continuam sendo fornecidos diretamente
   pelo usuario a plataforma.
5. Validar uma chamada minima e, quando possivel, o subject upstream.
6. Vincular o profile local.
7. Oferecer a primeira captura e acompanhar seu progresso.
8. Exibir autenticacao, ultima captura, freshness, erros e relatorios.

Esse fluxo pode ser exposto primeiro por CLI e depois por uma aplicacao. A
tecnologia da aplicacao permanece deliberadamente aberta.

## 8. Web local, Electron, Tauri ou hibrido

### 8.1 O que um app desktop pode melhorar

Uma aplicacao empacotada pode oferecer instalador, icone, atualizacao,
integracao com Keychain/servicos do sistema, notificacoes, processo de
background e uma experiencia de login e operacao mais coesa. Tauri fornece
bundling e instaladores por plataforma; distribuicao em macOS normalmente
envolve assinatura e notarizacao. Electron tambem possui APIs que usam os
mecanismos criptograficos do sistema, como `safeStorage`.

Referencias oficiais:

- [Tauri: distribuicao e assinatura](https://v2.tauri.app/distribute/)
- [Electron: safeStorage](https://www.electronjs.org/docs/latest/api/safe-storage)

### 8.2 O que o empacotamento nao resolve sozinho

Electron ou Tauri nao tornam cookies e profiles automaticamente seguros. Se o
computador ou a sessao do usuario estiverem integralmente comprometidos, uma
aplicacao executada pelo mesmo usuario nao oferece uma fronteira absoluta. O
modelo precisa declarar contra quais ameacas pretende proteger: outro usuario
local, outro processo no mesmo usuario, malware, copia de backup, vazamento por
log, extensao de navegador ou conteudo remoto comprometido.

Electron lembra que uma aplicacao desktop tem poderes maiores que um site e
que carregar conteudo remoto nao confiavel amplia o impacto de XSS. Suas
recomendacoes incluem desabilitar integracao Node em conteudo remoto, manter
isolamento de contexto e sandbox, validar IPC, limitar navegacao e permissoes e
manter Electron atualizado.

Tauri separa o core Rust do frontend no WebView e controla comandos nativos por
permissions, capabilities e scopes. Essa fronteira tambem depende de comandos
e permissoes corretamente desenhados; codigo no core ou em plugins continua
privilegiado.

Referencias oficiais:

- [Electron: guia de seguranca](https://www.electronjs.org/docs/latest/tutorial/security)
- [Electron: isolamento de contexto](https://www.electronjs.org/docs/latest/tutorial/context-isolation)
- [Tauri: modelo de seguranca](https://v2.tauri.app/security/)
- [Tauri: runtime authority](https://v2.tauri.app/security/runtime-authority/)
- [Tauri: scopes de comandos](https://v2.tauri.app/security/scope/)

### 8.3 Login remoto e shell privilegiado

As paginas de login das plataformas sao conteudo remoto e mudam sem controle
deste projeto. Uma direcao a avaliar e manter a interface principal composta
apenas por conteudo local e abrir o login em um navegador externo ou em um
processo dedicado, sem expor APIs privilegiadas da aplicacao a pagina remota.

Isso permitiria que um futuro app desktop orquestrasse login e captura sem
transformar cada site de IA em conteudo remoto dentro do renderer privilegiado.
O comportamento headed exigido por ChatGPT e Perplexity deve fazer parte dos
spikes antes de escolher o shell.

### 8.4 Segredos e profiles

Keychain, DPAPI, Secret Service, `safeStorage` ou um cofre como Stronghold podem
proteger pequenos segredos e chaves de envelope. Eles nao substituem uma
decisao sobre a arvore inteira de profiles Chromium, cookies e localStorage.

Pontos a investigar:

- manter profiles dedicados por conta e confiar na protecao oferecida pelo
  browser/OS;
- criptografar profiles quando a aplicacao estiver fechada, considerando custo,
  locks e risco de corrupcao;
- guardar apenas metadados e chaves no Keychain;
- limitar permissoes de filesystem e excluir profiles de backups inseguros;
- detectar e comunicar claramente expiracao ou ausencia de autenticacao; e
- definir como assinatura do app afeta acesso consistente ao Keychain.

Tauri possui plugin Stronghold para armazenamento de segredos, mas sua
adequacao a profiles completos nao foi validada nesta exploracao.

Referencia oficial:

- [Tauri: plugin Stronghold](https://v2.tauri.app/plugin/stronghold/)

## 9. Fronteira com `AI Interaction Analysis`

Antes de qualquer migracao de identidade ou schema, o consumidor deve receber
uma copia baseline da base atual:

1. localizar o projeto consumidor;
2. identificar exatamente quais Parquets ele usa;
3. copiar esses arquivos sem substituir inputs existentes sem validacao;
4. registrar hashes SHA-256, schemas, contagens, timestamp e revisao de origem;
5. executar o smoke test atual; e
6. manter o resultado como referencia de antes da mudanca.

Uma evolucao candidata e substituir o `dvc import` direto por um snapshot
analitico exportado atomicamente:

```text
data/unified selecionado + manifest
                 │
                 ▼
input local e reproduzivel do consumidor
```

O produtor continua sendo o cofre canonico de `raw`, `merged`, `processed` e
`unified`. O consumidor recebe apenas os Parquets necessarios e um manifesto de
proveniencia. A copia pode ser ignorada pelo Git e regenerada; o formato, o
destino e a politica de versoes ainda precisam ser definidos.

O projeto consumidor nao foi localizado automaticamente nos caminhos
inspecionados durante esta conversa. Seu caminho deve ser confirmado antes da
baseline.

## 10. Sequencia candidata quando o trabalho for retomado

1. Localizar o `AI Interaction Analysis` e produzir a baseline sem alterar sua
   logica analitica.
2. Definir o threat model local e os requisitos de instalacao/distribuicao.
3. Fazer spikes pequenos para web local, Electron e Tauri, incluindo login
   headed, Playwright, Keychain e subprocessos Python.
4. Escolher a arquitetura da aplicacao e da camada operacional mutavel.
5. Fechar a identidade de conta e sua persistencia.
6. Fechar a identidade canonica de conversas e a migracao de referencias.
7. Especificar `AccountService` e `PlatformAdapter`.
8. Implementar e validar o nucleo sem interface grafica.
9. Migrar ChatGPT; normalizar Gemini e NotebookLM.
10. Validar parser, unified, dashboard e Quarto, sem publicar.
11. Comparar um snapshot novo com a baseline no consumidor.
12. Implementar a interface operacional como entrega separada.
13. Adotar o contrato nas demais plataformas web de forma gradual.

Essa ordem e apenas uma hipotese. Em particular, o spike de shell pode mostrar
que o backend Python atual deve permanecer como processo separado ou servico
local, em vez de ser incorporado ao binario desktop.

## 11. Decisoes em aberto

### Identidade e schema

1. UUIDv4, UUIDv7 ou ULID para `account_id`?
2. Onde a identidade arquivavel da conta vive: banco operacional, JSON
   DVC-tracked, tabela Parquet propria ou combinacao?
3. O campo canonico atual `account` vira `account_id`, e como ocorre a
   deprecacao?
4. Deve existir uma tabela/dimensao `accounts` em `processed` e `unified`?
5. `account_id` passa a compor as chaves canonicas ou os IDs de conversa,
   projeto e artefato recebem namespace de conta?
6. Como migrar referencias existentes do Gemini, NotebookLM, ChatGPT e da
   camada curada sem perder ancoras?
7. Como armazenar ou proteger `upstream_subject` e quais plataformas o expoem
   de forma estavel?

### Estado e persistencia

8. Qual tecnologia armazena estado operacional mutavel: SQLite, outro banco ou
   arquivos estruturados?
9. O que pertence ao cofre DVC e o que pertence apenas ao estado local?
10. Como fazer backup da identidade de contas sem incluir credenciais?
11. Quais transicoes existem entre active, disabled e historical?
12. O que significa excluir uma conta na interface, considerando o principio de
    preservacao?

### Aplicacao e distribuicao

13. A superficie principal sera web local, Electron, Tauri ou uma combinacao?
14. Backend Python roda embutido, como sidecar ou como servico local separado?
15. Como empacotar Python, Playwright/Chromium, Quarto e dependencias nativas?
16. Quais sistemas operacionais precisam ser suportados inicialmente?
17. Como assinar, notarizar, atualizar e fazer rollback do app?
18. Login ocorre no navegador do sistema, Chromium gerenciado ou WebView
    dedicado?

### Seguranca

19. Qual e o threat model concreto?
20. O que precisa de Keychain e o que permanece em profiles do browser?
21. E aceitavel que um processo no mesmo usuario consiga ler profiles, ou isso
    precisa de mitigacao adicional?
22. Como impedir que conteudo remoto de login alcance comandos privilegiados?
23. Como redigir logs, crash reports e diagnosticos sem vazar tokens, cookies ou
    conteudo pessoal?
24. Como tratar backup local, FileVault e permissoes de filesystem?

### Pipeline e produto

25. Como registrar contas sem quantidade fixa e como descobrir capacidades de
    cada plataforma?
26. Uma falha em uma conta permite parse parcial ou bloqueia toda a plataforma?
27. Como gerar relatorios consolidados e individuais sem arquivos manuais por
    conta?
28. Como representar contas historicas sem profiles e sem poluir alertas de
    freshness?
29. Como a futura interface coordena filas, locks, browser headed e retry?
30. Ate onde a primeira implementacao deve normalizar plataformas existentes?

### Consumidor

31. Onde esta o checkout atual do `AI Interaction Analysis`?
32. Quais Parquets e revisoes ele realmente consome?
33. O snapshot substitui DVC import ou e primeiro uma camada de compatibilidade?
34. Onde o manifesto vive e qual e sua politica de versoes?
35. Como comparar a baseline com dados que mudam legitimamente por nova captura?

## 12. Criterios antes de implementar

O trabalho nao deve entrar em implementacao ate que exista uma especificacao
aprovada cobrindo pelo menos:

- identidade e persistencia de conta;
- chaves canonicas e migracao;
- fronteiras entre core, adaptadores e interfaces;
- threat model e tratamento de profiles;
- estrategia de aplicacao/distribuicao, ainda que em primeira fase;
- baseline e contrato com o consumidor;
- plano de rollback dos dados; e
- testes de isolamento, idempotencia, freshness e restauracao.

Enquanto essas decisoes permanecerem abertas, o comportamento atual continua
canonico. Nao se deve cadastrar uma segunda conta em paths compartilhados nem
publicar mudanca de schema como solucao provisoria.
