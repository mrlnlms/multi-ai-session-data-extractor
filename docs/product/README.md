# Produto e arquitetura da aplicacao

Este diretorio descreve a evolucao do projeto de extractor com superficies
separadas para uma **aplicacao local-first de arquivo pessoal de interacoes com
IA**. Comece por este mapa; os demais documentos aprofundam somente uma parte
da decisao.

## Direcao arquitetural

Hoje, a experiencia esta repartida entre duas superficies:

```text
dashboard/                  notebooks/
operacao e status           perfis e relatorios Quarto
        \                         /
         \ consomem servicos e Parquets
          v
src/application/ + src/workflows/ + data/unified/
```

O alvo nao e unir fisicamente essas pastas. E fazer uma unica aplicacao assumir
as experiencias estaveis de produto, mantendo o dominio fora do frontend:

```text
                 aplicacao local-first
        +----------------+----------------+
        | operacao       | arquivo/leitor |
        | e saude        | e busca        |
        +----------------+----------------+
        | curadoria assistida e visualizacoes |
        +-------------------------------------+
                         |
              servicos UI-neutral em src/
                         |
       arquivo canonico + estado curado separado
```

O Streamlit atual e um adaptador substituivel e pode servir de prototipo durante
a transicao. Os perfis Quarto padronizados por plataforma ou conta deixam de
ser uma superficie obrigatoria quando suas visualizacoes estaveis forem
absorvidas por paginas dinamicas da aplicacao. Quarto continua relevante para
analise exploratoria e autoral: perguntas abertas, investigacoes e experimentos
que nao pertencem ao fluxo permanente do produto.

O backend de captura, preservacao, contas, assets, schema e pipeline foi
consolidado primeiro, ao longo da evolucao do projeto. Streamlit e os perfis
Quarto ajudaram a usar e observar esse backend rapidamente como prototipo. A
proxima etapa e uma experiencia de produto mais coesa sobre essa base, reduzindo
a dependencia de Streamlit e dos QMDs padronizados no uso cotidiano. Isso nao
determina ainda o shell nem exige abandonar Quarto como bancada opcional.

O que existe hoje e um ponto de partida verificavel, nao a especificacao da
proxima interface. Lacunas como editar nomes de grupos, guiar logins, acompanhar
syncs e atualizar a visao unificada apos uma coleta seletiva sao trabalho da
transicao, nao motivos para conservar o fluxo atual. Contratos de preservacao,
proveniencia e separacao entre dados canonicos e estado local continuam valendo
quando a experiencia e a orquestracao mudarem.

Essa direcao nao escolhe ainda o shell final (web local, Electron, Tauri ou
hibrido) e nao autoriza remover `dashboard/`, `notebooks/` ou a integracao atual
com os relatorios antes que suas funcoes tenham substitutos validados.

## Mapa dos documentos

| Pergunta | Documento | Papel |
|---|---|---|
| O que o produto esta se tornando? | [product-vision.md](product-vision.md) | Visao validada das frentes de operacao, leitor e curadoria; nao e uma especificacao. |
| O que vem primeiro e qual trabalho esta pendente? | [../ROADMAP.md](../ROADMAP.md) | Prioridade operacional e sequencia corrente. |
| Como o leitor deve interpretar identidades, branches e eventos? | [reader-and-identity-contract.md](reader-and-identity-contract.md) | Contrato tecnico mantido para identidade e fidelidade. |
| Como funcionam hoje identidade, lifecycle, login local e sync por conta, e o que ainda depende da futura aplicacao? | [account-architecture.md](account-architecture.md) | Contrato atual do backend de contas e fronteira das decisoes futuras de produto/distribuicao. |
| Como as contas compartilham profiles Chrome? | [account-architecture.md](account-architecture.md#direcao-aprovada-para-compartilhamento-de-profiles) | Grupos, bindings locais, isolamento do acervo e restore do catálogo. |
| Como o dashboard atual e operado? | [../operations/dashboard.md](../operations/dashboard.md) | Manual da superficie existente, nao arquitetura-alvo. |

Quando existirem, planos temporarios, probes de decisao e handoffs de
implementacao pertencem a `private/docs/discussions/`; tarefas diretas nao
exigem a criacao desses documentos. Uma decisao duravel deve ser promovida ao
documento publico correspondente acima e nao deve permanecer visivel apenas
por ordem de criacao dos planos privados.

## Jornada e sequencia de transicao

A proxima frente de produto comeca pela aplicacao local que acompanha uma
jornada completa de coleta e exploracao. Esta e a direcao de implementacao,
nao uma afirmacao de que cada passo ja funciona na interface atual. A ordem
entre operacao, exploracao, leitor e curadoria orienta o trabalho; detalhes de
tecnologia e entregas ficam para o desenho de cada etapa. O
[roadmap](../ROADMAP.md) registra a prioridade corrente.

1. Criar e identificar grupos de navegador; cadastrar contas das plataformas
   web em cada grupo e permitir ajustar seus nomes e associacoes. Fontes CLI
   entram na coleta sem pertencer a um grupo de navegador.
2. Guiar login e relogin em navegador visivel, distinguindo a organizacao
   restauravel dos grupos, os profiles e cookies locais e a evidencia de
   autenticacao de cada conta.
3. Executar coleta completa ou seletiva por fonte ou conta, acompanhar
   progresso e falhas, e atualizar os dados unificados que a aplicacao le.
4. Explorar o acervo em paginas dinamicas: visao geral, perfis por fonte e
   conta, cobertura, volumes, evolucao e tabelas filtraveis. Os templates QMD
   atuais sao o ponto de partida para essas visoes descritivas; consultas e
   definicoes de metricas devem ser compartilhadas, sem criar duas verdades.
5. Acrescentar busca e leitor de conversas sobre o acervo unificado, com
   mensagens, eventos e assets conforme a evidencia de cada fonte.
6. Evoluir para edicao e curadoria em estado separado do arquivo canonico,
   integradas ao contexto de leitura.

O vault, a identidade canonica e a dimensao analitica de contas ja foram
concluidos e publicados. A primeira rodada de memoria/configuracao foi
concluida; retomadas dependem de nova evidencia. O leitor continua sendo a
maior lacuna de acesso ao conteudo preservado, mesmo vindo depois da primeira
experiencia de operacao e exploracao. Quarto permanece como bancada para
investigacoes autorais. A migracao de telas e relatorios exige substitutos
validados antes de retirar os caminhos atuais. O pipeline hoje renderiza Quarto
antes da publicacao; ao absorver as visoes padronizadas, essa dependencia de
renderizacao tambem precisa ser redesenhada sem enfraquecer a validacao dos
dados publicados.
