"""JSON adapter used by the browser-hosted Python runtime."""

from __future__ import annotations

import json
from pathlib import Path

from engine.calculator import calculate_all
from engine.classifier import auto_classify
from engine.decision_engine import BuildingProfile, DecisionEngine
from engine.report_builder import build_report
from engine.rule_loader import RuleLoader


ROOT = Path(__file__).resolve().parent.parent
RULESET_DIR = ROOT / "rulesets" / "2026-07-民建全分支-v2"

_loader = None
_engine = None


def _get_runtime():
    global _loader, _engine
    if _loader is None:
        _loader = RuleLoader(str(RULESET_DIR)).load_all()
        _engine = DecisionEngine(_loader)
    return _loader, _engine


def _garage_class(parking_spots: int, area: float) -> str:
    if parking_spots > 300 or area > 10000:
        return "Ⅰ"
    if parking_spots > 150 or area > 5000:
        return "Ⅱ"
    if parking_spots > 50 or area > 2000:
        return "Ⅲ"
    return "Ⅳ"


def _profile_from_dict(data: dict) -> BuildingProfile:
    profile = BuildingProfile()
    for key, value in data.items():
        if hasattr(profile, key):
            setattr(profile, key, value)

    profile.height_m = float(profile.height_m or 0)
    profile.floor_area_sqm = float(profile.floor_area_sqm or 0)
    profile.total_area_sqm = float(profile.total_area_sqm or 0)
    profile.clear_height_m = float(profile.clear_height_m or 0)
    profile.floors_above = int(profile.floors_above or 0)
    profile.floors_below = int(profile.floors_below or 0)
    profile.max_occupants = int(profile.max_occupants or 0)

    if not profile.total_area_sqm and profile.floor_area_sqm and profile.floors_above:
        profile.total_area_sqm = profile.floor_area_sqm * profile.floors_above
    if not profile.building_volume and profile.total_area_sqm:
        clear_height = profile.clear_height_m or 3.0
        profile.building_volume = profile.total_area_sqm * clear_height

    profile.has_basement = bool(profile.has_basement or profile.floors_below > 0)
    if profile.has_garage:
        profile.has_basement = True
        profile.garage_parking_spots = int(profile.garage_parking_spots or 0)
        profile.garage_total_area = float(profile.garage_total_area or 0)
        profile.garage_class = profile.garage_class or _garage_class(
            profile.garage_parking_spots, profile.garage_total_area
        )

    if profile.public_building_type == "医疗建筑":
        profile.is_medical = True
    elif profile.public_building_type == "教育建筑":
        profile.is_education = True
    elif profile.public_building_type == "商业建筑":
        profile.is_shop_exhibition = True

    profile.is_entertainment = bool(
        profile.is_entertainment or getattr(profile, "is_entertainment_venue", False)
    )
    profile.has_sprinkler_design = bool(
        profile.has_sprinkler_design
        or getattr(profile, "sprinkler_coverage", "") in {"全部设置", "局部设置"}
    )

    substances = profile.substances
    if isinstance(substances, str):
        profile.substances = [item.strip() for item in substances.replace("，", ",").split(",") if item.strip()]

    auto_classify(profile)
    return profile


def evaluate_profile(profile_data: dict) -> dict:
    """Evaluate one structured building profile and return serializable data."""
    if not isinstance(profile_data, dict):
        raise TypeError("profile_data 必须是对象")
    profile = _profile_from_dict(profile_data)
    loader, engine = _get_runtime()
    result = engine.evaluate(profile)
    calculation = calculate_all(profile, result["conclusions"], loader.lookup_tables)
    report = build_report(
        profile,
        result["conclusions"],
        calculation,
        result["inference_log"],
    )
    return {
        "profile": profile.to_dict(),
        "conclusions": result["conclusions"],
        "calculation": calculation,
        "inference_log": result["inference_log"],
        "warnings": result.get("warnings", []),
        "report": report,
        "ruleset": loader.get_meta().get("standards_version", "unknown"),
    }


def evaluate_profile_json(profile_json: str) -> str:
    """String-only bridge for JavaScript/Pyodide."""
    data = json.loads(profile_json)
    return json.dumps(evaluate_profile(data), ensure_ascii=False)
