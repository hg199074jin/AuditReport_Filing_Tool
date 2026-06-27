from PIL import Image, ImageDraw
import fitz  # PyMuPDF
import io
import os
from typing import Optional, List, Callable, Tuple
import copy
from app_logging import get_logger

_logger = get_logger(__name__)


class PDFProcessError(Exception):
    """PDF 处理过程中所有可预期错误的基类。

    每个异常实例都带 hint（排查建议），GUI 捕获后展示给用户，帮助非专业用户自助定位问题。
    设计原则：底层方法仍返回 bool（保持原有调用契约），但把失败原因记录到 self.last_error；
    致命错误在 process_pdf 主流程里抛出本异常（或子类），由 GUI 统一弹窗。
    """

    def __init__(self, message, hint=""):
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self):
        if self.hint:
            return f"{self.message}\n\n建议排查：{self.hint}"
        return self.message


class PDFLoadError(PDFProcessError):
    """PDF 文件加载失败（文件占用 / 损坏 / 路径无效 / 不是有效 PDF）。"""


class SealLoadError(PDFProcessError):
    """印章图片加载失败（路径失效 / 文件已删除 / 不是有效图片）。"""


class PDFMergeError(PDFProcessError):
    """PDF 页面合并或写出失败（权限不足 / 目标文件被占用）。"""


