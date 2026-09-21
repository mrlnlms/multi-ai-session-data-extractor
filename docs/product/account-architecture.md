# Instancias de conta e arquitetura da aplicacao

**Status:** contrato v2 implementado e publicado: UUID unico, metadados
editaveis, bindings locais, paths UUID-native e dimensao analitica derivada.
A migracao DVC do catalogo/layout v1 foi aplicada preservando os UUIDs e os
dados existentes; empacotamento da aplicacao continua uma frente separada.

**Origem:** 2026-08-31. **Revisto contra codigo e dados:** 2026-09-21.

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

Este documento preserva a origem da decisao, descreve o contrato que foi
implementado e separa dele as decisoes ainda abertas da futura aplicacao. O
estado observavel no codigo e nos dados prevalece sobre as hipoteses historicas
mantidas aqui.

## 2. Evidencia no estado atual

### 2.1 Plataformas web

Gemini e NotebookLM possuem profiles e arvores `raw`/`merged` por conta.
Gemini usa tres contas ativas e descobre automaticamente as arvores
`account-N` no parser; os relatorios individuais seguem o padrao
`*-acc-N.qmd`.

ChatGPT, Claude.ai, Kimi, Qwen e DeepSeek tambem usam um profile selecionavel
e arvores cumulativas isoladas por conta. Grok e Perplexity continuam com uma
conta configurada. Trocar apenas o profile sem isolar os dados pode:

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

O unificador considera conversa por `(source, account_id, conversation_id)` e
usa a mesma dimensao nas chaves das tabelas filhas. No contrato v2,
`account_id` vem do diretorio UUID e e validado contra o catalogo; `account`
permanece como rotulo legado.
IDs nativos e IDs derivados existentes nao mudam.

O projeto `AI Interaction Analysis` consome `processed` e `unified` por DVC.
Como ele e o unico consumidor e ambos os projetos sao pessoais, existe uma
janela favoravel para revisar esse acoplamento antes de publicar um schema ou
uma identidade novos.

### 2.4 Inventario local e operacoes explicitas

`src/accounts.py` consolida as instancias observaveis a partir de evidencias
independentes: defaults operacionais do catalogo de plataformas, chaves do
registro privado, diretorios de profile, arvores preservadas em `raw`/`merged`
e archives historicos declarados pela plataforma em `data/external`. Contas com
dados permanecem visiveis mesmo sem registro ou profile. Um profile presente
indica apenas estado local; nao comprova cookies validos nem autenticacao
upstream.

O inventario e exposto por `PlatformState.accounts` para callers em `src/` e
para a visao **Accounts** do dashboard Streamlit. O carregamento continua
somente leitura e offline, exibindo cada evidencia separadamente. Operacoes de
catalogo, binding, verificacao de login e sync seletivo passam por servicos em
`src/`, exigem acao/confirmacao e nao alteram schema ou publicacao. Gemini e
NotebookLM preservam `1`, `2`, `3` como ordem default, mas aceitam chaves
tecnicas seguras quando selecionadas explicitamente.

`src/account_catalog.py` acrescenta uma camada arquivavel, versionada e
restauravel por DVC, com UUID imutavel e lifecycle explicito (`active`,
`disabled` ou `historical`). `src/accounts.py` faz uma uniao lossless entre o
catalogo e as evidencias locais: registros sem qualquer evidencia continuam
visiveis como tombstones, e evidencias ausentes do catalogo continuam visiveis
como `Unclassified`. O UUIDv5 deterministico dessas contas legadas preserva a
identidade entre previews. Profile ausente, logout ou token perdido nunca
alteram lifecycle automaticamente.

### 2.5 Sessao da plataforma versus identidade do navegador

Um profile persistente do extrator e apenas um diretorio isolado de estado do
navegador. A autenticacao relevante e a sessao criada pelo servico upstream
dentro desse diretorio. Vincular o Chrome a uma conta Google, ativar sync do
navegador ou aceitar a criacao de um perfil nomeado pelo provedor e uma escolha
independente e opcional.

Nenhum inventario, auth-check, login ou sync pode usar o estado da conta do
Chrome como requisito, prova de autenticacao ou identidade da conta upstream.
O operador pode recusar o vinculo sem degradar a coleta. A identidade deve ser
confirmada pela propria plataforma; a saude da sessao, por uma leitura
upstream explicita. Um token local rejeitado tambem nao prova, sozinho, logout:
o cliente deve permitir que uma sessao ainda valida conclua seu refresh antes
de classificar a autenticacao como expirada.

No NotebookLM, cada subdiretorio de `data/external/notebooklm-snapshots/`
tambem materializa uma conta `archive:<nome-normalizado>`, igual a identidade
emitida pelo parser historico. A evidencia permite mostrar o acervo corporativo
inacessivel sem confundi-lo com as contas capturaveis `1`, `2` e `3`; ela nao
afirma por si so se a conta foi excluida upstream.

