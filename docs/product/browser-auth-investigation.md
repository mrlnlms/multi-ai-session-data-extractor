# Investigacao: autenticacao e profiles de navegador

Este documento registra hipoteses surgidas durante uma investigacao de uso de
disco no macOS. Ele orienta uma verificacao futura; nao altera o contrato
atual de contas, bindings ou coleta e nao autoriza mudancas em profiles locais.

## Contexto observado

O fluxo atual abre um navegador real para que a pessoa autentique cada conta
nas plataformas. Durante a investigacao de disco, alguns profiles do Chrome
usados pelo projeto aparentavam acumular cerca de 1 GB ou mais, enquanto um
profile pouco usado tinha poucos MB. Essa observacao nao foi uma medicao
sistematica nem prova que a sincronizacao Google causou o crescimento, mas
motivou revisar o custo e o modelo operacional dos profiles.

O onboarding pode tornar ambigua a diferenca entre autenticar-se no servico
coletado e entrar ou ativar sincronizacao Google no Chrome. O contrato vigente
ja diz que Google/Chrome Sync e opcional e nao e evidencia de autenticacao na
plataforma; a oportunidade em aberto e verificar se o fluxo e a orientacao ao
operador tornam essa separacao clara na pratica.

## Hipoteses a verificar

### 1. Login interativo e coleta headless

CAPTCHA, desafios anti-bot, confirmacao de dispositivo e MFA podem exigir um
navegador visivel para criar ou renovar a sessao. Em algumas fontes, uma sessao
ja estabelecida e persistida talvez permita syncs seguintes em modo headless.
Isso e uma hipotese por plataforma, nao uma capacidade geral presumida.

Verificar por fonte, com conta e profile de teste apropriados:

1. concluir login manual em modo headed e persistir a sessao;
2. fechar completamente o navegador;
3. reabrir a mesma sessao em modo headless e confirmar autenticacao pela
   resposta/comportamento da propria fonte;
4. comparar headed e headless, registrando challenges, falhas e sinais de
   login expirado;
5. observar a duracao da sessao e o comportamento apos renovacao/expiracao.

O fluxo candidato e: login inicial ou renovacao em navegador visivel; coleta
headless quando validada; interrupcao segura e pedido de login visivel quando
a fonte exigir interacao. Desafios nao devem ser contornados nem interpretados
como autenticacao bem-sucedida.

### 2. Perfil por conta da plataforma ou por identidade de autenticacao

O modelo operacional observado tende a associar cada conta de plataforma a um
profile persistente separado. Surgiu a hipotese de que contas em plataformas
diferentes, usadas pela mesma pessoa/identidade de autenticacao (por exemplo,
OAuth Google), poderiam compartilhar um profile; duas contas da mesma
plataforma continuariam precisando de estados isolados para evitar conflito de
sessao. Sete contas de plataforma poderiam, no cenario observado, corresponder
a tres identidades de autenticacao e potencialmente tres profiles, mas essa
contagem e apenas ilustrativa.

Cookies e armazenamento web sao particionados por origem, mas isso por si so
nao demonstra que compartilhar o profile seja seguro, funcional ou desejavel.
OAuth, selecao de conta, extensoes, isolamento entre contas, concorrencia de
sync e politicas das fontes podem impor limites adicionais. Verificar esses
limites antes de propor uma entidade `Browser Identity`/`Auth Identity` ou
alterar o binding atual de um UUID de conta para um profile local.

## Salvaguardas e criterios

- Autenticacao Google no site para OAuth e Google/Chrome Sync sao coisas
  distintas. Sync do navegador deve continuar opcional e nunca ser usado como
  proxy, requisito ou evidencia de autenticacao na fonte.
- Explicar no onboarding que a pessoa deve entrar no site da plataforma e nao
  precisa entrar ou ativar sincronizacao no Chrome. Avaliar se a orientacao
  atual e suficiente ou se a UX deve desencorajar/impedir essa etapa.
- Nao usar perfil Google do Chrome, extensoes, historico ou estado de sync
  como prova de identidade ou saude da conta upstream; a fonte e a autoridade.
- Medir profiles antes de atribuir uso de disco a cache, Sync ou duplicacao.
  Preservar o estado autenticado e nao apagar profiles ou caches durante a
  investigacao sem uma acao de limpeza separada e deliberada.
- Qualquer compartilhamento precisa manter contas da mesma plataforma
  isoladas, mapear explicitamente conta -> identidade/profile, e tratar
  profile, binding e auth health como estado local fora de Git, DVC e Parquet.
- Validar cada fonte independentemente. Headless pode ser aceito em uma fonte
  e recusado em outra; nao transformar observacoes pontuais em contrato global.

## Aprendizado de processo

