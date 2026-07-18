"""
rule_loader.py — JSON 规则库加载与索引

职责：
- 加载 rulesets/ 下所有 JSON 规则文件
- 按 scope / priority 建立索引
- 加载 lookup_tables
- 加载 decision_tree
"""

import json
import os
from pathlib import Path


class RuleLoader:
    """规则库加载器"""

    def __init__(self, ruleset_dir: str):
        """
        ruleset_dir: rulesets/2026-07-民建全分支-v2/ 的路径
        """
        self.ruleset_dir = Path(ruleset_dir)
        self.meta = {}
        self.decision_tree = {}
        self.rules = {}         # scope -> list of rule dicts
        self.rules_by_id = {}   # rule_id -> rule dict
        self.lookup_tables = {}

    def load_all(self):
        """加载全部"""
        self._load_meta()
        self._load_decision_tree()
        self._load_rules()
        self._load_lookup_tables()
        self._build_index()
        return self

    def _load_meta(self):
        path = self.ruleset_dir / "meta.json"
        with open(path, "r", encoding="utf-8") as f:
            self.meta = json.load(f)

    def _load_decision_tree(self):
        path = self.ruleset_dir / "decision_tree.json"
        with open(path, "r", encoding="utf-8") as f:
            self.decision_tree = json.load(f)

    def _load_rules(self):
        rules_dir = self.ruleset_dir / "rules"
        for fpath in sorted(rules_dir.glob("*.json")):
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            scope = data.get("scope", fpath.stem)
            self.rules[scope] = data.get("rules", [])

    def _load_lookup_tables(self):
        tbl_dir = self.ruleset_dir / "lookup_tables"
        for fpath in sorted(tbl_dir.glob("*.json")):
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.lookup_tables[fpath.stem] = data

    def _build_index(self):
        for scope, rule_list in self.rules.items():
            for rule in rule_list:
                rid = rule.get("id", "")
                if rid:
                    self.rules_by_id[rid] = rule

    # —— 查询方法 ——

    def get_rules_by_scope(self, scopes: list) -> list:
        """获取指定 scope 的所有规则（按 priority 降序）"""
        result = []
        for scope in scopes:
            result.extend(self.rules.get(scope, []))
        result.sort(key=lambda r: r.get("priority", 0), reverse=True)
        return result

    def get_rule_by_id(self, rule_id: str) -> dict:
        return self.rules_by_id.get(rule_id, {})

    def get_lookup(self, table_name: str):
        return self.lookup_tables.get(table_name, {})

    def get_decision_tree(self):
        return self.decision_tree

    def get_meta(self):
        return self.meta



    def rule_count(self) -> int:
        return sum(len(v) for v in self.rules.values())
