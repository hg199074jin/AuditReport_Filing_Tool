"""步骤③:处理赋码版报告。

把注协赋码后报告里的盖章页(签字页/报表页/附注末页)替换为原始报告的无章版,
并保留每页的二维码,生成可打印的最终报告。

核心机制(已实测验证):
- 注协二维码本质是每页底部的"数字签名层(Signature widget)"。
- 未被替换的页:直接原样保留,签名层二维码自动在。
- 被替换的页:先从注协原页抠出该页的二维码方块(只抠方块本身,不抠整条签名条,
  避免遮挡报表内容),用原PDF页替换后,再把二维码方块贴回右下角原位置。

注意:整合项目不支持插入页规则(spec 3.3),所有页映射统一走 replace_rules。

副作用:输出PDF在阅读器里可能提示"签名已修改/无效"(注协数字签名机制决定),
但二维码正常显示、打印正常(用户已确认可接受)。
"""
import io
import os
import fitz  # PyMuPDF
from PIL import Image
import numpy as np


def extract_qr_strip(cicpa_page, zoom=6.0):
    """从注协PDF某一页抠出底部签名层中的「二维码方块」本身。

    注协每页底部都有一个 Signature 类型的 widget。它的实际区域是一条
    横向的"签名条"(约465pt宽),但二维码方块只占最右侧约51pt宽。
    如果把整条都抠出来贴回,会遮住报表内容——所以这里只抠二维码方块。

    做法:先渲染整个签名条,用像素分析定位二维码方块(黑色像素密集区)
    的精确边界,然后只抠这一小块。每页的二维码各不相同,必须按页抠取。

    参数:
        cicpa_page: 注协PDF的页对象(fitz.Page)
        zoom: 渲染倍率(用于像素分析的中间图,越高定位越准)
    返回:
        (png_bytes, qr_rect, page_rect) —— 二维码方块的PNG + 在注协页上的
        实际坐标 + 注协页本身的尺寸(供贴回时判断横竖版缩放)
        如果该页没有签名widget,返回 None
    """
    widgets = list(cicpa_page.widgets()) if cicpa_page.widgets() else []
    if not widgets:
        return None

    # 签名条widget区域(二维码方块在其中)
    strip_rect = widgets[0].rect
    page_rect = fitz.Rect(cicpa_page.rect)

    # 渲染整个签名条用于像素分析
    pix = cicpa_page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=strip_rect)
    img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")

    # 用numpy统计黑色像素分布,定位二维码方块边界
    # 二维码区域:黑像素密集(每列至少15%是黑的)
    arr = np.array(img)
    bw = (arr < 128).astype(int)
    col_sum = bw.sum(axis=0)  # 按列
    H_px = arr.shape[0]
    col_threshold = H_px * 0.15
    active_cols = [x for x in range(len(col_sum)) if col_sum[x] > col_threshold]

    if active_cols:
        # 找到二维码方块的x范围,加少量留白(quiet zone)
        x0_px, x1_px = min(active_cols), max(active_cols)
        pad = int(H_px * 0.05)  # 约5%的留白
        x0_px = max(0, x0_px - pad)
        x1_px = min(arr.shape[1], x1_px + pad)
        # 转回PDF坐标
        qr_x0 = strip_rect.x0 + x0_px / zoom
        qr_x1 = strip_rect.x0 + x1_px / zoom
        qr_rect = fitz.Rect(qr_x0, strip_rect.y0, qr_x1, strip_rect.y1)
    else:
        # 兜底:像素分析失败时用整条(极少见)
        qr_rect = strip_rect

    # 用更高倍率重新渲染二维码方块本身(保证清晰)
    final_zoom = 8.0
    pix_qr = cicpa_page.get_pixmap(matrix=fitz.Matrix(final_zoom, final_zoom), clip=qr_rect)
    return pix_qr.tobytes("png"), qr_rect, page_rect


def paste_qr_strip(output_page, qr_png, qr_rect, cicpa_page_rect):
    """把抠出的二维码方块贴回输出页的底部原位置。

    自动适应横版/竖版页面:
      - 若输出页与注协原页尺寸一致(常见,都是A4竖版):直接贴回原坐标;
      - 若尺寸不同(如原PDF页是横版报表):按页宽等比缩放二维码,
        贴到输出页底部,右边距与原签名条保持一致。

    参数:
        output_page: 输出文档的页对象(fitz.Page),已用原PDF页替换好
        qr_png: extract_qr_strip 抠出的二维码PNG字节流
        qr_rect: extract_qr_strip 返回的二维码方块在注协页上的坐标(fitz.Rect)
        cicpa_page_rect: 抠码时注协页的尺寸(fitz.Rect)
    """
    page_rect = output_page.rect

    # 判断输出页与注协原页尺寸是否一致(给1pt容差)
    same_size = (abs(page_rect.width - cicpa_page_rect.width) <= 1 and
                 abs(page_rect.height - cicpa_page_rect.height) <= 1)

    if same_size:
        # 尺寸一致:直接用原二维码方块坐标,保证与注协版完全对齐
        target_rect = qr_rect
    else:
        # 尺寸不同(如横版报表页):按页宽等比缩放二维码,贴到底部
        scale = page_rect.width / cicpa_page_rect.width
        new_w = qr_rect.width * scale
        new_h = qr_rect.height * scale
        # 保持与注协原页相同的右边距
        right_margin = cicpa_page_rect.width - qr_rect.x1
        if right_margin < 0:
            right_margin = 0
        # 保持与注协原页相同的下边距(底部对齐)
        bottom_margin = cicpa_page_rect.height - qr_rect.y1
        if bottom_margin < 0:
            bottom_margin = 0
        new_x1 = page_rect.width - right_margin * scale
        new_x0 = new_x1 - new_w
        new_y1 = page_rect.height - bottom_margin * scale
        new_y0 = new_y1 - new_h
        target_rect = fitz.Rect(new_x0, new_y0, new_x1, new_y1)

    output_page.insert_image(target_rect, stream=qr_png)


