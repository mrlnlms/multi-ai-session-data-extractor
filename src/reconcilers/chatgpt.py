"""Reconciler do ChatGPT — junta raws de diferentes datas preservando historico."""

import json
import logging
from datetime import datetime
from pathlib import Path

from src.reconcilers.models import Plan, ReconcileReport

logger = logging.getLogger(__name__)


# Campos _* operacionais (mudam a cada captura mesmo sem mudar a conv).
# Excluidos da comparacao de enrichment no build_plan pra nao forcar to_use desnecessario.
# Adicionar futuros _capture_timing, _retry_count, etc aqui se surgirem.
OPERATIONAL_ENRICHMENT = {"_last_seen_in_server"}


def build_plan(current_raw: dict, previous_merged: dict | None) -> Plan:
    """Decide o que fazer com cada conv_id.

    Args:
        current_raw: dict com {"conversations": {id: raw_dict}} da captura atual.
        previous_merged: dict com {"conversations": {id: raw_dict}} do merged anterior, ou None.

    Returns:
        Plan com listas de IDs por bucket.
    """
    current_convs = current_raw.get("conversations") or {}
    previous_convs = (previous_merged or {}).get("conversations") or {}

    current_ids = set(current_convs.keys())
    previous_ids = set(previous_convs.keys())

    to_use = []
    to_copy = []

    for cid in current_ids:
        if cid not in previous_ids:
            to_use.append(cid)  # novo
            continue
        curr = current_convs[cid]
        prev = previous_convs[cid]
        curr_ut = curr.get("update_time", 0.0)
        prev_ut = prev.get("update_time", 0.0)
        # Enrichment semantico (_project_name, _project_id, _archived, ...) e injetado
        # pelo orchestrator sem alterar update_time do servidor. Comparar campos _*
        # (excluindo operacionais) garante idempotencia do reconcile e propagacao
        # de enrichment novo em reruns.
        curr_enrich = {k: v for k, v in curr.items()
                       if k.startswith("_") and k not in OPERATIONAL_ENRICHMENT}
        prev_enrich = {k: v for k, v in prev.items()
                       if k.startswith("_") and k not in OPERATIONAL_ENRICHMENT}
        if curr_ut > prev_ut or curr_enrich != prev_enrich:
            to_use.append(cid)  # updated (ou enrichment semantico mudou)
        else:
            to_copy.append(cid)  # unchanged

    missing = sorted(previous_ids - current_ids)
    to_copy.extend(missing)  # missing sao copiados tambem (preservacao)

    return Plan(
        to_use_from_current=sorted(to_use),
        to_copy_from_previous=sorted(to_copy),
        missing_from_server=missing,
    )


DROP_THRESHOLD = 0.5  # current/previous <= 0.5 aborta (queda >= 50%)


def run_reconciliation(
    raw_dir: Path,
    merged_output_base: Path,
    previous_merged: Path | None = None,
) -> ReconcileReport:
    """Executa reconciliacao: le raw + previous merged → produz novo merged.

    Args:
        raw_dir: dir do raw recem capturado (contem chatgpt_raw.json).
        merged_output_base: base tipo data/merged/ChatGPT/. Output vai em subdir datado.
        previous_merged: override de auto-detect. Se None, pega o mais recente em merged_output_base/.

    Returns:
        ReconcileReport.
    """
    raw_path = raw_dir / "chatgpt_raw.json"
    current_raw = json.loads(raw_path.read_text(encoding="utf-8"))

    if previous_merged is None:
        previous_merged = _find_latest_merged(merged_output_base)

    previous_data = None
    if previous_merged and previous_merged.exists():
        previous_data = json.loads(previous_merged.read_text(encoding="utf-8"))

    plan = build_plan(current_raw, previous_data)

    # Validacao de integridade: queda drastica aborta.
    # Compara (current + newly_missing) vs previous para nao penalizar preservacao de deletadas.
    current_count = len(current_raw.get("conversations", {}))
    previous_count = len((previous_data or {}).get("conversations", {}))
    if previous_count > 0:
        if current_count / previous_count < DROP_THRESHOLD:
            return ReconcileReport(
                aborted=True,
                abort_reason=(
                    f"Queda drastica na captura: previous={previous_count}, current={current_count}. "
                    f"Threshold: {DROP_THRESHOLD*100}%. Investigue antes de sobrescrever."
                ),
            )

    # Aplicar plan
    today = datetime.now().strftime("%Y-%m-%d")
    merged_convs = {}

    current_convs = current_raw.get("conversations", {})
    previous_convs = (previous_data or {}).get("conversations", {})

    for cid in plan.to_use_from_current:
        conv = dict(current_convs[cid])
        conv["_last_seen_in_server"] = today
        merged_convs[cid] = conv

    for cid in plan.to_copy_from_previous:
        if cid in plan.missing_from_server:
            # preserva do previous sem atualizar _last_seen_in_server
            merged_convs[cid] = previous_convs[cid]
        else:
            # unchanged e presente no servidor — usa previous mas atualiza _last_seen
            conv = dict(previous_convs[cid])
            conv["_last_seen_in_server"] = today
            merged_convs[cid] = conv

    # Contagens pro report
    new_ids = set(plan.to_use_from_current) - set(previous_convs.keys())
    updated_ids = set(plan.to_use_from_current) - new_ids

    report = ReconcileReport(
        added=len(new_ids),
        updated=len(updated_ids),
        copied=len(plan.to_copy_from_previous) - len(plan.missing_from_server),
        preserved_missing=len(plan.missing_from_server),
    )

    # Salvar merged
    output_dir = merged_output_base / today
    output_dir.mkdir(parents=True, exist_ok=True)
    merged_path = output_dir / "chatgpt_merged.json"
    merged_path.write_text(
        json.dumps(
            {
                "reconciled_at": datetime.now().isoformat(),
                "conversations": merged_convs,
            },
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )

    # Log
    log_path = output_dir / "reconcile_log.json"
    log_path.write_text(
        json.dumps(
            {
                "added": report.added,
                "updated": report.updated,
                "copied": report.copied,
                "preserved_missing": report.preserved_missing,
                "warnings": report.validation_warnings,
            },
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )

    return report


def _find_latest_merged(merged_base: Path) -> Path | None:
    """Pega o chatgpt_merged.json mais recente em merged_base/<YYYY-MM-DD>/."""
    if not merged_base.exists():
        return None
    candidates = sorted(merged_base.glob("*/chatgpt_merged.json"))
    return candidates[-1] if candidates else None
