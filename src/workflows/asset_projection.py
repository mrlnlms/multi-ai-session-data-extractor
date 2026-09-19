"""Read-only backfill from validated legacy projections into a temporary vault."""

from __future__ import annotations

import importlib
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from types import MappingProxyType
from typing import Iterable

import pandas as pd

from src.assets.contracts import (
    AssetEvidenceAdapter,
    AssetEvidenceContext,
    MessagePathEvidence,
    ProjectionReport,
    SourceInputs,
)
from src.assets.models import AssetScope
from src.assets.projection import project_assets
from src.assets.vault import AssetVault
from src.schema.models import (
    Asset,
    AssetLink,
    asset_links_to_df,
    assets_to_df,
    normalize_data_relative_path,
)


_SOURCE_MODULES = {
    "chatgpt": "chatgpt",
    "claude_ai": "claude_ai",
    "gemini": "gemini",
    "notebooklm": "notebooklm",
    "qwen": "qwen",
    "deepseek": "deepseek",
    "perplexity": "perplexity",
    "grok": "grok",
    "kimi": "kimi",
    "claude_code": "claude_code",
    "codex": "codex",
    "gemini_cli": "gemini_cli",
    "antigravity_cli": "antigravity_cli",
}

_SOURCE_FILES = {
    "chatgpt": ("ChatGPT", "chatgpt"),
    "claude_ai": ("Claude.ai", "claude_ai"),
    "gemini": ("Gemini", "gemini"),
    "notebooklm": ("NotebookLM", "notebooklm"),
    "qwen": ("Qwen", "qwen"),
    "deepseek": ("DeepSeek", "deepseek"),
    "perplexity": ("Perplexity", "perplexity"),
    "grok": ("Grok", "grok"),
    "kimi": ("Kimi", "kimi"),
    "claude_code": ("Claude Code", "claude_code"),
    "codex": ("Codex", "codex"),
    "gemini_cli": ("Gemini CLI", "gemini_cli"),
    "antigravity_cli": ("Antigravity CLI", "antigravity_cli"),
}

_EXTERNAL_EVIDENCE = {
    "chatgpt": ("chatgpt-extension-snapshot", "openai-gdpr-export", "manual-saves"),
    "claude_ai": ("claude-ai-snapshots", "manual-saves"),
    "gemini": ("manual-saves",),
    "notebooklm": ("notebooklm-snapshots",),
    "qwen": ("manual-saves",),
    "deepseek": ("deepseek-snapshots",),
    "perplexity": ("perplexity-orphan-threads",),
    "grok": ("grok-snapshots",),
    "claude_code": ("manual-saves",),
}


def source_inputs_from_data(
    data_root: Path, source: str, *, max_batch_bytes: int = 128 * 1024 * 1024
) -> SourceInputs:
    """Resolve the current read-only projection and preserved evidence for a source."""
    data_root = Path(data_root)
    try:
        folder, prefix = _SOURCE_FILES[source]
    except KeyError as exc:
        raise ValueError(f"unsupported asset source: {source!r}") from exc
    processed = data_root / "processed" / folder
    evidence = [
        path
        for path in (data_root / "raw" / folder, data_root / "merged" / folder)
        if path.exists()
    ]
    evidence.extend(
        path
        for name in _EXTERNAL_EVIDENCE.get(source, ())
        if (path := data_root / "external" / name).exists()
    )
    return SourceInputs(
        data_root=data_root,
        assets_path=processed / f"{prefix}_assets.parquet",
        asset_links_path=processed / f"{prefix}_asset_links.parquet",
        messages_path=processed / f"{prefix}_messages.parquet",
        evidence_paths=tuple(evidence),
        max_batch_bytes=max_batch_bytes,
    )


def load_asset_adapter(source: str) -> AssetEvidenceAdapter:
    try:
        module_name = _SOURCE_MODULES[source]
    except KeyError as exc:
        raise ValueError(f"unsupported asset source: {source!r}") from exc
    module = importlib.import_module(f"src.platforms.{module_name}.assets")
    adapter = module.ADAPTER
    if adapter.source != source:
        raise ValueError(f"asset adapter source mismatch: {source!r}")
    return adapter


def _optional(value: object) -> object | None:
    if value is None:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _optional_string(value: object) -> str | None:
    value = _optional(value)
    return None if value is None else str(value)


def _optional_int(value: object) -> int | None:
    value = _optional(value)
    return None if value is None else int(value)


def _optional_bool(value: object) -> bool | None:
    value = _optional(value)
    return None if value is None else bool(value)


