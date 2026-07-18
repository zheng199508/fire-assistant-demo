"""
calculator.py v3 — 消防计算模块（全面整改版）

改进:
- 所有计算使用 JSON lookup tables 而非硬编码
- 新增：防火分区完整矩阵、耐火极限明细、疏散参数、防火门等级
- 增强：喷淋参数、排烟参数、灭火器计算、特殊灭火系统判定
"""

from typing import Dict, Any, List


def _is_violation(profile) -> bool:
    """判断建筑是否违规（甲类高层/超层数等）"""
    return "违规" in getattr(profile, 'building_class', '')

def _get_effective_class(profile) -> str:
    """获取有效建筑分类（违规建筑退回合规分类用于计算）"""
    bc = getattr(profile, 'building_class', '')
    if "违规" not in bc:
        return bc
    if "厂房" in bc:
        return "单、多层厂房"
    elif "仓库" in bc:
        return "单、多层仓库"
    return bc

def calculate_all(profile, conclusions, lookup) -> Dict[str, Any]:
    result = {}
    result.update(calc_water_volume(profile, conclusions, lookup))
    result.update(check_fire_compartment(profile, conclusions, lookup))
    result.update(calc_fire_resistance_detail(profile, lookup))
    result.update(calc_evacuation_detail(profile, lookup))
    result.update(calc_fire_door_rating(profile, lookup))
    result.update(calc_sprinkler_params(profile, conclusions, lookup))
    result.update(calc_smoke_exhaust(profile, conclusions, lookup))
    result.update(calc_extinguisher(profile, conclusions, lookup))
    result.update(calc_special_systems(profile, conclusions, lookup))
    result["calculation_steps"] = result.get("calculation_steps", [])
    return result


# ─── 3.1 消防水量水池水箱 ───

def calc_water_volume(profile, conclusions, lookup) -> Dict[str, Any]:
    h = profile.height_m
    bt = profile.building_type
    cs = profile.civil_subtype
    fr = profile.fire_risk
    vol = profile.building_volume
    steps = []

    # 自喷覆盖范围（影响室内消火栓流量折减、防火分区等）
    sprinkler_coverage = getattr(profile, 'sprinkler_coverage', '')
    has_sprinkler = (sprinkler_coverage in ("全部设置", "局部设置"))
    if not has_sprinkler:
        has_sprinkler = any("喷水灭火" in c.get("conclusion", "") and c["conclusion_type"] == "required" for c in conclusions)
    if profile.has_garage and profile.garage_parking_spots > 10:
        has_sprinkler = True
    if getattr(profile, 'has_sprinkler_design', False):
        has_sprinkler = True
        # 向后兼容：has_sprinkler_design=True但sprinkler_coverage为空时，默认全部设置
        if not sprinkler_coverage:
            sprinkler_coverage = "全部设置"

    # 室外消火栓流量 — 从 lookup 表查
    outdoor = _lookup_outdoor_flow(profile, lookup)
    steps.append(f"室外消火栓设计流量: {outdoor} L/s（依据 GB 50974-2014 表3.3.2）")

    # 室内消火栓流量 — 从 lookup 表查
    indoor, indoor_guns = _lookup_indoor_flow(profile, lookup)
    indoor_original = indoor
    steps.append(f"室内消火栓设计流量: {indoor} L/s（同时使用{indoor_guns}支水枪，依据 GB 50974-2014 表3.5.2）")

    # 室内消火栓流量折减（仅全部设置自喷时适用，GB 50974-2014 第3.5.3条）
    indoor_reduced = False
    if sprinkler_coverage == "全部设置":
        if bt == "civil" and cs == "public" and indoor > 20:
            indoor = 20
            indoor_reduced = True
        elif bt == "civil" and cs == "residential" and indoor > 10:
            indoor = 10
            indoor_reduced = True
        if indoor_reduced:
            steps.append(f"室内消火栓流量折减: {indoor_original} → {indoor} L/s（全部设自喷，依据 GB 50974-2014 第3.5.3条）")

    # 火灾延续时间
    dur = _lookup_fire_duration(profile, lookup)
    steps.append(f"火灾延续时间: {dur:.1f} h（依据 GB 50974-2014 表3.6.2）")

    # 喷淋流量
    sprinkler_flow = 30 if has_sprinkler else 0
    sprinkler_dur = 1.0 if has_sprinkler else 0
    if has_sprinkler:
        coverage_note = "（全部设置）" if sprinkler_coverage == "全部设置" else "（局部设置）"
        steps.append(f"自动喷水灭火系统设计流量: {sprinkler_flow} L/s × {sprinkler_dur}h{coverage_note}（依据 GB 50974-2014 第3.6.1条）")

    outdoor_m3 = 3.6 * outdoor * dur
    indoor_m3 = 3.6 * indoor * dur
    sprinkler_m3 = 3.6 * sprinkler_flow * sprinkler_dur
    total = outdoor_m3 + indoor_m3 + sprinkler_m3
    steps.append(f"消防用水总量 = 3.6×{outdoor}×{dur} + 3.6×{indoor}×{dur} + 3.6×{sprinkler_flow}×{sprinkler_dur} = {total:.1f} m³")

    # 水池容积
    if profile.dual_municipal_water and profile.municipal_outdoor_flow_ok:
        pool = max(100, indoor_m3 + sprinkler_m3)
        needs_pool = total > 100
        steps.append(f"消防水池有效容积: {pool:.1f} m³（两路市政供水可靠 → 仅计入室内消火栓水量+喷淋水量，且≥100m³）")
    else:
        pool = total
        needs_pool = True
        steps.append(f"消防水池有效容积: {pool:.1f} m³（非两路可靠供水 → 计入全部消防用水量）")

    # 水箱容积 — 优先使用用户输入值，否则从 lookup 表查
    if getattr(profile, 'water_tank_volume', 0) > 0:
        tank = profile.water_tank_volume
        steps.append(f"高位消防水箱有效容积: {tank} m³（用户指定值）")
    else:
        tank = _lookup_water_tank(profile, lookup)
        steps.append(f"高位消防水箱有效容积: {tank} m³（依据 GB 50974-2014 第5.2.1条）")

    return {
        "outdoor_flow_Ls": outdoor, "indoor_flow_Ls": indoor, "indoor_guns": indoor_guns,
        "sprinkler_flow_Ls": sprinkler_flow, "sprinkler_duration_h": sprinkler_dur,
        "fire_duration_h": dur,
        "outdoor_water_m3": outdoor_m3, "indoor_water_m3": indoor_m3,
        "outdoor_flow_citation": "GB 50974-2014 表3.3.2",
        "indoor_flow_citation": "GB 50974-2014 表3.5.2",
        "sprinkler_water_m3": sprinkler_m3, "total_water_m3": total,
        "pool_volume_m3": pool, "needs_pool": needs_pool,
        "water_tank_m3": tank, "calculation_steps": steps,
    }


