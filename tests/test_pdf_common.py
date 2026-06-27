"""pdf_common 单元测试。"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from pdf_common import pt_to_px, px_to_pt, friendly_error_msg


def test_pt_to_px():
    # 1pt 在 2 倍渲染下 = 2px
    assert pt_to_px(72, scale=2.0) == 144


def test_px_to_pt():
    # 144px 在 2 倍渲染下 = 72pt
    assert px_to_pt(144, scale=2.0) == 72


def test_friendly_error_msg_permission_denied():
    e = Exception("code=2: cannot remove file 'x.pdf': Permission denied")
    msg = friendly_error_msg(e)
    assert "占用" in msg
    assert "关闭" in msg


def test_friendly_error_msg_no_such_file():
    e = Exception("No such file or directory: 'x.pdf'")
    msg = friendly_error_msg(e)
    assert "找不到" in msg


def test_friendly_error_msg_other():
    e = Exception("something else happened")
    msg = friendly_error_msg(e)
    assert "something else happened" in msg
