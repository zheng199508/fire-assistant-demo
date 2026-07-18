"""
report_builder.py v4 — 报告生成器（深度修复版）

改进:
- 结论摘要重构：建筑分类/设施配置分离
- 推理过程分组展示 + 规范原文引用
- 触发条件增强说明
- 设施配置清单含设计参数
- 防火分区增加地下室独立行
- 新增地下室消防章节
"""

import json, os
from typing import Dict, Any, List


def _load_norm_texts() -> dict:
    """加载规范原文查找表"""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, "rulesets", "2026-07-民建全分支-v2", "lookup_tables", "norm_texts.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("texts", {})
    except Exception:
        return {}


def _load_ruleset_meta() -> dict:
    """Load the single authoritative standards registry for report output."""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, "rulesets", "2026-07-民建全分支-v2", "meta.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _is_violation(profile) -> bool:
    """判断建筑是否违规（甲类高层/超层数等）"""
    return "违规" in getattr(profile, 'building_class', '')

def build_report(profile, conclusions, calculation, inference_log) -> str:
    lines = []
    norm_texts = _load_norm_texts()
    ruleset_meta = _load_ruleset_meta()
    lines.append("# 消防设施配置方案报告")
    lines.append("")
    ruleset_version = ruleset_meta.get("standards_version", "规则包版本未知")
    lines.append(f"> 规范版本：{ruleset_version} | 生成时间：自动生成")
    lines.append("")
    readiness = ruleset_meta.get("release_readiness", {})
    if not readiness.get("public_release_ready", False):
        lines.append("> ⚠️ **规则包状态：专业审核中，尚未达到公开发布质量门槛。**")
        lines.append("> 自动化测试仅证明程序按现有规则稳定执行，不代表规则语义已逐条通过规范复核。")
        lines.append("")

    # ── 违规警告横幅 ──
    violation = _is_violation(profile)
    if violation:
        lines.append("> ⛔ **建筑方案违规警告**")
        lines.append(f"> {profile.building_class}")
        lines.append("> 以下消防设施配置基于合规假设（按多层建筑取值）计算，仅供参考。")
        lines.append("> **实际设计需先调整建筑方案至合规范围（降低高度/层数，或调整火灾危险性类别）。**")
        lines.append("")

    # ── 结论摘要（重构）──
    lines.append("## 结论摘要")
    lines.append("")

    # 区域1: 建筑定性
    lines.append("### 建筑定性")
    lines.append("")
    lines.append("| 项目 | 判定 |")
    lines.append("|------|------|")
    bc = profile.building_class
    fr = profile.fire_resistance
    if violation:
        lines.append(f"| 建筑分类 | ⛔ **{bc}** |")
    else:
        lines.append(f"| 建筑分类 | **{bc}** |")
    lines.append(f"| 耐火等级 | **{fr}** |")
    lines.append(f"| 建筑高度 | {profile.height_m} m · 地上 {profile.floors_above} 层 |")
    if profile.fire_risk:
        lines.append(f"| 火灾危险性 | {profile.fire_risk}类 |")
    if profile.clear_height_m > 0:
        lines.append(f"| 净空高度 | {profile.clear_height_m} m |")
    if getattr(profile, 'is_medical', False):
        inpatient = "含住院部" if getattr(profile, 'is_inpatient', False) else "门诊/医技（不含住院）"
        important = " · 重要公共建筑" if getattr(profile, 'is_important_public_building', False) else ""
        lines.append(f"| 医疗建筑类型 | {inpatient}{important} |")
        if getattr(profile, 'corridor_layout', ''):
            lines.append(f"| 走道布房形式 | {profile.corridor_layout} |")
        if getattr(profile, 'has_special_medical_zone', False):
            lines.append(f"| 特殊医疗区域 | 手术室/ICU |")
    if profile.has_basement:
        lines.append(f"| 地下室 | {profile.floors_below} 层" + (f" · {profile.basement_function}" if profile.basement_function else "") + " |")
    if profile.has_garage:
        lines.append(f"| 地下车库 | {profile.garage_class}类 · {profile.garage_parking_spots} 辆 |")
    lines.append("")

    # 区域2: 核心设施配置（按系统分组，只展示 priority >= 85）
    lines.append("### 核心设施配置")
    lines.append("")
    # 过滤并分组
    core_conclusions = [c for c in conclusions if c.get("priority", 0) >= 85
                       and c["conclusion_type"] in ("required", "prohibited", "recommended")
                       and "建筑分类" not in c.get("scope", "")
                       and "civil.public" not in c.get("scope", "")
                       and "civil.residential" not in c.get("scope", "")
                       and "二类高层" not in c.get("conclusion", "")
                       and "一类高层" not in c.get("conclusion", "")
                       and "耐火等级" not in c.get("conclusion", "")]
    sys_map = _build_sys_map(core_conclusions)
    for sys_name, items in sys_map.items():
        if not items:
            continue
        icons = {"required": "✅", "prohibited": "❌", "recommended": "💡"}
        # 去重显示
        seen = set()
        for c in items:
            label = c["conclusion"][:60]
            if label in seen:
                continue
            seen.add(label)
            icon = icons.get(c["conclusion_type"], "")
            lines.append(f"| {sys_name} | {icon} {label} |")
    lines.append("")

    # 区域3: 关键风险
    prohibited = [c for c in conclusions if c["conclusion_type"] == "prohibited"
                  and "带电扑救" not in c.get("conclusion", "")]
    if prohibited:
        lines.append("### ⚠️ 禁止事项")
        lines.append("")
        for c in prohibited:
            lines.append(f"- ❌ {c['conclusion']}（*{c['citation']}*）")
        lines.append("")

    # ── 第1章 工程概况 ──
    lines.append("## 1. 工程概况")
    lines.append("")
    lines.append("### 1.1 建筑基本信息")
    lines.append("")
    lines.append("| 参数 | 取值 |")
    lines.append("|------|------|")
    lines.append(f"| 建筑类型 | {_fmt_type(profile)} |")
    lines.append(f"| 建筑分类 | {profile.building_class} |")
    lines.append(f"| 建筑高度 | {profile.height_m} m |")
    lines.append(f"| 地上层数 | {profile.floors_above} |")
    if profile.clear_height_m > 0:
        lines.append(f"| 净空高度 | {profile.clear_height_m} m |")
    lines.append(f"| 耐火等级 | {profile.fire_resistance} |")
    if profile.fire_risk:
        lines.append(f"| 火灾危险性 | {profile.fire_risk}类 |")
    if profile.building_type == "industrial" and profile.substances:
        lines.append(f"| 生产/储存物品 | {', '.join(profile.substances)} |")
        if getattr(profile, 'substance_risks', []):
            lines.append(f"| 危险性分类明细 | {'; '.join(profile.substance_risks)} |")
        if getattr(profile, 'auto_classified_risk', ''):
            lines.append(f"| 自动判定结果 | {profile.auto_classified_risk}类 |")
        if getattr(profile, 'paint_risk_override', ''):
            lines.append(f"| 油漆工段判定 | {profile.paint_risk_override} |")
    if getattr(profile, 'is_entertainment_venue', False):
        lines.append(f"| 歌舞娱乐场所 | {getattr(profile, 'entertainment_floor', '')} · 每厅≤{getattr(profile, 'entertainment_room_area', 0):.0f}㎡ |")
    if getattr(profile, 'is_kindergarten', False):
        lines.append(f"| 幼儿园/托儿所 | {getattr(profile, 'kindergarten_floor', '')} · GB 50016 第5.4.4条 |")
    if getattr(profile, 'has_open_corridor', False):
        lines.append(f"| 敞开式外廊 | 是 → 疏散距离+5m |")
    if profile.has_basement:
        lines.append(f"| 地下室 | {profile.floors_below} 层"
                     f"{' · ' + profile.basement_function if profile.basement_function else ''} |")
    if profile.has_garage:
        lines.append(f"| 地下车库 | 停车 {profile.garage_parking_spots} 辆 / {profile.garage_total_area} m² / {profile.garage_class}类 |")
    if getattr(profile, 'is_medical', False):
        inpatient = "含住院部" if getattr(profile, 'is_inpatient', False) else "门诊/医技（不含住院）"
        important = " · 重要公共建筑" if getattr(profile, 'is_important_public_building', False) else ""
        lines.append(f"| 医疗建筑类型 | {inpatient}{important} |")
        if getattr(profile, 'corridor_layout', ''):
            lines.append(f"| 走道布房形式 | {profile.corridor_layout} |")
        if getattr(profile, 'has_special_medical_zone', False):
            lines.append(f"| 特殊医疗区域 | 手术室/ICU |")
    if getattr(profile, 'has_podium', False):
        sep = "防火墙分隔" if getattr(profile, 'podium_separated_by_firewall', False) else "无防火墙分隔"
        lines.append(f"| 裙房 | 是 · {sep} |")
    if getattr(profile, 'has_commercial_outlet', False):
        lines.append(f"| 商业服务网点 | 是 · 最大单元{getattr(profile, 'commercial_outlet_unit_area', 0):.0f}㎡ |")
    if getattr(profile, 'is_mixed_use', False):
        sep = "防火墙分隔" if getattr(profile, 'is_mixed_separated', False) else "未分隔"
        lines.append(f"| 住宅与公建合建 | 是 · {sep} |")
    lines.append(f"| 两路市政供水 | {'是' if profile.dual_municipal_water else '否'} |")
    if profile.has_sprinkler_design:
        coverage = getattr(profile, 'sprinkler_coverage', '')
        coverage_label = {"全部设置": "全部设置", "局部设置": "局部设置"}.get(coverage, "已设计/拟设置")
        lines.append(f"| 自喷设计状态 | {coverage_label} |")
    # 设备用房
    if getattr(profile, 'has_boiler_room', False):
        loc = getattr(profile, 'boiler_room_location', '')
        lines.append(f"| 锅炉房 | {loc if loc else '是'} · GB 50016 第5.4.12条 |")
    if getattr(profile, 'has_generator_room', False):
        loc = getattr(profile, 'generator_room_location', '')
        lines.append(f"| 发电机房 | {loc if loc else '是'} · GB 50016 第5.4.13条 |")
    if getattr(profile, 'has_fire_control_room', False):
        loc = getattr(profile, 'fire_control_room_location', '')
        lines.append(f"| 消防控制室 | {loc if loc else '是'} · GB 50016 第8.1.7条 |")
    if getattr(profile, 'has_fire_pump_room', False):
        loc = getattr(profile, 'fire_pump_room_location', '')
        lines.append(f"| 消防水泵房 | {loc if loc else '是'} · GB 50974 第5.5.12条 |")
    lines.append("")

    # 建筑分类判定依据
    if profile.building_type == "civil":
        lines.append("### 1.2 建筑分类判定依据")
        lines.append("")
        h = profile.height_m
        bc = profile.building_class
        if "一类高层" in bc:
            if h > 50:
                lines.append(f"- **触发路径1**：建筑高度 {h}m > 50m → 一类高层公共建筑（GB 50016 表5.1.1）")
            elif h > 24:
                reasons = []
                if getattr(profile, 'is_medical', False):
                    reasons.append(f"医疗建筑（H={h}m > 24m）→ 一类高层公共建筑（GB 50016 表5.1.1）")
                if getattr(profile, 'is_important_public_building', False):
                    reasons.append("重要公共建筑 → 一类高层公共建筑（GB 50016 表5.1.1）")
                if getattr(profile, 'is_elderly_facility', False):
                    reasons.append("独立老年人照料设施 → 一类高层公共建筑（GB 50016 表5.1.1）")
                if not reasons:
                    reasons.append(f"H={h}m > 24m + 任一楼层>1000㎡ + 特定功能 → 一类高层公共建筑（GB 50016 表5.1.1路径2）")
                for r in reasons:
                    lines.append(f"- **触发**：{r}")
        elif "二类高层" in bc:
            lines.append(f"- H={h}m，24m < H ≤ 50m，不满足一类高层条件 → 二类高层公共建筑（GB 50016 表5.1.1）")
        else:
            lines.append(f"- H={h}m ≤ 24m → 单、多层公共建筑（GB 50016 表5.1.1）")
        # 裙房影响
        if getattr(profile, 'has_podium', False):
            if getattr(profile, 'podium_separated_by_firewall', False):
                lines.append("- **裙房**：防火墙分隔 → 裙房防火分区按单多层（2500㎡），疏散楼梯按封闭楼梯间（GB 50016 表5.1.1注3）")
            else:
                lines.append("- **裙房**：无防火墙分隔 → 裙房按高层主体要求（GB 50016 表5.1.1注3）")
        lines.append("")

    # ── 第2章 适用规范 ──
    lines.append("## 2. 适用规范")
    lines.append("")
    lines.append("**规则包登记的国家规范资料及当前覆盖程度**：")
    for std in _standards():
        lines.append(f"- {std}")
    lines.append("")

    # ── 第3章 规范判定推理与设施配置（合并版）──
    lines.append("## 3. 规范判定与设施配置")
    lines.append("")

    # 按系统分组，融合推理过程与配置清单
    sys_map = _build_sys_map(conclusions)
    global_idx = 0
    for sys_name, items in sys_map.items():
        if not items:
            continue
        lines.append(f"### {sys_name}")
        lines.append("")
        for c in items:
            global_idx += 1
            icon = {"required": "✅", "prohibited": "❌", "recommended": "💡", "conditional": "⚠️"}.get(c["conclusion_type"], "")
            lines.append(f"**{global_idx}. {icon} {c['conclusion']}**")
            lines.append(f"- **依据**：*{c['citation']}*")
            # 触发条件
            condition = c.get("condition_text", c.get("condition", ""))
            if condition:
                lines.append(f"- **触发条件**：{_fmt_trigger(condition, profile)}")
            # 规范原文
            norm_text = norm_texts.get(c.get("citation", ""), "")
            if norm_text:
                lines.append(f"> **规范原文**：{norm_text}")
            # 设计参数
            dp = c.get("design_params", {})
            if dp:
                for k, v in dp.items():
                    lines.append(f"- **{k}**：{v}")
            lines.append("")
    if global_idx == 0:
        lines.append("*无匹配规则（请检查输入参数）*")
    lines.append("")

    # ── 第4章 核心计算数据 ──
    lines.append("## 4. 核心计算数据")
    lines.append("")
    calc = calculation

    # 4.1 消防用水量
    lines.append("### 4.1 消防用水量与水池水箱")
    lines.append("")
    # 条件链展示
    lines.append("**用水量计算链**：")
    lines.append("")
    lines.append("| 系统 | 设计流量 | 延续时间 | 用水量 | 查表依据 |")
    lines.append("|------|---------|---------|--------|---------|")
    outdoor_flow = calc.get('outdoor_flow_Ls', 0)
    indoor_flow = calc.get('indoor_flow_Ls', 0)
    sprinkler_flow = calc.get('sprinkler_flow_Ls', 0)
    duration = calc.get('fire_duration_h', 0)
    outdoor_water = calc.get('outdoor_water_m3', 0)
    indoor_water = calc.get('indoor_water_m3', 0)
    sprinkler_water = calc.get('sprinkler_water_m3', 0)
    total_water = calc.get('total_water_m3', 0)
    
    outdoor_citation = calc.get('outdoor_flow_citation', 'GB 50974-2014 表3.3.2')
    indoor_citation = calc.get('indoor_flow_citation', 'GB 50974-2014 表3.5.2')
    
    lines.append(f"| 室外消火栓 | {outdoor_flow} L/s | {duration} h | {outdoor_water:.1f} m³ | {outdoor_citation} |")
    lines.append(f"| 室内消火栓 | {indoor_flow} L/s | {duration} h | {indoor_water:.1f} m³ | {indoor_citation} |")
    if sprinkler_flow > 0:
        lines.append(f"| 自动喷水灭火 | {sprinkler_flow} L/s | 1.0 h | {sprinkler_water:.1f} m³ | GB 50084-2017 |")
    lines.append(f"| **合计** | | | **{total_water:.1f} m³** | |")
    lines.append("")
    lines.append(f"> **计算公式**：V = 3.6 × ({outdoor_flow}×{duration} + {indoor_flow}×{duration}" +
                 (f" + {sprinkler_flow}×1.0" if sprinkler_flow > 0 else "") +
                 f") = {total_water:.1f} m³")
    lines.append("")
    
    # 水池容积说明
    lines.append("| 参数 | 数值 | 说明 |")
    lines.append("|------|------|------|")
    lines.append(f"| 高位消防水箱有效容积 | **{calc.get('water_tank_m3', 0)} m³** | GB 50974 第5.2.1条 |")
    if calc.get('needs_pool'):
        lines.append(f"| 消防水池有效容积 | **{calc.get('pool_volume_m3', 0):.1f} m³** | " +
                     (f"非两路可靠供水 → 计入全部消防用水量" if not profile.dual_municipal_water else
                      f"两路供水但市政流量不足 → 补足差额") + " |")
    lines.append("")
    
    # 关键判定说明
    if profile.dual_municipal_water:
        if profile.municipal_outdoor_flow_ok:
            lines.append(f"- ✅ 两路供水且市政可保证室外流量 → 水池仅需储存**室内消防用水量**（{indoor_water:.1f} m³ + 喷淋{sprinkler_water:.1f} m³）")
        else:
            lines.append(f"- ⚠️ 两路供水但市政流量不足室外{outdoor_flow}L/s → 水池需储存**室内+室外差额**")
    else:
        lines.append(f"- ❌ 单路供水 → 水池需储存**全部消防用水量**（{total_water:.1f} m³）")
    lines.append("")

    for step in calc.get("calculation_steps", []):
        lines.append(f"- {step}")
    lines.append("")

    # 4.2 防火分区面积校验（含地下室）
    lines.append("### 4.2 防火分区面积校验")
    lines.append("")
    if calc.get("is_violation_premise"):
        lines.append("> ⚠️ **建筑方案违规**，以下防火分区面积基于合规假设（按多层建筑取值）计算，仅供参考。")
        lines.append("> 实际设计需先调整建筑方案至合规范围。")
        lines.append("")
    cl = calc.get("compartment_limit", 0)
    clp = calc.get("compartment_limit_with_sprinkler", 0)
    if cl:
        lines.append("#### 地上部分")
        lines.append("")
        # 条件链展示
        lines.append("**防火分区面积计算链**：")
        lines.append("")
        lines.append("| 步骤 | 修正项 | 数值 | 依据 |")
        lines.append("|------|--------|------|------|")
        lines.append(f"| ① 基础值 | 按建筑分类/耐火等级查表 | {cl} m² | {calc.get('compartment_base_citation', 'GB 50016 表5.3.1/表3.3.1')} |")
        if clp != cl:
            sprinkler_cov = getattr(profile, 'sprinkler_coverage', '')
            if sprinkler_cov == "全部设置":
                lines.append(f"| ② 自喷修正 | 全部设自喷 → ×2.0 | {clp} m² | GB 50016 表5.3.1注1/第3.3.3条 |")
            elif sprinkler_cov == "局部设置":
                lines.append(f"| ② 自喷修正 | 局部设自喷 → 仅局部×2.0，整体限制不变 | {clp} m² | GB 50016 第3.3.3条 |")
            elif getattr(profile, 'has_sprinkler_design', False):
                # 向后兼容：has_sprinkler_design=True但未设置coverage
                lines.append(f"| ② 自喷修正 | 设自喷 → ×2.0 | {clp} m² | GB 50016 表5.3.1注1/第3.3.3条 |")
            else:
                lines.append(f"| ② 未设自喷 | 无面积翻倍 | {clp} m² | — |")
        # 商店放宽
        if getattr(profile, 'is_shop_qualifies_relax', False):
            lines.append(f"| ③ 商店放宽 | 满足GB 50016第5.3.4条四条件 | 4000/10000 m² | GB 50016 第5.3.4条 |")
        lines.append(f"| **最终值** | 防火分区最大允许面积 | **{clp} m²** | — |")
        lines.append("")
        
        # 判定结果
        actual_area = calc.get('compartment_actual_area', 0)
        lines.append(f"| 单层建筑面积 | {actual_area:.0f} m² |")
        lines.append(f"| 防火分区最大允许面积 | {clp} m² |")
        if calc.get('compartment_is_exceeded'):
            lines.append(f"| 是否超限 | ⚠️ **是（超限 {actual_area - clp:.0f} m²）** |")
        else:
            margin = (1 - actual_area / clp) * 100 if clp > 0 else 0
            if margin < 10:
                lines.append(f"| 是否超限 | ✅ 否（但接近阈值，安全余量仅 {margin:.1f}%） ⚠️ |")
            elif margin < 25:
                lines.append(f"| 是否超限 | ✅ 否（安全余量 {margin:.1f}%） |")
            else:
                lines.append(f"| 是否超限 | ✅ 否（安全余量 {margin:.1f}%） |")
        if calc.get('compartment_exceed_remedy'):
            lines.append(f"| 超限补救措施 | {calc.get('compartment_exceed_remedy')} |")
        for w in calc.get("compartment_warnings", []):
            lines.append(f"| ⚠️ | {w} |")
        lines.append("")

    # 裙房防火分区
    podium_limit = calc.get("podium_compartment_limit", 0)
    if podium_limit > 0:
        lines.append("#### 裙房部分")
        lines.append("")
        if calc.get("has_podium_with_firewall"):
            lines.append(f"| 裙房防火分区最大允许面积 | **{podium_limit} m²** |")
            lines.append(f"| 判定依据 | 防火墙分隔 → 裙房按单多层建筑（GB 50016 表5.1.1注3） |")
        else:
            lines.append(f"| 裙房防火分区最大允许面积 | **{podium_limit} m²** |")
            lines.append(f"| 判定依据 | 无防火墙分隔 → 裙房按高层主体要求 |")
        lines.append("")

    # 地下室防火分区
    bcl = calc.get("compartment_limit_basement", 0)
    bclp = calc.get("compartment_limit_basement_with_sprinkler", 0)
    if bcl and profile.has_basement:
        lines.append("#### 地下室部分")
        lines.append("")
        lines.append("| 参数 | 数值 |")
        lines.append("|------|------|")
        lines.append(f"| 地下室防火分区最大允许面积（无自喷） | {bcl} m² |")
        if bclp != bcl:
            lines.append(f"| 地下室防火分区最大允许面积（设自喷后） | {bclp} m² |")
        lines.append("")

    for step in calc.get("compartment_steps", []):
        lines.append(f"- {step}")
    lines.append("")

    # 4.3 构件耐火极限明细
    items = calc.get("fire_resistance_items", [])
    if items:
        lines.append("### 4.3 构件耐火极限明细")
        lines.append("")
        lines.append("| 构件名称 | 耐火极限要求 | 依据 |")
        lines.append("|----------|-------------|------|")
        for item in items:
            lines.append(f"| {item.get('构件', '')} | {item.get('耐火极限', '')} | {item.get('依据', '')} |")
        lines.append("")

    # 4.4 疏散设计参数
    ev_items = calc.get("evacuation_items", [])
    if ev_items:
        lines.append("### 4.4 疏散设计参数")
        lines.append("")
        lines.append("| 参数 | 要求 | 依据 |")
        lines.append("|------|------|------|")
        for item in ev_items:
            lines.append(f"| {item.get('参数', '')} | {item.get('要求', '')} | {item.get('依据', '')} |")
        lines.append("")

    # 4.5 防火门设置要求
    fd_items = calc.get("fire_door_items", [])
    if fd_items:
        lines.append("### 4.5 防火门设置要求")
        lines.append("")
        lines.append("| 设置部位 | 防火门等级 | 依据 |")
        lines.append("|----------|-----------|------|")
        for item in fd_items:
            lines.append(f"| {item.get('设置部位', '')} | {item.get('防火门等级', '')} | {item.get('依据', '')} |")
        lines.append("")

    # 4.6 喷淋参数
    sp = calc.get("sprinkler_params", {})
    if sp and "note" not in sp:
        lines.append("### 4.6 自动喷水灭火系统设计参数")
        lines.append("")
        lines.append("| 参数 | 取值 |")
        lines.append("|------|------|")
        # 中英文参数翻译映射
        sp_label_map = {
            "spray_density": "喷水强度",
            "coverage_area": "作用面积",
            "sprinkler_type": "喷头类型",
            "k_factor": "流量系数K",
            "max_spacing": "最大布置间距",
            "min_pressure": "最小工作压力",
            "response_type": "响应类型",
            "applicable_env": "适用环境",
            "system_type": "系统类型",
            "filling_time": "充水时间",
            "notes": "备注",
            "warning": "⚠️ 警告",
        }
        for k, v in sp.items():
            if k != "warning":
                label = sp_label_map.get(k, k)
                lines.append(f"| {label} | {v} |")
        if sp.get("warning"):
            lines.append(f"| ⚠️ 警告 | {sp['warning']} |")
        for note in calc.get("sprinkler_notes", []):
            lines.append(f"- {note}")
        lines.append("")

    # 4.7 排烟参数
    se = calc.get("smoke_exhaust_params", {})
    if se and "note" not in se:
        lines.append("### 4.7 防排烟设计参数")
        lines.append("")
        for k, v in se.items():
            if k != "citation":
                lines.append(f"- **{k}**：{v}")
        for step in calc.get("smoke_exhaust_steps", []):
            lines.append(f"- {step}")
        lines.append("")

    # 4.8 灭火器配置
    ex = calc.get("extinguisher_params", {})
    if ex:
        lines.append("### 4.8 灭火器配置设计")
        lines.append("")
        lines.append("| 参数 | 取值 |")
        lines.append("|------|------|")
        # 灭火器参数中英文翻译映射
        ex_label_map = {
            "hazard_level": "危险等级",
            "fire_type": "火灾类型",
            "recommended_type": "推荐灭火器类型",
            "min_rating": "单具最小灭火级别",
            "max_distance_m": "最大保护距离(m)",
            "unit_area_per_A": "单位灭火级别保护面积(A类)",
            "unit_area_per_B": "单位灭火级别保护面积(B类)",
            "citation": "依据",
            "K_correction": "修正系数K",
        }
        for k, v in ex.items():
            if k not in ["citation", "K_correction"]:
                label = ex_label_map.get(k, k)
                lines.append(f"| {label} | {v} |")
        for step in calc.get("extinguisher_steps", []):
            lines.append(f"- {step}")
        lines.append("")

    # 4.9 特殊灭火系统判定
    ss_items = calc.get("special_systems_items", [])
    if ss_items:
        lines.append("### 4.9 特殊灭火系统判定")
        lines.append("")
        lines.append("| 系统类型 | 是否需要 | 判定依据 | 依据 |")
        lines.append("|----------|----------|----------|------|")
        for item in ss_items:
            lines.append(f"| {item.get('系统', '')} | {item.get('是否需要', '')} | {item.get('判定依据', '')} | {item.get('依据', '')} |")
        lines.append("")

    # 4.10 地下室消防（如有）
    if profile.has_basement:
        lines.append("### 4.10 地下室消防设计参数")
        lines.append("")
        if profile.has_garage:
            lines.append(f"- 地下车库分类：**{profile.garage_class}类**汽车库")
            lines.append(f"- 停车数量：{profile.garage_parking_spots} 辆")
            lines.append(f"- 车库总面积：{profile.garage_total_area} m²")
            lines.append("- 地下车库应设机械排烟系统，换气次数 ≥ 6次/h")
            lines.append("- 地下车库应设自动喷水灭火系统（停车数>10辆时）")
            lines.append("- 车库防火分区：Ⅰ类 ≤ 2000 m²（设自喷可翻倍至 4000 m²）")
        lines.append("")

    # ── 第6章 潜在合规风险提示 ──
    lines.append("## 6. 潜在合规风险提示")
    lines.append("")
    if violation:
        lines.append(f"### ⛔ 建筑方案违规")
        lines.append(f"**{profile.building_class}**")
        lines.append("")
        lines.append("该建筑方案不符合 GB 50016-2014 强制性条文要求，在未调整建筑方案至合规范围前，")
        lines.append("后续消防设施配置结论不具备设计指导价值。建议：")
        lines.append("- 降低建筑高度至 ≤24m（多层建筑范围）")
        lines.append("- 调整层数至合规范围（甲类一级耐火 ≤2层，二级耐火 ≤1层）")
        lines.append("- 或重新评估火灾危险性类别（如核实生产物品是否确属甲类）")
        lines.append("")
    risks = []
    for w in calc.get("compartment_warnings", []):
        risks.append(w)
    _add_risks(profile, conclusions, risks)
    if risks:
        if not violation:
            lines.append("### 其他风险项")
            lines.append("")
        for r in risks:
            lines.append(f"- ⚠️ {r}")
    else:
        if not violation:
            lines.append("- 暂无明显合规风险")
    lines.append("")

    # ── 第7章 待现场核实 ──
    lines.append("## 7. 待现场核实与深化设计项")
    lines.append("")
    for item in _pending(profile):
        lines.append(f"- [ ] {item}")
    lines.append("")
    lines.append("---")
    lines.append("")
    standards = ruleset_meta.get("standards", [])
    direct_count = sum(
        1 for item in standards
        if isinstance(item, dict) and item.get("decision_rule_citations", 0) > 0
    )
    lines.append("> ⚠️ **免责声明**：本报告为审核中的设计参考 / 初步方案。")
    lines.append(f"> 规则包登记 {len(standards)} 本规范资料，其中 {direct_count} 本存在部分直接规则引用；这不等于完整覆盖这些规范。")
    lines.append("> 以下内容仅供参考，最终以现行规范原文、项目所在地要求及施工图审查意见为准。")
    lines.append("> 不可替代注册消防工程师或设计师签章的正式设计文件。")
    lines.append("")
    lines.append("*本报告由消防设施配置决策助手自动生成，仅供参考。*")

    return "\n".join(lines)