O incômodo operacional pode revelar uma premissa de modelagem que uma revisao
de codigo, feita dentro do desenho existente, nao questionaria. Neste caso, a
pergunta nao e apenas se a implementacao `plataforma + conta -> profile`
funciona, mas se esse isolamento e realmente necessario em todos os casos.
Investigar efeitos observados no uso e questionar a premissa antes de otimizar
a implementacao.

## Ligacoes com o estado atual

- O contrato atual de identidade, lifecycle, binding local e autenticacao
  continua em [account-architecture.md](account-architecture.md), incluindo
  que Chrome Sync nao e requisito nem evidencia de login upstream.
- O onboarding operacional atual esta descrito em [SETUP.md](../SETUP.md).
- O item de roadmap correspondente esta em
  [ROADMAP.md](../ROADMAP.md#authentication-and-browser-profile-model).

## Triagem estatica inicial (2026-09-26)

Esta triagem leu o onboarding, o contrato de contas, o registry, os comandos
de sync e os estados mantidos das plataformas. Nao abriu browsers nem leu
profiles autenticados; portanto, descreve o desenho e evidencias ja
documentadas, nao um novo teste de autenticacao.

### Headless por fonte

O fluxo de login das nove fontes web usa Chromium persistente com janela
visivel. Isso nao significa que todos os syncs usem headless, nem que o
comportamento tenha sido validado recentemente para todas as fontes.

| Fonte | Evidencia estatica atual | O que falta verificar |
|---|---|---|
| ChatGPT | O estado da plataforma registra captura DOM headed porque Cloudflare detecta headless. O sync ainda usa contexto headless para baixar fontes de Projects via request. | Distinguir captura principal de chamadas auxiliares e confirmar se algum subfluxo pode dispensar janela visivel. |
| Perplexity | O estado registra HTTP 403 do Cloudflare em headless; a captura atual e headed. | Nenhum ensaio novo; tratar headed como requisito ate evidencia em contrario. |
| Claude.ai | O comando de sync pede contexto headless. | Confirmar comportamento autenticado em execucao; o codigo sozinho nao prova sucesso da sessao. |
| Gemini | O comando de sync pede contexto headless; o estado registra execucao headless de tres contas. | Diferenciar esse registro historico de validacao de renovacao, expiracao e desafios atuais. |
| NotebookLM | O comando de sync e o orchestrator pedem contexto headless; o estado registra execucao headless de tres contas. | Diferenciar execucao historica de teste controlado de sessao expirada e reautenticacao. |
| Qwen | O comando de sync pede contexto headless. | Confirmacao empirica por conta e sinais explicitos de sessao invalida. |
| DeepSeek | O comando de sync pede contexto headless. | Confirmacao empirica por conta e sinais explicitos de sessao invalida. |
| Grok | O sync usa headless por padrao e oferece `--headed`. | Registrar resultado comparativo e desafios por fonte. |
| Kimi | O sync usa headless por padrao e oferece `--headed`. | Registrar resultado comparativo e desafios por fonte. |

### Compartilhamento de profile

O binding local atual e `account_id -> profile_key`, mas o caminho fisico e
construido tambem com o prefixo da plataforma (`<profile_prefix><profile_key>`).
Logo, repetir a mesma chave em duas plataformas ainda aponta para duas pastas
diferentes; o modelo atual nao representa compartilhamento de um mesmo
diretorio Chromium entre plataformas. Dentro de cada plataforma, bindings
duplicados para a mesma profile key sao rejeitados. Alem disso, `raw` e
`merged` permanecem isolados por UUID/conta, uma protecao necessaria mesmo se
alguma camada futura reutilizar autenticacao.

Assim, a ideia de reduzir o numero de profiles por identidade OAuth nao pode
ser implementada apenas reutilizando o mesmo rotulo de binding. Ela exigiria
um modelo explicito de identidade/profile compartilhado e mudancas no resolver
de caminhos, concorrencia e saude de autenticacao. A triagem nao estabelece
que compartilhar o user-data directory seja suportado pelo Chromium ou seguro
para estes extratores. Uma alternativa de menor acoplamento, ainda a avaliar,
e autenticar em cada profile de plataforma sem ativar Chrome Sync.

O onboarding ja diz que Sync e opcional, que o login deve ocorrer no site da
plataforma e que a identidade precisa ser conferida no proprio servico. Isso
evidencia que a orientacao textual existe; nao avalia sua clareza durante a
interacao real de login.

### Proximo passo delimitado

Antes de qualquer mudanca de contrato, medir os profiles existentes sem
inspecionar conteudo sensivel, selecionar uma fonte cujo sync headless ja
esteja documentado e uma conta de teste, e executar uma verificacao explicita
de autenticacao sem concorrencia. Para compartilhamento, primeiro verificar
se o objetivo e evitar multiplos logins ao provedor ou reduzir armazenamento:
os dois objetivos tem mecanismos e riscos diferentes. Qualquer teste que
abra, modifique, copie ou mova profiles locais fica para uma etapa deliberada;
esta triagem estatica nao fez essas operacoes.
