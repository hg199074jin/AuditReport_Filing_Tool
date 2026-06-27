"""两个步骤共用的 PDF 底层操作。

纯函数,不依赖 tkinter,便于单元测试。
目前包含:
- pt_to_px / px_to_pt:点与像素的坐标换算(给定渲染倍率)
- friendly_error_msg:把底层异常转成用户能看懂的中文提示

PDF 渲染逻辑(get_pixmap + PIL + ImageTk)不集中在这里,
各模块(step_upload / step_download / gui)就地复用原项目渲染代码,
因为两边的渲染场景差异较大,强行提取收益低。
"""


def pt_to_px(pt: float, scale: float) -> float:
    """点(pt)转像素(给定渲染倍率)。1pt × scale = N px。"""
    return pt * scale


def px_to_pt(px: float, scale: float) -> float:
    """像素转点。"""
    return px / scale


def friendly_error_msg(e: Exception) -> str:
    """把底层异常转成用户能看懂的中文提示。

    注意:此函数处理通用的系统级错误(文件占用/不存在)。
    step_upload 抛出的 PDFProcessError 自带 hint 字段(更具体的排查建议),
    gui 在调用本函数前应优先检查 PDFProcessError.hint,有 hint 则用 hint。
    """
    msg = str(e).lower()
    if "permission denied" in msg or "cannot remove" in msg or "access is denied" in msg:
        return ("无法保存文件,该文件可能正被其他程序占用。\n\n"
                "请检查:\n"
                "1. 是否有用 PDF 阅读器(Adobe Reader、WPS、浏览器等)打开了这个文件?请先关闭它。\n"
                "2. 换一个文件名或换一个文件夹重新保存试试。")
    if "no such file" in msg or "cannot find" in msg:
        return "找不到文件或文件夹,请检查路径是否正确、文件是否存在。"
    return f"处理时发生错误:{str(e)}"
