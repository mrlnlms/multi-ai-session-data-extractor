"""Script one-shot: extrai convs reais do merged e sanitiza pra virar fixtures
do parser v3. Roda 1x, gera os arquivos em tests/extractors/chatgpt/fixtures/.

Uso:
    PYTHONPATH=. .venv/bin/python scripts/extract_fixtures_v3.py

NAO comitar como ferramenta permanente — eh artefato unico desta etapa de
coleta empirica. Os fixtures gerados (sanitizados, sem PII) viram parte do
suite de testes; este script aqui pode ser deletado depois.
"""

import copy
import json
from pathlib import Path
from typing import Any

MERGED_PATH = Path("data/merged/ChatGPT/chatgpt_merged.json")
FIXTURES_DIR = Path("tests/extractors/chatgpt/fixtures")

# Campos que sao redactados (substituidos por placeholder mantendo shape)
PII_TEXT_KEYS = {
    "text",  # generic — em parts[], tether_quote, etc
    "snippet",  # search_result entries
    "summary",  # thoughts
    "content",  # reasoning_recap
    "name",  # author.name, attachment.name
}


def redact_string(value: Any) -> str:
    """Redact mantendo placeholder simples. Length nao eh preservada
    intencionalmente — evitar vazar info por estimativa."""
    if not isinstance(value, str):
        return value
    if not value.strip():
        return value  # vazia/whitespace nao tem PII
    return "[REDACTED]"


def sanitize_recursive(obj: Any, path: str = "", parent_role: str | None = None) -> Any:
    """Walk recursivo. Redacta valores em chaves PII_TEXT_KEYS e em
    estruturas conhecidas (parts[], tether_quote, etc). Mantem todas as
    keys e shape; so substitui o VALOR.

    parent_role rastreia se estamos dentro de um author (precisa saber se
    eh role=tool antes de decidir se redacta name).
    """
    if isinstance(obj, dict):
        out = {}
        # Detectar se este dict eh um author bloco — se sim, capturar role
        current_role = obj.get("role") if "role" in obj else None
        for k, v in obj.items():
            new_path = f"{path}.{k}" if path else k
            # Redacao especifica por chave
            if k == "title":
                # title pode ser:
                # - conv.title (PII): redactar
                # - tether_quote.serialization_title etc (system labels): preservar
                # Heuristica: se path contem "metadata" ou "generation",
                # eh system label.
                if "metadata" in path or "generation" in path or "dalle" in path:
                    out[k] = v
                else:
                    out[k] = redact_string(v) if isinstance(v, str) else v
            elif k == "name" and current_role is not None:
                # author.name: preservar se role=tool (eh tool name, nao PII).
                # Redactar se role=user/assistant (pode ser nome real).
                if current_role == "tool":
                    out[k] = v  # preservar tool name
                else:
                    out[k] = redact_string(v) if isinstance(v, str) else v
            elif k == "parts":
                # parts[] pode ser lista de strings ou de dicts
                if isinstance(v, list):
                    out[k] = [
                        redact_string(p) if isinstance(p, str)
                        else sanitize_recursive(p, f"{new_path}[]", current_role)
                        for p in v
                    ]
                else:
                    out[k] = v
            elif k == "url" and isinstance(v, str):
                # URLs podem ter info pessoal (file_id, share id). Redactar
                # mantendo prefix pra debug.
                if v.startswith("file-"):
                    out[k] = "file-[REDACTED]"
                elif v.startswith("https://"):
                    out[k] = "https://[REDACTED]"
                elif v.startswith("sediment://"):
                    out[k] = v  # asset pointer, preservar pra parser test
                else:
                    out[k] = v
            elif k == "domain" and isinstance(v, str):
                # tether_quote.domain — pode ser nome de arquivo do user
                out[k] = redact_string(v)
            elif k in PII_TEXT_KEYS and isinstance(v, str):
                out[k] = redact_string(v)
            elif k == "tether_quote" and isinstance(v, dict):
                # estrutura conhecida: text + maybe message_id, offsets
                out[k] = {
                    sk: redact_string(sv) if sk == "text" and isinstance(sv, str) else sv
                    for sk, sv in v.items()
                }
            elif k == "search_result_groups" and isinstance(v, list):
                # cada group tem entries[] com snippet
                out[k] = [sanitize_recursive(g, f"{new_path}[]", current_role) for g in v]
            elif k == "user_context_message_data" and isinstance(v, dict):
                # custom instructions — redactar tudo no value
                out[k] = {sk: redact_string(sv) if isinstance(sv, str) else sv
                         for sk, sv in v.items()}
            elif k == "attachments" and isinstance(v, list):
                # cada attachment tem name potencialmente sensitivo
                out[k] = [sanitize_recursive(a, f"{new_path}[]", current_role) for a in v]
            else:
                out[k] = sanitize_recursive(v, new_path, current_role)
        return out
    elif isinstance(obj, list):
        return [sanitize_recursive(item, f"{path}[{i}]", parent_role) for i, item in enumerate(obj)]
    else:
        return obj


