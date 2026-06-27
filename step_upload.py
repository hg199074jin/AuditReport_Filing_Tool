"""步骤①:准备上传版报告。

给原始审计报告加盖 CPA 章 + 事务所章,拼接被审计单位盖章的报表/附注,
生成上传到注协系统的报告。

封装 PDFProcessor(从上传项目提炼,已去掉 PyPDF2 fallback)。
对 gui 暴露 process_upload 函数,内部实例化 PDFProcessor 调 process_pdf。

复用的完整盖章链路(任一缺失都无法工作):
  find_seal_page(定位盖章页)
  → find_seal_anchors(提取事务所名/盖章/CPA签字位锚点)
  → compute_seal_positions(按物理尺寸cm→pt换算、CPA y坐标排序算位置)
      ├ _get_seal_target_size(尺寸计算)
      └ _firm_name_center_x(事务所名中心定位)
  → add_seals_to_page(实际盖章,依赖算出的 seal_positions 和预览图 page_image)
"""
from typing import Callable, List, Optional
from pdf_processor import PDFProcessor, PDFProcessError


def process_upload(
    original_pdf_path: str,
    stamp_pdf_path: str,          # 盖章报表PDF(被审计单位盖章的)
    appendix_pdf_path: str,       # 盖章附注PDF(被审计单位盖章的)
    company_seal_path: str,       # 事务所章图片
    accountant_seal_paths: List[Optional[str]],  # CPA章图片列表(2个,元素可为None)
    seal_page: int,               # 盖章页码(1基)
    stamp_start_page: int,        # 报表替换起始页(1基)
    stamp_end_page: int,          # 报表替换结束页(1基)
    progress_cb: Optional[Callable[[int, str], None]] = None,
) -> str:
    """生成上传报告,返回输出文件路径。

    参数说明见模块 docstring。progress_cb 签名:progress_cb(percent: int, stage: str)。

    成功:返回输出路径(原项目命名:处理完成_<原始文件名>.pdf,放原始报告同目录)。
    失败:抛 PDFProcessError(及子类),异常带 hint 字段(用户排查建议)。
         gui 捕获时应优先展示 hint。
    """
    processor = PDFProcessor()
    # 用关键词参数调用,避免 seal_page 与 stamp_start_page 这两个 int 传错位
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
    return processor.last_output_path
