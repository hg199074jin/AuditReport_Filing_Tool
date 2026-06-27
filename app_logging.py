"""统一的日志配置。

所有模块通过 `from app_logging import get_logger` 获取 logger，确保日志格式一致、
输出到同一文件（审计报备工具.log，UTF-8）。出问题时把该日志发给开发者即可定位。

设计要点：
- 只在首次导入时配置一次（logging 是全局的，重复 addHandler 会重复输出）。
- 文件名固定为“审计报备工具.log”，放在程序所在目录。
- 同时输出到文件（留底）和控制台（开发期可见）；打包/命令行运行时控制台日志仍可见。

iCCP 警告屏蔽（两层，缺一不可）：
- libpng 的 "iCCP: known incorrect sRGB profile" 是 C 库直接 fprintf 到 stderr 的,
  绕过 Python warnings 系统——所以光用 warnings.filterwarnings 拦不住它。
- PDF 渲染(fitz 把 PDF 页面转成 PNG)或某些带非标准 sRGB profile 的 PNG,
  都会触发该警告, 一加载 PDF 就刷屏, 但对功能完全无害。
- 这里用两层屏蔽:
  1) _suppress_libpng_iccp_warnings(): 重定向 C 层 stderr(fd=2), 过滤掉含
     "iCCP" 的行, 其余输出照常。专治 libpng 这种"绕过 Python 直接写 stderr"的库。
  2) warnings.filterwarnings(...): 兜 Python warnings 通道(对其它走该通道的警告有效)。
"""
import logging
import os
import sys
import threading
import warnings

# —— 第 1 层: 拦截 C 层 stderr 里的 libpng iCCP 警告 ——
# 在模块导入时执行一次。原理: 复制原 stderr(fd=2) 备份, 再把 fd=2 重定向到一个
# 管道; 后台线程读管道, 只把"非 iCCP"的行写回原 stderr。这样 libpng 写到 stderr
# 的 iCCP 警告被吞掉, 而真正有用的 stderr 输出(如其它库的致命错误)不受影响。
_iccp_filter_lock = threading.Lock()
_iccp_filter_installed = False


def _suppress_libpng_iccp_warnings():
    """重定向 C 层 stderr, 过滤掉 libpng 的 iCCP 警告行。

    只过滤含 'iCCP' 的行(逐行判断), 其它 stderr 输出原样转发, 避免误吞重要错误。
    幂等: 重复调用安全(用锁 + 标志位保证只装一次)。
    失败时静默(最坏后果只是警告没被屏蔽, 不影响程序运行)。
    """
    global _iccp_filter_installed
    with _iccp_filter_lock:
        if _iccp_filter_installed:
            return
        try:
            import ctypes

            # 保存原始 stderr 的文件描述符(复制一份, 后面写回用它)
            stderr_fd = sys.stderr.fileno() if hasattr(sys.stderr, 'fileno') else 2
            saved_stderr = os.dup(stderr_fd)

            # 建管道: filter_writer 写 → 管道 → reader 读
            read_fd, write_fd = os.pipe()

            # 把进程级 fd=2(C 库用的那个)指向管道写端 → libpng 写 stderr 就进了管道
            os.dup2(write_fd, stderr_fd)
            os.close(write_fd)

            def _reader_loop():
                """后台读管道, 非 iCCP 行转发到原 stderr。"""
                try:
                    # 用文件对象按行读, 编码容忍(警告多为 ASCII; 容错 errors='replace')
                    with os.fdopen(read_fd, 'r', encoding='utf-8', errors='replace') as pipe_r:
                        with os.fdopen(saved_stderr, 'w', encoding='utf-8', errors='replace') as real_err:
                            for line in pipe_r:
                                # 含 iCCP 的行吞掉(典型: "libpng warning: iCCP: known incorrect sRGB profile")
                                if 'iCCP' in line:
                                    continue
                                real_err.write(line)
                                real_err.flush()
                except Exception:
                    # 读线程挂了也不要紧: 顶多 iCCP 警告又冒出来, 不影响主程序
                    pass

            t = threading.Thread(target=_reader_loop, name='libpng-iccp-filter', daemon=True)
            t.start()
            _iccp_filter_installed = True
        except Exception:
            # 任何一步失败(如某些打包环境 fd 操作受限)都静默, 不阻断程序
            _iccp_filter_installed = True  # 标记已尝试, 不再重试


# 模块导入即安装(早于任何 PDF/PNG 加载)
_suppress_libpng_iccp_warnings()

# —— 第 2 层: Python warnings 通道(兜其它走该通道的警告) ——
# 屏蔽 libpng 的 iCCP 警告。
# 当 PIL/Pillow 通过 libpng 解码某些带"非标准 sRGB profile"的 PNG（常见于
# Photoshop 另存、某些印章/图标制作工具导出的文件）时,libpng 会在 stderr
# 输出 "iCCP: known incorrect sRGB profile"。这只是 libpng 的健康提醒,
# 不影响图片加载、不影响盖章功能、不影响最终 PDF——只输出位置有点烦人。
# 注意: 此行对 libpng 本身无效(libpng 走 C 层 stderr, 见上方第 1 层);
# 保留它是为了同时屏蔽 Python 层(如 Pillow/warnings)可能转发的同类警告。
warnings.filterwarnings("ignore", message=".*iCCP: known incorrect sRGB profile.*")

_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "审计报备工具.log")
_configured = False


def _configure_once():
    """配置根 logger，只执行一次。"""
    global _configured
    if _configured:
        return
    _configured = True

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 文件处理器（UTF-8，避免中文乱码）
    try:
        file_handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
        file_handler.setFormatter(fmt)
        file_handler.setLevel(logging.DEBUG)
        logging.getLogger().addHandler(file_handler)
    except Exception as e:
        # 日志初始化失败不应阻断程序运行
        print(f"[警告] 无法创建日志文件: {e}")

    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    console_handler.setLevel(logging.INFO)
    logging.getLogger().addHandler(console_handler)

    logging.getLogger().setLevel(logging.DEBUG)


def get_logger(name):
    """获取一个已命名的 logger。首次调用会自动完成全局配置。"""
    _configure_once()
    return logging.getLogger(name)