def _build_sys_map(conclusions):
    sys_map = {
        "室外消火栓系统": [],
        "室内消火栓系统": [],
        "自动喷水灭火系统": [],
        "火灾自动报警系统": [],
        "防烟排烟系统": [],
        "消防电梯": [],
        "灭火器": [],
        "消防应急照明与疏散指示": [],
        "消防电源": [],
        "消防控制室": [],
        "防火分隔": [],
        "安全疏散": [],
    }
    for c in conclusions:
        matched = False
        for kw, sys_name in [
            ("室外消火栓", "室外消火栓系统"), ("室内消火栓", "室内消火栓系统"),
            ("喷水灭火", "自动喷水灭火系统"), ("自喷", "自动喷水灭火系统"),
            ("自动报警", "火灾自动报警系统"), ("FAS", "火灾自动报警系统"),
            ("防烟", "防烟排烟系统"), ("排烟", "防烟排烟系统"),
            ("消防电梯", "消防电梯"), ("灭火器", "灭火器"),
            ("疏散照明", "消防应急照明与疏散指示"), ("应急照明", "消防应急照明与疏散指示"),
            ("疏散指示", "消防应急照明与疏散指示"),
            ("负荷", "消防电源"), ("用电", "消防电源"), ("电源", "消防电源"),
            ("控制室", "消防控制室"),
            ("防火分区", "防火分隔"), ("防火墙", "防火分隔"),
            ("安全出口", "安全疏散"), ("疏散", "安全疏散"), ("楼梯", "安全疏散"),
        ]:
            if kw in c.get("conclusion", "") or kw in c.get("scope", ""):
                sys_map[sys_name].append(c)
                matched = True
                break
        if not matched:
            # 建筑分类/耐火等级相关 → 归入"建筑定性"（不在此展示）
            if "建筑分类" in c.get("scope", "") or "耐火等级" in c.get("conclusion", ""):
                continue
            sys_map.setdefault("其他", []).append(c)
    return sys_map