def _lookup_vol_tier(risk_data, vol, default_val):
    """从体积分档的 lookup 数据中查询对应流量"""
    if vol > 50000:
        return risk_data.get("V>50000", risk_data.get("default", default_val))
    elif vol > 20000:
        return risk_data.get("20000<V≤50000", risk_data.get("default", default_val))
    elif vol > 5000:
        return risk_data.get("5000<V≤20000", risk_data.get("default", default_val))
    else:
        return risk_data.get("V≤5000", risk_data.get("default", default_val))


def _lookup_outdoor_flow(profile, lookup) -> int:
    """从 outdoor_hydrant_flow.json 查室外消火栓流量"""
    tbl = lookup.get("outdoor_hydrant_flow", {})
    bt = profile.building_type
    h = profile.height_m
    vol = profile.building_volume

    if bt == "civil":
        civ = tbl.get("civil", {})
        if profile.civil_subtype == "residential":
            res = civ.get("住宅", {})
            if h > 54 and vol > 100000:
                return res.get("H>54m_V>100000", 30)
            elif h > 54:
                return res.get("H>54m_V≤100000", 25)
            elif h > 27:
                return res.get("27m<H≤54m", 20)
            else:
                return res.get("H≤27m", 15)
        else:
            pub = civ.get("公共建筑", {})
            if h > 50 and vol > 50000:
                return pub.get("H>50m_V>50000", 40)
            elif h > 50:
                return pub.get("H>50m_V≤50000", 30)
            elif h > 24:
                return pub.get("24m<H≤50m", 25)
            else:
                return pub.get("H≤24m", 20)
    else:
        # fire_risk 存储的是"甲"/"乙"等（不含"类"后缀），但 lookup table 键名是"甲类"/"乙类"等
        risk_key = profile.fire_risk + "类" if profile.fire_risk else ""
        vol = profile.building_volume
        if profile.industrial_subtype == "workshop":
            ws = tbl.get("industrial_workshop", {})
            risk_data = ws.get(risk_key, ws.get(profile.fire_risk, {}))
            if isinstance(risk_data, dict):
                return _lookup_vol_tier(risk_data, vol, 25)
            return risk_data
        else:
            wh = tbl.get("industrial_warehouse", {})
            risk_data = wh.get(risk_key, wh.get(profile.fire_risk, {}))
            if isinstance(risk_data, dict):
                return _lookup_vol_tier(risk_data, vol, 25)
            return risk_data
    return 20