A mesma regra vale para qualquer fonte web: se uma conta perder token, profile
ou acesso upstream, suas arvores `raw`/`merged` continuam materializando a
identidade no inventario mesmo sem registro privado. Uma futura acao de
"excluir conta" no produto deve significar retirar sua capacidade de captura e
registrar lifecycle historico, nunca apagar a identidade ou o acervo. Enquanto
esse lifecycle explicito nao existir, a interface descreve apenas as evidencias
locais e nao presume a causa da perda de acesso.

## 3. Distincao central

O modelo atual separa dois conceitos:

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

### 3.1 Glossario de conta

Os nomes abaixo descrevem responsabilidades diferentes e nao devem ser
apresentados ao usuario como se fossem equivalentes:

| Nome | Significado |
|---|---|
| `display_name` | Nome livre e editavel escolhido pelo usuario, como `Trabalho` ou `Estudos`. Quando estiver vazio, a aplicacao deve gerar uma apresentacao util a partir da plataforma e do e-mail conhecido. |
| `email` | E-mail usado na conta upstream, quando informado pelo usuario ou observado de forma confiavel pelo conector. Nao e senha, cookie nem chave interna. |
| `account_id` | UUID imutavel que identifica a conta dentro do acervo. E a identidade canonica usada pelos servicos, bindings e dados publicados. |
| `technical_key` | Locator presente apenas no catalogo v1 e no planejamento da migracao; nao pertence ao modelo v2. |
| `profile_key` | Nome local, especifico da maquina, do profile de navegador vinculado ao `account_id`. |
| binding | Associacao local entre o `account_id` e o `profile_key` que contem a sessao autenticada naquela instalacao. |
| auth health | Ultima observacao explicita sobre a validade da sessao local; nao e inferida apenas porque um profile existe. |

O `account_id` e o identificador duravel. O codigo le o catalogo v1 somente
para produzir um plano de migracao completo e nao serializa seu locator legado
no v2. Paths duraveis usam `account-<UUID>`; o binding continua resolvendo o
UUID para um profile local. A compatibilidade v1 permanece somente como leitor
finito para restauracoes anteriores a migracao ja publicada.

## 4. Contratos implementados

Os pontos abaixo descrevem o comportamento canonico atual:

1. A arquitetura possui um nucleo comum de contas e capacidades declaradas no
   registro de plataformas, em vez de reproduzir regras de identidade em cada
   script.
2. As nove plataformas web usam o contrato comum. Gemini e NotebookLM mantem
   suas chaves default por compatibilidade, mas contas selecionadas
   explicitamente nao dependem de uma quantidade fixa.
3. CLI e dashboard chamam os mesmos servicos UI-neutral. Regras de conta nao
   moram em `argparse` ou Streamlit.
4. O registro privado legado e apenas evidencia local e nunca funciona como
   chave, path ou identidade. O catalogo persiste `display_name` livre e
   editavel e e-mail opcional; quando o nome estiver vazio, a apresentacao usa
   plataforma e e-mail conhecido.
5. A identidade interna da conta e um UUID imutavel. Contas anteriores ao
   catalogo receberam UUIDv5 deterministico; novas contas recebem UUID proprio.
6. Um futuro identificador estavel fornecido pela plataforma sera dado
   separado. Ele podera detectar login na conta errada, sem substituir
   automaticamente a identidade interna.
7. Ciclo de vida e autenticacao sao estados independentes. Uma conta pode estar
   ativa com login ausente ou expirado; ausencia de cookies nao a transforma em
   conta historica.
8. Depois de restaurar Git + DVC em outra maquina, o catalogo preserva a mesma
   identidade. O profile e o binding local precisam ser recriados antes de uma
   nova captura.
9. Credenciais nunca entram em Git, DVC, Parquet ou logs. Profiles continuam
   sendo estado local descartavel e recriavel por login.
10. A abertura da interface de contas e somente leitura; cadastro, lifecycle,
    binding, verificacao de login e sync seletivo sao acoes explicitas e
    preview-first da entrega operacional.
11. `account_id` ja foi publicado nos Parquets sem substituir o campo legado
    `account`; o consumidor continua recebendo `processed` e `unified` por DVC
    import.
12. `accounts.parquet` e derivado do catalogo e nao o substitui como fonte
    autoritativa; ele nao publica locators legados nem estado local.

## 5. Modelo de dominio atual

O dominio atual separa identidade arquivavel, binding local e observacao de
autenticacao. Campos futuros nao sao presumidos pelo contrato existente.

### 5.1 Identidade arquivavel da conta

