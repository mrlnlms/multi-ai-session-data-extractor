from pathlib import Path

from src.workflows import serve_reports


def test_report_urls_are_sorted_and_use_selected_port(tmp_path: Path):
    (tmp_path / "z.html").write_text("z")
    (tmp_path / "a.html").write_text("a")
    (tmp_path / "ignored.txt").write_text("x")

    assert serve_reports.report_urls(port=8766, output_dir=tmp_path) == [
        "http://localhost:8766/a.html",
        "http://localhost:8766/z.html",
    ]


def test_start_requires_rendered_output(tmp_path: Path):
    try:
        serve_reports.start_server(output_dir=tmp_path / "missing")
    except FileNotFoundError as error:
        assert "render a Quarto notebook first" in str(error)
    else:
        raise AssertionError("missing report directory must fail")
