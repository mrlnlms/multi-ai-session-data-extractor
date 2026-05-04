# serve-qmds.sh — cheatsheet

Local script to bring up/tear down the HTTP server that serves the data profiles
(`notebooks/_output/<plat>.html`) in the browser.

## Usage

```bash
./scripts/serve-qmds.sh           # bring up + url in the terminal
./scripts/serve-qmds.sh status    # running or stopped?
./scripts/serve-qmds.sh open      # bring up (if needed) + open 15 tabs
./scripts/serve-qmds.sh stop      # kill
./scripts/serve-qmds.sh restart   # stop + start
```

## What it does differently from raw `python -m http.server`

- Runs in the background (close the terminal and it keeps going) — `nohup` + stdout redirect
- Stores PID in `.serve-qmds.pid` (gitignored) — `stop` kills by exact PID, no need for `lsof`
- Detects an occupied port before trying to bring it up (useful message instead of stack trace)
- Idempotent — `start` while already running = shows the URL, no error
- `open` opens 15 tabs in safari/chrome (default browser)