def extract_conv(merged: dict, conv_id: str) -> dict:
    """Extrai conv inteira do merged + sanitiza."""
    conv = merged["conversations"].get(conv_id)
    if not conv:
        raise ValueError(f"conv_id {conv_id} nao encontrado no merged")
    sanitized = sanitize_recursive(copy.deepcopy(conv))
    return {"conversation_id": conv_id, "conversation": sanitized}


# Mapeamento feature -> conv_id (escolhidas empiricamente)
CANDIDATES = {
    "raw_with_branches.json":         "670efa03-508c-8323-a4dd-bd0eaca99cf0",
    "raw_with_voice.json":            "69499a7b-5ac4-8330-9e0d-2f1ec4d2c1aa",  # placeholder, fix abaixo
    "raw_with_dalle.json":            "68258145-4d40-800c-9bae-fba7377d8ac4",  # placeholder
    "raw_with_canvas.json":           "67ed845a-b978-800c-907d-9c93f4030ad7",  # placeholder
    "raw_with_deep_research.json":    "698c0802-35d8-8330-9d3a-0c1aa1a85a9c",  # placeholder
    "raw_with_tether_quote.json":     "67dada8d-bf44-800c-bcfd-d3a8e25e0c4f",  # placeholder
    "raw_with_custom_gpt.json":       "691ea2cb-0a78-8328-9ef9-c4f2cad7bb87",  # placeholder
    "raw_with_tools.json":            "66eaed5e-5110-800c-ba8f-13e51e3a5ec7",  # placeholder
}


def find_full_id(merged: dict, prefix: str) -> str:
    """Recebe um prefix curto (13 chars) e acha o full ID."""
    for cid in merged["conversations"]:
        if cid.startswith(prefix):
            return cid
    raise ValueError(f"Nenhum conv_id comeca com {prefix}")


def main():
    print("=== Carregando merged ===")
    with open(MERGED_PATH, encoding="utf-8") as f:
        merged = json.load(f)
    print(f"OK: {len(merged['conversations'])} convs no merged\n")

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    # Resolver IDs completos (a partir dos prefixos vistos no candidato discovery)
    prefixes = {
        "raw_with_branches.json": "670efa03",
        "raw_with_voice.json": "69499a7b",
        "raw_with_dalle.json": "68258145",
        "raw_with_canvas.json": "67ed845a",
        "raw_with_deep_research.json": "698c0802",
        "raw_with_tether_quote.json": "67dada8d",
        "raw_with_custom_gpt.json": "691ea2cb",
        "raw_with_tools.json": "66eaed5e",
    }

    for fname, prefix in prefixes.items():
        try:
            cid = find_full_id(merged, prefix)
            fixture = extract_conv(merged, cid)
            out_path = FIXTURES_DIR / fname
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(fixture, f, ensure_ascii=False, indent=2)
            n_nodes = len((fixture["conversation"].get("mapping") or {}))
            print(f"OK: {fname}  conv_id={cid[:13]}  ({n_nodes} nodes)")
        except Exception as e:
            print(f"FAIL: {fname}  prefix={prefix}  err={e}")


if __name__ == "__main__":
    main()