def _lookup_indoor_flow(profile, lookup) -> tuple:
    """从 indoor_hydrant_flow.json 查室内消火栓流量"""
    tbl = lookup.get("indoor_hydrant_flow", {})
    bt = profile.building_type
    h = profile.height_m
    fr = profile.fire_risk

    if bt == "civil":
        civ = tbl.get("civil", {})
        if profile.civil_subtype == "residential":
            if h > 54:
                r = civ.get("住宅_H>54m", {})
            elif h > 27:
                r = civ.get("住宅_27m<H≤54m", {})
            else:
                r = civ.get("住宅_H≤27m", {})
        else:
            if h > 50:
                r = civ.get("公建_H>50m_medium", {})
            elif h > 24:
                r = civ.get("公建_24m<H≤50m", {})
            else:
                r = civ.get("公建_H≤24m", {})
    else:
        if profile.industrial_subtype == "workshop":
            ws = tbl.get("industrial_workshop", {})
            if fr == "甲":
                r = ws.get("甲类", {})
            elif fr == "乙":
                r = ws.get("乙类", {})
            elif fr == "丙":
                if h > 50:
                    r = ws.get("丙类_H>50m", {})
                elif h > 24:
                    r = ws.get("丙类_24m<H≤50m", {})
                else:
                    r = ws.get("丙类_H≤24m", {})
            elif fr == "丁":
                r = ws.get("丁类_H>24m", {}) if h > 24 else ws.get("丁类_H≤24m", {})
            elif fr == "戊":
                r = ws.get("戊类_H>24m", {}) if h > 24 else ws.get("戊类_H≤24m", {})
            else:
                # 未指定火灾危险性，使用丙类作为默认
                r = ws.get("丙类_H≤24m", {"flow_Ls": 20, "guns": 4})
        else:
            wh = tbl.get("industrial_warehouse", {})
            if fr == "甲":
                r = wh.get("甲类", {})
            elif fr == "乙":
                r = wh.get("乙类", {})
            elif fr == "丙":
                if h > 24:
                    if profile.building_volume > 10000:
                        r = wh.get("丙类_H>24m_V>10000", {})
                    else:
                        r = wh.get("丙类_H>24m_V≤10000", {})
                else:
                    r = wh.get("丙类_H≤24m", {})
            elif fr == "丁":
                r = wh.get("丁类_H>24m", {}) if h > 24 else wh.get("丁类_H≤24m", {})
            elif fr == "戊":
                r = wh.get("戊类_H>24m", {}) if h > 24 else wh.get("戊类_H≤24m", {})
            else:
                # 未指定火灾危险性，使用丙类作为默认
                r = wh.get("丙类_H≤24m", {"flow_Ls": 20, "guns": 4})

    return r.get("flow_Ls", 20), r.get("guns", 4)


def _lookup_fire_duration(profile, lookup) -> float:
    """从 fire_duration.json 查火灾延续时间"""
    tbl = lookup.get("fire_duration", {}).get("durations", {})
    if profile.building_type == "industrial":
        if profile.fire_risk in ["甲", "乙", "丙"]:
            return tbl.get("甲乙丙类厂房/仓库", 3.0)
        else:
            return tbl.get("丁戊类厂房/仓库", 2.0)
    if profile.has_garage:
        return tbl.get("汽车库", 2.0)
    return tbl.get("其他民用（含住宅/一般公建）", 2.0)


def _lookup_water_tank(profile, lookup) -> int:
    """从 water_tank.json 查高位水箱容积"""
    tbl = lookup.get("water_tank", {}).get("volumes", {})
    h = profile.height_m
    bt = profile.building_type
    bc = profile.building_class

    if bt == "civil" and profile.civil_subtype == "residential":
        if h > 100:
            return tbl.get("一类高层住宅_H>100m", 36)
        elif h > 54:
            return tbl.get("一类高层住宅_H<=100m", 18)
        elif h > 27:
            return tbl.get("二类高层住宅", 12)
        else:
            return tbl.get("多层住宅_H>21m", 6)
    elif bt == "civil":
        # 使用建筑分类而非仅高度判断（医疗建筑H=28m可为一类高层）
        if h > 100:
            return tbl.get("一类高层公建_H>100m", 50)
        elif "一类高层" in bc:
            return tbl.get("一类高层公建_H<=100m", 36)
        elif h > 50:
            return tbl.get("一类高层公建_H<=100m", 36)
        elif "二类高层" in bc:
            return tbl.get("二类高层公建", 12)
        elif h > 24:
            return tbl.get("二类高层公建", 12)
        else:
            return tbl.get("多层公建", 18)
    else:
        return tbl.get("工业_>25L/s", 18)
    return 12