class PDFProcessor:
    # 印章默认位置（单位：预览渲染图的像素坐标，2倍渲染下 A4 约 1190×1684 px）
    # 坐标原点在左上角，x 向右增、y 向下增。
    # 默认按"落款处"版式设定：公章盖事务所名称处，两个会计师章盖 CPA 签字栏右侧上下排列。
    # 用户在预览界面拖拽后，以拖拽到的最终位置为准，这里的值只是初始起点。
    #
    # 说明：这些值是为标准 A4 报告（预览图高约 1684px）估算的；若报告尺寸不同，
    # 可能会有微小偏差，导出时 add_seals_to_page 会做越界保护，预览时也可拖拽调整。
    # （旧版 gui.py 里默认是 company=(250,830)/accountant1=(870,850)/accountant2=(870,1020)，
    #  本次统一数据源时一并更新为更接近真实"落款处"的位置。）
    DEFAULT_SEAL_POSITIONS = {
        'company':    {'x': 220, 'y': 1480},   # 公章：落款事务所名称处（左下区域）
        'accountant1': {'x': 980, 'y': 1500},   # 会计师章1：CPA 签字栏右上
        'accountant2': {'x': 980, 'y': 1580},   # 会计师章2：CPA 签字栏右下
    }

    # 盖章页识别用的文本标记（候选句列表）
    # 这几句通常出现在审计报告中“关键审计事项”或“其他事项”段落的开头,盖章页常在
    # 报告正文中部偏后(整体文件前 10 页内)。任一句命中即视为找到盖章页。
    # 匹配策略：先做文本归一化(去空白/全半角转换/去标点),再按字符相似度(默认 0.8 阈值)模糊匹配。
    SEAL_PAGE_MARKERS = [
        "我们与治理层就计划的审计范围、时间安排和重大审计发现等事项进行沟通，包括沟通我们在审计中识别出的值得关注的内部控制缺陷。",
        "对管理层使用持续经营假设的恰当性得出结论。同时，根据获取的审计证据，就可能导致对贵公司持续经营能力产生重大疑虑的事项或情况是否存在重大不确定性得出结论。",
        "评价财务报表的总体列报、结构和内容（包括披露），并评价财务报表是否公允反映相关交易和事项。",
    ]
    # 模糊匹配阈值：候选句的字符在归一化后被页内归一化文本覆盖比例,达到此值即视为命中
    SEAL_PAGE_MATCH_THRESHOLD = 0.8
    # 在原始 PDF 前 N 页内查找（盖章页通常在前 10 页）
    SEAL_PAGE_SEARCH_MAX = 10

    # —— 文字锚点定位常量（替代固定坐标,让印章位置自适应不同版式）——
    # 事务所名称锚点(匹配页面文字,用于公章定位)
    FIRM_NAME_KEYWORDS = ["河南大梁会计师事务所"]
    # 公章中心在事务所名关键词内的横向偏移(单位: 字符数, 正=往右)。
    # 关键词"河南大梁会计师事务所"共 10 字, 几何中心是第 5 字"计"。
    # 用户希望公章中心落在"师"字(第 7 字), 故往右偏 1.5 个字。
    # 若报告版式变化导致公章横向略偏, 改这个常量微调即可(±0.5 ≈ 半个字宽)。
    FIRM_NAME_CENTER_OFFSET_CHARS = 1.5
    # 事务所公章位置选项（用于定位"（盖章）"）
    FIRM_STAMP_TEXT_KEYWORDS = ["盖章"]
    # CPA 签字位关键词(优先匹配带"中国"的)
    CPA_KEYWORDS_PRIMARY = ["中国注册会计师"]
    # 备用 CPA 关键词(如果主关键词没找到 2 个,再尝试这个)
    CPA_KEYWORDS_FALLBACK = ["注册会计师"]
    # —— 印章物理尺寸(厘米)——
    # 用户要求实际盖章大小: 公章 4×4cm, CPA 章 3.4×2.3cm(长边×短边)。
    # fitz PDF 坐标单位是"点"(1/72 英寸), 1 cm = 72/2.54 ≈ 28.3465 点。
    # 不再用"文字高度×倍数"估算, 改用固定物理尺寸, 保证导出 PDF 里印章大小精确、
    # 且预览所见即导出所得(预览2倍渲染图上尺寸 = cm×CM_TO_PT×2)。
    CM_TO_PT = 72.0 / 2.54
    SEAL_PHYSICAL_SIZE_CM = {
        'company':    {'long': 4.0, 'short': 4.0},   # 公章: 正方形 4×4cm
        'accountant': {'long': 3.4, 'short': 2.3},   # CPA章: 3.4×2.3cm(长×短)
    }

    def __init__(self):
        self.original_pdf = None
        self.stamp_pdf_fitz = None  # 盖章报表(fitz)
        self.appendix_pdf_fitz = None  # 盖章附注(fitz)
        self.company_seal = None
        self.accountant_seals = []
        self.page_image = None
        self.pdf_doc = None  # PyMuPDF文档对象
        self.current_page = None  # 当前显示的页面（从0开始），None 表示尚未加载
        # 印章位置：初始为 None，加载印章时尚未拖拽则使用 DEFAULT_SEAL_POSITIONS
        self.seal_positions = {
            'company': {'x': None, 'y': None},
            'accountant1': {'x': None, 'y': None},
            'accountant2': {'x': None, 'y': None}
        }
        # 最近一次失败的详细原因（GUI 弹窗会读取它给用户排查建议）
        self.last_error = None
        # 最近一次成功处理后的输出文件路径（供 GUI 展示）
        self.last_output_path = None

    def _record_error(self, error_type, message, hint):
        """统一记录失败原因到 self.last_error，供 GUI 读取后展示给用户。

        error_type: 异常类（PDFLoadError / SealLoadError / PDFMergeError）
        message: 具体错误信息（含原始异常文本）
        hint: 给非专业用户的排查建议
        """
        err = error_type(message, hint)
        self.last_error = err
        # 同时写日志（留底，便于开发者排查；用户看不到这里）
        _logger.error("%s | 排查建议: %s", message, hint)

    def load_original_pdf(self, pdf_path: str) -> bool:
        """加载原始PDF文件"""
        try:
            self.pdf_doc = fitz.open(pdf_path)
            # 首次加载时 current_page 为 None,需显式渲染第 1 页(索引 0);
            # 否则 page_image 一直为 None,后续 compute_seal_positions 会抛
            # "预览图未渲染"错误(而 _auto_detect_seal_page 未捕获该异常)。
            first_page = self.current_page if self.current_page is not None else 0
            self.update_preview_page(first_page)
            return True
        except Exception as e:
            self._record_error(
                PDFLoadError,
                f"加载原始PDF失败：{e}",
                "文件可能被其他程序占用（请关闭 Word / Adobe Reader），"
                "或路径含特殊字符、文件已损坏、不是有效的 PDF。"
            )
            return False

    def update_preview_page(self, page_num: int) -> bool:
        """更新预览页面。失败时静默返回 False（预览失败不应弹窗打扰用户）。"""
        try:
            if self.pdf_doc and 0 <= page_num < len(self.pdf_doc):
                self.current_page = page_num
                # 获取PDF页面
                page = self.pdf_doc[page_num]
                # 将PDF页面渲染为图像
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2倍缩放以获得更好的质量
                img_data = pix.tobytes("png")
                self.page_image = Image.open(io.BytesIO(img_data))
                return True
        except Exception as e:
            # 预览渲染失败不影响最终处理，不污染 last_error（那是给处理流程用的），
            # 仅写 debug 日志留底。
            _logger.debug("预览渲染失败（不影响最终处理）：%s", e)
        return False

    def get_total_pages(self) -> int:
        """获取PDF总页数"""
        return len(self.pdf_doc) if self.pdf_doc else 0

    @staticmethod
    def _normalize_text(text: str) -> str:
        """文本归一化,用于印章页文本匹配。

        处理:
        - 去除所有空白字符(空格/制表符/换行/全角空格等)
        - 全角字符 → 半角(常见标点: , . ( ) , ; : ! ? 等)
        - 中文标点统一 → 英文标点(便于跨版式匹配,符号差异不影响语义)
        - 去除常见标点(逗号、句号、引号、括号、分号、冒号、问号、感叹号、破折号、顿号、书名号)
        - 转小写(对中文无影响,主要照顾可能的英文混入)

        归一化后,"我们对...,时间安排和重大..."与"我们对,时间安排和重大..."应能匹配上。
        """
        if not text:
            return ""
        # 全角字符 → 半角（ord 范围: 全角空格 0x3000, 全角数字/字母/符号 0xFF01-0xFF5E）
        result_chars = []
        for ch in text:
            code = ord(ch)
            if 0xFF01 <= code <= 0xFF5E:
                # 全角字符 → 对应半角
                result_chars.append(chr(code - 0xFEE0))
            elif code == 0x3000:
                # 全角空格 → 半角空格
                result_chars.append(' ')
            else:
                result_chars.append(ch)
        normalized = ''.join(result_chars)
        # 去除所有空白
        normalized = ''.join(normalized.split())
        # 转小写
        normalized = normalized.lower()
        # 去除常见标点
        for punct in ',.()()""\'\';:!?、。,.;:!?''""''()【】《》""''-—…':
            normalized = normalized.replace(punct, '')
        return normalized

    def _marker_match_ratio(self, page_text: str, marker: str) -> float:
        """计算 marker 在 page_text 里的覆盖率。

        返回: ratio ∈ [0, 1]。ratio = (marker 在 page_text 中作为子序列连续出现的长度 / marker 长度)。
        用滑动窗口找 page_text 中与 marker 归一化后最长的公共子串长度,然后除以 marker 长度。

        为简化实现,使用 Python 内置的序列匹配算法(类似 LCS 但用滑动窗口找最长公共子串):
        """
        n_text = self._normalize_text(page_text)
        n_marker = self._normalize_text(marker)
        if not n_marker:
            return 0.0
        if n_marker in n_text:
            # 完整子串命中,直接 1.0
            return 1.0
        # 退化:滑窗找最长公共子串(O(m*n),m 和 n 都是归一化后的字符数,通常几十~几百,够用)
        max_match = 0
        m, n = len(n_marker), len(n_text)
        if m > n:
            # marker 比页文本还长,不可能 100% 覆盖,直接用整段比较
            # 退化为简单计数
            common = sum(1 for c in n_marker if c in n_text)
            return common / m
        for i in range(n - m + 1):
            window = n_text[i:i + m]
            # 计算 marker 与 window 的逐位相同字符数
            same = sum(1 for a, b in zip(n_marker, window) if a == b)
            if same > max_match:
                max_match = same
                if max_match == m:
                    break
        return max_match / m

    def find_seal_page(self, max_pages: Optional[int] = None,
                       threshold: Optional[float] = None) -> Optional[int]:
        """在前 N 页中查找包含“盖章页标记句”的页(返回 1 基页码)。

        用于 GUI 在用户选择原始 PDF 后,自动识别盖章页码,免去人工翻看。
        用户仍可在界面手工调整自动识别的结果(填回页码输入框)。

        参数:
            max_pages: 在前几页里查找,默认 SEAL_PAGE_SEARCH_MAX (10)。
            threshold: 模糊匹配阈值,默认 SEAL_PAGE_MATCH_THRESHOLD (0.8)。

        返回:
            找到的 1 基页码(>=1);未找到返回 None。
        """
        if self.pdf_doc is None:
            return None
        max_n = max_pages if max_pages is not None else self.SEAL_PAGE_SEARCH_MAX
        th = threshold if threshold is not None else self.SEAL_PAGE_MATCH_THRESHOLD

        total = len(self.pdf_doc)
        search_n = min(max_n, total)
        for i in range(search_n):
            try:
                page = self.pdf_doc[i]
                text = page.get_text("text")
            except Exception as e:
                _logger.debug("提取第 %d 页文本失败,跳过: %s", i + 1, e)
                continue
            for marker in self.SEAL_PAGE_MARKERS:
                ratio = self._marker_match_ratio(text, marker)
                if ratio >= th:
                    _logger.info("自动识别盖章页: 第 %d 页(匹配率 %.0f%%, 标记: \"%s...\")",
                                 i + 1, ratio * 100, marker[:20])
                    return i + 1
        _logger.info("前 %d 页内未找到盖章页标记(阈值 %.0f%%)", search_n, th * 100)
        return None

    def find_seal_anchors(self, page: Optional[int] = None) -> dict:
        """在盖章页提取文字锚点(事务所名/CPA 签字位),用于自动定位印章坐标。

        参数:
            page: 1 基页码,默认从 find_seal_page() 自动获取。

        返回 dict(键):
            page: 实际使用的 1 基页码
            firm_box: {x0, y0, x1, y1, width, height, text} 或 None(事务所名)
            firm_stamp_box: 同上,"（盖章）" 位置(可选,可能 None)
            cpa_boxes: list[box],所有匹配 "中国注册会计师" 的 box
            primary_cpa_box: cpa_boxes 中 y 最大的(最下方)= 主审 CPA
            review_cpa_box: cpa_boxes 中 y 第二大的 = 复核 CPA
        异常:
            PDFProcessError: 必须找到 2 个 CPA 签字位(决策 4),否则抛出。
        """
        if self.pdf_doc is None:
            raise PDFProcessError("PDF 未加载", "请先加载原始报告 PDF。")

        if page is None:
            page = self.find_seal_page()
            if page is None:
                raise PDFProcessError(
                    "未找到盖章页,无法提取印章锚点。",
                    "请确认报告 PDF 是标准版式(含\"关键审计事项\"段),"
                    "或手动在盖章页码框里填入正确页码。"
                )

        pdf_page = self.pdf_doc[page - 1]
        try:
            text_dict = pdf_page.get_text("dict")
        except Exception as e:
            raise PDFProcessError(
                f"提取盖章页文字失败：{e}",
                "盖章页可能为扫描件(无文字层),无法自动定位。"
                "可继续手动拖拽印章调整位置。"
            )

        # 遍历所有 spans,按归一化文本匹配关键词
        spans = []  # 收集所有匹配到的 span:{x0,y0,x1,y1,text_normalized,text_raw,size}
        for block in text_dict.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    raw = span.get("text", "").strip()
                    if not raw:
                        continue
                    norm = self._normalize_text(raw)
                    bbox = span.get("bbox", (0, 0, 0, 0))
                    spans.append({
                        "x0": bbox[0], "y0": bbox[1],
                        "x1": bbox[2], "y1": bbox[3],
                        "width": bbox[2] - bbox[0],
                        "height": bbox[3] - bbox[1],
                        "text_raw": raw, "text_norm": norm,
                        "size": span.get("size", 10.0),
                    })

        # 1) 找事务所名(firm_box):第一个匹配的 span
        firm_box = None
        for kw in self.FIRM_NAME_KEYWORDS:
            kw_norm = self._normalize_text(kw)
            for sp in spans:
                if kw_norm in sp["text_norm"]:
                    firm_box = sp
                    break
            if firm_box:
                break

        # 2) 找"（盖章）"位置(firm_stamp_box):在 firm_box 下方 50pt 内的"盖章"span
        firm_stamp_box = None
        if firm_box:
            for kw in self.FIRM_STAMP_TEXT_KEYWORDS:
                kw_norm = self._normalize_text(kw)
                for sp in spans:
                    if kw_norm in sp["text_norm"]:
                        # 必须在 firm_box 附近(同行或略下方)
                        # 范围 -10pt ~ 80pt: 覆盖同行小偏移和稍远的版式(用户原写 50pt,
                        # 实际有同行排列的版式,dy 可能为负;也有跨行 50-80pt 的)
                        dy = sp["y0"] - firm_box["y1"]
                        if -10 <= dy <= 80:
                            firm_stamp_box = sp
                            break
                if firm_stamp_box:
                    break

        # 3) 找所有"中国注册会计师"位置(cpa_boxes)
        cpa_boxes = []
        primary_count = 0  # 记录主关键词命中数(给错误信息用)
        for kw in self.CPA_KEYWORDS_PRIMARY:
            kw_norm = self._normalize_text(kw)
            for sp in spans:
                if kw_norm in sp["text_norm"]:
                    cpa_boxes.append(sp)
                    primary_count += 1
            if len(cpa_boxes) >= 2:
                break

        # 备用:如果主关键词没找够 2 个,再用 "注册会计师" 补充
        fallback_count = 0
        if len(cpa_boxes) < 2:
            for kw in self.CPA_KEYWORDS_FALLBACK:
                kw_norm = self._normalize_text(kw)
                for sp in spans:
                    # 跳过已经收集的(去重:避免同一位置被两次收录)
                    if kw_norm in sp["text_norm"] and not any(
                        sp["x0"] == existing["x0"] and sp["y0"] == existing["y0"]
                        for existing in cpa_boxes
                    ):
                        cpa_boxes.append(sp)
                        fallback_count += 1
                if len(cpa_boxes) >= 2:
                    break

        # 4) 必须有 2 个 CPA 签字位(决策 4:不允许只有一个)
        if len(cpa_boxes) < 2:
            raise PDFProcessError(
                f"在盖章页(第 {page} 页)只找到 {len(cpa_boxes)} 个 CPA 签字位(主关键词 {primary_count} 个 + 备用关键词 {fallback_count} 个),必须有 2 个(主审 + 复核)。",
                "请检查报告 PDF 是否为标准版式(含两个\"中国注册会计师\"签字位),"
                "或手动拖拽印章调整位置。"
            )

        # 5) 排序:从上往下。PyMuPDF 的 y 向下递增,所以 y 小的=更上方
        # 标准审计报告版式: 主审 CPA 在上(签字栏第一行),复核 CPA 在下(第二行)。
        # cpa_boxes[0] = y 最小的(最上方) = 主审 CPA
        # cpa_boxes[1] = y 第二小的(偏下) = 复核 CPA
        cpa_boxes.sort(key=lambda b: b["y0"])

        result = {
            "page": page,
            "firm_box": firm_box,
            "firm_stamp_box": firm_stamp_box,
            "cpa_boxes": cpa_boxes,
            "primary_cpa_box": cpa_boxes[0],
            "review_cpa_box": cpa_boxes[1],
        }
        _logger.info(
            "提取盖章锚点: 页=%d 事务所名=%s (\"盖章\"=%s) CPA 数=%d",
            page,
            firm_box["text_raw"] if firm_box else "未找到",
            firm_stamp_box["text_raw"] if firm_stamp_box else "未找到",
            len(cpa_boxes),
        )
        return result

    def compute_seal_positions(self, anchors: dict,
                               img_size: Optional[Tuple[int, int]] = None) -> dict:
        """根据锚点计算三个印章的左上角坐标(预览渲染图的像素坐标,等比缩放长边)。

        参数:
            anchors: find_seal_anchors() 返回的字典
            img_size: (img_w, img_h) 预览渲染图尺寸(像素)。为 None 时从 self.page_image 取。

        返回:
            { 'company': {'x': x, 'y': y, 'size': long_edge},
              'accountant1': ...,
              'accountant2': ... }
            size 是印章在该坐标下的"长边"像素数(add_seals_to_page 据此等比缩放)

        异常:
            PDFProcessError: 锚点缺失导致无法计算(决策 3: 事务所名缺失则用默认)
            - CPA 锚点缺失已在 find_seal_anchors 阶段抛错,这里不会再缺
            - 事务所名缺失:用 DEFAULT_SEAL_POSITIONS,但 size 兜底为 None(用既有默认大小)

        公式来源:用户提供的"文字锚点定位"规范

        坐标系约定(易碎点,改 render matrix 时要同步改这里):
        - 输入: anchors 里的 bbox 是 fitz 的 PDF 点(72 DPI, 左上原点, y 向下)
        - 输出: x/y/size 是"预览渲染图"的像素坐标(2 倍渲染, A4 约 1190×1684 px)
        - 转换: pt2px = img_w / page_w  (像素 = PDF 点 × pt2px)
        - 依赖: page_image 必须是 2 倍渲染图(update_preview_page 内部用 Matrix(2,2)),
          这与 GUI 预览画布的缩放无关(scale_factor 是后续 preview 显示的二次缩放,
          用户拖拽坐标也是 2 倍图坐标,均一致)
        - 若改动 update_preview_page 的渲染 matrix,必须同步检查本方法是否仍正确
        """
        if img_size is None:
            if self.page_image is None:
                raise PDFProcessError("预览图未渲染,无法计算印章位置。", "请先加载原始 PDF。")
            img_size = self.page_image.size  # (w, h)
        img_w, img_h = img_size
        # 锚点坐标系:PyMuPDF 的 PDF 点(72 DPI),转像素需按渲染 scale
        # page_width / img_w = scale,所以 pdf_pt = pixel * scale
        # 像素 = pdf_pt / scale = pdf_pt * img_w / page_width
        page_w = float(self.pdf_doc[anchors["page"] - 1].rect.width)
        # fitz PDF 坐标 → 预览像素坐标 的换算系数
        # 注意:fitz 的 bbox 是 PDF 点(原点在左上, y 向下);预览图也是左上原点 y 向下,方向一致
        # 所以: 像素坐标 = PDF 点 * (img_w / page_w)
        pt2px = img_w / page_w

        result = {}

        # —— 1. 事务所公章 ——
        # 公章中心定位: 不用 firm_box 整框的几何中心。
        # 因为事务所名所在 span 往往同行还连着"（普通合伙）"甚至"中国注册会计师"
        # (见日志: 事务所名="河南大梁会计师事务所（普通合伙）  中国注册会计师"),
        # 整框中心会偏右、落在"合伙"上。正确做法是按事务所名关键词在 span 文本中的
        # 字符位置(同一 span 内中文等宽),算出"河南大梁会计师事务所"这部分子区间的中心,
        # 让公章正好盖在事务所名上(落在"计师事"附近)。
        # 公章大小固定 4×4cm(用户要求), 不再随事务所名字号缩放
        firm_box = anchors.get("firm_box")
        if firm_box:
            cx = self._firm_name_center_x(firm_box)
            cy = (firm_box["y0"] + firm_box["y1"]) / 2
            # 目标尺寸: 预览像素(2倍图) = 4cm × CM_TO_PT × 2
            firm_w, firm_h = self._get_seal_target_size('company', self.company_seal, unit='px')
            x = int(cx * pt2px - firm_w / 2)
            y = int(cy * pt2px - firm_h / 2)
            x = max(0, min(x, img_w - int(firm_w)))
            y = max(0, min(y, img_h - int(firm_h)))
            result["company"] = {"x": x, "y": y, "size": (firm_w, firm_h)}
        else:
            # 决策 3: 找不到事务所名, 用默认位置, size 同样用物理尺寸
            default = self.DEFAULT_SEAL_POSITIONS["company"]
            firm_w, firm_h = self._get_seal_target_size('company', self.company_seal, unit='px')
            result["company"] = {"x": default["x"], "y": default["y"], "size": (firm_w, firm_h)}
            _logger.warning("未找到事务所名锚点,公章用默认位置")

        # —— 2/3. CPA 章(固定 3.4×2.3cm), 横向右偏签字位 ——
        def _place_cpa(cpa_box, key):
            src_img = self.accountant_seals[int(key[-1]) - 1] if len(self.accountant_seals) >= int(key[-1]) else None
            cp_w, cp_h = self._get_seal_target_size(key, src_img, unit='px')
            # 横向: 签字位右边界 + 文字高度×2.40; 纵向: 居中偏下 0.55×文字高度
            cx = cpa_box["x1"] + cpa_box["height"] * 2.40
            cy = (cpa_box["y0"] + cpa_box["y1"]) / 2 + cpa_box["height"] * 0.55
            x = int(cx * pt2px - cp_w / 2)
            y = int(cy * pt2px - cp_h / 2)
            x = max(0, min(x, img_w - int(cp_w)))
            y = max(0, min(y, img_h - int(cp_h)))
            return {"x": x, "y": y, "size": (cp_w, cp_h)}

        result["accountant1"] = _place_cpa(anchors["primary_cpa_box"], "accountant1")
        result["accountant2"] = _place_cpa(anchors["review_cpa_box"], "accountant2")

        _logger.info(
            "计算印章位置: 公章=(%d,%d,%.0f×%.0fpx) 主审CPA=(%d,%d,%.0f×%.0fpx) 复核CPA=(%d,%d,%.0f×%.0fpx)",
            result["company"]["x"], result["company"]["y"],
            result["company"]["size"][0], result["company"]["size"][1],
            result["accountant1"]["x"], result["accountant1"]["y"],
            result["accountant1"]["size"][0], result["accountant1"]["size"][1],
            result["accountant2"]["x"], result["accountant2"]["y"],
            result["accountant2"]["size"][0], result["accountant2"]["size"][1],
        )
        return result

    def load_stamp_pdf(self, pdf_path: str) -> bool:
        """加载盖章报表PDF。

        用 PyMuPDF(fitz) 打开(整合项目已去掉 PyPDF2 fallback,
        fitz 兼容性足够,能读出"Boolean object"等结构)。
        加载后存到 self.stamp_pdf_fitz (fitz.Document)。
        """
        try:
            self.stamp_pdf_fitz = fitz.open(pdf_path)
            return True
        except Exception as e:
            self._record_error(
                PDFLoadError,
                f"加载盖章报表PDF失败：{e}",
                "文件可能被其他程序占用、路径含特殊字符、或不是有效的 PDF。"
            )
            self.stamp_pdf_fitz = None
            return False

    def load_appendix_pdf(self, pdf_path: str) -> bool:
        """加载盖章附注PDF(用 fitz)。"""
        try:
            self.appendix_pdf_fitz = fitz.open(pdf_path)
            return True
        except Exception as e:
            self._record_error(
                PDFLoadError,
                f"加载盖章附注PDF失败：{e}",
                "文件可能被其他程序占用、路径含特殊字符、或不是有效的 PDF。"
            )
            self.appendix_pdf_fitz = None
            return False

    def load_seals(self, company_seal_path: Optional[str], accountant_seal_paths: List[Optional[str]]) -> bool:
        """加载印章图片"""
        try:
            # 先校验路径是否存在（给比"打开失败"更具体的提示）
            missing = []
            for label, p in [('公章', company_seal_path),
                             ('会计师章1', accountant_seal_paths[0] if len(accountant_seal_paths) > 0 else None),
                             ('会计师章2', accountant_seal_paths[1] if len(accountant_seal_paths) > 1 else None)]:
                if p and not os.path.exists(p):
                    missing.append(f"{label}（{p}）")
            if missing:
                raise FileNotFoundError("以下印章图片文件不存在：\n  - " + "\n  - ".join(missing))

            # 保存当前的印章位置（用深拷贝，避免后续原地修改 pos 字典时误判是否已拖拽）
            current_positions = copy.deepcopy(self.seal_positions)

            if company_seal_path:
                self.company_seal = Image.open(company_seal_path)

            self.accountant_seals = []
            for i, path in enumerate(accountant_seal_paths):
                if path:
                    self.accountant_seals.append(Image.open(path))

            # 恢复之前设置的位置；若用户尚未拖拽过（坐标为 None），则使用统一默认值
            for seal_type, pos in current_positions.items():
                if pos['x'] is not None and pos['y'] is not None:
                    self.seal_positions[seal_type] = pos
                else:
                    default = self.DEFAULT_SEAL_POSITIONS.get(seal_type)
                    if default:
                        self.set_seal_position(seal_type, default['x'], default['y'])

            return True
        except FileNotFoundError as e:
            self._record_error(
                SealLoadError,
                f"印章图片加载失败：{e}",
                "印章图片可能被移动或删除。请点击\"管理\"按钮，重新选择对应的印章图片文件。"
            )
            return False
        except Exception as e:
            self._record_error(
                SealLoadError,
                f"印章图片加载失败：{e}",
                "图片可能已损坏或格式不被支持（建议使用 PNG/JPG）。请到印章管理重新选择。"
            )
            return False
            
    def set_seal_position(self, seal_type: str, x: int, y: int) -> bool:
        """设置印章的默认位置
        
        参数:
            seal_type: 印章类型 ('company', 'accountant1', 'accountant2')
            x: X坐标（像素）
            y: Y坐标（像素）
        """
        if seal_type in self.seal_positions:
            # 只更新 x/y,保留 size 等其他字段（文字锚点定位时写入的 size 不能被拖拽覆盖,
            # 否则用户拖一下印章会回退到固定 100/80px,违反决策 5）
            self.seal_positions[seal_type]['x'] = x
            self.seal_positions[seal_type]['y'] = y
            return True
        return False

    def _get_seal_target_size(self, seal_type, source_image, unit='pt'):
        """统一计算印章目标尺寸(三个用途共用: 预览/定位/盖章)。

        物理尺寸(用户要求): 公章 4×4cm, CPA 章 3.4×2.3cm(长边×短边)。
        横放/竖放按印章图片自身宽高比: 图片横长方形(long=宽,short=高);
        图片竖长方形(long=高,short=宽);近似正方形则按图片比例套用长边×短边。

        参数:
            seal_type: 'company' 或 'accountant1'/'accountant2'
            source_image: PIL.Image, 用于判断横竖放
            unit: 'pt' 返回 fitz PDF 点(导出用); 'px' 返回预览渲染像素(2倍图)

        返回:
            (w, h) 元组, 单位由 unit 决定
        """
        cat = 'company' if seal_type == 'company' else 'accountant'
        cm = self.SEAL_PHYSICAL_SIZE_CM[cat]
        scale = self.CM_TO_PT if unit == 'pt' else self.CM_TO_PT * 2.0
        long_pt = cm['long'] * scale
        short_pt = cm['short'] * scale
        if source_image is None:
            return long_pt, short_pt  # 无图兜底: 按横放
        img_w, img_h = source_image.size
        # 图片自身宽>高 → 横放(长边当宽); 否则竖放(长边当高)
        if img_w >= img_h:
            return long_pt, short_pt
        return short_pt, long_pt

    def _firm_name_center_x(self, firm_box) -> float:
        """计算事务所名(不含"(普通合伙)""中国注册会计师"等同行附加文字)的水平中心 x。

        背景: 提取到的事务所名 span 文本往往是 "河南大梁会计师事务所（普通合伙）  中国注册会计师"
        (同一行被并进了一个 span), 整框中心会偏右、落在"合伙"上。用户希望公章正好盖在
        事务所名本身(约落在"计师事"附近)。

        做法: 在 span 文本里找出事务所名关键词(如"河南大梁会计师事务所")的字符索引区间,
        同一 span 内中文等宽, 按字符比例把索引区间映射成 x 坐标, 取区间中心,
        再按 FIRM_NAME_CENTER_OFFSET_CHARS 做横向微调(正=往右, 单位=字宽)。
        让公章正好盖在事务所名上(按用户校准落在"师"字)。找不到关键词时回退为整框几何中心。
        """
        x0, y0, x1, y1 = firm_box["x0"], firm_box["y0"], firm_box["x1"], firm_box["y1"]
        raw = firm_box.get("text_raw", "")
        if not raw or x1 <= x0:
            return (x0 + x1) / 2.0
        char_w = (x1 - x0) / max(1, len(raw))  # 单个字符宽度(span 等宽假设)
        # 用第一个匹配到的事务所名关键词定位字符区间
        for kw in self.FIRM_NAME_KEYWORDS:
            start = raw.find(kw)
            if start >= 0:
                end = start + len(kw)
                # 关键词几何中心字符位置 + 横向偏移(用户校准)
                mid_char = (start + end - 1) / 2.0 + self.FIRM_NAME_CENTER_OFFSET_CHARS
                cx = x0 + char_w * (mid_char + 0.5)
                _logger.debug(
                    "事务所名子区间定位: 关键词'%s' 在 '%s' 内 [%d:%d], 偏移%.1f字, 中心x=%.1f",
                    kw, raw, start, end, self.FIRM_NAME_CENTER_OFFSET_CHARS, cx,
                )
                return cx
        # 回退: 整框几何中心
        return (x0 + x1) / 2.0
        
    def get_preview_image(self, scale: float = 0.5) -> Optional[Image.Image]:
        """获取预览图像(印章总是画在当前预览页上)。

        印章位置参数 (seal_positions[*].x/y) 是基于当前 page_image 算出的(通常在盖章页
        由锚点定位,或用户拖拽调整)。只要用户只在盖章页预览,印章位置就准确。
        """
        if self.page_image:
            preview = self.page_image.copy()

            img_w, img_h = preview.size
            # 公章
            if self.company_seal:
                company_pos = self.seal_positions['company']
                if company_pos['x'] is not None and company_pos['y'] is not None:
                    # 预览尺寸 = 物理尺寸(cm→点→2倍渲染像素), 与导出一致(所见即所得)
                    tw, th = self._get_seal_target_size('company', self.company_seal, unit='px')
                    seal_preview = self._resize_seal_exact(self.company_seal.copy(), tw, th)
                    px, py = self._clamp_pos(company_pos, seal_preview.size, img_w, img_h)
                    preview.paste(seal_preview, (px, py), seal_preview)

            for i, seal in enumerate(self.accountant_seals):
                if seal and i < 2:  # 确保只处理前两个印章
                    key = f'accountant{i+1}'
                    pos = self.seal_positions[key]
                    if pos['x'] is not None and pos['y'] is not None:
                        tw, th = self._get_seal_target_size(key, seal, unit='px')
                        seal_preview = self._resize_seal_exact(seal.copy(), tw, th)
                        px, py = self._clamp_pos(pos, seal_preview.size, img_w, img_h)
                        preview.paste(seal_preview, (px, py), seal_preview)
            
            # 缩放预览图像
            width, height = preview.size
            new_size = (int(width * scale), int(height * scale))
            preview = preview.resize(new_size)
            return preview
        return None

    def _resize_seal(self, seal_image, target_size):
        """调整印章大小"""
        if seal_image.mode != 'RGBA':
            seal_image = seal_image.convert('RGBA')
        aspect = seal_image.size[0] / seal_image.size[1]
        if aspect > 1:
            new_size = (target_size, int(target_size / aspect))
        else:
            new_size = (int(target_size * aspect), target_size)
        return seal_image.resize(new_size)

    def _resize_seal_exact(self, seal_image, target_w, target_h):
        """把印章缩放到精确的目标尺寸(target_w, target_h),保留透明背景。

        用于按物理尺寸(cm→点→像素)渲染,保证预览与导出大小完全一致。
        """
        if seal_image.mode != 'RGBA':
            seal_image = seal_image.convert('RGBA')
        return seal_image.resize((int(round(target_w)), int(round(target_h))))

    def _clamp_pos(self, pos, seal_size, img_w, img_h):
        """把印章左上角坐标限制在画布内，避免贴出边界看不见。

        pos: {'x','y'} 印章左上角坐标；seal_size: (w,h) 印章尺寸；img_w/img_h: 画布宽高。
        返回 (x, y) 限制后的坐标。
        """
        x = max(0, min(pos['x'], img_w - seal_size[0]))
        y = max(0, min(pos['y'], img_h - seal_size[1]))
        return x, y
    
    def add_seals_to_page(self, out_doc: "fitz.Document", page_index_in_out: int,
                          src_doc: "fitz.Document", page_index_in_src: int) -> bool:
        """在 fitz 输出文档的指定页上叠加印章(完全用 fitz 操作,不再用 PyPDF2)。

        参数:
            out_doc: fitz 输出文档(由 process_pdf 创建)
            page_index_in_out: 输出文档中的页索引(0 基)
            src_doc: 源 fitz 文档(原始 PDF,用于取底图尺寸)
            page_index_in_src: 源文档中的页索引(0 基,与 out_doc 中对应页内容相同)

        实现说明:
        - 不再需要"fitz → 转 PDF → PyPDF2 merge"桥接(那是早期 PyPDF2 时代的折中)。
        - 现在直接用 out_doc[page_index_in_out] 调 insert_image(overlay=True)
          把印章盖在该页内容之上。
        - 印章位置 (x, y) 来自 self.seal_positions(预览坐标系,基于 page_image)。
          需要按 src_page.rect.width / page_image.width 的比例换算成 fitz 坐标。
        """
        try:
            if not (0 <= page_index_in_out < len(out_doc)):
                raise Exception(f"输出页索引 {page_index_in_out} 超出范围")
            if not (0 <= page_index_in_src < len(src_doc)):
                raise Exception(f"源页索引 {page_index_in_src} 超出范围")

            out_page = out_doc[page_index_in_out]
            src_page = src_doc[page_index_in_src]
            page_width = float(src_page.rect.width)
            page_height = float(src_page.rect.height)

            # 预览渲染图尺寸 → fitz 坐标换算系数
            img_w, img_h = self.page_image.size
            scale = page_width / img_w  # 像素→fitz 点 (2 倍渲染下约 0.5)

            for seal_type, pos in self.seal_positions.items():
                if pos['x'] is None or pos['y'] is None:
                    continue

                if seal_type == 'company' and self.company_seal:
                    seal_image = self.company_seal
                elif seal_type.startswith('accountant') and len(self.accountant_seals) > int(seal_type[-1]) - 1:
                    seal_image = self.accountant_seals[int(seal_type[-1]) - 1]
                else:
                    continue

                # 印章目标尺寸用固定物理尺寸(cm→点), 不用图片原始像素。
                # 这样导出 PDF 里印章就是精确的 4×4cm / 3.4×2.3cm, 且与预览一致。
                # 横放/竖放由 _get_seal_target_size 按图片宽高比判定。
                seal_w_pt, seal_h_pt = self._get_seal_target_size(seal_type, seal_image, unit='pt')
                seal_bytes = io.BytesIO()
                seal_image.save(seal_bytes, format='PNG')
                try:
                    # 左上角坐标(用户预览中看到的位置, 预览像素→fitz 点)
                    x = pos['x'] * scale
                    y = pos['y'] * scale
                    # 越界保护
                    x = max(0, min(x, page_width - seal_w_pt))
                    y = max(0, min(y, page_height - seal_h_pt))
                    out_page.insert_image(
                        fitz.Rect(x, y, x + seal_w_pt, y + seal_h_pt),
                        stream=seal_bytes.getvalue(),
                        overlay=True,       # 印章盖在文字上方
                    )
                finally:
                    seal_bytes.close()

            return True

        except Exception as e:
            self._record_error(
                PDFMergeError,
                f"添加印章时出错：{e}",
                "可能是该页内容特殊或印章图片异常。可尝试在预览中微调印章位置后再试。"
            )
            return False

    def process_pdf(self, original_pdf_path: str, stamp_pdf_path: str, appendix_pdf_path: str,
                    company_seal_path: str, accountant_seal_paths: List[Optional[str]],
                    stamp_start_page: int, stamp_end_page: int, seal_page: int,
                    progress_cb: Optional[Callable[[int, str], None]] = None) -> bool:
        """处理PDF文件并保存，支持自定义替换页码范围和盖章页码。

        参数:
            original_pdf_path: 原始报告 PDF 路径
            stamp_pdf_path: 盖章报表 PDF 路径（用于替换中间页）
            appendix_pdf_path: 盖章附注 PDF 路径（用于替换最后一页）
            company_seal_path: 公章图片路径
            accountant_seal_paths: 会计师章图片路径列表（2 个，元素可为 None）
            stamp_start_page / stamp_end_page: 要替换为“盖章报表”的页码范围（1 基）
            seal_page: 盖章页码（1 基）
            progress_cb: 可选进度回调，签名 progress_cb(percent: int, stage: str)。
                         GUI 在后台线程调用时传入，用于实时更新进度条。percent 取值 0~100。

        返回:
            成功返回 True。
        抛出:
            PDFProcessError（或其子类）：任何失败都抛出带排查建议（hint）的异常，
            由调用方捕获并向用户展示。
        """
        try:
            # —— 1. 加载各文件（每步校验成功，失败则带上已记录的原因抛出）——
            if progress_cb: progress_cb(5, "加载原始 PDF")
            if not self.load_original_pdf(original_pdf_path):
                raise self.last_error or PDFLoadError("加载原始PDF失败")

            if progress_cb: progress_cb(15, "加载盖章报表")
            if not self.load_stamp_pdf(stamp_pdf_path):
                raise self.last_error or PDFLoadError("加载盖章报表PDF失败")

            if progress_cb: progress_cb(25, "加载盖章附注")
            if not self.load_appendix_pdf(appendix_pdf_path):
                raise self.last_error or PDFLoadError("加载盖章附注PDF失败")

            if progress_cb: progress_cb(35, "加载印章")
            if not self.load_seals(company_seal_path, accountant_seal_paths):
                raise self.last_error or SealLoadError("加载印章图片失败")

            # —— 2. 页码合法性校验（在动笔写出前拦截，避免半成品文件）——
            total_pages = len(self.pdf_doc)  # 原始 PDF 用 fitz 打开(.pdf_doc)
            if total_pages < 2:
                raise PDFMergeError(
                    f"原始PDF总页数不足（仅 {total_pages} 页），无法按当前规则处理。",
                    "至少需要 2 页（要替换最后一页为附注）。"
                )
            if not (1 <= seal_page <= total_pages):
                raise PDFMergeError(
                    f"盖章页码 {seal_page} 超出原始PDF总页数 {total_pages}。",
                    "请在\"页面设置\"里把盖章页码改到 1~总页数 范围内。"
                )
            if not (1 <= stamp_start_page <= stamp_end_page):
                raise PDFMergeError(
                    f"替换页码范围不合法：起始 {stamp_start_page}、结束 {stamp_end_page}。",
                    "起始页应 ≤ 结束页，且都 ≥ 1。"
                )
            if stamp_end_page >= total_pages:
                raise PDFMergeError(
                    f"替换结束页码 {stamp_end_page} 超过原始PDF倒数第二页（总页数 {total_pages}）。",
                    f"替换范围不能覆盖最后一页（最后一页要留给附注）。请把结束页改到 ≤ {total_pages - 1}。"
                )

            # —— 3. 组装页面（完全用 fitz, 不用 PyPDF2）——
            # 优先用 fitz 打开的原始 PDF;若只有 PyPDF2 版,临时用 fitz 重新打开做底图
            original_fitz = self.pdf_doc  # load_original_pdf 已经用 fitz 打开
            if original_fitz is None:
                # fallback 情况(理论不会发生, load_original_pdf 总用 fitz)
                raise PDFMergeError("内部错误: 原始 PDF 未加载")

            out_doc = fitz.open()  # 输出文档(空白)

            if progress_cb: progress_cb(40, "处理前置页面")
            # 复制替换范围前的页面（包含盖章页）
            for i in range(stamp_start_page - 1):
                out_doc.insert_pdf(original_fitz, from_page=i, to_page=i)
                if (i + 1) == seal_page:
                    # 在刚插入的页(索引 = i)上盖章
                    if not self.add_seals_to_page(out_doc, i, original_fitz, i):
                        raise self.last_error or PDFMergeError("添加印章失败")

            if progress_cb: progress_cb(60, "替换盖章报表页")
            # 替换指定范围的页面(整合项目已去掉 PyPDF2,只用 fitz)
            for i in range(stamp_start_page - 1, stamp_end_page):
                idx = i - (stamp_start_page - 1)
                if self.stamp_pdf_fitz is not None:
                    if idx < len(self.stamp_pdf_fitz):
                        out_doc.insert_pdf(self.stamp_pdf_fitz, from_page=idx, to_page=idx)

            if progress_cb: progress_cb(75, "处理后续页面")
            # 复制剩余页面
            for i in range(stamp_end_page, total_pages - 1):
                out_doc.insert_pdf(original_fitz, from_page=i, to_page=i)
            # 用附注的全部页面替换原始 PDF 的最后一页(多页附注)
            if self.appendix_pdf_fitz is not None:
                for k in range(len(self.appendix_pdf_fitz)):
                    out_doc.insert_pdf(self.appendix_pdf_fitz, from_page=k, to_page=k)

            # —— 4. 写出文件(用 fitz.save, 不用 PyPDF2)——
            if progress_cb: progress_cb(90, "保存文件")
            output_path = os.path.join(os.path.dirname(original_pdf_path),
                                       f"处理完成_{os.path.basename(original_pdf_path)}")
            out_doc.save(output_path, garbage=4, deflate=True)  # 压缩减小输出文件大小
            out_doc.close()

            if progress_cb: progress_cb(100, "完成")
            self.last_output_path = output_path
            _logger.info("PDF 处理完成，输出: %s", output_path)
            return True
        except PDFProcessError:
            # 已是带 hint 的自定义异常，直接向上抛（GUI 会展示 message + hint）
            raise
        except PermissionError as e:
            raise PDFMergeError(
                f"保存文件失败（无写入权限）：{e}",
                "目标目录可能只读，或输出文件正被其他程序占用（如已用 Adobe 打开）。"
                "请关闭占用该文件的程序后重试。"
            )
        except Exception as e:
            # 未预期的异常，也包装一层，避免裸 Exception 让用户摸不着头脑
            raise PDFProcessError(
                f"处理PDF时发生未预期错误：{e}",
                "请截图此错误信息反馈，便于排查。可先尝试关闭所有 PDF 相关程序后重试。"
            )