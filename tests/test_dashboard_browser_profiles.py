from streamlit.testing.v1 import AppTest

from src.browser_profile_catalog import load_browser_profile_catalog

def _render_empty_accounts():
    from dashboard.views.accounts import render

    render([])


def test_browser_profile_controls_render_without_local_catalog(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_function(_render_empty_accounts).run()

    assert not app.exception
    assert any(item.value == "Browser profiles — prototype" for item in app.subheader)
    assert any(item.label == "1. Create browser group" for item in app.expander)


def test_browser_group_creation_requires_preview_and_confirmation(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_function(_render_empty_accounts).run()
    app.text_input(key="browser_group_name").set_value("Foton").run()
    app.button(key="browser_group_preview").click().run()

    catalog_path = tmp_path / "data" / "accounts" / "browser_profiles.json"
    assert not catalog_path.exists()
    app.checkbox(key="browser_group_confirm").check().run()
    app.button(key="browser_group_apply").click().run()

    assert not app.exception
    assert load_browser_profile_catalog(catalog_path).records[0].display_name == "Foton"
