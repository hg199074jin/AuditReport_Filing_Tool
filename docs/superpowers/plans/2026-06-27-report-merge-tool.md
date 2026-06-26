# 审计报告报备处理工具 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把"审计报备-上传"和"审计报告-下载"两个独立工具整合成一个带侧面步骤导航的统一桌面软件,公共参数只填一次。

**Architecture:** 新建独立项目「审计报告报备工具」。`gui.py` 负责步骤导航界面与流程编排;`step_upload.py`/`step_download.py` 分别封装两个步骤的处理逻辑(从原项目提炼为函数);`pdf_common.py` 提取两步共用的 PDF 操作;`config_manager.py` 复用并扩展印章配置。Tkinter + PyMuPDF + Pillow + numpy。

**Tech Stack:** Python 3.12、Tkinter、PyMuPDF(fitz)、Pillow、numpy

**设计文档(spec):** `docs/superpowers/specs/2026-06-27-report-merge-tool-design.md`

**原项目参考(只读,不改动):**
- 上传: `..\审计报备-上传\pdf_processor.py`、`config_manager.py`、`seals_config.json`
- 下载: `..\审计报告-下载\gui.py`、`config.json`

---

## 关于测试策略的说明

本项目是 **Tkinter GUI + PDF 操作**工具,主体逻辑是可视化、交互式、文件驱动的,强行套用"每个函数先写 pytest 失败测试"会形式化且低效(大量 mock fitz/ Tkinter 收益极低)。

采取**务实分层**:
- **纯计算逻辑**(页码转换、坐标计算、规则生成)→ 写 pytest 单元测试
- **PDF/GUI 操作**(渲染、盖章、替换、界面)→ 用真实 PDF 做冒烟测试(提供测试文件路径,跑通后人工核对输出),不写自动化测试
- 每个 Task 末尾都有**冒烟验证步骤**(具体怎么跑、预期看到什么)

测试文件统一放 `tests/`,冒烟测试用的 PDF 放 `tests/fixtures/`(加入 .gitignore,不入库)。

---

## 文件结构

| 文件 | 职责 | 创建/复用 |
|---|---|---|
| `main.py` | 启动入口(转调 gui.main) | 新建(沿用原项目两行式) |
| `gui.py` | 步骤导航界面、公共配置区、预览区、状态编排 | **新写** |
| `step_upload.py` | 步骤①处理:盖章+拼接,生成上传报告 | 从上传项目 `PDFProcessor` 提炼 |
| `step_download.py` | 步骤③处理:替换盖章页+抠码贴回,生成可打印报告 | 从下载项目提炼 |
| `pdf_common.py` | 共用:PDF 渲染、坐标转换、友好错误 | 从两项目提取 |
| `config_manager.py` | 印章库 + 上次选用记忆(新增 last_used) | 复用并扩展上传项目 |
| `seals_config.json` | 印章库(复用上传项目已调好的) | 复制自上传项目 |
| `config.json` | 默认页码配置 | 新建(参考下载项目结构) |
| `requirements.txt` | 依赖 | 新建 |
| `审计报告报备工具.bat` | Windows 启动脚本 | 新建 |
| `.gitignore` | 忽略缓存/产物/测试 fixtures | 新建 |
| `tests/` | 单元测试 | 新建 |

---

## Task 0: 项目骨架与环境

**Files:**
- Create: `requirements.txt`、`main.py`、`.gitignore`、`审计报告报备工具.bat`
- Create: `seals_config.json`(复制自上传项目)
- Create: `config.json`

- [ ] **Step 1: 创建 requirements.txt**

```
PyMuPDF
Pillow
numpy
```

- [ ] **Step 2: 创建 .gitignore**(已存在,核对内容)

确认 `.gitignore` 已含 `.venv/`、`__pycache__/`、`*.log`、`处理完成_*.pdf`、`替换完成_*.pdf`、`tests/fixtures/`。