# ─── 3.2 防火分区校验 ───

def check_fire_compartment(profile, conclusions, lookup) -> Dict[str, Any]:
    tbl = lookup.get("fire_compartment_detail", {})
    h = profile.height_m
    bt = profile.building_type
    fr = profile.fire_risk
    area = profile.floor_area_sqm
    steps = []
    warnings = []

    violation = _is_violation(profile)
    effective_class = _get_effective_class(profile)

    sprinkler_coverage = getattr(profile, 'sprinkler_coverage', '')
    has_sprinkler = (sprinkler_coverage in ("全部设置", "局部设置"))
    if not has_sprinkler:
        has_sprinkler = any("喷水灭火" in c.get("conclusion", "") or "自喷" in c.get("conclusion", "")
                           for c in conclusions)
    if profile.has_garage and profile.garage_parking_spots > 10:
        has_sprinkler = True
    if getattr(profile, 'has_sprinkler_design', False):
        has_sprinkler = True
        # 向后兼容：has_sprinkler_design=True但sprinkler_coverage为空时，默认全部设置
        if not sprinkler_coverage:
            sprinkler_coverage = "全部设置"
    is_full_sprinkler = (sprinkler_coverage == "全部设置")

    limit = 1500
    limit_with = 3000
    basement_limit = 500
    basement_limit_with = 1000

    if bt == "civil":
        if "高层" in effective_class:
            if "住宅" in effective_class:
                d = tbl.get("civil", {}).get("高层住宅", {}).get("一级", {})
            else:
                d = tbl.get("civil", {}).get("高层公建", {}).get("一级", {})
        else:
            if "住宅" in effective_class:
                d = tbl.get("civil", {}).get("单多层住宅", {}).get(profile.fire_resistance, {})
            else:
                d = tbl.get("civil", {}).get("单多层公建", {}).get(profile.fire_resistance, {})
        limit = d.get("no_sprinkler", 1500)
        limit_with = d.get("with_sprinkler", limit * 2)

        if profile.has_basement:
            bd = tbl.get("civil", {}).get("地下半地下", {}).get("一级", {})
            basement_limit = bd.get("no_sprinkler", 500)
            basement_limit_with = bd.get("with_sprinkler", basement_limit * 2)
    elif bt == "industrial":
        is_workshop = profile.industrial_subtype == "workshop"
        key = "industrial_workshop" if is_workshop else "industrial_warehouse"
        # fire_risk 存储的是"甲"/"乙"等（不含"类"后缀），但 lookup table 键名是"甲类"/"乙类"等
        risk_key = fr + "类" if fr else ""
        data = tbl.get(key, {}).get(risk_key, tbl.get(key, {}).get(fr, {}))
        # 仓库丁戊类使用合并键"丁戊类"
        if not data and not is_workshop and fr in ["丁", "戊"]:
            data = tbl.get(key, {}).get("丁戊类", {})
        if not data and fr:
            data = tbl.get(key, {})

        # 违规建筑：使用合规分类（多层）进行查找
        if violation:
            layer_key = "多层" if profile.floors_above > 1 else "单层"
        elif h > 24:
            layer_key = "高层"
        elif profile.floors_above > 1:
            layer_key = "多层"
        else:
            layer_key = "单层"

        lookup_key = f"{layer_key}_{profile.fire_resistance}"
        d = data.get(lookup_key, data.get(f"单层_{profile.fire_resistance}", {}))
        if not d:
            for k in data:
                if profile.fire_resistance in k:
                    d = data[k]
                    break
        limit = d.get("no_sprinkler", 2000)
        limit_with = d.get("with_sprinkler", limit * 2)

    if violation:
        steps.append(f"⚠️ 建筑方案违规，以下防火分区面积基于合规假设（{effective_class}）计算，仅供参考")

    # 商店营业厅/展览厅放宽（GB 50016 第5.3.4条）
    is_shop_relax = getattr(profile, 'is_shop_qualifies_relax', False)
    if is_shop_relax and bt == "civil" and is_full_sprinkler:
        if h > 24:
            shop_limit = 4000
            limit_with = max(limit_with, shop_limit)
            steps.append(f"商店营业厅放宽: 防火分区最大允许面积 4000 m²（全部设自喷+报警+不燃材料，GB 50016 第5.3.4条）")
        elif profile.has_basement:
            shop_limit = 2000
            basement_limit_with = max(basement_limit_with, shop_limit)
            steps.append(f"商店营业厅（地下）放宽: 防火分区最大允许面积 2000 m²（GB 50016 第5.3.4条）")
        else:
            shop_limit = 10000
            limit_with = max(limit_with, shop_limit)
            steps.append(f"商店营业厅放宽: 防火分区最大允许面积 10000 m²（单层/首层，GB 50016 第5.3.4条）")

    # 自喷修正：全部设置→面积×2，局部设置→仅局部面积翻倍，整体限制不变
    if is_full_sprinkler:
        steps.append(f"地上防火分区最大允许面积: {limit} m²（全部设自喷 → ×2.0 = {limit_with} m²）")
        if profile.has_basement:
            steps.append(f"地下室防火分区最大允许面积: {basement_limit} m²（全部设自喷 → ×2.0 = {basement_limit_with} m²）")
    elif has_sprinkler:
        limit_with = limit  # 局部设置仅局部面积翻倍，整体限制不变
        steps.append(f"地上防火分区最大允许面积: {limit} m²（局部设自喷 → 仅局部面积可翻倍，整体限制不变）")
        if profile.has_basement:
            basement_limit_with = basement_limit
            steps.append(f"地下室防火分区最大允许面积: {basement_limit} m²（局部设自喷 → 整体限制不变）")
    else:
        limit_with = limit
        steps.append(f"地上防火分区最大允许面积: {limit} m²（未设自动喷水灭火系统）")
        if profile.has_basement:
            basement_limit_with = basement_limit
            steps.append(f"地下室防火分区最大允许面积: {basement_limit} m²（未设自喷）")

    is_exceeded = area > 0 and area > limit_with
    if is_exceeded:
        warnings.append(f"⚠️ 防火分区超限: 标准层面积 {area:.0f} m² > 允许 {limit_with} m²！需增加防火墙或增设自动灭火系统")

    if violation:
        warnings.append("⚠️ 建筑方案违规，防火分区面积校验基于合规假设（按多层建筑取值），实际设计需先调整建筑方案至合规范围")

    # 裙房防火分区（仅民用建筑H>24m且含裙房时）
    podium_limit = 0
    has_podium = getattr(profile, 'has_podium', False)
    podium_separated = getattr(profile, 'podium_separated_by_firewall', False)
    if bt == "civil" and h > 24 and has_podium:
        if podium_separated:
            # 防火墙分隔 → 裙房按单多层
            pd = tbl.get("civil", {}).get("单多层公建", {}).get(profile.fire_resistance, {})
            podium_limit = pd.get("no_sprinkler", 2500)
            if is_full_sprinkler:
                podium_limit = pd.get("with_sprinkler", podium_limit * 2)
            steps.append(f"裙房防火分区最大允许面积: {podium_limit} m²（防火墙分隔 → 按单多层建筑，GB 50016 表5.1.1注3）")
        else:
            steps.append("⚠️ 裙房未设防火墙分隔 → 裙房防火分区按高层主体要求（同地上部分）")
            podium_limit = limit_with

    return {
        "compartment_limit": limit,
        "compartment_limit_with_sprinkler": limit_with,
        "compartment_limit_basement": basement_limit,
        "compartment_limit_basement_with_sprinkler": basement_limit_with,
        "compartment_actual_area": area,
        "compartment_is_exceeded": is_exceeded,
        "compartment_exceed_remedy": "增加防火墙分割或增设自动灭火系统" if is_exceeded else "",
        "compartment_warnings": warnings,
        "compartment_steps": steps,
        "is_violation_premise": violation,
        "compartment_base_citation": "GB 50016 表3.3.1" if profile.building_type == "industrial" else "GB 50016 表5.3.1",
        "podium_compartment_limit": podium_limit,
        "has_podium_with_firewall": has_podium and podium_separated,
    }


