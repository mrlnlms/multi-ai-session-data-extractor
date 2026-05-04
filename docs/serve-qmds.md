# serve-qmds.sh — cheatsheet

Script local pra subir/derrubar o servidor HTTP que serve os data profiles
(`notebooks/_output/<plat>.html`) no navegador.

## Uso

```bash
./scripts/serve-qmds.sh           # sobe + url no terminal
./scripts/serve-qmds.sh status    # rodando ou parado?
./scripts/serve-qmds.sh open      # sobe (se preciso) + abre 15 abas
./scripts/serve-qmds.sh stop      # mata
./scripts/serve-qmds.sh restart   # stop + start
```

## O que ele faz diferente do `python -m http.server` cru

- Roda em background (fecha terminal e continua) — `nohup` + redirect de stdout
- Guarda PID em `.serve-qmds.pid` (gitignored) — `stop` mata pelo PID exato, sem precisar de `lsof`
- Detecta porta ocupada antes de tentar subir (mensagem útil em vez de erro stack)
- Idempotente — `start` rodando já = mostra URL, não dá erro
- `open` abre as 15 abas do safari/chrome (default browser)
