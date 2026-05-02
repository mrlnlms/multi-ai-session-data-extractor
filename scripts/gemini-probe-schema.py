"""Probe profundo do schema raw do Gemini batchexecute.

Itera todas as convs em data/merged/Gemini/account-{1,2}/conversations/ e
mapeia:
  - estrutura raw (lengths e types em cada nivel)
  - features detectadas (Deep Research, multi-modal, drafts, citations)
  - distribuicao de campos
  - campos que so aparecem em algumas convs
"""

import json
from collections import Counter, defaultdict
from pathlib import Path


def _walk_path(obj, path: str = "raw"):
    """Yield (path, type_name, length_or_value)."""
    if obj is None:
        yield (path, "None", None)
    elif isinstance(obj, list):
        yield (path, "list", len(obj))
        for i, item in enumerate(obj[:30]):  # limite pra evitar explosao
            yield from _walk_path(item, f"{path}[{i}]")
    elif isinstance(obj, dict):
        yield (path, "dict", len(obj))
        for k, v in list(obj.items())[:30]:
            yield from _walk_path(v, f"{path}.{k}")
    elif isinstance(obj, str):
        yield (path, "str", len(obj))
    elif isinstance(obj, bool):
        yield (path, "bool", obj)
    elif isinstance(obj, int):
        yield (path, "int", obj)
    elif isinstance(obj, float):
        yield (path, "float", obj)
    else:
        yield (path, type(obj).__name__, str(obj)[:40])


def _has_substr(obj, needles: list[str]) -> set[str]:
    """Retorna quais needles aparecem em strings dentro do obj."""
    found = set()
    def walk(x):
        if isinstance(x, str):
            for n in needles:
                if n in x:
                    found.add(n)
        elif isinstance(x, list):
            for item in x:
                walk(item)
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
    walk(obj)
    return found


def main():
    convs_data: list[dict] = []
    for acc in [1, 2]:
        cdir = Path(f"data/merged/Gemini/account-{acc}/conversations")
        if not cdir.exists():
            continue
        for jp in sorted(cdir.glob("*.json")):
            try:
                obj = json.loads(jp.read_text(encoding="utf-8"))
            except Exception:
                continue
            obj["_account"] = acc
            convs_data.append(obj)

    print(f"Total convs: {len(convs_data)}")
    print()

    # ============================================================
    # 1. Estrutura top-level do raw
    # ============================================================
    print("=== TOP-LEVEL SHAPE ===")
    raw_shapes: Counter = Counter()
    for c in convs_data:
        raw = c.get("raw")
        if not raw:
            continue
        shape = f"list[{len(raw)}]={[type(x).__name__ for x in raw]}"
        raw_shapes[shape] += 1
    for shape, count in raw_shapes.most_common(5):
        print(f"  {count:3d}× {shape}")
    print()

    # ============================================================
    # 2. raw[0] (turns wrapper) — qual o length tipico?
    # ============================================================
    print("=== raw[0] turn count distribution ===")
    turn_counts: Counter = Counter()
    for c in convs_data:
        raw = c.get("raw")
        if raw and raw[0]:
            turn_counts[len(raw[0])] += 1
    for tc, count in sorted(turn_counts.items()):
        print(f"  {count:3d} convs com {tc} turns")
    print()

    # ============================================================
    # 3. Estrutura tipica de um turn (raw[0][0])
    # ============================================================
    print("=== TURN structure (raw[0][i]) ===")
    turn_shapes: Counter = Counter()
    for c in convs_data:
        raw = c.get("raw")
        if not (raw and raw[0]):
            continue
        for turn in raw[0]:
            if not isinstance(turn, list):
                continue
            shape = f"len={len(turn)} types={[type(x).__name__ for x in turn]}"
            turn_shapes[shape] += 1
    for shape, count in turn_shapes.most_common(8):
        print(f"  {count:4d}× {shape}")
    print()

    # ============================================================
    # 4. Features detectadas (substring search no JSON)
    # ============================================================
    print("=== FEATURES via substring ===")
    needles = [
        "lh3.googleusercontent.com",     # imagens
        "deep research",                  # DR mode
        "Deep Research",
        "Imagen",                         # image generation
        "googleusercontent",
        "thinking",                       # thinking mode
        "model_response_id",              # alternative response (drafts)
        "draft_message",
        "search_results",
        "grounding",
        "citations",
        "share",
        "lamda",                          # model name
        "gemini-2",
        "MaZiqc",
        "/d/",                            # drive doc
        "youtube",
    ]
    feature_counts: dict[str, int] = defaultdict(int)
    for c in convs_data:
        found = _has_substr(c.get("raw"), needles)
        for n in found:
            feature_counts[n] += 1
    for n in needles:
        print(f"  {feature_counts.get(n, 0):4d}/{len(convs_data)} convs com '{n}'")
    print()

    # ============================================================
    # 5. Inspecao detalhada de UM turn rico (com mais elements)
    # ============================================================
    print("=== SAMPLE TURN (most fields populated) ===")
    sample = None
    sample_score = 0
    for c in convs_data:
        raw = c.get("raw")
        if not (raw and raw[0]):
            continue
        for turn in raw[0]:
            if not isinstance(turn, list):
                continue
            score = sum(1 for x in turn if x is not None)
            if score > sample_score:
                sample = (c["uuid"], c["_account"], turn)
                sample_score = score
    if sample:
        uuid, acc, turn = sample
        print(f'  conv={uuid} account={acc}')
        print(f'  turn len={len(turn)}, populated={sample_score}')
        for i, item in enumerate(turn):
            if item is None:
                print(f'    [{i}]: None')
            elif isinstance(item, list):
                s = json.dumps(item, ensure_ascii=False)[:200]
                print(f'    [{i}]: list({len(item)}) {s}')
            else:
                s = str(item)[:200]
                print(f'    [{i}]: {type(item).__name__} {s}')
    print()

    # ============================================================
    # 6. raw[0][0][3] — response data (25 elementos!) — desconstruir
    # ============================================================
    print("=== RESPONSE STRUCTURE raw[0][i][3] (response data, 25 fields) ===")
    if sample:
        uuid, acc, turn = sample
        if len(turn) > 3 and isinstance(turn[3], list):
            resp = turn[3]
            print(f'  resp len={len(resp)}')
            for i, item in enumerate(resp):
                if item is None:
                    print(f'    resp[{i}]: None')
                elif isinstance(item, list):
                    s = json.dumps(item, ensure_ascii=False)[:200]
                    print(f'    resp[{i}]: list({len(item)}) {s}')
                elif isinstance(item, str):
                    print(f'    resp[{i}]: str {item[:100]!r}')
                else:
                    print(f'    resp[{i}]: {type(item).__name__} {str(item)[:60]}')


if __name__ == "__main__":
    main()