# ─── 3.3 耐火极限明细 ───

def calc_fire_resistance_detail(profile, lookup) -> Dict[str, Any]:
    tbl = lookup.get("fire_resistance_detail", {})
    bt = profile.building_type
    key = "industrial" if bt == "industrial" else "civil"
    data = tbl.get(key, {}).get(profile.fire_resistance, tbl.get(key, {}).get("一级", {}))
    special = tbl.get("special", {})

    # 判断是否需要4h防火墙（GB 50016-2014 第3.2.9条）
    is_workshop = profile.industrial_subtype == "workshop"
    is_warehouse = profile.industrial_subtype == "warehouse"
    needs_4h_firewall = (
        (is_workshop and profile.fire_risk in ["甲", "乙"]) or
        (is_warehouse and profile.fire_risk in ["甲", "乙", "丙"])
    )

    items = []
    for component, value in data.items():
        if component not in ["citation"]:
            # 当需要4h防火墙时，替换通用3h防火墙条目
            if component == "防火墙" and needs_4h_firewall:
                items.append({"构件": "防火墙（甲、乙类厂房和甲、乙、丙类仓库内）",
                              "耐火极限": special.get("甲乙类厂房和甲乙丙类仓库防火墙", "≥ 4.00h"),
                              "依据": special.get("citation_special", "GB 50016-2014 第3.2.9条")})
            else:
                items.append({"构件": component, "耐火极限": value, "依据": data.get("citation", "GB 50016-2014")})

    if profile.has_garage:
        items.append({"构件": "车库与其他部位分隔", "耐火极限": "防火墙 + ≥ 2.00h 不燃性楼板", "依据": "GB 50067-2014 第5.1.6条"})

    return {"fire_resistance_items": items}