def _load_assets(path: Path, source: str) -> tuple[Asset, ...]:
    frame = pd.read_parquet(path)
    result: list[Asset] = []
    for row in frame.to_dict("records"):
        item = Asset(
            asset_id=str(row["asset_id"]),
            source=str(row["source"]),
            account_id=_optional_string(row.get("account_id")),
            asset_kind=str(row["asset_kind"]),
            asset_origin=str(row["asset_origin"]),
            file_name=_optional_string(row.get("file_name")),
            mime_type=_optional_string(row.get("mime_type")),
            size_bytes=_optional_int(row.get("size_bytes")),
            asset_path=_optional_string(row.get("asset_path")),
            is_model_generated=_optional_bool(row.get("is_model_generated")),
            is_preserved_missing=_optional_bool(row.get("is_preserved_missing")),
            is_binary_available=bool(row["is_binary_available"]),
            created_at=_optional(row.get("created_at")),
            metadata_json=_optional_string(row.get("metadata_json")),
        )
        if item.source != source:
            raise ValueError(f"asset parquet contains another source: {item.source!r}")
        result.append(item)
    return tuple(result)


def _load_links(path: Path, source: str) -> tuple[AssetLink, ...]:
    frame = pd.read_parquet(path)
    result: list[AssetLink] = []
    for row in frame.to_dict("records"):
        item = AssetLink(
            asset_link_id=str(row["asset_link_id"]),
            source=str(row["source"]),
            account_id=_optional_string(row.get("account_id")),
            asset_id=str(row["asset_id"]),
            object_type=str(row["object_type"]),
            object_id=str(row["object_id"]),
            conversation_id=_optional_string(row.get("conversation_id")),
            message_id=_optional_string(row.get("message_id")),
            project_id=_optional_string(row.get("project_id")),
            role=str(row["role"]),
            ordinal=_optional_int(row.get("ordinal")),
            content_block_index=_optional_int(row.get("content_block_index")),
            metadata_json=_optional_string(row.get("metadata_json")),
        )
        if item.source != source:
            raise ValueError(f"asset link parquet contains another source: {item.source!r}")
        result.append(item)
    return tuple(result)


def _message_path_evidence(
    path: Path,
    source: str,
    assets: tuple[Asset, ...],
    data_root: Path,
) -> tuple[MessagePathEvidence, ...]:
    frame = pd.read_parquet(path)
    by_path: dict[tuple[str | None, str], str] = {}
    fallback: dict[str, list[tuple[str | None, str]]] = defaultdict(list)
    for asset in assets:
        if asset.asset_path is None:
            continue
        relative = normalize_data_relative_path(asset.asset_path)
        key = (asset.account_id, relative)
        if key in by_path:
            raise ValueError(f"ambiguous asset path in one account: {relative}")
        by_path[key] = asset.asset_id
        fallback[relative].append((asset.account_id, asset.asset_id))

    digest_lookup: dict[tuple[str | None, str], list[str]] | None = None

    def digest(path_value: Path) -> str:
        checksum = hashlib.sha256()
        with path_value.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                checksum.update(block)
        return checksum.hexdigest()

    def find_by_digest(account_id: str | None, relative: str) -> str | None:
        nonlocal digest_lookup
        if digest_lookup is None:
            digest_lookup = defaultdict(list)
            for asset in assets:
                if not asset.is_binary_available or asset.asset_path is None:
                    continue
                asset_relative = normalize_data_relative_path(asset.asset_path)
                asset_digest = digest(data_root / asset_relative)
                digest_lookup[(asset.account_id, asset_digest)].append(asset.asset_id)
        target = data_root / relative
        if not target.is_file():
            raise ValueError(f"message asset path is missing: {relative}")
        target_digest = digest(target)
        candidates = digest_lookup.get((account_id, target_digest), [])
        if not candidates:
            candidates = [
                asset_id
                for (candidate_account, candidate_digest), asset_ids in digest_lookup.items()
                if candidate_digest == target_digest
                for asset_id in asset_ids
            ]
        return candidates[0] if len(candidates) == 1 else None

    result: list[MessagePathEvidence] = []
    for row in frame.to_dict("records"):
        if str(row["source"]) != source:
            raise ValueError(f"message parquet contains another source: {row['source']!r}")
        values = _optional(row.get("asset_paths"))
        if values is None:
            continue
        account_id = _optional_string(row.get("account_id"))
        for ordinal, value in enumerate(values):
            relative = normalize_data_relative_path(str(value))
            asset_id = by_path.get((account_id, relative))
            if asset_id is None:
                candidates = fallback.get(relative, [])
                if len(candidates) == 1:
                    _, asset_id = candidates[0]
                else:
                    asset_id = find_by_digest(account_id, relative)
                if asset_id is None:
                    raise ValueError(f"message path has no unique asset: {relative}")
            result.append(
                MessagePathEvidence(
                    asset_id=asset_id,
                    conversation_id=str(row["conversation_id"]),
                    message_id=str(row["message_id"]),
                    ordinal=ordinal,
                )
            )
    return tuple(result)


def _chunks(assets: tuple[Asset, ...], max_bytes: int) -> Iterable[tuple[Asset, ...]]:
    current: list[Asset] = []
    size = 0
    for asset in assets:
        asset_size = asset.size_bytes or 0
        if current and size + asset_size > max_bytes:
            yield tuple(current)
            current = []
            size = 0
        current.append(asset)
        size += asset_size
    if current:
        yield tuple(current)


