# 审计报告报备处理工具

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![PyMuPDF](https://img.shields.io/badge/PyMuPDF-PDF处理-green.svg)](https://pymupdf.readthedocs.io/)
[![Tkinter](https://img.shields.io/badge/GUI-Tkinter-orange.svg)]()
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/平台-Windows-lightgrey.svg)]()

> 一条流水线把原始审计报告处理成**可打印的报备版报告**:盖章 → 上传注协赋码 → 替换盖章页并保留二维码。把原来两个独立小工具(「审计报备-上传」「审计报告-下载」)整合成一个带步骤导航的桌面软件。

```
原始报告 → 加盖CPA/事务所章 + 拼接盖章报表/附注 → 上传注协赋码 → 替换盖章页为无章版并保留二维码 → 可打印报告
```

公共参数(原始报告路径、页码)只填一次,自动识别盖章页和报表范围。

---

## 界面

**三栏布局**:左侧步骤导航栏 | 中间公共配置+步骤内容 | 右侧 PDF 预览。

```
┌─────┬────────────────────┬──────────┐
│侧边栏│ 公共配置(两步共用)  │          │
│     │ 原始报告:[浏览...]   │  PDF预览  │
│✓①准备│ 盖章页:[自动识别]    │  (独立栏 │
│●②赋码│ 报表范围:[自动计算]  │   竖长条)│
│○③下载├────────────────────┤          │
│     │ 当前步骤内容        │          │
│     │ (随侧边栏切换)      │          │
└─────┴────────────────────┴──────────┘
```

**自动识别**:选完原始报告,自动识别盖章页(签字页)并填入;选完盖章报表PDF,自动计算报表替换范围。识别结果在公共配置区底部蓝色提示行显示。

---

## 三步流程

### ① 准备上传版
1. 选原始报告 → **自动识别盖章页**(可手动改)
2. 选盖章报表PDF → **自动计算报表替换范围**(可手动改)
3. 选事务所章、CPA章(主审/复核)、盖章附注PDF
4. 点「生成上传报告」→ 加盖 CPA/事务所章 + 拼接报表/附注
5. 输出 `处理完成_<原始报告名>.pdf`,自动跳到步骤②

### ② 等待赋码(提示页)
- 显示生成的上传报告路径,点「📂 打开所在文件夹」快速取文件
- 手动到注协系统:上传 → 等待赋码 → 下载赋码报告
- 回来点**「▶ 下一步:处理赋码版」**进入步骤③

> 💡 步骤③默认锁定,必须从步骤②点「下一步」解锁。这样避免误操作跳步。

### ③ 处理赋码版
1. 选赋码报告
2. 点「用默认规则填充」自动生成替换规则(盖章页/报表范围/附注末页)
3. 点「生成可打印报告」→ 替换盖章页为无章版 + 保留二维码
4. 输出 `替换完成_<赋码报告名>.pdf`

**二维码怎么保留的**:注协每页底部都有数字签名层(含二维码)。未替换的页原样保留,二维码自动在;被替换的页先抠出该页二维码方块,替换后再贴回右下角。横版报表页按页宽等比缩放。

---

## 安装

需要 Python 3.8+(本机用 3.12)。

```bash
# 在项目目录内创建虚拟环境
python -m venv .venv
source .venv/Scripts/activate      # Git Bash
# 或 .venv\Scripts\activate.bat    # CMD

# 安装依赖
python -m pip install -r requirements.txt
```

**依赖**:`PyMuPDF`、`Pillow`、`numpy`(步骤③抠码用)。

## 运行

```bash
python main.py
```

或双击 `审计报告报备工具.bat`。

---

## 配置

### `seals_config.json`(印章库)
印章库(名称→路径),复用上传项目已调好的参数(公章 4×4cm、CPA 3.4×2.3cm 等)。新增字段:
- `last_used_cpa` / `last_used_firm`:上次选用的印章路径,**打开软件自动选中**(印章固定不变,省得每次重选)

### `config.json`(默认页码)
打开软件即预填的页码(自动识别后会被覆盖):
```json
{
  "seal_page": 5,
  "report_start": 6,
  "report_end": 11,
  "auto_add_last_page_rule": true
}
```
- `seal_page`:盖章页/签字页(1基),选原始报告后自动识别覆盖
- `report_start`/`report_end`:报表替换范围,选盖章报表PDF后自动计算覆盖
- `auto_add_last_page_rule`:步骤③自动追加"最后一页(附注末页)替换规则"

---

## 常见问题

### Q: 保存时报"权限拒绝/文件被占用"?
输出文件正被 PDF 阅读器(WPS/Adobe/浏览器)打开。关闭它,或换文件名保存。

### Q: 步骤③输出PDF提示"签名已修改/无效"?
这是注协数字签名机制决定的(替换页后签名校验失效),但**二维码正常显示、打印正常**,不影响使用。

### Q: 印章位置不对?
印章定位逻辑复用上传项目(事务所名锚点定位)。如需微调,改 `pdf_processor.py` 里的 `FIRM_NAME_CENTER_OFFSET_CHARS` 常量。

### Q: 自动识别盖章页不准?
自动识别扫描前10页找"我们与治理层就..."等标记句。少数非标准格式可能识别不到,此时状态行提示"请手动设置",手动填页码即可。

---

## 项目结构

```
审计报告报备工具/
├── main.py              # 启动入口
├── gui.py               # 步骤导航界面 + 状态编排 + 自动识别
├── step_upload.py       # 步骤①:盖章+拼接(封装 pdf_processor)
├── step_download.py     # 步骤③:替换+保码
├── pdf_processor.py     # 盖章处理类(复用上传项目,去PyPDF2)
├── pdf_common.py        # 共用:坐标转换+友好错误
├── config_manager.py    # 印章库+上次记忆+默认页码
├── app_logging.py       # 日志(含libpng iCCP警告屏蔽)
├── seals_config.json    # 印章库
├── config.json          # 默认页码
├── requirements.txt
├── 审计报告报备工具.bat
└── docs/superpowers/    # 设计文档(spec)+实现计划(plan)
```