# ─── 3.4 疏散参数 ───

def calc_evacuation_detail(profile, lookup) -> Dict[str, Any]:
    tbl = lookup.get("evacuation_params", {})
    h = profile.height_m
    bt = profile.building_type

    params = {}
    if bt == "civil" and profile.civil_subtype == "residential":
        data = tbl.get("civil_residential", {})
        if h > 54:
            params = data.get("H>54m", {})
        elif h > 33:
            params = data.get("33m<H≤54m", {})
        elif h > 27:
            params = data.get("27m<H≤33m", {})
        elif h > 21:
            params = data.get("21m<H≤27m", {})
        else:
            params = data.get("H≤21m", {})
    elif bt == "civil":
        data = tbl.get("civil_public", {})
        if "一类高层" in profile.building_class:
            params = data.get("一类高层", {})
        elif "二类高层" in profile.building_class:
            if h > 32:
                params = data.get("二类高层_H>32m", {})
            else:
                params = data.get("二类高层_H<=32m", {})
        else:
            params = data.get("单多层", {})
    elif bt == "industrial" and profile.industrial_subtype == "workshop":
        params = tbl.get("industrial_workshop", {})
    elif bt == "industrial":
        params = tbl.get("industrial_warehouse", {})

    # 构建疏散参数列表
    items = []
    label_map = {
        "每单元安全出口": "每单元/每防火分区安全出口",
        "每防火分区安全出口": "每防火分区安全出口",
        "楼梯间形式": "疏散楼梯间形式",
        "疏散距离_两出口间": "疏散距离（两安全出口间）",
        "疏散距离_袋形走道": "疏散距离（袋形走道）",
        "疏散宽度": "疏散宽度指标",
        "首层疏散外门宽度": "首层疏散外门宽度",
        "疏散距离": "疏散距离",
    }
    for k, v in params.items():
        if k != "citation":
            items.append({"参数": label_map.get(k, k), "要求": v, "依据": params.get("citation", "")})

    # 全部设自喷时疏散距离可×1.25（GB 50016 表5.5.17注3）
    sprinkler_coverage = getattr(profile, 'sprinkler_coverage', '')
    if sprinkler_coverage == "全部设置" and profile.building_type == "civil":
        items.append({"参数": "疏散距离调整", "要求": "全部设自喷 → 疏散距离×1.25（GB 50016 表5.5.17注3）",
                      "依据": "GB 50016-2014 表5.5.17注3"})

    # 敞开式外廊 → 疏散距离+5m（GB 50016 表5.5.17注1）
    if getattr(profile, 'has_open_corridor', False):
        items.append({"参数": "疏散距离调整", "要求": "敞开式外廊 → 疏散距离+5m（GB 50016 表5.5.17注1）",
                      "依据": "GB 50016-2014 表5.5.17注1"})

    return {"evacuation_items": items}


# ─── 3.5 防火门等级 ───

def calc_fire_door_rating(profile, lookup) -> Dict[str, Any]:
    tbl = lookup.get("fire_door_rating", {})
    items = []

    for grade, doors in tbl.items():
        if not isinstance(doors, dict):
            continue
        for location, rating in doors.items():
            if location == "citation":
                continue
            # 过滤不适用的建筑类型条目
            if profile.building_type == "civil":
                if profile.civil_subtype == "residential" and "公建" in location:
                    continue
                if profile.civil_subtype == "public" and "住宅" in location:
                    continue
            items.append({"设置部位": location, "防火门等级": rating.split("|")[0] if "|" in str(rating) else str(rating), "依据": doors.get("citation", "")})

    return {"fire_door_items": items}


# ─── 3.6 自动喷水灭火系统参数 ───

