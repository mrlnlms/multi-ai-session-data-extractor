"""Cruza timestamps do MyActivity.html com conversas do scraper.

Uso: python scripts/gemini-merge-timestamps.py [--account 1]

Le:
  - data/raw/Gemini Data/account-{N}/gemini-full-export.json (scraper)
  - data/raw/Gemini Data/account-{N}/MyActivity.html (Takeout)

Salva:
  - data/raw/Gemini Data/account-{N}/gemini-enriched.json (com timestamps)
  - data/raw/Gemini Data/account-{N}/match-report.txt (relatorio)
"""

import argparse
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup
from dateutil import parser as dateparser


def normalize(text: str) -> str:
    """Normaliza texto pra comparacao: lowercase, sem espacos extras."""
    return re.sub(r"\s+", " ", text.lower().strip())[:80]


def parse_activities(html_path: Path) -> list[dict]:
    """Extrai prompts e timestamps do MyActivity.html."""
    html = html_path.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    cells = soup.select(".outer-cell")

    # Patterns pra timestamps em ingles e portugues
    ts_patterns = [
        # Ingles: Mar 23, 2026, 1:22:13 AM GMT-03:00
        re.compile(
            r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
            r" \d{1,2}, \d{4}, \d{1,2}:\d{2}:\d{2}\s*[AP]M\s*GMT[+-]\d{2}:\d{2})"
        ),
        # Portugues: 26 de mar. de 2026, 13:42:07 BRT
        re.compile(
            r"(\d{1,2} de \w{3,4}\.? de \d{4}, \d{1,2}:\d{2}:\d{2}\s*\w{2,4})"
        ),
    ]

    # Meses em portugues
    pt_months = {
        "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
        "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
    }

    # Timezones brasileiros
    br_tz = {"BRT": "-03:00", "BRST": "-02:00", "AMT": "-04:00"}

    def parse_pt_timestamp(ts_str: str) -> str:
        """Parseia timestamp em portugues pra ISO."""
        # 26 de mar. de 2026, 13:42:07 BRT
        m = re.match(
            r"(\d{1,2}) de (\w{3,4})\.? de (\d{4}), (\d{1,2}:\d{2}:\d{2})\s*(\w{2,4})",
            ts_str,
        )
        if not m:
            return ts_str
        day, month_str, year, time, tz = m.groups()
        month = pt_months.get(month_str[:3].lower(), 1)
        offset = br_tz.get(tz, "-03:00")
        return f"{year}-{month:02d}-{int(day):02d}T{time}{offset}"

    # Pattern pra detectar inicio do prompt
    prompt_prefix = re.compile(r"Prompted\s+", re.IGNORECASE)

    activities = []
    for cell in cells:
        content = cell.select_one(".content-cell.mdl-cell--6-col")
        if not content:
            continue

        raw = content.get_text(separator="\n")

        # Extrair timestamp (tenta todos os patterns)
        timestamp_str = ""
        for pattern in ts_patterns:
            ts_match = pattern.search(raw)
            if ts_match:
                timestamp_str = ts_match.group(1).strip()
                break

        if not timestamp_str:
            continue

        # Extrair prompt (tudo entre "Prompted " e o timestamp)
        prompt = ""
        pm = prompt_prefix.search(raw)
        if pm and ts_match:
            prompt = raw[pm.end():ts_match.start()].strip()

        # Parsear timestamp
        try:
            if any(c in timestamp_str for c in ["AM", "PM", "GMT"]):
                ts = dateparser.parse(timestamp_str)
                iso = ts.isoformat()
            else:
                iso = parse_pt_timestamp(timestamp_str)
        except Exception:
            iso = timestamp_str

        activities.append({
            "prompt": prompt,
            "prompt_norm": normalize(prompt),
            "timestamp_raw": timestamp_str,
            "timestamp_iso": iso,
        })

    return activities


