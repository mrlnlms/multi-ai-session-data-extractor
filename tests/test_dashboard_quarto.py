from pathlib import Path
from subprocess import CompletedProcess

from dashboard import quarto


def test_report_server_base_url_defaults_to_local_server(monkeypatch):
    monkeypatch.delenv("QMD_REPORT_BASE_URL", raising=False)

    assert quarto.report_server_base_url() == "http://localhost:8765"


def test_report_server_base_url_accepts_override_and_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv("QMD_REPORT_BASE_URL", "http://127.0.0.1:8766/")

    assert quarto.report_server_base_url() == "http://127.0.0.1:8766"


def test_report_urls_point_directly_to_rendered_filename(monkeypatch):
    monkeypatch.setenv("QMD_REPORT_BASE_URL", "http://localhost:8765")

    assert quarto.report_url("Claude.ai") == "http://localhost:8765/claude-ai.html"
    assert (
        quarto.report_url_for_qmd(Path("notebooks/chatgpt-acc-1.qmd"))
        == "http://localhost:8765/chatgpt-acc-1.html"
    )


def test_render_and_publish_qmd_has_no_static_publication_api(monkeypatch, tmp_path):
    qmd = tmp_path / "gemini.qmd"
    qmd.touch()
    monkeypatch.setattr(
        quarto,
        "_render_qmd_path",
        lambda _qmd: CompletedProcess(["quarto", "render"], 0, "", ""),
    )

    success, error = quarto.render_and_publish_qmd(qmd)

    assert success is True
    assert error is None
    assert not hasattr(quarto, "copy_to_static_for_qmd")
    assert not hasattr(quarto, "STATIC_DIR")