def calc_sprinkler_params(profile, conclusions, lookup) -> Dict[str, Any]:
    sp = lookup.get("sprinkler_params", {})
    params = {}
    notes = []

    # 根据用户选择的自喷覆盖范围判断
    sprinkler_coverage = getattr(profile, 'sprinkler_coverage', '')
    has = (sprinkler_coverage in ("全部设置", "局部设置"))
    if not has:
        has = any("喷水灭火" in c.get("conclusion", "") and c["conclusion_type"] == "required" for c in conclusions)
    if profile.has_garage and profile.garage_parking_spots > 10:
        has = True
    if getattr(profile, 'has_sprinkler_design', False):
        has = True

    if not has:
        return {"sprinkler_params": {"note": "本建筑无需设置自动喷水灭火系统"}, "sprinkler_notes": []}

    h = profile.height_m

    if profile.has_garage:
        params = sp.get("汽车库", {})
        notes.append("汽车库喷头布置: 停车位上方或侧上方布置，机械车库按载车板分层设喷头并设集热板")
    elif profile.building_type == "industrial":
        if profile.industrial_subtype == "warehouse":
            # 仓库喷淋参数
            wh = sp.get("仓库", {})
            fr = profile.fire_risk
            if fr in ["甲", "乙"]:
                params = wh.get("仓库危险级II级", {})
                notes.append("甲/乙类仓库: 按仓库危险级II级设计")
            elif fr == "丙":
                params = wh.get("仓库危险级II级", {})
            else:
                params = wh.get("仓库危险级I级", {})
            # 高大空间判定
            if h > 12:
                hs = sp.get("高大空间", {}).get("仓库_净高>12m", {})
                params["warning"] = hs.get("note", "净空高度超过闭式系统应用范围")
                notes.append("⚠️ 仓库净高>12m: 应采用雨淋系统或固定消防炮/自动跟踪定位射流灭火系统")
        else:
            # 厂房喷淋参数
            ws = sp.get("工业建筑-厂房", {})
            fr = profile.fire_risk
            if fr in ["甲", "乙"]:
                params = ws.get("严重危险级I级", {})
            elif fr == "丙":
                params = ws.get("中危险级II级", {})
            else:
                params = ws.get("中危险级I级", {})
            if h > 12:
                notes.append("⚠️ 厂房净高>12m: 需评估是否采用雨淋系统或大空间智能灭火装置")
    else:
        # 民用建筑
        params = sp.get("民用建筑", {}).get("中危险级II级", {})
        if h > 12:
            hs = sp.get("高大空间", {}).get("民用_净高12-18m", {})
            params.update(hs)
            if h > 18:
                hs2 = sp.get("高大空间", {}).get("民用_净高>18m", {})
                params["warning"] = hs2.get("note", "")
                notes.append("⚠️ 民用净高>18m: 应采用雨淋系统或固定消防炮/自动跟踪定位射流灭火系统")

    return {"sprinkler_params": params, "sprinkler_notes": notes}


# ─── 3.7 防排烟参数 ───

def calc_smoke_exhaust(profile, conclusions, lookup) -> Dict[str, Any]:
    se = lookup.get("smoke_exhaust", {})
    params = {}
    steps = []
    notes = []

    has_dp = any("排烟" in c.get("conclusion", "") for c in conclusions)
    if profile.has_garage:
        has_dp = True

    if not has_dp:
        return {"smoke_exhaust_params": {"note": "本建筑无需设置排烟设施"}, "smoke_exhaust_steps": []}

    # 防烟分区
    zone = se.get("防烟分区", {})
    steps.append(f"防烟分区最大面积: {zone.get('最大面积_3m<净高≤6m', '1000 m²')}（净高≤6m）")

    if profile.has_garage:
        params = se.get("汽车库", {})
        steps.append("汽车库排烟: 每个防烟分区 ≤ 2000 m²，排烟口距最远点 ≤ 30m")
        steps.append(f"补风量: {params.get('补风量', '≥ 排烟量50%')}")
    elif profile.building_type == "industrial":
        ws = se.get("厂房_丙类", {})
        params.update(ws)
        steps.append("厂房排烟: 自然排烟开窗面积 ≥ 地面面积2%，或设机械排烟")
    else:
        civ = se.get("民用建筑", {})
        params.update(civ)
        steps.append("民用建筑排烟: 自然排烟开窗面积 ≥ 地面面积2%，或机械排烟")
        steps.append(f"补风量: {civ.get('补风量', '≥ 排烟量50%')}")

    # 过滤不适用的建筑类型条目
    if profile.building_type == "civil":
        if profile.civil_subtype == "residential":
            params = {k: v for k, v in params.items() if "公建" not in k}
        else:
            params = {k: v for k, v in params.items() if "住宅" not in k}

    return {"smoke_exhaust_params": params, "smoke_exhaust_steps": steps, "smoke_exhaust_notes": notes}


# ─── 3.8 灭火器配置 ───

