"""Deterministic building classification.

This module deliberately has no UI or third-party dependencies.  Keeping the
classification entry point here allows the rule engine, automated tests and a
future browser client to share the same professional logic without importing
Streamlit.
"""


def auto_classify(profile):
    """Populate ``building_class`` and the default fire-resistance grade.

    The implementation is intentionally equivalent to the legacy
    ``app._auto_classify`` function.  Moving it is an architectural change, not
    a normative-rule change; rule corrections must be reviewed and tested
    separately.
    """
    p = profile
    h = p.height_m
    bt = p.building_type
    cs = getattr(p, "civil_subtype", "public") if bt == "civil" else None

    if bt == "civil":
        if cs == "residential":
            if h > 54:
                p.building_class = "一类高层住宅建筑"
            elif h > 27:
                p.building_class = "二类高层住宅建筑"
            else:
                p.building_class = "单、多层住宅建筑"
        else:
            if h > 50:
                p.building_class = "一类高层公共建筑"
            elif h > 24:
                if (
                    getattr(p, "is_medical", False)
                    or getattr(p, "is_important_public_building", False)
                    or getattr(p, "is_elderly_facility", False)
                ):
                    p.building_class = "一类高层公共建筑"
                else:
                    p.building_class = "二类高层公共建筑"
            else:
                p.building_class = "单、多层公共建筑"
    else:
        isub = getattr(p, "industrial_subtype", "workshop")
        fire_risk = getattr(p, "fire_risk", "")
        floors_above = p.floors_above
        fire_resistance = getattr(p, "fire_resistance", "一级")
        if isub == "workshop":
            if h > 24:
                if fire_risk == "甲":
                    violations = ["甲类厂房不得建为高层（GB 50016 第3.3.1条 表3.3.1）"]
                    if fire_resistance == "一级" and floors_above > 2:
                        violations.append(
                            f"甲类厂房（一级耐火）最多允许2层，当前{floors_above}层"
                            "（GB 50016 第3.3.1条 表3.3.1）"
                        )
                    elif fire_resistance == "二级" and floors_above > 1:
                        violations.append(
                            f"甲类厂房（二级耐火）最多允许1层，当前{floors_above}层"
                            "（GB 50016 第3.3.1条 表3.3.1）"
                        )
                    p.building_class = "违规：" + "；".join(violations)
                else:
                    p.building_class = "高层厂房"
            else:
                if fire_risk == "甲":
                    if fire_resistance == "一级" and floors_above > 2:
                        p.building_class = (
                            f"违规：甲类厂房（一级耐火）最多允许2层，当前{floors_above}层"
                            "（GB 50016 第3.3.1条 表3.3.1）"
                        )
                    elif fire_resistance == "二级" and floors_above > 1:
                        p.building_class = (
                            f"违规：甲类厂房（二级耐火）最多允许1层，当前{floors_above}层"
                            "（GB 50016 第3.3.1条 表3.3.1）"
                        )
                    else:
                        p.building_class = "单、多层厂房"
                elif fire_risk == "乙" and fire_resistance == "二级" and floors_above > 6:
                    p.building_class = (
                        f"违规：乙类厂房（二级耐火）最多允许6层，当前{floors_above}层"
                        "（GB 50016 第3.3.1条 表3.3.1）"
                    )
                else:
                    p.building_class = "单、多层厂房"
        else:
            if h > 24:
                if fire_risk == "甲":
                    violations = ["甲类仓库不得建为高层（GB 50016 第3.3.2条 表3.3.2）"]
                    if floors_above > 1:
                        violations.append(
                            f"甲类仓库最多允许1层，当前{floors_above}层"
                            "（GB 50016 第3.3.2条 表3.3.2）"
                        )
                    p.building_class = "违规：" + "；".join(violations)
                else:
                    p.building_class = "高层仓库"
            elif fire_risk == "甲" and floors_above > 1:
                p.building_class = (
                    f"违规：甲类仓库最多允许1层，当前{floors_above}层"
                    "（GB 50016 第3.3.2条 表3.3.2）"
                )
            else:
                p.building_class = "单、多层仓库"

    if "一类高层" in p.building_class or getattr(p, "has_basement", False):
        p.fire_resistance = getattr(p, "fire_resistance", "") or "一级"
    elif "二类高层" in p.building_class:
        p.fire_resistance = getattr(p, "fire_resistance", "") or "二级"
    elif bt == "industrial":
        fire_risk = getattr(p, "fire_risk", "")
        if fire_risk in ["甲", "乙"]:
            p.fire_resistance = getattr(p, "fire_resistance", "") or "一级"
        elif "高层" in p.building_class and "违规" not in p.building_class:
            p.fire_resistance = getattr(p, "fire_resistance", "") or "一级"
        elif "违规" in p.building_class:
            p.fire_resistance = getattr(p, "fire_resistance", "") or "一级"
        else:
            p.fire_resistance = getattr(p, "fire_resistance", "") or "二级"
    else:
        p.fire_resistance = getattr(p, "fire_resistance", "") or "二级"

    return p
