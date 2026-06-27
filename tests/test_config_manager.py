"""config_manager 单元测试。"""
import sys
import os
import json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def test_last_used_persistence(tmp_path):
    """last_used_cpa 应跨实例持久化(写入文件)。"""
    cfg = tmp_path / "seals_config.json"
    cfg.write_text(json.dumps({"company_seals": {}, "accountant_seals": {}}), encoding="utf-8")
    pages = tmp_path / "config.json"
    pages.write_text(json.dumps({}), encoding="utf-8")

    from config_manager import ConfigManager
    cm = ConfigManager(config_path=str(cfg))
    assert cm.get_last_used_cpa() is None
    cm.set_last_used_cpa("C:/seal.png")
    assert cm.get_last_used_cpa() == "C:/seal.png"

    # 重新加载,验证持久化
    cm2 = ConfigManager(config_path=str(cfg))
    assert cm2.get_last_used_cpa() == "C:/seal.png"


def test_last_used_firm(tmp_path):
    cfg = tmp_path / "seals_config.json"
    cfg.write_text(json.dumps({"company_seals": {}, "accountant_seals": {}}), encoding="utf-8")

    from config_manager import ConfigManager
    cm = ConfigManager(config_path=str(cfg))
    assert cm.get_last_used_firm() is None
    cm.set_last_used_firm("C:/firm.png")
    assert cm.get_last_used_firm() == "C:/firm.png"


def test_get_default_pages_from_config(tmp_path):
    """默认页码应从 config.json 读取,缺失字段用安全默认值。"""
    cfg = tmp_path / "seals_config.json"
    cfg.write_text(json.dumps({"company_seals": {}, "accountant_seals": {}}), encoding="utf-8")
    pages = tmp_path / "config.json"
    pages.write_text(json.dumps({
        "seal_page": 3, "report_start": 4, "report_end": 8,
        "auto_add_last_page_rule": False
    }), encoding="utf-8")

    from config_manager import ConfigManager
    cm = ConfigManager(config_path=str(cfg))
    p = cm.get_default_pages()
    assert p["seal_page"] == 3
    assert p["report_start"] == 4
    assert p["report_end"] == 8
    assert p["auto_add_last_page_rule"] is False


def test_get_default_pages_fallback_when_missing(tmp_path):
    """config.json 不存在时用安全默认值。"""
    cfg = tmp_path / "seals_config.json"
    cfg.write_text(json.dumps({"company_seals": {}, "accountant_seals": {}}), encoding="utf-8")
    # 不创建 config.json

    from config_manager import ConfigManager
    cm = ConfigManager(config_path=str(cfg))
    p = cm.get_default_pages()
    assert p["seal_page"] == 5
    assert p["report_start"] == 6
    assert p["report_end"] == 11
    assert p["auto_add_last_page_rule"] is True


def test_seal_library_crud(tmp_path):
    """印章库增删查。"""
    cfg = tmp_path / "seals_config.json"
    cfg.write_text(json.dumps({"company_seals": {}, "accountant_seals": {}}), encoding="utf-8")

    from config_manager import ConfigManager
    cm = ConfigManager(config_path=str(cfg))
    cm.add_company_seal("测试公章", "C:/test.png")
    assert cm.get_company_seals()["测试公章"] == "C:/test.png"
    cm.remove_company_seal("测试公章")
    assert "测试公章" not in cm.get_company_seals()