> **注意前缀**:产物前缀以**代码实际行为**为准(`处理完成_` / `替换完成_`,沿用原项目)。spec 里写的 `上传报告_`/`可打印报告_` 只是描述性命名,实现时以代码为准。

- [ ] **Step 3: 创建虚拟环境并安装依赖**

Run(Git Bash,工作目录为新项目根):
```bash
python -m venv .venv
source .venv/Scripts/activate
python -m pip install --upgrade pip
python -m pip install PyMuPDF Pillow numpy
```
**重要**:严格在项目内 `.venv` 安装,不污染全局。安装后 `pip freeze > requirements.txt` 锁定实际版本。

Expected: 三个包安装成功,`.venv\` 目录生成。

- [ ] **Step 4: 复制印章配置**

把 `..\审计报备-上传\seals_config.json` 复制到本项目根。**不要**改动里面的印章路径(那是用户已调好的)。后续 Task 6 会扩展 last_used 字段。

- [ ] **Step 5: 创建 config.json(默认页码)**

```json
{
  "# 说明": "默认页码配置,打开软件即预填。1基页码。",
  "seal_page": 5,
  "report_start": 6,
  "report_end": 11,
  "auto_add_last_page_rule": true
}
```
说明:`seal_page`=盖章页/签字页(通常第5页),`report_start`-`report_end`=报表页范围,`auto_add_last_page_rule`=步骤③自动追加最后一页替换规则。

- [ ] **Step 6: 创建 main.py**

```python
from gui import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 7: 创建 启动脚本**

`审计报告报备工具.bat`(参考原项目 .bat,激活 .venv 后跑 main.py):
```bat
@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python main.py
pause
```

- [ ] **Step 8: 冒烟验证——环境可用**

Run:
```bash
source .venv/Scripts/activate
python -c "import fitz, PIL, numpy; print('fitz', fitz.__doc__[:20]); print('OK')"
```
Expected: 打印 fitz 版本信息和 OK,无 ImportError。

- [ ] **Step 9: 提交**

```bash
git add requirements.txt main.py .gitignore seals_config.json config.json 审计报告报备工具.bat
git commit -m "chore: 项目骨架与虚拟环境(PyMuPDF+Pillow+numpy)"
```

---

## Task 1: pdf_common.py — 共用 PDF 操作

**Files:**
- Create: `pdf_common.py`
- Test: `tests/test_pdf_common.py`

封装两个步骤都要用的底层操作。从原项目提取,不依赖 Tkinter(纯函数,便于测试)。

- [ ] **Step 1: 写失败测试——坐标转换**

`tests/test_pdf_common.py`:
```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from pdf_common import pt_to_px, px_to_pt

def test_pt_to_px():
    # 1pt 在 2 倍渲染下 = 2px
    assert pt_to_px(72, scale=2.0) == 144

def test_px_to_pt():
    # 144px 在 2 倍渲染下 = 72pt
    assert px_to_pt(144, scale=2.0) == 72
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_pdf_common.py -v`
Expected: FAIL(ImportError, pdf_common 不存在)

- [ ] **Step 3: 实现 pdf_common.py 的坐标转换**

```python
"""两个步骤共用的 PDF 底层操作。纯函数,不依赖 Tkinter。"""
import fitz

def pt_to_px(pt: float, scale: float) -> float:
    """点(pt)转像素(给定渲染倍率)。1pt × scale = N px。"""
    return pt * scale

def px_to_pt(px: float, scale: float) -> float:
    """像素转点。"""
    return px / scale
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_pdf_common.py -v`
Expected: PASS

- [ ] **Step 5: 补充友好错误处理函数**

