from __future__ import annotations

import pandas as pd

from dashboard.views.overview import _cached_asset_graph_stats


def test_asset_graph_stats_count_web_sources_independently(tmp_path):
    assets_path = tmp_path / "assets.parquet"
    links_path = tmp_path / "asset_links.parquet"
    pd.DataFrame(
        {
            "source": ["chatgpt", "qwen", "claude_code"],
            "is_binary_available": [True, False, True],
        }
    ).to_parquet(assets_path, index=False)
    pd.DataFrame({"asset_link_id": ["one", "two"]}).to_parquet(links_path, index=False)

    stats = _cached_asset_graph_stats(
        str(assets_path),
        str(links_path),
        (assets_path.stat().st_mtime, links_path.stat().st_mtime),
    )

    assert stats == {
        "assets": 3,
        "links": 2,
        "web_sources": 2,
        "available": 2,
    }
