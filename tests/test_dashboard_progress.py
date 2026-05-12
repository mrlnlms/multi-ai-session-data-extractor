"""Testes do parser de progresso do stdout dos syncs."""
from dashboard.progress import parse_progress


class TestParseProgress:
    def test_bracket_format_fetcher(self):
        # claude_ai/qwen/deepseek/gemini/perplexity/grok/kimi
        assert parse_progress("  [12/345] ok=12 skip=0 err=0") == (12, 345)

    def test_bracket_format_with_uuid(self):
        # NotebookLM orchestrator fetch
        line = "  [3/47] a1b2c3d4 'Meu Notebook' — ok, sources=5/5"
        assert parse_progress(line) == (3, 47)

    def test_bracket_format_chatgpt_refetch(self):
        # ChatGPT refetch_known via logger.info
        line = "2026-05-12 14:30:00 INFO   [50/1171] updated=50 errors=0"
        assert parse_progress(line) == (50, 1171)

    def test_bracket_format_grok_asset(self):
        line = "  [80/82] dl=80 skip=0 err=0"
        assert parse_progress(line) == (80, 82)

    def test_notebooklm_asset_progresso(self):
        line = "  progresso: 230/1171 (audios dl=13 skip=0, videos dl=0 skip=0)"
        assert parse_progress(line) == (230, 1171)

    def test_no_match_returns_none(self):
        assert parse_progress("ETAPA 1/4: Captura de conversas") is None
        # "1/4" no formato de etapa nao tem brackets — bom assim, evita
        # confundir etapa com progresso real
        assert parse_progress("audios dl=13 skip=0") is None
        assert parse_progress("") is None

    def test_zero_total_returns_none(self):
        # Defesa contra divisao por zero downstream
        assert parse_progress("[0/0] empty") is None

    def test_picks_first_bracket_when_multiple(self):
        # Nao deveria acontecer, mas garante determinismo
        line = "[5/10] foo [99/100] bar"
        assert parse_progress(line) == (5, 10)
