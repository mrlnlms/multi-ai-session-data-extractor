# Web collection runbook

Procedimento reutilizavel para atualizar fontes web sem rebaixar o acervo.
Ele complementa [pipeline.md](pipeline.md): os comandos e particularidades de
cada fonte continuam no respectivo `state.md`.

## Antes de executar

1. Leia `AGENTS.md`, o `state.md` da fonte e, quando existir,
   `server-behavior.md`.
2. Inspecione `git status --short` e preserve mudancas alheias.
3. Confira logs de captura/reconciliacao, timestamps de raw/merged/processed e
   a presenca do perfil local. Um perfil existente nao prova que a sessao ainda
   esta autorizada.
4. Nao apague, resete ou force dados a “bater”. Uma ausencia no servidor e
   evidencia a preservar, nao sujeira local.

Se o login expirou, peca ao operador para concluir o login interativo da
plataforma. Nao extraia credenciais do perfil nem tente contornar a sessao.

## Ciclo por fonte

1. Execute o `<source>-sync.py` com a menor abrangencia segura.
2. Verifique discovery e reconciliacao. Se houver discovery parcial, mantenha
   raw/merged existentes e siga o fallback documentado — por exemplo,
   `refetch_known` quando a fonte o oferecer.
3. So depois de reconcile saudavel, execute `<source>-parse.py` para fontes
   web. O parquet resultante deve ser mais novo que os insumos relevantes.
4. Registre comando, flags, contagens `added`/`updated`/`preserved_missing`,
   status e proxima acao segura.

Trabalhe em lotes pequenos. Comece pela fonte explicitamente pedida; na falta
de escopo, prefira fontes de conta unica estaveis antes das multi-conta e das
que exigem janela visivel.

## Mudanca de interface ou API

Uma resposta inesperada e evidencia, nao justificativa para reescrever uma
fonte inteira.

1. Pare apenas a fonte afetada e preserve logs.
2. Identifique a fronteira de discovery, fetch ou parse que falhou.
3. Consulte a documentacao da fonte e observe trafego autenticado quando
   necessario.
4. Aplique a menor mudanca compativel, com teste de regressao.
5. Rode testes focados, repita a fonte em modo seguro e so entao continue.

## Fechamento da rodada

Depois que todas as fontes em escopo tiverem Parquets atuais, execute
`scripts/unify-parquets.py`, valide a atualidade do conjunto unificado e
renderize apenas os perfis Quarto afetados quando isso ajudar na verificacao.

`dvc push` e `dvc gc` nao fazem parte deste runbook: publicacao e retencao sao
operacoes deliberadas descritas em [dvc-runbook.md](dvc-runbook.md).
