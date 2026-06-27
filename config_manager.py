"""印章库管理 + 上次选用记忆 + 默认页码读写。

复用上传项目 ConfigManager 的印章库增删查,
新增 last_used_cpa / last_used_firm 跨次记忆字段(原项目没有此功能),
新增默认页码读写(读 config.json 预填公共配置区)。

不依赖 tkinter(原项目用 messagebox 报错,这里改用 print,便于单元测试)。
错误本就罕见,print 提示足够;gui 如需弹窗可自行包装。
"""
import json
import os


class ConfigManager:
    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = os.path.join(os.path.dirname(__file__), 'seals_config.json')
        self.config_file = config_path
        # 默认页码配置文件路径(与印章配置同目录)
        self.pages_file = os.path.join(os.path.dirname(config_path), 'config.json')
        self.config = self._load()

    def _load(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                    cfg.setdefault("company_seals", {})
                    cfg.setdefault("accountant_seals", {})
                    return cfg
            except Exception as e:
                print(f"加载配置失败: {e}")
        return {"company_seals": {}, "accountant_seals": {}}

    def _save(self):
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"保存配置失败: {e}")

    # —— 印章库增删查(复用上传项目) ——
    def get_company_seals(self):
        """返回事务所章库 {名称: 路径}。"""
        return self.config["company_seals"]

    def get_accountant_seals(self):
        """返回 CPA 章库 {名称: 路径}。"""
        return self.config["accountant_seals"]

    def add_company_seal(self, name, path):
        self.config["company_seals"][name] = path
        self._save()

    def add_accountant_seal(self, name, path):
        self.config["accountant_seals"][name] = path
        self._save()

    def remove_company_seal(self, name):
        self.config["company_seals"].pop(name, None)
        self._save()

    def remove_accountant_seal(self, name):
        self.config["accountant_seals"].pop(name, None)
        self._save()

    # —— 上次选用记忆(新增,原项目无此功能) ——
    def get_last_used_cpa(self):
        """返回上次选用的 CPA 章路径(单个),无则 None。"""
        return self.config.get("last_used_cpa")

    def set_last_used_cpa(self, path):
        self.config["last_used_cpa"] = path
        self._save()

    def get_last_used_firm(self):
        """返回上次选用的事务所章路径,无则 None。"""
        return self.config.get("last_used_firm")

    def set_last_used_firm(self, path):
        self.config["last_used_firm"] = path
        self._save()

    # —— 默认页码读写(新增,读 config.json) ——
    def get_default_pages(self):
        """返回 {seal_page, report_start, report_end, auto_add_last_page_rule}。

        文件不存在或字段缺失时返回安全默认值。
        seal_page: 盖章页/签字页(1基,通常第5页)
        report_start/report_end: 报表页范围
        auto_add_last_page_rule: 步骤③是否自动追加最后一页替换规则
        """
        defaults = {"seal_page": 5, "report_start": 6, "report_end": 11,
                    "auto_add_last_page_rule": True}
        if os.path.exists(self.pages_file):
            try:
                with open(self.pages_file, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                for k in defaults:
                    if k in cfg:
                        defaults[k] = cfg[k]
            except Exception as e:
                print(f"加载页码配置失败: {e}")
        return defaults