def _write_projection(report: ProjectionReport, output_root: Path) -> None:
    destination = output_root / "asset-projections" / report.source
    destination.mkdir(parents=True, exist_ok=True)
    assets_to_df(list(report.assets)).to_parquet(destination / "assets.parquet", index=False)
    asset_links_to_df(list(report.links)).to_parquet(
        destination / "asset_links.parquet", index=False
    )
    (destination / "message_paths.json").write_text(
        json.dumps(dict(report.message_paths), ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = {
        "source": report.source,
        "scope_count": report.scope_count,
        "commit_count": report.commit_count,
        "asset_count": report.asset_count,
        "link_count": report.link_count,
        "available_count": report.available_count,
        "message_path_count": report.message_path_count,
        "evidence_paths": report.evidence_paths,
    }
    (destination / "report.json").write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def project_source_assets(
    source: str,
    inputs: SourceInputs,
    vault_root: Path,
    output_root: Path,
) -> ProjectionReport:
    """Backfill one source without mutating its evidence, then project it."""
    if not isinstance(inputs, SourceInputs):
        raise TypeError("inputs must be SourceInputs")
    vault_root = Path(vault_root)
    output_root = Path(output_root)
    if vault_root.absolute() != (output_root / "assets").absolute():
        raise ValueError("vault_root must be output_root/assets for compatible paths")
    for path in (
        inputs.data_root,
        inputs.assets_path,
        inputs.asset_links_path,
        inputs.messages_path,
        *inputs.evidence_paths,
    ):
        if not path.exists():
            raise FileNotFoundError(path)

    adapter = load_asset_adapter(source)
    assets = _load_assets(inputs.assets_path, source)
    links = _load_links(inputs.asset_links_path, source)
    message_paths = _message_path_evidence(
        inputs.messages_path, source, assets, inputs.data_root
    )
    asset_keys = {(asset.account_id, asset.asset_id) for asset in assets}
    link_order = {link.asset_link_id: index for index, link in enumerate(links)}
    for link in links:
        if (link.account_id, link.asset_id) not in asset_keys:
            raise ValueError(f"link has no source asset: {link.asset_id}")

    accounts: list[str | None] = []
    for asset in assets:
        if asset.account_id not in accounts:
            accounts.append(asset.account_id)
    if not accounts:
        accounts.append(None)

    vault = AssetVault(vault_root, runtime_root=output_root / ".runtime" / "asset-vault")
    scopes: list[AssetScope] = []
    for account_id in accounts:
        scoped_assets = tuple(asset for asset in assets if asset.account_id == account_id)
        batches = tuple(_chunks(scoped_assets, inputs.max_batch_bytes)) or ((),)
        for chunk in batches:
            chunk_ids = {asset.asset_id for asset in chunk}
            context = AssetEvidenceContext(
                source=source,
                account_id=account_id,
                assets=chunk,
                links=tuple(
                    link
                    for link in links
                    if link.account_id == account_id and link.asset_id in chunk_ids
                ),
                link_order=link_order,
                message_paths=tuple(
                    item for item in message_paths if item.asset_id in chunk_ids
                ),
                data_root=inputs.data_root,
                evidence_paths=inputs.evidence_paths,
            )
            state = vault.commit(adapter.collect(context))
            if state.scope not in scopes:
                scopes.append(state.scope)

    projected_assets: list[Asset] = []
    projected_links: list[AssetLink] = []
    projected_paths: dict[str, list[str]] = {}
    commit_count = 0
    for scope in scopes:
        state = vault.load_state(scope)
        commit_count += len(state.committed_captures)
        projection = project_assets(state, output_root)
        projected_assets.extend(projection.assets)
        projected_links.extend(projection.links)
        for message_id, paths in projection.message_paths.items():
            destination = projected_paths.setdefault(message_id, [])
            for path in paths:
                if path not in destination:
                    destination.append(path)

    projected_asset_by_key = {
        (asset.account_id, asset.asset_id): asset for asset in projected_assets
    }
    projected_link_by_id = {link.asset_link_id: link for link in projected_links}
    try:
        projected_assets = [
            projected_asset_by_key[(asset.account_id, asset.asset_id)] for asset in assets
        ]
        projected_links = [
            projected_link_by_id[link.asset_link_id] for link in links
        ]
    except KeyError as exc:
        raise ValueError(f"projection lost a public identity: {exc.args[0]!r}") from exc

    report = ProjectionReport(
        source=source,
        scope_count=len(scopes),
        commit_count=commit_count,
        asset_count=len(projected_assets),
        link_count=len(projected_links),
        available_count=sum(asset.is_binary_available for asset in projected_assets),
        # The published messages table may repeat one message_id on multiple
        # branch rows. Count the ordered source occurrences, while the mapping
        # remains keyed by message_id for reinjection into every matching row.
        message_path_count=len(message_paths),
        evidence_paths=tuple(str(path) for path in inputs.evidence_paths),
        assets=tuple(projected_assets),
        links=tuple(projected_links),
        message_paths=MappingProxyType(
            {message_id: tuple(paths) for message_id, paths in projected_paths.items()}
        ),
    )
    _write_projection(report, output_root)
    return report