往 `pdf_common.py` 追加:
```python
def friendly_error_msg(e: Exception) -> str:
    """把底层异常转成用户能看懂的中文提示。"""
    msg = str(e).lower()
    if "permission denied" in msg or "cannot remove" in msg or "access is denied" in msg:
        return ("无法保存文件,该文件可能正被其他程序占用。\n\n"
                "请检查:是否有用 PDF 阅读器(Adobe Reader、WPS、浏览器等)打开了这个文件?请先关闭它;\n"
                "或换一个文件名/文件夹重新保存。")
    if "no such file" in msg or "cannot find" in msg:
        return "找不到文件或文件夹,请检查路径是否正确、文件是否存在。"
    return f"处理时发生错误:{str(e)}"
```

- [ ] **Step 6: 提交**

```bash
git add pdf_common.py tests/test_pdf_common.py
git commit -m "feat: pdf_common 共用操作(坐标转换+友好错误)"
```

---

## Task 2: config_manager.py — 印章配置 + 上次记忆

**Files:**
- Create: `config_manager.py`(复用上传项目 + 扩展 last_used)
- Create: `tests/test_config_manager.py`

- [ ] **Step 1: 写失败测试——last_used 记忆**

`tests/test_config_manager.py`:
```python
import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

def test_last_used_get_set(tmp_path, monkeypatch):
    # 把配置文件指到临时目录,避免污染真实配置
    cfg = tmp_path / "seals_config.json"
    cfg.write_text(json.dumps({"company_seals": {}, "accountant_seals": {}}), encoding="utf-8")
    from config_manager import ConfigManager
    cm = ConfigManager(config_path=str(cfg))
    assert cm.get_last_used_cpa() is None
    cm.set_last_used_cpa("C:/seal.png")
    assert cm.get_last_used_cpa() == "C:/seal.png"
    # 重新加载,验证持久化
    cm2 = ConfigManager(config_path=str(cfg))
    assert cm2.get_last_used_cpa() == "C:/seal.png"
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_config_manager.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 config_manager.py**

复用上传项目的 ConfigManager 结构,**去掉 messagebox 依赖**(改用 print,避免测试弹窗),**新增 last_used_cpa/last_used_firm 的 get/set**,**新增默认页码读写(读 config.json)**:

> **先核实 messagebox**:实现前先 Read `..\审计报备-上传\config_manager.py`,确认原项目是否真的 import tkinter(messagebox)。原项目确实 `from tkinter import messagebox`(load_config/save_config 里用)。整合项目改为 print(或直接静默,因为错误本就罕见),去掉 tkinter 依赖以便测试。

```python
"""印章库管理 + 上次选用记忆 + 默认页码读写。

复用上传项目 ConfigManager 的印章库增删查,
新增 last_used_cpa / last_used_firm 跨次记忆字段,
新增默认页码读写(读 config.json 预填公共配置区)。
不依赖 tkinter(便于测试),错误用 print 提示。
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
        return self.config["company_seals"]

    def get_accountant_seals(self):
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

    # —— 上次选用记忆(新增) ——
    def get_last_used_cpa(self):
        return self.config.get("last_used_cpa")

    def set_last_used_cpa(self, path):
        self.config["last_used_cpa"] = path
        self._save()

    def get_last_used_firm(self):
        return self.config.get("last_used_firm")

    def set_last_used_firm(self, path):
        self.config["last_used_firm"] = path
        self._save()

    # —— 默认页码读写(新增,读 config.json) ——
    def get_default_pages(self):
        """返回 {seal_page, report_start, report_end, auto_add_last_page_rule}。
        文件不存在或字段缺失时返回安全默认值。"""
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_config_manager.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add config_manager.py tests/test_config_manager.py
git commit -m "feat: config_manager 印章库+上次选用记忆"
```

---

## Task 3: step_upload.py — 步骤①盖章+拼接

**Files:**
- Create: `step_upload.py`
- Test: `tests/fixtures/`(冒烟测试,不入库)

从上传项目 `PDFProcessor` 提炼。**关键**:复用完整盖章链路(find_seal_page→find_seal_anchors→compute_seal_positions→add_seals_to_page),不能只搬 add_seals_to_page。

- [ ] **Step 1: 通读原项目 PDFProcessor 的相关方法**

读取 `..\审计报备-上传\pdf_processor.py`,重点:`load_original_pdf`、`find_seal_page`、`find_seal_anchors`、`compute_seal_positions`、`_get_seal_target_size`、`_firm_name_center_x`、`_resize_seal_exact`、`add_seals_to_page`、`process_pdf`(第845-980行)。

理解每个函数的输入输出和依赖关系(尤其 add_seals_to_page 依赖 self.seal_positions 和 self.page_image)。

- [ ] **Step 2: 提炼 step_upload.py**

把 PDFProcessor 的盖章+拼接逻辑提取为**一个函数 `process_upload(...)`**,签名设计:
```python
def process_upload(
    original_pdf_path: str,
    stamp_pdf_path: str,        # 盖章报表PDF
    appendix_pdf_path: str,     # 盖章附注PDF
    company_seal_path: str,     # 事务所章
    accountant_seal_paths: list,  # CPA章列表(2个)
    seal_page: int,             # 盖章页码(1基)
    stamp_start_page: int,      # 报表替换起始页(1基)
    stamp_end_page: int,        # 报表替换结束页(1基)
    progress_cb=None,           # progress_cb(percent, stage)
) -> str:
    """生成上传报告,返回输出路径。失败抛 PDFProcessError。"""
```

实现要点:
- 直接从 PDFProcessor 继承/实例化,调用其 process_pdf 逻辑(最省事且最不易错的方式:实例化 PDFProcessor,调 process_pdf,只是把 PDFProcessor 类从原项目搬过来,去掉 PyPDF2 fallback 分支)。
- **去掉 PyPDF2**:原项目顶部 `from PyPDF2 import PdfReader` 和 process_pdf 里的 PyPDF2 fallback 分支全部删除(主路径已全切 fitz)。
- 输出路径沿用原项目:`处理完成_<原始文件名>.pdf`(放在原始报告同目录),返回该路径。
- 印章加载、页码校验沿用原项目逻辑。
- **异常透传(重要)**:`process_pdf` 抛 `PDFProcessError`(及子类),这些异常带 `hint` 字段(用户排查建议)。`process_upload` 必须**原样向上抛出这些异常**,不要吞掉。gui 在调用时**优先检查 `PDFProcessError.hint`**:有 hint 则 message + hint 一起显示,没有 hint 才回退到 `friendly_error_msg`。
- **参数传递(防错位)**:`process_pdf` 原签名参数顺序与 `process_upload` 不同。**必须用关键词参数**调用,避免 seal_page 与 stamp_start_page 这两个 int 传错位:
  ```python
  processor.process_pdf(
      original_pdf_path=original_pdf_path,
      stamp_pdf_path=stamp_pdf_path,
      appendix_pdf_path=appendix_pdf_path,
      company_seal_path=company_seal_path,
      accountant_seal_paths=accountant_seal_paths,
      stamp_start_page=stamp_start_page,
      stamp_end_page=stamp_end_page,
      seal_page=seal_page,
      progress_cb=progress_cb,
  )
  ```
- **logging**:原 PDFProcessor 顶部用了 `_logger`。整合项目保留 logging(沿用原配置),或改为 print——实现时统一为 print,避免引入 logging 配置复杂度。

> 注:把 `PDFProcessor` 类整体搬过来作为 step_upload 的内部实现是可接受的(它本就是一个内聚的处理类)。step_upload.py 暴露 `process_upload` 函数作为对 gui 的接口,内部用 PDFProcessor。`PDFProcessError` 异常族一并搬过来(gui 需要识别它取 hint)。

- [ ] **Step 3: 冒烟测试——真实 PDF 跑通**

准备测试文件(放 `tests/fixtures/`,不入库):
- 一份原始报告 PDF
- 对应的盖章报表 PDF、盖章附注 PDF
- 印章图片(用 seals_config.json 里的真实路径)

Run:
```bash
source .venv/Scripts/activate
python -c "
from step_upload import process_upload
out = process_upload(
    original_pdf_path=r'<替换为本地原始报告路径>',
    stamp_pdf_path=r'<替换为本地盖章报表PDF>',
    appendix_pdf_path=r'<替换为本地盖章附注PDF>',
    company_seal_path=r'<替换为本地事务所章图片>',
    accountant_seal_paths=[r'<CPA章1>', r'<CPA章2>'],
    seal_page=5, stamp_start_page=6, stamp_end_page=11,
    progress_cb=lambda p,s: print(f'{p}% {s}')
)
print('输出:', out)
"
```
(注:路径需替换为本机真实文件。印章路径可从 `seals_config.json` 取。冒烟测试用的 PDF 放 `tests/fixtures/`,已 gitignore。)
```
Expected: 进度走到 100%,输出 `处理完成_原始报告.pdf`,打开能看到盖章页有 CPA+事务所章、报表页已替换为盖章报表。

- [ ] **Step 4: 提交**

```bash
git add step_upload.py
git commit -m "feat: step_upload 步骤①盖章+拼接(复用上传项目逻辑,去掉PyPDF2)"
```

---

## Task 4: step_download.py — 步骤③替换+保码

**Files:**
- Create: `step_download.py`

从下载项目 `gui.py` 提炼 `_extract_qr_strip`、`_paste_qr_strip`、替换逻辑。

- [ ] **Step 1: 通读下载项目相关方法**

读取 `..\审计报告-下载\gui.py`:`_extract_qr_strip`(539行)、`_paste_qr_strip`(598行)、`process_files`(642行)。

- [ ] **Step 2: 提炼 step_download.py**

暴露函数:
```python
def process_download(
    cicpa_pdf_path: str,        # 赋码报告
    original_pdf_path: str,     # 原始报告(提供无章替换页)
    replace_rules: list,        # [{"cicpa":(s,e),"original":(s,e)}, ...]
    progress_cb=None,
) -> str:
    """生成可打印报告,返回输出路径。失败抛异常。"""
```

> **关于 insert_rules(插入页规则)**:原下载项目有独立的 insert_rules 机制(插入封面/目录页)。但 spec 3.3 已明确"附注末页走 replace_rules 的自动最后一页规则,不单独配置"——整合项目**不支持插入页规则**,所有页映射统一走 replace_rules。故 `process_download` 签名**不含 insert_rules**。提炼代码时把原 process_files 里处理 insert_rules 的分支删除。

实现要点:
- 把 `_extract_qr_strip`、`_paste_qr_strip` 原样搬过来(它们已是纯函数,依赖 fitz+PIL+numpy)。
- `process_files` 的核心流程(原生复制基底→抠码→替换→贴回→保存)提炼为 `process_download`,去掉 Tkinter 依赖(messagebox 改抛异常,由 gui 捕获转友好提示),**去掉 insert_rules 处理分支**。
- 输出路径:`替换完成_<赋码报告文件名>.pdf`,默认放赋码报告同目录(`output_dir=None` 时)。签名增加 `output_dir: str = None` 参数,gui 传入;None 时取 `os.path.dirname(cicpa_pdf_path)`。

- [ ] **Step 3: 冒烟测试——真实 PDF 跑通**

Run:
```bash
source .venv/Scripts/activate
python -c "
from step_download import process_download
out = process_download(
    cicpa_pdf_path=r'<替换为本地赋码报告路径>',
    original_pdf_path=r'<替换为本地原始报告路径>',
    replace_rules=[{'cicpa':(5,5),'original':(5,5)},{'cicpa':(6,11),'original':(6,11)},{'cicpa':(13,13),'original':(13,13)}],
    progress_cb=lambda p,s: print(f'{p}% {s}')
)
print('输出:', out)
"
```
(注:路径需替换为本机真实文件。冒烟测试用的 PDF 放 `tests/fixtures/`,已 gitignore。)
Expected: 输出 `替换完成_注协赋码后报告.pdf`,替换页有二维码方块(不遮挡内容),未替换页二维码保留。

- [ ] **Step 4: 提交**

```bash
git add step_download.py
git commit -m "feat: step_download 步骤③替换+保码(复用下载项目逻辑)"
```

---

## Task 5: gui.py — 步骤导航界面骨架

**Files:**
- Create: `gui.py`

这是最大的一块。先搭骨架(侧边栏+三步切换+公共配置区+预览区),不接处理逻辑。

- [ ] **Step 1: 搭主窗口与侧边栏**

`gui.py`:
```python
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os

# 配色/字体(沿用下载项目风格)
COLORS = {
    'primary': '#2563EB', 'primary_hover': '#1D4ED8',
    'secondary': '#64748B', 'success': '#10B981', 'danger': '#EF4444',
    'bg_light': '#F8FAFC', 'bg_white': '#FFFFFF',
    'text_primary': '#0F172A', 'text_secondary': '#475569',
}
FONTS = {
    'title': ('Microsoft YaHei UI', 14, 'bold'),
    'heading': ('Microsoft YaHei UI', 11, 'bold'),
    'body': ('Microsoft YaHei UI', 10),
}

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("审计报告报备处理工具")
        self.root.geometry("1200x780")
        self.root.configure(bg=COLORS['bg_light'])
        # 配置管理器(印章库 + 上次记忆 + 默认页码)
        from config_manager import ConfigManager
        self.cfg = ConfigManager()
        # 状态机:current_step (1/2/3), step_status {1:'active',2:'locked',3:'locked'}
        self.current_step = 1
        self.step_status = {1: 'active', 2: 'locked', 3: 'locked'}
        self._build_sidebar()
        self._build_main_area()
        self._load_defaults()   # 从 config.json 读默认页码预填公共配置区
        self._show_step(1)

    def _load_defaults(self):
        # 用 self.cfg.get_default_pages() 预填盖章页/报表页范围 Entry
        pages = self.cfg.get_default_pages()
        self.seal_page_var.set(pages['seal_page'])
        self.report_start_var.set(pages['report_start'])
        self.report_end_var.set(pages['report_end'])
        # 印章自动选中上次(last_used)
        # (在步骤①内容区构建时,下拉默认选 last_used_cpa / last_used_firm)

    def _build_sidebar(self):
        # 左侧 180px 宽,三个步骤按钮 + 分隔线 + 预览入口
        ...
    def _build_main_area(self):
        # 右侧:公共配置区(始终可见)+ 步骤内容容器 + 预览区容器
        ...
    def _show_step(self, step):
        # 根据 step 切换右侧内容,更新侧边栏状态显示
        ...
    def run(self):
        self.root.mainloop()

def main():
    root = tk.Tk()
    App(root).run()
```

填充 `_build_sidebar`、`_build_main_area`、`_show_step` 的具体实现:
- 侧边栏:三个 Label/Button,显示"✓①准备上传 / ●②等赋码 / ○③处理下载",点击切换(locked 状态不可点)。
- 公共配置区:原始报告路径(浏览按钮)+ 盖章页/报表页范围 Entry + 附注自动复选。
- 步骤内容容器:三个 Frame(step1_frame/step2_frame/step3_frame),`_show_step` 用 pack_forget 切换显示。

- [ ] **Step 2: 冒烟测试——界面能显示**

Run: `python main.py`
Expected: 窗口出现,左侧三个步骤(①可点,②③灰),右侧公共配置区+步骤①内容区+预览区占位。点①能切换显示。关闭不报错。

- [ ] **Step 3: 提交**

```bash
git add gui.py
git commit -m "feat: gui 步骤导航界面骨架(侧边栏+公共配置+三步切换)"
```

---

## Task 6: gui.py — 步骤①内容区与处理接入

**Files:**
- Modify: `gui.py`

- [ ] **Step 1: 实现步骤①内容区**

在 step1_frame 里添加:
- 事务所章选择(下拉选自印章库 + 浏览,初始自动选中 last_used_firm)
- CPA章选择(下拉选自印章库 + 浏览,2个)
- 盖章报表PDF、盖章附注PDF 浏览
- "生成上传报告"按钮

- [ ] **Step 2: 接入 step_upload.process_upload**

点击"生成上传报告":
- 校验:原始报告、印章、报表/附注PDF 都选了,不齐提示缺哪个
- 用线程跑 process_upload(避免界面卡死),进度回调更新进度条对话框
- **输出目录**:process_upload 内部沿用原项目行为,放原始报告同目录,文件名 `处理完成_<原文件名>.pdf`(不弹保存框)
- 成功:记录输出路径,侧边栏①变✓,②解锁变●,自动切到步骤②
- **失败提示**:优先检查异常是否为 `PDFProcessError`(step_upload 抛出),有 `hint` 字段则 message+hint 一起显示,否则用 friendly_error_msg
- 选完印章后调 set_last_used_cpa/set_last_used_firm 记忆

- [ ] **Step 3: 冒烟测试——完整跑步骤①**

Run: `python main.py`,填好参数,点生成。
Expected: 生成 `处理完成_xxx.pdf`,①变✓,自动跳②。

- [ ] **Step 4: 提交**

```bash
git add gui.py
git commit -m "feat: gui 步骤①内容区+接入step_upload"
```

---

## Task 7: gui.py — 步骤②提示页 + 步骤③内容区与处理接入

**Files:**
- Modify: `gui.py`

- [ ] **Step 1: 实现步骤②提示页**

step2_frame:
- Label 显示"上传报告已生成:[路径]"
- "打开所在文件夹"按钮:`os.startfile(os.path.dirname(path))`,try/except 捕获路径失效
- 操作指引文字

- [ ] **Step 2: 实现步骤③内容区**

step3_frame:
- 赋码报告路径(浏览)
- 替换规则列表(从公共页码默认生成:盖章页→单页规则、报表范围→区间规则,可编辑/增删,沿用下载项目的规则UI)
- "生成可打印报告"按钮

- [ ] **Step 3: 接入 step_download.process_download**

- 校验:赋码报告、原始报告都选了,replace_rules 非空
- 线程跑 process_download,进度回调
- **输出目录**:gui 传 `output_dir=None`,由 process_download 默认放赋码报告同目录(`os.path.dirname(cicpa_pdf_path)`)。无需弹保存框,沿用原下载项目"同目录输出"行为(原项目虽有保存框但默认目录就是同目录,整合项目简化为直接同目录,文件名带 `替换完成_` 前缀避免覆盖原赋码文件)。
- 成功:③变✓,提示完成;失败:优先检查 `PDFProcessError.hint`(step_download 抛的异常),有 hint 用 hint,否则 friendly_error_msg
- 页码映射:公共配置的原始侧页码 + 用户在③界面确认的赋码侧页码 → replace_rules。规则生成是纯计算,可顺带加一个 pytest(Task 7 Step 2.5)

- [ ] **Step 4: 冒烟测试——完整跑步骤②③**

Run: `python main.py`,从步骤①一路走到③(中间手动准备赋码报告)。
Expected: ②显示路径+打开文件夹按钮;③生成 `替换完成_xxx.pdf`,替换页二维码正确、不遮挡。

- [ ] **Step 5: 提交**

```bash
git add gui.py
git commit -m "feat: gui 步骤②提示页+步骤③内容区与处理接入"
```

---

## Task 8: gui.py — 预览区与状态机完善

**Files:**
- Modify: `gui.py`

- [ ] **Step 1: 实现预览区**

预览区随步骤显示对应 PDF:
- 步骤①:选了原始报告后,预览原始报告(翻页)
- 步骤③:选了赋码报告后,预览赋码报告
- 复用下载项目的 get_pixmap + PIL + ImageTk 渲染方式

- [ ] **Step 2: 完善状态机**

- 重做①:点击侧边栏①(已✓状态)→ 弹确认"重做会清空②③进度,确定?"→ 确认后重置 step_status、清空②③全部输入。**清空清单(全部清空)**:
  - 步骤②的输出路径记录
  - 步骤③的赋码报告路径、replace_rules 列表、预览状态
  - 步骤①的输出路径记录(因为重做会生成新的)
  - 公共配置(原始报告/页码)**保留不清空**(用户可能只是想重新生成,原始报告没换)
- ②③锁定时点击:提示"请先完成上一步"
- 进入③前置校验:必须有赋码报告路径

- [ ] **Step 3: 冒烟测试——预览+状态流转**

Run: `python main.py`
Expected: ①预览原始报告可翻页;③预览赋码报告;重做①会清空②③。

- [ ] **Step 4: 提交**

```bash
git add gui.py
git commit -m "feat: gui 预览区+状态机完善(重做清空/锁定提示)"
```

---

## Task 9: README 与收尾

**Files:**
- Create: `README.md`

- [ ] **Step 1: 写 README**

参考下载项目 README 结构,内容覆盖:
- 项目简介(整合两个工具的目的)
- 三步流程说明
- 环境要求与安装(Python 3.12、.venv、pip install -r requirements.txt)
- 使用说明(步骤①②③)
- 配置说明(seals_config.json 印章库、config.json 页码)
- 常见问题(文件被占用、签名提示)

- [ ] **Step 2: 最终冒烟测试——端到端**

用真实报告从步骤①走到③,核对最终 `替换完成_xxx.pdf`:
- 替换页无章、有二维码、不遮挡
- 未替换页二维码保留
- 文件能正常打开打印

- [ ] **Step 3: 提交**

```bash
git add README.md
git commit -m "docs: README 与使用说明"
```

---

## 执行顺序与依赖

```
Task 0 (骨架/环境)
      │
      ├──► Task 1 (pdf_common) ──┐  [坐标工具+友好错误,被 gui 引用]
      ├──► Task 2 (config)  ─────┤  [印章库+页码,被 gui 引用]
      ├──► Task 3 (upload)  ─────┤  [盖章+拼接,被 gui Task6 引用]
      └──► Task 4 (download)──── ┤  [替换+保码,被 gui Task7 引用]
                                 │
                                 ▼
                          Task 5 (gui骨架) ─► Task 6 (步骤①)
                                            ─► Task 7 (步骤②③)
                                            ─► Task 8 (预览/状态)
                                            ─► Task 9 (README)
```

- **Task 1-4 互相独立,可并行**(Task 1 的 pdf_common 仅含坐标工具+友好错误,不依赖 Task 2/3/4)。
- **Task 5+ 依赖前面的处理模块**(gui 要 import step_upload/step_download/config_manager/pdf_common)。
- 建议执行顺序:0 → (1,2,3,4 并行)→ 5 → 6 → 7 → 8 → 9。

> **pdf_common 职责澄清**:Task 1 只放坐标工具(pt↔px)和 friendly_error_msg。PDF 渲染逻辑(get_pixmap+PIL+ImageTk)不强制提炼到 pdf_common——step_upload/step_download 各自就地复用原项目渲染代码,gui 预览(Task 8)也直接用 fitz+PIL。避免为"共用"而强行提取实际差异较大的渲染代码。spec 7.2"共用渲染"表述以此计划为准(渲染就地复用,不集中)。
