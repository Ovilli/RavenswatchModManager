"""Pack carries each lang/<locale>.toml [manifest] to the registry upload."""

from rsmm.cli.json_bridge import _manifest_translations


def test_collects_translated_store_text(tmp_path):
    lang = tmp_path / "lang"
    lang.mkdir()
    (lang / "ZH-S.toml").write_text(
        '[manifest]\nname = "更强的敌人"\nsummary = "  敌人更强。 "\nauthor = "ignored"\n'
        '[strings]\nhello = "not store text"\n', encoding="utf-8")
    (lang / "EN.toml").write_text('[manifest]\nname = "English is the base"\n', encoding="utf-8")
    (lang / "JA.toml").write_text("not = [valid toml", encoding="utf-8")

    assert _manifest_translations(tmp_path) == {
        "ZH-S": {"name": "更强的敌人", "summary": "敌人更强。"},
    }


def test_caps_lengths_to_the_upload_schema(tmp_path):
    (tmp_path / "lang").mkdir()
    (tmp_path / "lang" / "DE.toml").write_text(
        f'[manifest]\nname = "{"x" * 300}"\n', encoding="utf-8")
    assert len(_manifest_translations(tmp_path)["DE"]["name"]) == 128


def test_no_lang_folder_means_no_translations(tmp_path):
    assert _manifest_translations(tmp_path) == {}
