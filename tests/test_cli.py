import pytest

from reelscribe import cli


def test_version(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--version"])
    assert e.value.code == 0
    assert "reelscribe" in capsys.readouterr().out


def test_status_on_fresh_library(tmp_path, capsys):
    rc = cli.main(["status", "--library", str(tmp_path / "newlib")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "videos       0" in out
    assert "next number  1" in out


def test_no_library_configured(tmp_path, monkeypatch, capsys):
    from reelscribe import config
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "nope.json")
    with pytest.raises(SystemExit) as e:
        cli.main(["status"])
    assert "No library configured" in str(e.value)


def test_bundle_nothing_pending(tmp_path, capsys):
    rc = cli.main(["bundle", "--library", str(tmp_path / "lib")])
    assert rc == 0
    assert "Nothing pending" in capsys.readouterr().out


def test_config_roundtrip(tmp_path, monkeypatch, capsys):
    from reelscribe import config
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "cfg.json")
    rc = cli.main(["config", "--library", str(tmp_path / "L"), "--model", "base.en"])
    assert rc == 0
    cfg = config.load()
    assert cfg["whisper_model"] == "base.en"
    assert cfg["library"].endswith("L")