```text
Account
  account_id             UUID imutavel gerado pelo sistema
  platform               nome canonico da plataforma
  display_name           nome livre opcional
  email                  e-mail opcional
  lifecycle_status       active | disabled | historical
  created_at
  updated_at
```

Regras atuais:

- `account_id` nunca e reutilizado;
- `historical` e uma decisao explicita de preservacao sem novas capturas;
- `disabled` interrompe operacao sem apagar dados ou identidade;
- profile ausente ou autenticacao expirada nao altera lifecycle;
- `display_name` e e-mail sao metadados opcionais editaveis do catalogo; e
- nenhum desses campos substitui o UUID nem e inferido de profile ou estado de
  autenticacao.

### 5.2 Vinculo local de autenticacao

```text
AccountBinding
  account_id
  profile_key
  updated_at

AuthObservation
  account_id
  status                 valid | expired | missing | unknown | error
  checked_at
  evidence_method        probe | operator | sync
  detail                 diagnostico curto e redigido
```

O vinculo e especifico da maquina. Depois de uma restauracao limpa, a conta
continua existindo, mas a autenticacao fica ausente ate um novo binding e
login. Uma futura verificacao por subject upstream exigira evidencia estavel
da plataforma e nao faz parte do contrato atual.

### 5.3 Por que catalogo, `.storage` e Parquet coexistem

As tres superficies nao sao cadastros concorrentes:

| Superficie | Papel | Autoritativa para |
|---|---|---|
| `data/accounts/catalog.json` | Estado operacional pequeno, duravel e restauravel | Quais contas existem, seus UUIDs e lifecycle |
| `.storage/` | Estado desta instalacao | Qual profile local esta vinculado e qual foi a ultima observacao de autenticacao |
| `data/unified/accounts.parquet` | Projecao analitica regeneravel e somente leitura | Consultas e joins dos consumidores com `account_id` |

O Parquet nao substitui o catalogo: ele e gerado a partir dele e nao deve ser
editado para cadastrar ou renomear contas. O `.storage/` tambem nao substitui o
catalogo: ao restaurar o acervo em outra maquina, a identidade permanece, mas o
login precisa ser refeito. Uma futura aplicacao pode armazenar catalogo e
estado local em tabelas distintas de um mesmo banco local, como SQLite, sem
eliminar essa separacao de responsabilidades; isso seria uma migracao propria,
nao uma consequencia da criacao da dimensao Parquet.

Presenca de profile nunca produz `valid` por inferencia. Uma observacao valida
declara como foi obtida: leitura minima automatizada (`probe`), confirmacao
explicita em navegador visivel (`operator`) ou sync seletivo e parse concluídos
com sucesso (`sync`). A confirmacao do operador nao tenta contornar protecoes
anti-bot e permanece estado local.

### 5.4 Registro de plataformas

`src/platforms/registry.py` declara metadados e capacidades de selecao das nove
fontes web sem acoplar a interface aos extractors. Os modulos de login, probe,
sync e parse permanecem junto de cada plataforma; nao existe hoje uma classe
monolitica `PlatformAdapter`.

O parser continua sendo uma fronteira de dados. Ele consome todas as instancias
validas de uma plataforma e produz os Parquets da plataforma, com procedencia
de conta preservada.

## 6. Fluxo implementado

```text
servicos UI-neutral em src/
  ├── catalogo e inventario de contas
  ├── bindings e auth health locais
  ├── capacidades no registro de plataformas
  └── planejamento/execucao por account_id
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
                 dashboard/relatorios                 DVC import no consumidor
```

Falhas, discovery baseline, logs e freshness devem ser avaliados por instancia
antes de serem agregados por plataforma. Uma falha em uma conta nao pode marcar
outra como removida. O pipeline nao deve declarar estado verde se `processed`
ou `unified` forem anteriores aos inputs modificados.

## 7. Interface operacional atual e evolucao futura

A visao de produto ja preve cadastro de fontes e contas, login/relogin, estados
ativo/desativado/historico, sync seletivo, erros e freshness. A conversa atual
adicionou um requisito: registrar e sincronizar uma conta suportada deve ser uma
operacao normal do produto, nao uma tarefa que dependa de um agente de IA ou de
edicao de codigo.

A pagina **Accounts** oferece controles preview-first sobre os servicos
canonicos. Ela nao executa rede na abertura, nao automatiza login e exige
confirmacao para mutacoes; lifecycle nunca exclui identidade ou dados.

O fluxo operacional disponivel hoje permite:

1. Selecionar uma plataforma suportada.
2. Adicionar uma conta com nome de exibicao e e-mail opcional.
3. O sistema gera o UUID imutavel antes de qualquer path duravel.
4. Abrir o fluxo de login; senha e MFA continuam sendo fornecidos diretamente
   pelo usuario a plataforma.