def _group_by_scope(conclusions, inference_log) -> dict:
    """按 scope 分组结论，用于推理过程分组展示"""
    scope_names = {
        "fire_hydrant": "消火栓系统",
        "sprinkler": "自动喷水灭火系统",
        "fire_alarm": "火灾自动报警系统",
        "smoke_control": "防烟排烟系统",
        "extinguisher": "灭火器配置",
        "lighting": "消防应急照明",
        "power": "消防电源与配电",
        "civil.residential": "住宅建筑专项",
        "civil.public": "公共建筑专项",
        "industrial.workshop": "厂房专项",
        "industrial.warehouse": "仓库专项",
        "garage": "汽车库专项",
    }
    groups = {}
    # 从结论中构建分组
    for c in conclusions:
        scope = c.get("scope", "其他")
        name = scope_names.get(scope, scope)
        if name not in groups:
            groups[name] = []
        groups[name].append(c)
    return groups


def _fmt_trigger(condition, profile):
    """将条件文本和建筑画像结合，生成触发逻辑说明"""
    c = condition
    parts = []
    h = profile.height_m
    area = profile.floor_area_sqm
    vol = profile.building_volume

    # 建筑类型说明
    if profile.building_type == "civil":
        if profile.civil_subtype == "residential":
            parts.append(f"本建筑为住宅，建筑高度 {h}m，地上 {profile.floors_above} 层")
        else:
            type_desc = "公共建筑"
            if getattr(profile, 'is_medical', False):
                inpatient = "含住院部" if getattr(profile, 'is_inpatient', False) else "门诊/医技（不含住院）"
                important = "省级重要公共建筑" if getattr(profile, 'is_important_public_building', False) else "普通医院"
                type_desc = f"医疗建筑（{inpatient}，{important}）"
            elif getattr(profile, 'is_elderly_facility', False):
                type_desc = "老年人照料设施"
            elif getattr(profile, 'is_education', False):
                type_desc = "教育建筑"
            elif getattr(profile, 'is_entertainment', False):
                type_desc = "歌舞娱乐放映游艺场所"
            elif getattr(profile, 'is_shop_exhibition', False):
                type_desc = "商店/展览建筑"
            parts.append(f"本建筑为{type_desc}，建筑高度 {h}m，地上 {profile.floors_above} 层")
    elif profile.building_type == "industrial":
        parts.append(f"本建筑为{'厂房' if profile.industrial_subtype == 'workshop' else '仓库'}，火灾危险性 {profile.fire_risk}类，高度 {h}m")

    if profile.building_class:
        if "违规" in profile.building_class:
            parts.append(f"建筑方案违规（{profile.building_class}）")
        else:
            parts.append(f"建筑分类为 {profile.building_class}")

    # 高度触发条件
    if "H > 50m" in c or "H>50" in c:
        parts.append(f"建筑高度 {h}m > 50m，满足条件")
    elif "H > 24m" in c or "H>24" in c:
        parts.append(f"建筑高度 {h}m > 24m（高层建筑），满足条件")
    if "H > 32m" in c or "H>32" in c:
        parts.append(f"建筑高度 {h}m > 32m，满足条件")
    if "H > 100m" in c or "H>100" in c:
        parts.append(f"建筑高度 {h}m > 100m（超高层），满足条件")
    if "H > 21m" in c or "H>21" in c:
        parts.append(f"建筑高度 {h}m > 21m，满足条件")

    # 面积/体积触发
    if area > 0 and ("建筑面积" in c or "S >" in c):
        parts.append(f"标准层面积 {area:.0f} m²")
    if vol > 0 and ("体积" in c or "V >" in c):
        parts.append(f"建筑体积约 {vol:.0f} m³")

    # 地下室触发
    if "地下室" in c or "地下" in c:
        if profile.has_basement:
            func = f"（{profile.basement_function}）" if profile.basement_function else ""
            parts.append(f"设有 {profile.floors_below} 层地下室{func}，满足条件")

    # 车库触发
    if "汽车库" in c or "全地下车库" in c:
        if profile.has_garage:
            parts.append(f"设有地下汽车库（{profile.garage_class}类，{profile.garage_parking_spots}辆）")
        else:
            parts.append("未设汽车库，不触发车库相关规则")

    # 特殊属性
    if "住院" in c and getattr(profile, 'is_inpatient', False):
        parts.append("含住院部分，满足条件")
    if "中庭" in c and profile.has_large_atrium:
        parts.append("设有中庭，满足条件")
    if "长度>20m疏散走道" in c:
        parts.append(f"疏散走道长度 {profile.corridor_length_m}m > 20m，满足条件")
    if "可燃幕墙" in c and profile.has_combustible_curtain_wall:
        parts.append("设有可燃幕墙")
    if "消防电梯" in c and "一类高层" in profile.building_class:
        parts.append(f"一类高层公共建筑，强制设置消防电梯")

    return "；".join(parts) if parts else condition[:100]


