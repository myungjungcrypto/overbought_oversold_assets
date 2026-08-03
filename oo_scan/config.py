"""자산 유니버스 설정 로더 — config/assets.yaml을 dataclass로 검증·적재한다."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

SUPPORTED_SOURCES = {"ccxt", "yfinance"}
SUPPORTED_CLASSES = {
    "crypto", "index", "em_index", "bond", "reit", "rate", "commodity", "fx", "vol",
}

# 리포트 그룹핑용 자산군 한글 라벨 (표시 순서 고정)
ASSET_CLASS_LABELS_KO: dict[str, str] = {
    "crypto": "크립토",
    "index": "주요 지수",
    "em_index": "신흥국 지수",
    "bond": "채권",
    "reit": "부동산",
    "rate": "금리",
    "commodity": "원자재",
    "fx": "환율",
    "vol": "변동성",
}

REQUIRED_FIELDS = ("id", "name_ko", "asset_class", "source", "symbol")


class ConfigError(ValueError):
    """설정 파일이 유효하지 않을 때 발생."""


@dataclass(frozen=True)
class Asset:
    """자산 1종의 정의."""

    id: str
    name_ko: str
    asset_class: str
    source: str
    symbol: str
    exchanges: tuple[str, ...] = ()
    symbol_overrides: dict[str, str] = field(default_factory=dict)
    display_scale: float = 1.0
    display_unit: str | None = None

    def symbol_for(self, exchange: str) -> str:
        """거래소별 심볼 오버라이드를 반영한 심볼을 반환한다."""
        return self.symbol_overrides.get(exchange, self.symbol)


@dataclass(frozen=True)
class AppConfig:
    """전체 설정."""

    assets: tuple[Asset, ...]

    def by_id(self, asset_id: str) -> Asset:
        """ID로 자산을 찾는다. 없으면 KeyError."""
        for a in self.assets:
            if a.id == asset_id:
                return a
        raise KeyError(asset_id)


def default_config_path() -> Path:
    """리포 루트 기준 기본 설정 파일 경로."""
    return Path(__file__).resolve().parent.parent / "config" / "assets.yaml"


def _parse_asset(raw: dict, index: int) -> Asset:
    """yaml 항목 1개를 Asset으로 변환·검증한다."""
    for f in REQUIRED_FIELDS:
        if not raw.get(f):
            raise ConfigError(f"assets[{index}]: 필수 필드 누락 — {f}")
    if raw["source"] not in SUPPORTED_SOURCES:
        raise ConfigError(f"assets[{index}] ({raw['id']}): 미지원 source — {raw['source']}")
    if raw["asset_class"] not in SUPPORTED_CLASSES:
        raise ConfigError(
            f"assets[{index}] ({raw['id']}): 미지원 asset_class — {raw['asset_class']}"
        )
    exchanges = tuple(raw.get("exchanges") or ())
    if raw["source"] == "ccxt" and not exchanges:
        raise ConfigError(f"assets[{index}] ({raw['id']}): ccxt 자산은 exchanges가 필요하다")
    return Asset(
        id=str(raw["id"]),
        name_ko=str(raw["name_ko"]),
        asset_class=str(raw["asset_class"]),
        source=str(raw["source"]),
        symbol=str(raw["symbol"]),
        exchanges=exchanges,
        symbol_overrides=dict(raw.get("symbol_overrides") or {}),
        display_scale=float(raw.get("display_scale", 1.0)),
        display_unit=raw.get("display_unit"),
    )


def load_config(path: Path | str | None = None) -> AppConfig:
    """설정 파일을 읽어 AppConfig를 반환한다. 유효하지 않으면 ConfigError."""
    p = Path(path) if path is not None else default_config_path()
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("assets"), list):
        raise ConfigError("최상위에 assets 리스트가 필요하다")
    assets = tuple(_parse_asset(raw, i) for i, raw in enumerate(data["assets"]))
    seen: set[str] = set()
    for a in assets:
        if a.id in seen:
            raise ConfigError(f"중복 자산 ID — {a.id}")
        seen.add(a.id)
    return AppConfig(assets=assets)