5. Validar uma chamada minima ou registrar confirmacao explicita do operador.
6. Vincular o profile local.
7. Executar sync e parse seletivos para a conta ativa.
8. Exibir lifecycle, evidencias locais e autenticacao observada.

CLI e dashboard chamam os mesmos servicos de dominio. Nome livre, progresso
detalhado, fila, retry e uma experiencia integrada de login permanecem temas da
futura aplicacao. Sua tecnologia continua deliberadamente aberta.

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

O consumidor existe no checkout irmao `AI Interaction Analysis`. Ele importa
`data/processed/` e `data/unified/` deste projeto por `dvc import` congelado e
registra seu contrato em `docs/unified-schema.md`, com smoke test proprio apos
atualizacoes deliberadas. A publicacao de `account_id` preservou o campo legado
`account`; nao foi necessario substituir o mecanismo de consumo.

Uma evolucao candidata e substituir o `dvc import` direto por um snapshot
analitico exportado atomicamente:

```text
data/unified selecionado + manifest
                 │
                 ▼
input local e reproduzivel do consumidor
```

O produtor continua sendo o cofre canonico de `raw`, `merged`, `assets`,
`processed`, `unified` e do catalogo em `accounts`. Um snapshot analitico com
manifesto permanece apenas uma possivel evolucao futura; nao e migracao em
andamento nem bloqueio para a dimensao de contas.

## 10. Fundacao concluida e proximas fronteiras

A fundacao reutilizavel de contas esta implementada nas nove plataformas web:
catalogo, inventario lossless, lifecycle, bindings, auth health, sync seletivo,
isolamento de paths, `account_id` publicado e `accounts.parquet` derivado do
catalogo. A frente estrutural de identidade de contas esta concluida; ela nao
depende da escolha do shell futuro.

Memoria/configuracao preservada, leitor, fila operacional, empacotamento e
distribuicao sao frentes separadas. Implementa-las nao deve reabrir a identidade
arquivavel ja publicada sem nova evidencia ou requisito incompatível.

## 11. Decisoes fechadas e abertas

A numeracao abaixo preserva os identificadores da lista original para manter
referencias historicas legiveis.

### Identidade e schema — decisoes fechadas ate 2026-09-21

1. Contas legadas usam UUIDv5 determinístico já persistido no catálogo.
2. A identidade arquivável vive em `data/accounts/catalog.json`, sob DVC.
3. `account_id` foi acrescentado; `account` foi preservado para compatibilidade.
4. A migracao preservou o catalogo como fonte autoritativa e publicou
   `accounts.parquet` como dimensao analitica derivada, somente leitura e sem
   locators legados.
5. `account_id` compõe as chaves sem alterar IDs existentes.
6. Web e NotebookLM histórico recebem UUID; CLI/manual permanecem nulos.
7. `upstream_subject` continua fora do contrato até existir evidência estável.

### Estado e persistencia — contrato atual

8. O catalogo arquivavel vive em `data/accounts/catalog.json`, sob DVC.
9. Bindings, profiles e auth health permanecem em `.storage/`, fora de Git,
   DVC e Parquet.
10. Lifecycle e autenticacao sao independentes; as transicoes de lifecycle sao
    explicitas, rejeitam no-op e nunca apagam identidade ou dados.
11. Uma acao futura chamada "excluir conta" deve retirar capacidade operacional
    e preservar catalogo e acervo; a experiencia e o nome final dessa acao ainda
    pertencem ao desenho da aplicacao.

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

25. Registro dinamico, capacidades e selecao por conta estao implementados para
    as nove plataformas web.
26. Contas historicas permanecem visiveis no inventario sem exigir profile nem
    participar dos alvos de sync.
27. Geracao dinamica de relatorios consolidados/individuais, filas, retry e
    coordenacao de browser headed permanecem decisoes da futura experiencia.

### Consumidor

31. O consumidor usa `processed` e `unified` por DVC import congelado.
32. Se um snapshot substituir esse contrato no futuro, onde vivem manifesto,
    politica de versoes e comparacao de mudancas legitimas?

## 12. Criterios para evolucoes futuras

Mudancas no backend existente devem preservar UUIDs, isolamento de paths,
catalogo lossless, separacao entre lifecycle e autenticacao, ausencia de
credenciais em superficies publicadas e compatibilidade deliberada com o
consumidor. Mudancas de schema seguem os gates normais de revisao, teste e
publicacao do projeto.

Empacotamento ou substituicao da interface exigem, adicionalmente, threat model,
tratamento de profiles, estrategia de distribuicao e rollback. Essas decisoes
nao bloqueiam manutencao do backend atual nem a frente independente de
memoria/configuracao de contas.
