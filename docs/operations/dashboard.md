# Dashboard operacional

O dashboard Streamlit oferece uma visão local dos dados capturados e uma forma
assistida de executar o pipeline. Ele descobre as 13 fontes a partir de
`data/`; uma plataforma sem captura continua aparecendo, mas sem métricas ou
histórico.

Para instalação, login e perfis de navegador, consulte [SETUP.md](../SETUP.md).
Para rodar scripts manualmente, consulte [pipeline.md](pipeline.md).

## Iniciar

```bash
PYTHONPATH=. .venv/bin/streamlit run dashboard.py
```

Abra o endereço mostrado pelo Streamlit, normalmente
<http://localhost:8501>. O dashboard não é um serviço publicado nem uma fonte
de verdade separada: ele lê o estado local produzido pela captura e pelos
Parquets.

## O que a interface mostra

A visão geral reúne totais capturados, ativos e `preserved_missing`, idade das
capturas, alertas de queda de discovery e uma linha do tempo cumulativa. Cada
plataforma abre uma visão própria com logs de captura/reconciliação, estado do
parquet, métricas e relatórios Quarto disponíveis.

Use **Reload data** após uma rodada manual para invalidar o cache do
Streamlit. Os indicadores descrevem o que existe em disco; eles não substituem
a verificação de que `processed` está mais recente que `raw` e `merged`.

## Executar o pipeline

Na visão geral, **Update all** executa as fontes que possuem sync. Em uma
plataforma, **Run full pipeline** limita a captura àquela fonte. Ambos usam a
mesma sequência:

```text
1. sync + parse
2. unify Parquets
3. render Quarto
4. publish (opcional)
```

Para fontes web, o dashboard executa o parser logo após um sync bem-sucedido.
Isso é diferente de chamar `scripts/<fonte>-sync.py` diretamente no terminal,
caso em que o parse continua sendo um passo explícito. Os syncs das fontes CLI
já incluem copy e parse.

Uma falha nas etapas 2 ou 3 impede a publicação. Na etapa 1, falhas parciais
são registradas, mas a rodada pode continuar quando ao menos uma fonte for
capturada; revise o resultado antes de tratar a rodada como saudável.

### Publish

**Stage 4/4: Publish to DVC + git push** vem marcado por padrão, mas é uma
ação deliberada do operador. Quando marcado, o dashboard atualiza os
ponteiros DVC, cria o commit de dados se necessário, executa `dvc push` e
`git push`. Desmarque-o para capturar, processar e revisar localmente sem
publicar nada.

Publicação muda estado fora do checkout. Não a use para contornar uma
inconsistência de dados; resolva primeiro a causa e siga as regras do
[DVC runbook](dvc-runbook.md).

## Rodar sem interface

O equivalente para terminal é:

```bash
# Exclui por padrão ChatGPT e Perplexity, que exigem browser visível.
PYTHONPATH=. .venv/bin/python scripts/headless-pipeline.py --no-publish

# Para um subconjunto explícito:
PYTHONPATH=. .venv/bin/python scripts/headless-pipeline.py \
  --plats=Claude.ai,Gemini --no-publish
```

Sem `--no-publish`, o comando solicita a mesma publicação deliberada do
pipeline completo. Incluir ChatGPT ou Perplexity em `--plats` pode abrir uma
janela de navegador e requer ambiente gráfico funcional.

## Logs, locks e diagnóstico

- `data/raw/<Fonte>/capture_log.jsonl`: histórico de captura da fonte.
- `data/merged/<Fonte>/reconcile_log.jsonl`: histórico de reconciliação.
- `.runtime/pipeline-runs.jsonl`: resumo de execuções feitas pelo dashboard ou
  pelo modo headless.
- `.runtime/locks/pipeline.lock`: bloqueio que impede duas rodadas completas
  simultâneas.

O lock registra o processo pai e subprocessos. Quando o processo pai já não
existe, a próxima execução tenta recuperar o lock obsoleto; não apague um lock
de uma rodada que ainda esteja em andamento. Para problemas de credenciais,
captura parcial ou assets, use o `state.md` da plataforma listado em
[extractor engineering](../extractor-engineering/README.md).

## Relatórios Quarto

O dashboard oferece os HTMLs Quarto já renderizados e pode renderizar os que
ainda não existirem. O servidor separado de HTML continua opcional e é
controlado pela barra lateral; os mesmos comandos estão em
[pipeline.md](pipeline.md).