def process_download(
    cicpa_pdf_path: str,            # 赋码报告
    original_pdf_path: str,         # 原始报告(提供无章替换页)
    replace_rules: list,            # [{"cicpa":(s,e),"original":(s,e)}, ...]  1基页码
    progress_cb=None,               # progress_cb(percent, stage)
    output_dir: str = None,         # 输出目录,None时放赋码报告同目录
) -> str:
    """生成可打印报告,返回输出路径。

    replace_rules 结构:[{"cicpa":(start,end), "original":(start,end)}, ...]
    页码均为 1 基。每条规则把注协PDF的 cicpa(start..end) 页替换为
    原始PDF的 original(start..end) 页(两边页数必须相等)。

    成功:返回输出路径(替换完成_<赋码文件名>.pdf)。
    失败:抛 ValueError(页码非法)或 Exception(其它),由 gui 捕获转友好提示。
    """
    original_doc = None
    cicpa_doc = None
    output_doc = None
    try:
        if progress_cb: progress_cb(0, "正在打开PDF文件...")

        original_doc = fitz.open(original_pdf_path)
        cicpa_doc = fitz.open(cicpa_pdf_path)

        # 验证页码范围
        if progress_cb: progress_cb(5, "验证页码范围...")
        for rule in replace_rules:
            cicpa_start, cicpa_end = rule["cicpa"]
            orig_start, orig_end = rule["original"]
            if cicpa_end > len(cicpa_doc) or orig_end > len(original_doc):
                raise ValueError(
                    f"规则错误：页码超出文档范围。注协PDF最多 {len(cicpa_doc)} 页，"
                    f"原PDF最多 {len(original_doc)} 页。")

        # 以注协PDF为基底原生复制,签名层二维码自动保留
        if progress_cb: progress_cb(15, "正在加载注协PDF基底...")
        output_doc = fitz.open()
        output_doc.insert_pdf(cicpa_doc)

        # ---- 收集替换对 + 抠码 ----
        replace_pairs = []
        for rule in replace_rules:
            cicpa_start, cicpa_end = rule["cicpa"]
            orig_start, orig_end = rule["original"]
            for i in range(cicpa_end - cicpa_start + 1):
                cicpa_idx = cicpa_start + i - 1   # 0基
                orig_idx = orig_start + i - 1     # 0基
                replace_pairs.append((cicpa_idx, orig_idx))

        # 先从注协原页抠出每页二维码(替换前必须抠,否则签名层丢)
        if progress_cb: progress_cb(25, "正在抠取各页二维码...")
        qr_cache = {}
        for cicpa_idx, orig_idx in replace_pairs:
            if cicpa_idx in qr_cache:
                continue
            if 0 <= cicpa_idx < len(cicpa_doc):
                result = extract_qr_strip(cicpa_doc[cicpa_idx])
                if result:
                    qr_cache[cicpa_idx] = result

        # 执行替换:从大到小避免索引错位
        if progress_cb: progress_cb(45, "正在执行页面替换...")
        for sorted_pos, (cicpa_idx, orig_idx) in enumerate(
                sorted(replace_pairs, key=lambda x: x[0], reverse=True)):
            progress = 45 + (25 * (sorted_pos + 1) / len(replace_pairs))
            if progress_cb: progress_cb(progress,
                f"正在替换第 {cicpa_idx+1} 页为原PDF第 {orig_idx+1} 页...")
            output_doc.delete_page(cicpa_idx)
            output_doc.insert_pdf(original_doc,
                                  from_page=orig_idx, to_page=orig_idx,
                                  start_at=cicpa_idx)

        # 贴回二维码
        if progress_cb: progress_cb(72, "正在贴回二维码...")
        for cicpa_idx, orig_idx in replace_pairs:
            if cicpa_idx not in qr_cache:
                continue
            if 0 <= cicpa_idx < len(output_doc):
                page = output_doc[cicpa_idx]
                qr_png, qr_rect, cicpa_page_rect = qr_cache[cicpa_idx]
                try:
                    paste_qr_strip(page, qr_png, qr_rect, cicpa_page_rect)
                except Exception as e:
                    print(f"在第 {cicpa_idx+1} 页贴回二维码时出错: {e}")

        # 保存
        if progress_cb: progress_cb(95, "正在保存文件...")
        out_dir = output_dir if output_dir else os.path.dirname(cicpa_pdf_path)
        output_path = os.path.join(out_dir, f"替换完成_{os.path.basename(cicpa_pdf_path)}")
        output_doc.save(output_path, garbage=4, deflate=True, clean=True)

        if progress_cb: progress_cb(100, "完成")
        return output_path
    finally:
        try:
            if output_doc:
                output_doc.close()
            if original_doc:
                original_doc.close()
            if cicpa_doc:
                cicpa_doc.close()
        except Exception:
            pass
