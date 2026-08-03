"""config 로더 테스트 (B3)."""

from pathlib import Path

import pytest

from oo_scan.config import ASSET_CLASS_LABELS_KO, ConfigError, load_config


def test_real_config_loads_28_assets() -> None:
    """실제 assets.yaml은 28종이고 자산군이 전부 라벨에 존재한다."""
    cfg = load_config()
    assert len(cfg.assets) == 28
    ids = [a.id for a in cfg.assets]
    assert len(ids) == len(set(ids))
    for a in cfg.assets:
        assert a.asset_class in ASSET_CLASS_LABELS_KO


def test_real_config_hype_fallback_and_em_group() -> None:
    """HYPE는 폴백 체인·심볼 오버라이드가 있고 신흥국 그룹이 존재한다."""
    cfg = load_config()
    hype = cfg.by_id("HYPE")
    assert hype.exchanges[0] == "hyperliquid"
    assert hype.symbol_for("hyperliquid") == "HYPE/USDC"
    assert hype.symbol_for("bybit") == "HYPE/USDT"
    assert any(a.asset_class == "em_index" for a in cfg.assets)


def test_rate_display_scale() -> None:
    """^TNX는 display_scale 0.1이 적용돼 있다."""
    cfg = load_config()
    assert cfg.by_id("US10Y").display_scale == pytest.approx(0.1)


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "assets.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_duplicate_id_rejected(tmp_path: Path) -> None:
    """중복 ID는 ConfigError."""
    p = _write(
        tmp_path,
        """
assets:
  - {id: BTC, name_ko: 비트코인, asset_class: crypto, source: ccxt, symbol: BTC/USDT, exchanges: [binance]}
  - {id: BTC, name_ko: 비트코인2, asset_class: crypto, source: ccxt, symbol: BTC/USDT, exchanges: [binance]}
""",
    )
    with pytest.raises(ConfigError, match="중복"):
        load_config(p)


def test_missing_field_rejected(tmp_path: Path) -> None:
    """필수 필드 누락은 ConfigError."""
    p = _write(tmp_path, "assets:\n  - {id: X, asset_class: fx, source: yfinance, symbol: Y}\n")
    with pytest.raises(ConfigError, match="누락"):
        load_config(p)


def test_ccxt_requires_exchanges(tmp_path: Path) -> None:
    """ccxt 자산에 exchanges가 없으면 ConfigError."""
    p = _write(
        tmp_path,
        "assets:\n  - {id: X, name_ko: 엑스, asset_class: crypto, source: ccxt, symbol: X/USDT}\n",
    )
    with pytest.raises(ConfigError, match="exchanges"):
        load_config(p)


def test_unsupported_source_rejected(tmp_path: Path) -> None:
    """미지원 source는 ConfigError."""
    p = _write(
        tmp_path,
        "assets:\n  - {id: X, name_ko: 엑스, asset_class: fx, source: bloomberg, symbol: X}\n",
    )
    with pytest.raises(ConfigError, match="source"):
        load_config(p)