def calc_extinguisher(profile, conclusions, lookup) -> Dict[str, Any]:
    ec = lookup.get("extinguisher_config", {})
    params = {}
    steps = []

    if profile.has_garage:
        params = ec.get("汽车库", {})
        steps.append("汽车库灭火器: 中危险级（A类+B类），ABC干粉灭火器 MF/ABC4 或 MF/ABC5，最大保护距离 20m")
        return {"extinguisher_params": params, "extinguisher_steps": steps}

    if profile.building_type == "civil" and profile.civil_subtype == "residential":
        params = ec.get("A类火灾", {}).get("轻危险级", {})
        steps.append("住宅灭火器: 轻危险级，ABC干粉灭火器 MF/ABC2 或 MF/ABC3，最大保护距离 25m")
    elif profile.building_type == "civil":
        params = ec.get("A类火灾", {}).get("中危险级", {})
        steps.append("公共建筑灭火器: 中危险级，ABC干粉灭火器 MF/ABC4，最大保护距离 20m")
    else:
        fr = profile.fire_risk
        if fr in ["甲", "乙"]:
            params = ec.get("A类火灾", {}).get("严重危险级", {})
            steps.append("甲/乙类场所灭火器: 严重危险级，ABC干粉灭火器 MF/ABC5/8，最大保护距离 15m")
        elif fr == "丙":
            params = ec.get("A类火灾", {}).get("中危险级", {})
            steps.append("丙类场所灭火器: 中危险级，ABC干粉灭火器 MF/ABC4，最大保护距离 20m")
        else:
            params = ec.get("A类火灾", {}).get("轻危险级", {})
            steps.append("丁/戊类场所灭火器: 轻危险级，ABC干粉灭火器 MF/ABC2/3，最大保护距离 25m")

    # 计算公式
    formula = ec.get("calculation_formula", "")
    steps.append(f"计算方式: {formula}")
    steps.append(f"修正系数 K: 见 GB 50140-2005 表7.3.2")

    return {"extinguisher_params": params, "extinguisher_steps": steps}


# ─── 3.9 特殊灭火系统判定 ───

def calc_special_systems(profile, conclusions, lookup) -> Dict[str, Any]:
    ss = lookup.get("special_systems", {})
    items = []
    h = profile.height_m
    bt = profile.building_type
    ch = getattr(profile, 'clear_height_m', 0.0)  # 净空高度

    # 雨淋系统 — 使用净空高度而非建筑高度
    needs_deluge = False
    deluge_reason = ""
    if ch > 0:
        if ch > 12 and bt == "industrial":
            needs_deluge = True
            deluge_reason = f"净空高度 {ch}m > 12m（工业），超过闭式系统应用范围"
        elif ch > 18 and bt == "civil":
            needs_deluge = True
            deluge_reason = f"净空高度 {ch}m > 18m（民用），超过闭式系统应用范围"
        elif profile.fire_risk == "甲" and bt == "industrial":
            needs_deluge = True
            deluge_reason = "甲类场所，火灾水平蔓延速度快"
    else:
        deluge_reason = "未填写净空高度，无法判定（默认不触发）"
    items.append({"系统": "雨淋系统", "是否需要": "是" if needs_deluge else "否（待确认）" if ch == 0 else "否", "判定依据": deluge_reason, "依据": ss.get("雨淋系统", {}).get("citation", "")})

    # 水幕系统
    items.append({"系统": "水幕系统", "是否需要": "否（默认）", "判定依据": "未使用防火卷帘替代防火墙或需开口防火分隔", "依据": ss.get("水幕系统", {}).get("citation", "")})

    # 气体灭火系统 — 根据用户画像中的设备用房决定
    needs_gas = getattr(profile, 'has_equipment_room', False)
    gas_reason = ""
    if needs_gas:
        room_types = getattr(profile, 'equipment_room_types', [])
        gas_reason = f"设有重要设备用房：{', '.join(room_types)}，需设气体灭火系统保护"
    else:
        gas_reason = "未指定重要设备用房（变配电室/发电机房/通信机房等），默认不触发"
    items.append({"系统": "气体灭火系统", "是否需要": "是" if needs_gas else "否（默认）", "判定依据": gas_reason, "依据": ss.get("气体灭火系统", {}).get("citation", "")})

    # 干粉灭火系统
    items.append({"系统": "干粉灭火系统", "是否需要": "否（默认）", "判定依据": "无水源且可燃液体/气体场所条件未触发", "依据": ss.get("干粉灭火系统", {}).get("citation", "")})

    # 泡沫灭火系统
    items.append({"系统": "泡沫灭火系统", "是否需要": "否（默认）", "判定依据": "无甲/乙/丙类液体储罐区", "依据": ss.get("泡沫灭火系统", {}).get("citation", "")})

    return {"special_systems_items": items}