def _standards():
    meta = _load_ruleset_meta()
    standards = meta.get("standards", [])
    result = []
    for standard in standards:
        if isinstance(standard, dict) and standard.get("id") and standard.get("name"):
            role = str(standard.get("role", "覆盖程度未说明"))
            result.append(f"{standard['id']} {standard['name']} — {role}")
    return result or ["规则包未提供可用的规范清单"]


def _short_sys(conclusion: str) -> str:
    return conclusion[:50] if len(conclusion) <= 50 else conclusion[:48] + "…"


def _fmt_type(profile) -> str:
    bt = profile.building_type
    if bt == "civil":
        return "民用建筑 · " + ("住宅" if profile.civil_subtype == "residential" else "公共建筑")
    elif bt == "industrial":
        return f"工业建筑 · {'厂房' if profile.industrial_subtype == 'workshop' else '仓库'} · {profile.fire_risk}类"
    return "未知"


def _add_risks(profile, conclusions, risks):
    h = profile.height_m
    fa = profile.floors_above
    fr = getattr(profile, 'fire_risk', '')
    industrial = profile.building_type == "industrial"
    is_workshop = getattr(profile, 'industrial_subtype', '') == "workshop"
    is_warehouse = getattr(profile, 'industrial_subtype', '') == "warehouse"
    violation = _is_violation(profile)
    
    if h > 54 and profile.civil_subtype == "residential":
        risks.append("一类高层住宅：消防电梯为强制要求（GB 50016 第7.3.1条），实践中易遗漏。")
        risks.append("一类高层住宅每户应设避难房间（GB 50016 第5.5.32条）。")
    if h > 33 and profile.civil_subtype == "residential":
        risks.append(f"H={h}m > 33m，疏散楼梯必须是防烟楼梯间（GB 50016 第5.5.27条）。")
    if profile.has_garage and profile.garage_parking_spots > 10:
        risks.append("地下车库应设自动喷水灭火系统（GB 50067 第7.2.1条），停车数>10辆触发。")
    if fr in ["甲", "乙"] and profile.has_basement:
        risks.append(f"{fr}类场所/仓库不应设置在地下或半地下（GB 50016 第3.3.4条）。")
    if fr == "甲" and is_workshop:
        risks.append("甲类厂房严禁设置办公室、休息室（确需贴邻时，只能用防爆墙+二级耐火+不小于二级耐火等级）。")
        # 层数/高度违规已在building_class中体现，此处仅补充未覆盖的情况
        if not violation:
            if fa > 1 and profile.fire_resistance == "二级":
                risks.append(f"甲类厂房（二级耐火）最多允许1层，当前{fa}层，超出GB 50016 第3.3.1条限制。")
            elif fa > 2 and profile.fire_resistance == "一级":
                risks.append(f"甲类厂房（一级耐火）最多允许2层，当前{fa}层，超出GB 50016 第3.3.1条限制。")
            if h > 24:
                risks.append(f"甲类厂房高度{h}m > 24m，按高度定义属高层厂房，但甲类厂房不允许建设为高层建筑（GB 50016 第3.3.1条）。")
    if fr == "乙" and is_workshop and fa > 6:
        risks.append(f"乙类厂房（一、二级耐火）最多允许6层，当前{fa}层，超出GB 50016 第3.3.1条限制。")
    if fr == "甲" and is_warehouse:
        risks.append("甲类仓库严禁设置在地下或半地下（GB 50016 第3.3.4条）。")
        if not violation and fa > 1:
            risks.append(f"甲类仓库最多允许1层，当前{fa}层，超出GB 50016 表3.3.2限制。")


