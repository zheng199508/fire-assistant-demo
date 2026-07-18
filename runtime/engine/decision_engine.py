"""
decision_engine.py v4 — 决策引擎（全面整改版）

改进:
- 新增 BuildingProfile 字段（火灾危险性自动分类、油漆工段、中间仓库等）
- classify_risk() 按 GB 50016 3.1.2 条判定多物质/油漆工段
- _condition_matches() 返回 (bool, str) 支持 tags 显式过滤
- evaluate() 传递 rule_tags，推理日志记录匹配原因
"""

import re, json, os
from typing import Dict, Any, List, Tuple


class BuildingProfile:
    def __init__(self):
        self.building_type: str = ""
        self.civil_subtype: str = ""
        self.industrial_subtype: str = ""
        self.height_m: float = 0.0
        self.total_area_sqm: float = 0.0
        self.floor_area_sqm: float = 0.0
        self.floors_above: int = 0
        self.floors_below: int = 0
        self.building_volume: float = 0.0
        self.fire_risk: str = ""
        self.building_class: str = ""
        self.fire_resistance: str = ""
        self.has_basement: bool = False
        self.has_garage: bool = False
        self.garage_parking_spots: int = 0
        self.garage_total_area: float = 0.0
        self.garage_class: str = ""
        self.is_elderly_facility: bool = False
        self.is_medical: bool = False
        self.is_inpatient: bool = False  # 是否含住院部分
        self.is_education: bool = False
        self.is_entertainment: bool = False
        self.is_shop_exhibition: bool = False
        self.has_central_ac: bool = False
        self.dual_municipal_water: bool = False
        self.municipal_outdoor_flow_ok: bool = False
        self.substances: List[str] = []
        self.has_paint_workshop: bool = False
        self.paint_area_ratio: float = 0.0
        self.paint_process_closed: bool = False
        self.paint_negative_pressure: bool = False
        self.paint_gas_alarm: bool = False
        self.has_mid_warehouse: bool = False
        self.mid_warehouse_substance: str = ""
        # 新增字段
        self.auto_classified_risk: str = ""
        self.substance_risks: List[str] = []
        self.risk_override_reason: str = ""
        self.paint_workshop_area: float = 0.0
        self.paint_workshop_ratio_percent: float = 0.0
        self.paint_risk_override: str = ""
        self.mid_warehouse_risk: str = ""
        self.mid_warehouse_affects_main: bool = False
        self.environment_temp: float = 20.0
        self.has_large_atrium: bool = False
        self.corridor_length_m: float = 0.0
        self.has_combustible_curtain_wall: bool = False
        self._substance_risk_map = None
        # v4 新增字段
        self.is_important_public_building: bool = False  # 是否重要公共建筑（省级/500床以上）
        self.clear_height_m: float = 0.0  # 净空高度（室内地面到顶棚）
        self.has_sprinkler_design: bool = False  # 是否已设计自喷
        self.basement_function: str = ""  # 地下室功能：仅停车/停车+设备/商业/其他
        # v5 新增字段 - 建筑画像扩展
        self.medical_type: str = ""  # 综合医院/专科医院/门诊楼/住院部/医养结合
        self.bed_count: int = 0  # 床位数
        self.daily_patients: int = 0  # 日均门诊量
        self.max_occupants: int = 0  # 最大同时使用人数
        self.structure_type: str = ""  # 框架/框剪/剪力墙/钢结构
        self.power_dual_supply: bool = False  # 双回路供电
        self.power_generator: bool = False  # 有柴油发电机
        self.has_special_zone: bool = False  # 有特殊危险区域
        self.special_zones: List[str] = []  # 氧气站/放射科/实验室等
        self.fire_lane_width_m: float = 0.0  # 消防车道宽度
        self.insulation_grade: str = ""  # 外墙保温材料等级 A/B1/B2
        self.water_supply_pipe_dn: str = ""  # 市政供水管径 DN100/DN150/DN200
        self.water_supply_pressure_mpa: float = 0.0  # 市政供水压力
        self.basement_parking_spots: int = 0  # 地下室车位数
        self.floor_functions: str = ""  # 各层功能描述
        self.has_oxygen_station: bool = False  # 有氧气站
        self.has_radiology: bool = False  # 有放射科
        self.has_laboratory: bool = False  # 有实验室/检验科
        self.public_building_type: str = ""  # 公建细分：医疗/教育/办公/商业/文化体育/其他
        # v5 扩展 - 建筑画像深度增强
        self.has_equipment_room: bool = False  # 有变配电室/发电机房/通信机房
        self.equipment_room_types: List[str] = []  # 设备用房类型列表
        self.corridor_layout: str = ""  # 走道布房：单面布房/双面布房
        self.has_special_medical_zone: bool = False  # 手术室/ICU
        self.has_fire_pump_room: bool = False  # 消防水泵房
        self.fire_pump_room_location: str = ""  # 水泵房位置
        self.has_fire_control_room: bool = False  # 消防控制室
        self.fire_control_room_location: str = ""  # 消防控制室位置
        self.water_pool_type: str = ""  # 消防水池形式
        self.is_boarding_school: bool = False  # 寄宿制学校
        self.has_lab_chemical: bool = False  # 实验室/化学药品室
        self.has_dining: bool = False  # 餐饮
        self.has_cinema: bool = False  # 电影院/剧场
        self.max_single_floor_area: float = 0.0  # 最大单层营业面积
        self.water_tank_type: str = ""  # 高位消防水箱类型
        self.water_tank_volume: float = 0.0  # 高位消防水箱有效容积
        # v6 新增字段 - 复杂逻辑优化
        self.has_podium: bool = False  # 是否有裙房
        self.podium_separated_by_firewall: bool = False  # 裙房与主体是否防火墙分隔
        self.has_open_corridor: bool = False  # 是否敞开式外廊
        self.sprinkler_coverage: str = ""  # 自喷覆盖范围：full/partial/none
        self.has_commercial_outlet: bool = False  # 住宅是否有商业服务网点
        self.commercial_outlet_unit_area: float = 0.0  # 商业网点最大单元面积
        self.is_entertainment_venue: bool = False  # 是否歌舞娱乐放映游艺场所
        self.entertainment_floor: str = ""  # 歌舞娱乐所在楼层
        self.entertainment_room_area: float = 0.0  # 歌舞娱乐每厅最大面积
        self.is_shop_qualifies_relax: bool = False  # 商店营业厅是否满足放宽四条件
        self.is_kindergarten: bool = False  # 是否幼儿园/托儿所
        self.kindergarten_floor: str = ""  # 幼儿园所在楼层
        self.has_boiler_room: bool = False  # 是否有锅炉房
        self.boiler_room_location: str = ""  # 锅炉房位置：地下/首层/贴邻/屋顶
        self.has_generator_room: bool = False  # 是否有柴油发电机房
        self.generator_room_location: str = ""  # 发电机房位置：地下/首层/屋顶
        self.oil_storage_volume: float = 0.0  # 储油间容量(m³)
        self.atrium_area: float = 0.0  # 中庭面积
        self.atrium_floors: int = 0  # 中庭连通层数
        self.residential_door_grade_b: bool = False  # 住宅户门是否乙级防火门
        self.is_mixed_use: bool = False  # 是否住宅与商业/办公合建
        self.is_mixed_separated: bool = False  # 合建是否防火墙分隔
        self.layers_in_24m_with_large_area: bool = False  # 24m以上完整楼层是否有>1000㎡

    def load_substance_map(self, ruleset_dir: str):
        path = os.path.join(ruleset_dir, "lookup_tables", "substance_risk_map.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                self._substance_risk_map = json.load(f)

    def classify_risk(self) -> str:
        """按 GB 50016 表3.1.1/3.1.3 + 第3.1.2条自动判定火灾危险性"""
        # 如果fire_risk已预设，仍需检查油漆工段升级
        if self.fire_risk:
            worst = self.fire_risk
            if worst in ["丁", "戊"] and self.industrial_subtype == "workshop" and self.has_paint_workshop:
                self.paint_workshop_ratio_percent = self.paint_area_ratio
                if self.paint_area_ratio >= 10:
                    if self.paint_process_closed and self.paint_negative_pressure and self.paint_gas_alarm:
                        self.paint_risk_override = "油漆工段占比≥10%但满足封闭工艺+负压+气体报警三项条件，按GB 50016第3.1.2条仍可按丁戊类确定"
                    else:
                        self.paint_risk_override = "甲类"
                        worst = "甲"
                elif self.paint_area_ratio >= 5:
                    self.paint_risk_override = f"油漆工段占比{self.paint_area_ratio:.1f}%≥5%，需确认是否满足三项条件（封闭工艺+负压+气体报警），否则按较大危险性确定"
            self.auto_classified_risk = worst
            self.fire_risk = worst
            return worst

        if not self._substance_risk_map:
            return self.fire_risk or ""

        key = "production" if self.industrial_subtype == "workshop" else "storage"
        risk_map = self._substance_risk_map.get(key, {})
        if not risk_map:
            return self.fire_risk or ""

        risks = []
        self.substance_risks = []
        for s in self.substances:
            found = False
            for cat, items in risk_map.items():
                if s in items:
                    risks.append(cat.replace("类", ""))
                    self.substance_risks.append(f"{s}→{cat}")
                    found = True
                    break
            if not found:
                self.substance_risks.append(f"{s}→未识别")
                risks.append("未知")

        order = {"甲": 0, "乙": 1, "丙": 2, "丁": 3, "戊": 4, "未知": 2}
        if risks:
            worst = min(risks, key=lambda x: order.get(x, 2))
        else:
            worst = "丁"

        # 油漆工段判定（仅丁戊类厂房）
        if worst in ["丁", "戊"] and self.industrial_subtype == "workshop" and self.has_paint_workshop:
            self.paint_workshop_ratio_percent = self.paint_area_ratio
            if self.paint_area_ratio >= 10:
                if self.paint_process_closed and self.paint_negative_pressure and self.paint_gas_alarm:
                    self.paint_risk_override = "油漆工段占比≥10%但满足封闭工艺+负压+气体报警三项条件，按GB 50016第3.1.2条仍可按丁戊类确定"
                else:
                    self.paint_risk_override = "甲类"
                    worst = "甲"
            elif self.paint_area_ratio >= 5:
                self.paint_risk_override = f"油漆工段占比{self.paint_area_ratio:.1f}%≥5%，需确认是否满足三项条件（封闭工艺+负压+气体报警），否则按较大危险性确定"

        self.auto_classified_risk = worst
        self.fire_risk = worst
        return worst

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}

    def get_tags(self) -> list:
        tags = [self.building_type]
        if self.civil_subtype:
            tags.append(self.civil_subtype)
        if self.industrial_subtype:
            tags.append(self.industrial_subtype)
        if self.fire_risk:
            tags.append(self.fire_risk)
        if self.building_class:
            tags.append(self.building_class)
        if self.has_basement:
            tags.append("地下室")
        if self.has_garage:
            tags.append("汽车库")
        if self.is_elderly_facility:
            tags.append("老年人")
        if self.is_medical:
            tags.append("医疗")
        if self.is_education:
            tags.append("教育")
        if self.is_entertainment:
            tags.append("歌舞娱乐")
        if self.is_shop_exhibition:
            tags.append("商店展览")
        if self.has_paint_workshop:
            tags.append("油漆工段")
        if self.has_mid_warehouse:
            tags.append("中间仓库")
        if self.is_inpatient:
            tags.append("住院")
        if self.is_boarding_school:
            tags.append("寄宿制学校")
        if self.has_lab_chemical:
            tags.append("实验室")
        if self.has_dining:
            tags.append("餐饮")
        if self.has_cinema:
            tags.append("电影院")
        if self.has_equipment_room:
            tags.append("设备用房")
        if self.is_kindergarten:
            tags.append("幼儿园")
        if self.has_boiler_room:
            tags.append("锅炉房")
        if self.has_generator_room:
            tags.append("发电机房")
        if self.has_fire_control_room:
            tags.append("消防控制室")
        if self.has_fire_pump_room:
            tags.append("消防水泵房")
        return [t for t in tags if t]