def match_messages(conversations: list[dict], activities: list[dict]) -> tuple:
    """Cruza mensagens do scraper com activities por texto do prompt."""
    matched = 0
    unmatched = 0
    report_lines = []

    # Indice de activities por texto normalizado (primeiros N chars)
    activity_index = {}
    for act in activities:
        for length in [60, 40, 25]:
            key = act["prompt_norm"][:length]
            if key and key not in activity_index:
                activity_index[key] = act

    for conv in conversations:
        conv_matched = 0
        first_ts = None
        last_ts = None

        for msg in conv["messages"]:
            user_norm = normalize(msg["user"])

            # Tenta match por tamanhos decrescentes
            best = None
            for length in [60, 40, 25]:
                key = user_norm[:length]
                if key in activity_index:
                    best = activity_index[key]
                    break

            if best:
                msg["timestamp_raw"] = best["timestamp_raw"]
                msg["timestamp_iso"] = best["timestamp_iso"]
                matched += 1
                conv_matched += 1

                ts = best["timestamp_iso"]
                if first_ts is None or ts < first_ts:
                    first_ts = ts
                if last_ts is None or ts > last_ts:
                    last_ts = ts
            else:
                msg["timestamp_raw"] = None
                msg["timestamp_iso"] = None
                unmatched += 1

        # Metadados da conversa
        conv["matched_timestamps"] = conv_matched
        conv["unmatched_timestamps"] = conv["message_count"] - conv_matched
        conv["first_timestamp"] = first_ts
        conv["last_timestamp"] = last_ts

        status = "FULL" if conv_matched == conv["message_count"] else (
            "PARTIAL" if conv_matched > 0 else "NONE"
        )
        report_lines.append(
            f"  [{status:7s}] {conv_matched:2d}/{conv['message_count']:2d} "
            f"matched — {conv['title'][:60]}"
        )

    return matched, unmatched, report_lines


def interpolate_timestamps(conversations: list[dict]) -> int:
    """Interpola timestamps faltantes baseado nos vizinhos dentro da conversa."""
    interpolated = 0

    for conv in conversations:
        msgs = conv["messages"]
        if len(msgs) < 2:
            continue

        # Passa 1: forward fill (propaga timestamp anterior)
        # Passa 2: backward fill (propaga timestamp seguinte)
        # Passa 3: marca como interpolado

        timestamps = [m.get("timestamp_iso") for m in msgs]

        # Forward fill
        filled = list(timestamps)
        for i in range(1, len(filled)):
            if filled[i] is None and filled[i - 1] is not None:
                filled[i] = filled[i - 1]

        # Backward fill
        for i in range(len(filled) - 2, -1, -1):
            if filled[i] is None and filled[i + 1] is not None:
                filled[i] = filled[i + 1]

        # Aplica
        for i, msg in enumerate(msgs):
            if msg["timestamp_iso"] is None and filled[i] is not None:
                msg["timestamp_iso"] = filled[i]
                msg["timestamp_raw"] = None  # Marca que nao eh original
                msg["timestamp_interpolated"] = True
                interpolated += 1
            else:
                msg["timestamp_interpolated"] = False

        # Atualiza metadados da conversa
        valid_ts = [m["timestamp_iso"] for m in msgs if m["timestamp_iso"]]
        if valid_ts:
            conv["first_timestamp"] = min(valid_ts)
            conv["last_timestamp"] = max(valid_ts)

    return interpolated


def main(account: int):
    base = Path(f"data/raw/Gemini Data/account-{account}")
    export_path = base / "gemini-full-export.json"
    activity_path = base / "MyActivity.html"
    enriched_path = base / "gemini-enriched.json"
    report_path = base / "match-report.txt"

    if not export_path.exists():
        print(f"Export nao encontrado: {export_path}")
        return
    if not activity_path.exists():
        print(f"MyActivity nao encontrado: {activity_path}")
        return

    # Parse
    print("Parsing MyActivity...")
    activities = parse_activities(activity_path)
    print(f"  {len(activities)} activities com timestamp")

    print("Loading scraper export...")
    conversations = json.load(export_path.open())
    total_msgs = sum(c["message_count"] for c in conversations)
    print(f"  {len(conversations)} conversas, {total_msgs} turnos")

    # Match
    print("\nMatching...")
    matched, unmatched, report_lines = match_messages(conversations, activities)

    # Interpolacao
    print("Interpolating missing timestamps...")
    interpolated = interpolate_timestamps(conversations)
    final_with_ts = sum(
        1 for c in conversations for m in c["messages"] if m["timestamp_iso"]
    )
    final_without = total_msgs - final_with_ts

    # Salvar enriched
    enriched_path.write_text(
        json.dumps(conversations, indent=2, ensure_ascii=False)
    )

    # Report
    report = [
        f"=== Gemini Timestamp Match Report (account {account}) ===",
        f"Activities: {len(activities)}",
        f"Conversas: {len(conversations)}",
        f"Turnos: {total_msgs}",
        f"Matched (direto): {matched} ({matched/total_msgs*100:.1f}%)" if total_msgs else "Matched: 0",
        f"Interpolated: {interpolated}",
        f"Total com timestamp: {final_with_ts} ({final_with_ts/total_msgs*100:.1f}%)" if total_msgs else "",
        f"Sem timestamp: {final_without}",
        "",
        "Per conversation:",
        *report_lines,
    ]
    report_text = "\n".join(report)
    report_path.write_text(report_text)

    print(f"\n{report_text}")
    print(f"\nSaved enriched to {enriched_path}")
    print(f"Saved report to {report_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", type=int, default=1, choices=[1, 2])
    args = parser.parse_args()
    main(args.account)
