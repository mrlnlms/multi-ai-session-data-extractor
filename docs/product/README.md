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

Essa direcao nao escolhe ainda o shell final (web local, Electron, Tauri ou
hibrido) e nao autoriza remover `dashboard/`, `notebooks/` ou a integracao atual
com os relatorios antes que suas funcoes tenham substitutos validados.

## Mapa dos documentos

| Pergunta | Documento | Papel |
|---|---|---|
| O que o produto esta se tornando? | [product-vision.md](product-vision.md) | Visao validada das frentes de operacao, leitor e curadoria; nao e uma especificacao. |
| O que vem primeiro e qual trabalho esta pendente? | [../ROADMAP.md](../ROADMAP.md) | Prioridade operacional e sequencia corrente. |
| Onde localizar planos e registros de trabalho relacionados, sem ler tudo? | [development-evidence-map.md](development-evidence-map.md) | Mapa seletivo por tema e estado; nao define prioridades. |
| Como o leitor deve interpretar identidades, branches e eventos? | [reader-and-identity-contract.md](reader-and-identity-contract.md) | Contrato tecnico mantido para identidade e fidelidade. |
| Como contas, login local e empacotamento podem funcionar? | [account-architecture.md](account-architecture.md) | Exploracao arquitetural pausada, com decisoes abertas. |
| Como o dashboard atual e operado? | [../operations/dashboard.md](../operations/dashboard.md) | Manual da superficie existente, nao arquitetura-alvo. |

Planos temporarios, probes de decisao e handoffs de implementacao pertencem a
`private/docs/discussions/`. Uma decisao duravel deve ser promovida ao documento
publico correspondente acima; nao deve permanecer visivel apenas por ordem de
criacao dos planos privados.

## Sequencia de transicao

Esta e uma sequencia arquitetural para quando a aplicacao for desenvolvida,
nao a fila de trabalho do presente. A prioridade temporal fica no
[roadmap](../ROADMAP.md): memoria/configuracao de conta, dimensao analitica de
contas e centralizacao fisica dos binarios preservados sao frentes proximas;
leitor e mudanca do remoto DVC ficam no futuro.

1. Manter captura, preservacao, schema e publicacao independentes da interface.
2. Completar somente os contratos de dados exigidos por experiencias concretas,
   como identidade estavel, contas e assets navegaveis.
3. Construir o primeiro leitor read-only sobre os Parquets unificados.
4. Incorporar operacao, saude e curadoria por fatias verticais reutilizando
   `src/application/` e `src/workflows/`.
5. Substituir gradualmente paginas e relatorios padronizados apenas depois de
   validar equivalencia funcional.
6. Manter Quarto/notebooks como bancada analitica, nao como frontend obrigatorio
   do arquivo.