class DecisionEngine:
    # 泛化规则ID列表 — 这些规则对所有建筑都适用，不提供建筑特异性指导
    SKIP_RULE_IDS = {
        "ME-0121",  # "不应使用灭火器带电扑救" — 通用电气安全规则
        # 火灾危险性分类标签（仅描述类别定义，非设计要求）
        "IW-0043", "IW-0044", "IW-0045", "IW-0046", "IW-0047", "IW-0048",
        "IW-0049",  # "按火灾危险性较大的部分确定" — 分类原则，非设计要求
        "IS-0058", "IS-0059", "IS-0060",  # 仓库火灾危险性分类标签
        "IS-0061",  # "按火灾危险性最大的物品确定" — 分类原则，非设计要求
    }

    def __init__(self, rule_loader):
        self.loader = rule_loader
        self.inference_log: List[Dict] = []

    def _active_scopes(self, profile: BuildingProfile) -> List[str]:
        scopes = ["fire_hydrant", "sprinkler", "fire_alarm", "smoke_control",
                  "extinguisher", "lighting", "power"]
        if profile.building_type == "civil":
            scopes.append("civil.residential" if profile.civil_subtype == "residential" else "civil.public")
        elif profile.building_type == "industrial":
            scopes.append("industrial.workshop" if profile.industrial_subtype == "workshop" else "industrial.warehouse")
        if profile.has_garage:
            scopes.append("garage")
        return scopes

    def evaluate(self, profile: BuildingProfile) -> Dict[str, Any]:
        self.inference_log = []
        conclusions = []
        active_scopes = self._active_scopes(profile)

        for scope in active_scopes:
            rules = self.loader.rules.get(scope, [])
            for rule in rules:
                if rule.get("id") in self.SKIP_RULE_IDS:
                    continue
                cond = rule["condition"]
                rule_tags = rule.get("tags", [])
                matched, reason = self._condition_matches(cond, profile, rule_tags)
                if matched:
                    conclusions.append({
                        "id": rule["id"],
                        "scope": rule["scope"],
                        "condition_text": cond,
                        "conclusion": rule["conclusion"],
                        "conclusion_type": rule["conclusion_type"],
                        "citation": rule["citation"],
                        "priority": rule.get("priority", 80),
                        "notes": rule.get("notes", ""),
                        "design_params": rule.get("design_params", {}),
                        "tags": rule_tags,
                    })
                    self.inference_log.append({
                        "rule_id": rule["id"],
                        "condition": cond,
                        "conclusion": rule["conclusion"],
                        "citation": rule["citation"],
                        "matched": True,
                        "reason": reason,
                    })

        # 结论去重增强：同一结论不同 scope/citation 合并
        seen_keys = {}
        deduped = []
        for c in conclusions:
            # 核心语义 key（仅取结论内容，不区分 scope，去重更彻底）
            core = re.sub(r'\s+', '', c["conclusion"][:80].strip())
            if core in seen_keys:
                # 合并 citation
                existing = deduped[seen_keys[core]]
                if c["citation"] not in existing["citation"]:
                    existing["citation"] += " / " + c["citation"]
                # 合并 design_params
                if c.get("design_params"):
                    existing.setdefault("design_params", {})
                    existing["design_params"].update(c["design_params"])
                # 保留更高 priority
                if c["priority"] > existing["priority"]:
                    existing["priority"] = c["priority"]
            else:
                seen_keys[core] = len(deduped)
                deduped.append(c)
        deduped.sort(key=lambda c: c["priority"], reverse=True)

        # 喷淋系统类型互斥：地上湿式/地下干式（无地下车库时只用湿式）
        has_wet = any("湿式" in c.get("conclusion", "") for c in deduped)
        has_dry = any("干式" in c.get("conclusion", "") for c in deduped)
        if has_wet and has_dry:
            if not profile.has_basement or not profile.has_garage:
                # 无地下室车库 → 只用湿式系统
                deduped = [c for c in deduped if "干式" not in c.get("conclusion", "")]
            # 有地下室且有车库 → 保留两条，分别标注地上/地下（已在结论中说明）

        # 收集警告
        warnings = []
        # 防火分区超限警告由 calculator 处理
        return {"conclusions": deduped, "inference_log": self.inference_log, "warnings": warnings}

    def _condition_matches(self, cond: str, p: BuildingProfile, rule_tags: List[str] = None) -> Tuple[bool, str]:
        """条件匹配引擎 — 返回 (是否匹配, 原因)"""
        c = cond

        # ═══════════════ 第 0 层：显式标签过滤 ═══════════════
        if rule_tags and len(rule_tags) > 0:
            # 建筑类型标签
            if "civil" in rule_tags and p.building_type != "civil":
                return False, "建筑类型不匹配: 需要民用建筑"
            if "industrial" in rule_tags and p.building_type != "industrial":
                return False, "建筑类型不匹配: 需要工业建筑"
            if "garage" in rule_tags and not p.has_garage:
                return False, "建筑类型不匹配: 需要汽车库"
            # 子类型标签
            if "residential" in rule_tags and p.civil_subtype != "residential":
                return False, "子类型不匹配: 需要住宅"
            if "public" in rule_tags and p.civil_subtype != "public":
                return False, "子类型不匹配: 需要公共建筑"
            if "workshop" in rule_tags and p.industrial_subtype != "workshop":
                return False, "子类型不匹配: 需要厂房"
            if "warehouse" in rule_tags and p.industrial_subtype != "warehouse":
                return False, "子类型不匹配: 需要仓库"
            # 火灾危险性标签（任一匹配即可）
            rule_risks = [r for r in ["甲", "乙", "丙", "丁", "戊"] if r in rule_tags]
            if rule_risks and p.fire_risk not in rule_risks:
                return False, f"火灾危险性不匹配: 需要{'/'.join(rule_risks)}类"
            # 特殊属性标签
            if "地下室" in rule_tags and not p.has_basement:
                return False, "需要地下室"
            if "老年人" in rule_tags and not p.is_elderly_facility:
                return False, "需要老年人照料设施"
            if "医疗" in rule_tags and not p.is_medical:
                return False, "需要医疗建筑"
            if "住院" in rule_tags and not p.is_inpatient:
                return False, "需要住院部分"
            if "教育" in rule_tags and not p.is_education:
                return False, "需要教育建筑"
            if "歌舞娱乐" in rule_tags and not p.is_entertainment:
                return False, "需要歌舞娱乐场所"
            if "商店展览" in rule_tags and not p.is_shop_exhibition:
                return False, "需要商店/展览建筑"
            if "油漆工段" in rule_tags and not p.has_paint_workshop:
                return False, "需要油漆工段"
            if "中间仓库" in rule_tags and not p.has_mid_warehouse:
                return False, "需要中间仓库"
            if "寄宿制学校" in rule_tags and not getattr(p, 'is_boarding_school', False):
                return False, "需要寄宿制学校"
            if "实验室" in rule_tags and not getattr(p, 'has_lab_chemical', False):
                return False, "需要实验室/化学药品室"
            if "餐饮" in rule_tags and not getattr(p, 'has_dining', False):
                return False, "需要餐饮场所"
            if "电影院" in rule_tags and not getattr(p, 'has_cinema', False):
                return False, "需要电影院/剧场"
            if "设备用房" in rule_tags and not getattr(p, 'has_equipment_room', False):
                return False, "需要重要设备用房"
            if "幼儿园" in rule_tags and not getattr(p, 'is_kindergarten', False):
                return False, "需要幼儿园/托儿所"
            if "锅炉房" in rule_tags and not getattr(p, 'has_boiler_room', False):
                return False, "需要锅炉房"
            if "发电机房" in rule_tags and not getattr(p, 'has_generator_room', False):
                return False, "需要发电机房"
            if "消防控制室" in rule_tags and not getattr(p, 'has_fire_control_room', False):
                return False, "需要消防控制室"
            if "消防水泵房" in rule_tags and not getattr(p, 'has_fire_pump_room', False):
                return False, "需要消防水泵房"
            # 建筑分类标签
            if "一类高层住宅" in rule_tags and p.building_class != "一类高层住宅建筑":
                return False, "建筑分类不匹配: 需要一类高层住宅"
            if "二类高层住宅" in rule_tags and p.building_class != "二类高层住宅建筑":
                return False, "建筑分类不匹配: 需要二类高层住宅"
            if "一类高层公建" in rule_tags and p.building_class != "一类高层公共建筑":
                return False, "建筑分类不匹配: 需要一类高层公建"
            if "高层厂房" in rule_tags and "高层厂房" not in p.building_class:
                return False, "建筑分类不匹配: 需要高层厂房"
            if "高层仓库" in rule_tags and "高层仓库" not in p.building_class:
                return False, "建筑分类不匹配: 需要高层仓库"

        # ═══════════════ 第 1 层：硬拒绝 ═══════════════

        # 1a. 民用建筑 → 禁止包含工业关键词的规则（但允许同时包含民用关键词的OR条件）
        if p.building_type == "civil":
            ind_kw = ["厂房", "仓库", "甲类", "乙类", "丙类", "丁类", "戊类",
                      "员工宿舍", "变配电站", "高架仓库", "高层仓库",
                      "多层仓库", "单层仓库", "生产场所", "储存", "化学品",
                      "工业建筑"]
            if any(kw in c for kw in ind_kw):
                # 如果同时包含民用关键词，说明是OR条件（如"H>24m建筑或工业建筑"），允许通过
                civ_cross_kw = ["住宅", "公建", "公共建筑", "民用建筑", "高层建筑", "多层建筑"]
                if not any(kw in c for kw in civ_cross_kw):
                    return False, "民用建筑不适用工业规则"
            # 住宅专属规则不应匹配公共建筑（但"含一类高层住宅"等说明性文字不影响）
            if "住宅" in c and "非住宅" not in c and p.civil_subtype == "public":
                # 如果同时包含"民用建筑"/"公共建筑"/"公建"，说明是通用规则而非住宅专属
                if not any(kw in c for kw in ["一类高层民用建筑", "二类高层民用建筑", "公共建筑", "公建"]):
                    return False, "公共建筑不适用住宅专属规则"
            # 公建专属规则不应匹配住宅
            if ("公建" in c or "公共建筑" in c) and "非公建" not in c and p.civil_subtype == "residential":
                return False, "住宅建筑不适用公建专属规则"

        # 1b. 工业建筑 → 禁止包含民用住宅/公建关键词的规则
        if p.building_type == "industrial":
            civ_kw = ["住宅", "公建", "公共建筑", "医院", "病房", "托儿所",
                      "幼儿园", "学校", "歌舞娱乐", "老年人", "商店", "展览",
                      "避难层", "避难房间", "旅馆", "剧场", "电影院",
                      "疗养院", "病房楼"]
            if any(kw in c for kw in civ_kw):
                return False, "工业建筑不适用民用规则"

        # 1c. 无车库 → 禁止车库专属规则
        if not p.has_garage:
            garage_kw = ["汽车库", "停车数", "修车库", "机械式汽车库", "全地下车库", "车库"]
            # 先检查否定形式（如 "非全地下车库" 表示"不是全地下车库"，不需有车库）
            has_negation = any(f"非{kw}" in c for kw in garage_kw)
            if not has_negation:
                if any(kw in c for kw in garage_kw):
                    return False, "无汽车库，跳过车库规则"

        # 1d. 火灾危险性不匹配（支持多风险条件如"甲、乙类"）
        risk_map = {"甲类": "甲", "乙类": "乙", "丙类": "丙", "丁类": "丁", "戊类": "戊"}
        found_risks = [(kw, val) for kw, val in risk_map.items() if kw in c]
        # 补充识别"甲、乙类"模式（"甲、"后紧跟"乙类"，"甲类"不在其中但"甲"是有效风险）
        risk_chars = re.findall(r'([甲乙丙丁戊])、', c)
        for rc in risk_chars:
            if rc not in [val for _, val in found_risks]:
                found_risks.append((f"{rc}、", rc))
        if found_risks and p.fire_risk:
            if all(p.fire_risk != val for _, val in found_risks):
                expected = "/".join(kw for kw, _ in found_risks)
                return False, f"火灾危险性不匹配: 规则需要{expected}，当前为{p.fire_risk}类"

        # 1e. 特定建筑分类关键词不匹配
        # 注：如果同时包含"一类高层民用建筑"（通用），则跳过"一类高层住宅"的专属检查
        if "一类高层住宅" in c and "一类高层民用建筑" not in c and p.building_class != "一类高层住宅建筑":
            return False, "建筑分类不匹配: 需要一类高层住宅"
        if "二类高层住宅" in c and "二类高层民用建筑" not in c and p.building_class != "二类高层住宅建筑":
            return False, "建筑分类不匹配: 需要二类高层住宅"
        if ("一类高层公建" in c or "一类高层公共建筑" in c) and p.building_class != "一类高层公共建筑":
            return False, "建筑分类不匹配: 需要一类高层公建"
        if "二类高层公建" in c and p.building_class != "二类高层公共建筑":
            return False, "建筑分类不匹配: 需要二类高层公建"
        if "二类高层民用建筑" in c and p.building_class not in ["二类高层住宅建筑", "二类高层公共建筑"]:
            return False, "建筑分类不匹配: 需要二类高层民用建筑"
        if "一类高层民用建筑" in c and p.building_class not in ["一类高层住宅建筑", "一类高层公共建筑"]:
            return False, "建筑分类不匹配: 需要一类高层民用建筑"

        # 1f. 地下/半地下（"及其地下/半地下室"表示扩展条件，不强制要求有地下室）
        # 若"地下/半地下"出现在OR条件中（如"地下/半地下或地上四层及以上"），不强制要求有地下室
        if ("地下或半地下" in c or "地下/半地下" in c) and not p.has_basement:
            if "及其地下" not in c:
                # 检查是否处于OR条件中（"地下/半地下或..." → 另一分支可能仍匹配）
                or_match = re.search(r'(?:地下[/或]半地下)\s*或\s*[^）)]+', c)
                if not or_match:
                    return False, "无地下室，跳过地下规则"

        # 1g. 特殊建筑类型
        if "老年人照料设施" in c and not p.is_elderly_facility:
            return False, "非老年人照料设施"
        if ("医疗建筑" in c or ("医疗" in c and "建筑" in c)) and not p.is_medical:
            return False, "非医疗建筑"
        if "大/中型幼儿园" in c and not p.is_education:
            return False, "非教育建筑"
        if "歌舞娱乐" in c and not p.is_entertainment:
            return False, "非歌舞娱乐场所"
        if "托儿所" in c and not p.is_education:
            return False, "非教育建筑"

        # 1h. 中庭 / 疏散走道条件
        if "中庭" in c and not p.has_large_atrium:
            return False, "无中庭"
        if "长度>20m疏散走道" in c and p.corridor_length_m <= 20:
            return False, f"走道长度 {p.corridor_length_m}m ≤ 20m"

        # 1i. 否定条件：非甲、乙类工业建筑 → 甲/乙类工业建筑不适用
        if "非甲、乙类工业建筑" in c or "非甲乙类工业建筑" in c:
            if p.building_type == "industrial" and p.fire_risk in ["甲", "乙"]:
                return False, "甲/乙类工业建筑不适用湿式系统（应采用雨淋/水喷雾等特殊系统）"

        # 1i. 非一类高层 / 非二类高层（排除条件）
        if any(kw in c for kw in ["非一类高层", "非一类高层条件"]) and p.building_class and "一类高层" in p.building_class:
            return False, "建筑为一类高层，不适用此类规则"
        if any(kw in c for kw in ["非二类高层", "非二类高层条件"]) and p.building_class and "二类高层" in p.building_class:
            return False, "建筑为二类高层，不适用此类规则"

        # H > N
        m = re.search(r'H\s*>\s*(\d+)', c)
        if m and p.height_m <= float(m.group(1)):
            return False, f"高度不满足: H={p.height_m}m ≤ {m.group(1)}m"
        # H <= N
        m = re.search(r'H\s*<=\s*(\d+)', c)
        if m and p.height_m > float(m.group(1)):
            return False, f"高度不满足: H={p.height_m}m > {m.group(1)}m"
        # H >= N
        m = re.search(r'H\s*>=\s*(\d+)', c)
        if m and p.height_m < float(m.group(1)):
            return False, f"高度不满足: H={p.height_m}m < {m.group(1)}m"
        # N < H <= M
        m = re.search(r'(\d+)\s*<\s*H\s*<=\s*(\d+)', c)
        if m:
            lo, hi = float(m.group(1)), float(m.group(2))
            if not (lo < p.height_m <= hi):
                return False, f"高度不满足: {lo} < H={p.height_m} ≤ {hi}"
        # S > N
        m = re.search(r'S\s*>\s*(\d+)', c)
        if m:
            # 根据上下文选择面积：车库规则用 garage_total_area，否则用 total_area_sqm
            area = p.garage_total_area if (p.has_garage and ("车库" in c or "汽车库" in c)) else p.total_area_sqm
            if area <= float(m.group(1)):
                return False, f"面积不满足: S={area:.0f} ≤ {m.group(1)}"
        # S <= N
        m = re.search(r'S\s*<=\s*(\d+)', c)
        if m:
            area = p.garage_total_area if (p.has_garage and ("车库" in c or "汽车库" in c)) else p.total_area_sqm
            if area > float(m.group(1)):
                return False, f"面积不满足: S={area:.0f} > {m.group(1)}"
        # N < S <= M
        m = re.search(r'(\d+)\s*<\s*S\s*<=\s*(\d+)', c)
        if m:
            area = p.garage_total_area if (p.has_garage and ("车库" in c or "汽车库" in c)) else p.total_area_sqm
            lo, hi = float(m.group(1)), float(m.group(2))
            if not (lo < area <= hi):
                return False, f"面积不满足: {lo} < S={area:.0f} ≤ {hi}"
        # 停车数 > N
        m = re.search(r'停车数\s*>\s*(\d+)', c)
        if m and p.garage_parking_spots <= float(m.group(1)):
            return False, f"停车数不满足: {p.garage_parking_spots} ≤ {m.group(1)}"
        # 停车数 <= N
        m = re.search(r'停车数\s*<=\s*(\d+)', c)
        if m and p.garage_parking_spots > float(m.group(1)):
            return False, f"停车数不满足: {p.garage_parking_spots} > {m.group(1)}"
        # 停车数 N~M 范围
        m = re.search(r'停车数\s*(\d+)\s*~\s*(\d+)', c)
        if m:
            lo, hi = float(m.group(1)), float(m.group(2))
            if not (lo <= p.garage_parking_spots <= hi):
                return False, f"停车数不满足: {p.garage_parking_spots} 不在 {lo}~{hi} 范围"
        # 车库分类关键词匹配（如 "Ⅰ类汽车库" 仅当 garage_class 匹配时通过）
        for gc in ["Ⅰ类汽车库", "Ⅱ类汽车库", "Ⅲ类汽车库", "Ⅳ类汽车库"]:
            if gc in c and p.garage_class != gc[0]:
                return False, f"车库分类不匹配: 需要{gc}，当前为{p.garage_class}类"

        # ═══════════════ 第 2.5 层：特殊场所位置/楼层条件 ═══════════════
        # 幼儿园/托儿所所在楼层
        if "所在楼层为四层及以上" in c:
            kf = getattr(p, 'kindergarten_floor', '')
            if "四层及以上" not in kf:
                return False, f"幼儿园所在楼层不满足: 当前为{kf or '未设置'}，需为四层及以上"
        if "所在楼层为首层~三层" in c:
            kf = getattr(p, 'kindergarten_floor', '')
            if "四层及以上" in kf or not kf:
                return False, f"幼儿园所在楼层不满足: 当前为{kf or '未设置'}"
        # 锅炉房位置
        if "锅炉房所在位置" in c:
            bl = getattr(p, 'boiler_room_location', '')
            if not bl:
                return False, "锅炉房位置未设置"
            if "地下" in c and "地下" not in bl:
                return False, f"锅炉房位置不匹配: 需在地下，当前为{bl}"
            if "贴邻" in c and "贴邻" not in bl:
                return False, f"锅炉房位置不匹配: 需贴邻，当前为{bl}"
        # 发电机房位置
        if "发电机房所在位置" in c:
            gl = getattr(p, 'generator_room_location', '')
            if not gl:
                return False, "发电机房位置未设置"
        # 消防控制室位置
        if "消防控制室所在位置" in c:
            fcl = getattr(p, 'fire_control_room_location', '')
            if not fcl:
                return False, "消防控制室位置未设置"
            if "非首层/地下一层靠外墙" in c:
                if fcl in ["首层靠外墙", "地下一层靠外墙"]:
                    return False, f"消防控制室位置满足规范要求: {fcl}"
        # 消防水泵房位置
        if "消防水泵房所在位置" in c:
            fpl = getattr(p, 'fire_pump_room_location', '')
            if not fpl:
                return False, "消防水泵房位置未设置"

        # ═══════════════ 第 3 层：放行 ═══════════════
        return True, "条件匹配"

    def _eval_condition(self, cond: str, p: BuildingProfile) -> Tuple[bool, str]:
        """兼容旧接口（_test_rules.py 使用）"""
        return self._condition_matches(cond, p)