def _pending(profile) -> list:
    items = []
    if not getattr(profile, 'has_fire_pump_room', False):
        items.append("水泵房具体位置及尺寸（建议在建筑画像中补充）")
    if not profile.water_pool_type:
        items.append("消防水池及高位水箱具体位置")
    items.append("各层消火栓具体点位（需结合平面布置复核保护半径）")
    items.append("防火门等级确认（甲级/乙级/丙级，按各部分规范要求）")
    items.append("电缆井/管道井每层防火封堵具体做法")
    if profile.has_garage:
        items.append("地下车库排烟风机选型及安装位置")
        items.append("车库喷头具体布置（需结合结构梁布置）")
    if profile.building_type == "industrial":
        items.append("厂房/仓库内部防火分隔墙及防火分区确认")
        if profile.fire_risk in ["甲", "乙"]:
            items.append("防爆泄压面积计算及泄压设施位置")
        if profile.has_mid_warehouse:
            items.append("中间仓库防火分隔及耐火极限确认")
    if profile.has_paint_workshop:
        items.append("油漆工段封闭工艺、负压、可燃气体报警系统具体方案")
    if getattr(profile, 'has_equipment_room', False):
        items.append("气体灭火系统具体设计参数（需根据设备用房类型和体积确定）")
    return items
