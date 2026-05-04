# Segurança e uso ético

Este documento descreve como o projeto lida com credenciais, qual é o
escopo de uso pretendido, e considerações sobre termos de uso das
plataformas.

## TL;DR

- Você só captura **suas próprias contas**, com cookies do **seu próprio
  login**. A ferramenta não burla autenticação nem acessa dados de
  terceiros.
- Cookies/profiles ficam em `.storage/` (gitignored — nunca commitado).
- Nenhuma credencial sai da sua máquina (nem para serviços externos).
- Se você compartilhar este projeto com outra pessoa, ela precisa fazer
  o login dela mesma — profiles não são portáveis nem compartilháveis.

## Como o login funciona

Cada plataforma tem um script `scripts/<plat>-login.py`:

1. Abre uma instância isolada do Chromium (via Playwright) apontando
   para a página de login da plataforma.
2. Você loga manualmente — email, senha, eventualmente captcha ou 2FA.
   O script **não recebe nem armazena** suas credenciais.
3. Depois do login completar, o Playwright salva os cookies de sessão
   em `.storage/<plataforma>-profile-<conta>/`. Esse diretório fica no
   filesystem local, dentro do diretório do projeto.
4. Os scripts de captura subsequentes reusam esse profile — abrem o
   navegador com os cookies já carregados, sem precisar logar de novo.

**O que fica em `.storage/`:**

- Cookies HTTP da plataforma
- LocalStorage / IndexedDB do browser
- Cache do navegador (irrelevante)

**O que NÃO fica em `.storage/`:**

- Sua senha (a plataforma só envia/recebe cookies de sessão depois do
  login completar)
- Tokens de API permanentes (use ChatGPT API key separadamente — esta
  ferramenta usa só a API web interna)

## O que `.gitignore` protege

```
.storage/        # cookies/profiles de cada plataforma
data/raw/        # dados crus capturados (suas conversas)
data/merged/     # dados consolidados
data/processed/  # parquets canônicos
data/unified/    # parquets cross-platform
data/external/   # snapshots manuais (exports GDPR, clippings, etc)
.venv/           # ambiente virtual Python
```

**Antes de fazer push:** sempre confirme que está commitando só código,
não dados pessoais. `git status` deve mostrar zero arquivos em `data/`,
`.storage/`, `.venv/`.

## Termos de uso (ToS) das plataformas

Esta ferramenta usa **APIs internas** das plataformas, autenticadas com
cookies do seu próprio login. Isso é a mesma coisa que o navegador faz
quando você usa o app oficial — só que automatizado.

**O que isso significa:**

- Você está acessando dados que já têm permissão de ver (sua própria
  conta).
- Você não está fazendo scraping de dados públicos de terceiros.
- Você não está compartilhando suas credenciais com a ferramenta.
- Você não está burlando rate limits de forma agressiva (a ferramenta
  faz requisições incrementais, com pausas onde apropriado).

**O que NÃO está coberto:**

- Cláusulas específicas de ToS que proíbem **qualquer** automação,
  mesmo de uso pessoal. Algumas plataformas (notavelmente OpenAI nos
  ToS atuais) têm linguagem ampla sobre "scraping" e "automação". Leia
  os ToS de cada plataforma antes de usar e considere se o uso pessoal
  legítimo se enquadra na proibição.
- Esta ferramenta **não foi auditada** por advogado nem revisada por
  nenhuma das plataformas. Ela existe para arquivamento pessoal e
  pesquisa — não use em contexto profissional crítico sem entender as
  implicações de ToS.

**Em resumo:** se você está logado na plataforma e acessando suas
próprias conversas, esta ferramenta apenas automatiza o que você já
faria manualmente. Mas a interpretação legal de "automação" varia por
ToS — leia os termos da sua plataforma.

## Boas práticas

### Antes de subir o repositório

```bash
# Verifique zero arquivos sensíveis
git status

# Confirme que .storage/ e data/ estão gitignored
git check-ignore .storage/ data/

# Confirme zero credenciais em commits passados
git log --all -p | grep -iE "password|cookie|token|api[_-]?key" | head
```

Se aparecer credencial em commit antigo (mesmo que removida depois),
o histórico do Git ainda contém. Recomendado: `git filter-repo` ou
recriar o repositório do zero antes de tornar público.

### Rotação de cookies

Cookies de sessão das plataformas geralmente duram meses, mas podem ser
invalidados:

- Pela plataforma (logout em outro dispositivo, política de segurança)
- Por você (logout explícito, troca de senha)
- Após inatividade prolongada

Se uma captura começar a falhar com 401/403, refaça o login da
plataforma específica:

```bash
rm -rf .storage/<plataforma>-profile-<conta>
python scripts/<plataforma>-login.py
```

### Antes de compartilhar uma máquina ou backup

Os profiles em `.storage/` permitem acesso à sua conta nas plataformas
sem precisar de senha (basta um navegador conseguir ler os cookies).
**Tratar `.storage/` com o mesmo cuidado de qualquer cache de browser
logado.**

Se você for emprestar a máquina, fazer backup público, ou descartar:

```bash
rm -rf .storage/
```

## Reportando vulnerabilidades

Se você encontrar uma vulnerabilidade no código (ex: injection,
exfiltração não-intencional de credenciais, leak de dados), abra uma
issue **privada** ou contate diretamente o mantenedor. Não exponha
publicamente até que o fix esteja em produção.

## Limitações desta política

- Não cobrimos comportamento das próprias plataformas (ex: o que a
  OpenAI faz com seus dados, ou se o ChatGPT pode detectar uso desta
  ferramenta).
- Não somos auditores de segurança. O código é fornecido como-está
  (ver [LICENSE](../LICENSE)).
- Se a sua conta é corporativa/enterprise, verifique a política da sua
  organização sobre arquivamento local de dados.
