# Investigação: espaço e compartilhamento de profiles Chrome

Esta é uma hipótese para investigar; não altera o contrato atual de contas,
bindings ou autenticação.

## Contexto

Uma investigação de uso de disco observou que alguns profiles locais do Chrome
usados pelo projeto pareciam ocupar cerca de 1 GB ou mais, enquanto outro
profile tinha poucos MB. A observação não foi uma medição sistemática e não
identifica a causa do crescimento.

O modelo atual mantém profiles separados por plataforma e conta. Surgiu a
hipótese de que contas em plataformas diferentes, autenticadas com a mesma
identidade Google, talvez pudessem compartilhar um profile local e evitar
duplicação. Isso ainda não foi verificado e pode envolver limites de sessão,
isolamento e concorrência.

## Evidência necessária

- Medir o tamanho dos profiles existentes sem inspecionar conteúdo pessoal.
- Distinguir dados temporários do browser de armazenamento associado a login
  ou sincronização.
- Verificar se reutilizar um profile entre plataformas é suportado e mantém
  sessões corretas; não inferir isso apenas porque o provedor de login é o
  mesmo.
- Entender se a motivação principal é reduzir espaço em disco, repetir menos
  logins ou ambos.

## Limites atuais

- Login no site da plataforma e Google/Chrome Sync são coisas distintas.
  Chrome Sync continua opcional e não é requisito nem evidência de autenticação
  upstream.
- O binding local continua associando UUID de conta a uma chave de profile
  local. O caminho físico também inclui o prefixo da plataforma, então repetir
  a mesma chave não compartilha o mesmo diretório.
- Dados `raw` e `merged` continuam isolados por conta. Qualquer mudança futura
  precisa preservar essa separação e manter profiles, bindings e auth health
  em `.storage/`.
- Não copiar, mover ou apagar profiles autenticados como parte desta hipótese.

## Referências

- O contrato atual de contas e bindings está em
  [account-architecture.md](account-architecture.md).
- As instruções de login estão em [SETUP.md](../SETUP.md).
- A hipótese no roadmap está em
  [ROADMAP.md](../ROADMAP.md#chrome-profile-storage-and-reuse).
