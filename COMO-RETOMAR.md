# Como retomar os projetos

Baixou do Google Drive? Segue o passo a passo pra cada projeto voltar a funcionar.

> **Atualizacao de 2026-08-29:** a recuperacao do extractor foi concluida e a
> arvore reconciliada foi promovida. Consulte `docs/RECOVERY.md` para a trilha
> de auditoria e os caminhos de rollback. Antes de uma nova coleta, confirme o
> remoto com `dvc status -c` e preserve o snapshot. O baseline reconciliado
> foi enviado e verificado em 2026-08-29. O Google Drive continua apenas como
> remoto transitorio ate a migracao planejada para R2.

---

## 1. AI Interaction Analysis

```bash
cd "AI Interaction Analysis"

# Recriar o ambiente virtual
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

**Git remote:** `https://github.com/mrlnlms/ia-interaction-analysis.git`

---

## 2. multi-ai-session-data-extractor

```bash
cd "multi-ai-session-data-extractor"

# Recriar o ambiente virtual
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Git remote:** `https://github.com/mrlnlms/multi-ai-session-data-extractor.git`

---

## Notas

- Os `.venv` foram removidos antes do backup (recria com os comandos acima)
- A reconciliacao do extractor foi concluida em 2026-08-29. Os backups
  temporarios e manifestos locais foram descartados em 2026-08-31, apos uma
  restauracao limpa do cache em `.dvc/cache` e confirmacao de sincronismo com
  o remoto. O resumo da auditoria permanece em `docs/RECOVERY.md` e no Git.
- Se precisar do DVC depois pra versionamento: `pip install 'dvc[gdrive]'`
- Backup feito em **6 de julho de 2026**
