"""Unit tests for calibration math and config I/O."""

from pathlib import Path
import pytest

from tools.calibrator import abs_to_rel, load_config, rel_to_abs, save_config


def test_abs_to_rel_and_rel_to_abs_720p():
    """Verify coordinate conversions on 720p resolution."""
    table_rect = (100, 50, 1000, 600)
    abs_rect = (200, 110, 150, 60)

    rel = abs_to_rel(abs_rect, table_rect)
    assert rel == [0.1, 0.1, 0.15, 0.1]

    restored = rel_to_abs(rel, table_rect)
    assert restored == abs_rect


def test_abs_to_rel_and_rel_to_abs_1080p():
    """Verify coordinate conversions on 1080p resolution."""
    table_rect = (200, 100, 1500, 900)
    abs_rect = (500, 325, 300, 180)

    rel = abs_to_rel(abs_rect, table_rect)
    assert rel == [0.2, 0.25, 0.2, 0.2]

    restored = rel_to_abs(rel, table_rect)
    assert restored == abs_rect


def test_invalid_table_dimensions_raise():
    """Verify ValueError is raised when table dimensions are not strictly positive."""
    valid_abs = (10, 10, 50, 50)
    valid_rel = [0.1, 0.1, 0.1, 0.1]

    with pytest.raises(ValueError):
        abs_to_rel(valid_abs, (0, 0, 0, 500))

    with pytest.raises(ValueError):
        abs_to_rel(valid_abs, (0, 0, 500, 0))

    with pytest.raises(ValueError):
        abs_to_rel(valid_abs, (0, 0, -100, 500))

    with pytest.raises(ValueError):
        rel_to_abs(valid_rel, (0, 0, 0, 500))

    with pytest.raises(ValueError):
        rel_to_abs(valid_rel, (0, 0, 500, -10))


def test_config_load_and_save(tmp_path: Path):
    """Verify config loading, modifying, and saving using tmp_path."""
    config = load_config("config.json")
    assert "rois" in config
    assert "pot" in config["rois"]

    target_file = tmp_path / "custom_config.json"
    config["rois"]["pot"] = [0.45, 0.35, 0.1, 0.05]
    config["hud"]["opacity"] = 0.8

    save_config(config, target_file)

    reloaded = load_config(target_file)
    assert reloaded["rois"]["pot"] == [0.45, 0.35, 0.1, 0.05]
    assert reloaded["hud"]["opacity"] == 0.8
    assert reloaded["version"] == "1.0"
