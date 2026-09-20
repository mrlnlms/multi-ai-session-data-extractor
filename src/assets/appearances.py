"""Append-only semantic appearances derived by validated web parsers."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Iterable, Mapping

from src.schema.models import Asset, AssetLink, Message, normalize_data_relative_path

from .contracts import MessagePathEvidence
from .models import AssetScope, CaptureBatch, RecordEnvelope
from .state import canonical_json
from .vault import AssetVault


APPEARANCE_NAMESPACE = uuid.UUID("a0f32d0c-ffcf-5865-a514-8d2119cbbd3a")


def link_appearance_payload(
    link: AssetLink, *, projection_order: int | None = None
) -> dict[str, object]:
    payload: dict[str, object] = {
        "appearance_id": link.asset_link_id,
        "asset_link_id": link.asset_link_id,
        "delivery_id": link.asset_id,
        "object_type": link.object_type,
        "object_id": link.object_id,
        "conversation_id": link.conversation_id,
        "message_id": link.message_id,
        "project_id": link.project_id,
        "role": link.role,
        "ordinal": link.ordinal,
        "content_block_index": link.content_block_index,
        "position_confidence": "exact",
        "projection_kind": "asset_link",
        "metadata_json": link.metadata_json,
    }
    if projection_order is not None:
        payload["projection_order"] = projection_order
    return payload


def message_path_appearance_payload(
    source: str,
    account_id: str | None,
    item: MessagePathEvidence,
) -> dict[str, object]:
    appearance_id = str(
        uuid.uuid5(
            APPEARANCE_NAMESPACE,
            "\x1f".join(
                (
                    source,
                    account_id or "",
                    item.asset_id,
                    item.conversation_id,
                    item.message_id,
                    str(item.ordinal),
                )
            ),
        )
    )
    return {
        "appearance_id": appearance_id,
        "delivery_id": item.asset_id,
        "object_type": "message",
        "object_id": item.message_id,
        "conversation_id": item.conversation_id,
        "message_id": item.message_id,
        "project_id": None,
        "role": "unknown",
        "ordinal": item.ordinal,
        "content_block_index": None,
        "position_confidence": "exact",
        "projection_kind": "message_path",
        "metadata_json": None,
    }


def commit_web_asset_appearances(
    asset_vault: AssetVault,
    *,
    source: str,
    account_id: str | None,
    links: Iterable[AssetLink],
    message_paths: Iterable[MessagePathEvidence],
    evidence_path: Path,
) -> str:
    """Persist parser-derived relationships for already captured deliveries."""
    scope = AssetScope(source, account_id)
    state = asset_vault.load_state(scope)
    delivery_ids = {
        str(record.payload["delivery_id"])
        for record in state.by_type["delivery"]
    }
    link_rows = [link_appearance_payload(link) for link in links]
    path_rows = [
        message_path_appearance_payload(source, account_id, item)
        for item in message_paths
    ]
    rows_by_id: dict[str, dict[str, object]] = {}
    for row in (*link_rows, *path_rows):
        delivery_id = str(row["delivery_id"])
        if delivery_id not in delivery_ids:
            raise ValueError(
                "appearance has no captured delivery in "
                f"{scope.source}/{scope.account_key}: {delivery_id}"
            )
        appearance_id = str(row["appearance_id"])
        previous = rows_by_id.get(appearance_id)
        if previous is not None and previous != row:
            raise ValueError(f"conflicting current appearance: {appearance_id}")
        rows_by_id.setdefault(appearance_id, row)

    ordered = [rows_by_id[key] for key in sorted(rows_by_id)]
    capture_payload: dict[str, object] = {
        "source": source,
        "account_id": account_id,
        "capture_method": "web_parser_semantic_enrichment",
        "complete_discovery": True,
        "evidence_path": str(Path(evidence_path)),
        "appearances_authoritative": True,
        "message_paths_authoritative": True,
    }
    fingerprint = {"capture": capture_payload, "appearances": ordered}
    capture_id = "web-appearances-" + hashlib.sha256(
        canonical_json(fingerprint)
    ).hexdigest()
    if capture_id in state.committed_captures:
        return capture_id
    records = [
        RecordEnvelope("capture", 1, capture_id, True, capture_payload)
    ]
    records.extend(
        RecordEnvelope("appearance", 1, capture_id, True, row)
        for row in ordered
    )
    asset_vault.commit(CaptureBatch(scope, capture_id, tuple(records)))
    return capture_id


def message_path_evidence(
    messages: Iterable[object], assets_by_path: Mapping[str, str]
) -> tuple[MessagePathEvidence, ...]:
    """Resolve ordered legacy message paths to their canonical asset IDs."""
    evidence: list[MessagePathEvidence] = []
    for message in messages:
        paths = getattr(message, "asset_paths", None) or []
        for ordinal, path in enumerate(paths):
            asset_id = assets_by_path.get(str(path))
            if asset_id is None:
                raise ValueError(f"message asset path has no parsed asset: {path}")
            evidence.append(
                MessagePathEvidence(
                    asset_id=asset_id,
                    conversation_id=str(getattr(message, "conversation_id")),
                    message_id=str(getattr(message, "message_id")),
                    ordinal=ordinal,
                )
            )
    return tuple(evidence)


def commit_web_parser_appearances(
    asset_vault: AssetVault,
    *,
    source: str,
    assets: Iterable[Asset],
    links: Iterable[AssetLink],
    messages: Iterable[Message],
    evidence_path: Path,
) -> tuple[str, ...]:
    """Commit complete parser-derived semantic snapshots per account scope."""
    assets_by_account: dict[str | None, list[Asset]] = {}
    for asset in assets:
        if asset.source != source:
            raise ValueError(f"asset is outside parser source: {asset.asset_id}")
        assets_by_account.setdefault(asset.account_id, []).append(asset)
    links_by_account: dict[str | None, list[AssetLink]] = {}
    for link in links:
        if link.source != source:
            raise ValueError(f"link is outside parser source: {link.asset_link_id}")
        links_by_account.setdefault(link.account_id, []).append(link)
    messages_by_account: dict[str | None, list[Message]] = {}
    for message in messages:
        if message.source != source:
            raise ValueError(f"message is outside parser source: {message.message_id}")
        messages_by_account.setdefault(message.account_id, []).append(message)

    capture_ids: list[str] = []
    for account_id, account_assets in assets_by_account.items():
        assets_by_path: dict[str, str] = {}
        for asset in account_assets:
            if asset.asset_path is None:
                continue
            path = normalize_data_relative_path(asset.asset_path)
            previous = assets_by_path.get(path)
            if previous is not None and previous != asset.asset_id:
                raise ValueError(f"multiple assets share parsed path: {path}")
            assets_by_path[path] = asset.asset_id
        account_messages = messages_by_account.get(account_id, [])
        for message in account_messages:
            if message.asset_paths:
                message.asset_paths = [
                    normalize_data_relative_path(path) for path in message.asset_paths
                ]
        capture_ids.append(commit_web_asset_appearances(
            asset_vault,
            source=source,
            account_id=account_id,
            links=tuple(links_by_account.get(account_id, ())),
            message_paths=message_path_evidence(account_messages, assets_by_path),
            evidence_path=evidence_path,
        ))

    unexpected_link_accounts = set(links_by_account) - set(assets_by_account)
    if unexpected_link_accounts:
        raise ValueError(
            "appearance accounts have no parsed assets: "
            f"{sorted(unexpected_link_accounts, key=str)}"
        )
    return tuple(capture_ids)
