"""审计报告报备处理工具 - 主界面。

侧面步骤导航 + 公共配置区 + 各步骤内容区 + 预览区。

侧边栏三步:
  ① 准备上传版:盖章+拼接,生成上传报告(复用 step_upload)
  ② 等待赋码:纯提示页(赋码在注协网站手动做)
  ③ 处理赋码版:替换盖章页+保码,生成可打印报告(复用 step_download)

状态机:线性约束(①→②→③),本次运行内记忆,重做①清空②③。
印章路径跨次记忆(config_manager),其它参数本次内。
"""
import os
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import fitz
from PIL import Image, ImageTk
import io

from config_manager import ConfigManager
from pdf_common import friendly_error_msg

# 配色(沿用下载项目风格,商务蓝)
COLORS = {
    'primary': '#2563EB',
    'primary_hover': '#1D4ED8',
    'secondary': '#64748B',
    'success': '#10B981',
    'danger': '#EF4444',
    'bg_light': '#F8FAFC',
    'bg_white': '#FFFFFF',
    'border': '#E2E8F0',
    'text_primary': '#0F172A',
    'text_secondary': '#475569',
    'step_done': '#10B981',
    'step_active': '#2563EB',
    'step_locked': '#CBD5E1',
}
FONTS = {
    'title': ('Microsoft YaHei UI', 14, 'bold'),
    'heading': ('Microsoft YaHei UI', 11, 'bold'),
    'body': ('Microsoft YaHei UI', 10),
    'small': ('Microsoft YaHei UI', 9),
}


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("审计报告报备处理工具")
        self.root.geometry("1280x800")
        self.root.configure(bg=COLORS['bg_light'])

        # 配置管理器(印章库 + 上次记忆 + 默认页码)
        self.cfg = ConfigManager()

        # —— 公共配置变量 ——
        self.original_pdf_path = tk.StringVar()
        self.seal_page_var = tk.IntVar()
        self.report_start_var = tk.IntVar()
        self.report_end_var = tk.IntVar()

        # —— 步骤①专属变量 ——
        self.firm_seal_path = tk.StringVar()       # 事务所章
        self.cpa1_seal_path = tk.StringVar()       # CPA章1
        self.cpa2_seal_path = tk.StringVar()       # CPA章2
        self.stamp_pdf_path = tk.StringVar()       # 盖章报表PDF
        self.appendix_pdf_path = tk.StringVar()    # 盖章附注PDF
        self.upload_output_path = None             # 步骤①输出路径(内存)

        # —— 步骤③专属变量 ——
        self.cicpa_pdf_path = tk.StringVar()       # 赋码报告
        self.replace_rules = []                    # [{"cicpa":(s,e),"original":(s,e)}]
        self.download_output_path = None

        # —— 状态机 ——
        # current_step: 1/2/3
        # step_status: {1:'active'/'done', 2:'locked'/'active'/'done', 3:'locked'/'active'/'done'}
        self.current_step = 1
        self.step_status = {1: 'active', 2: 'locked', 3: 'locked'}

        # —— 预览相关 ——
        self.preview_doc = None
        self.preview_page_num = tk.IntVar(value=1)
        self.preview_total = 0
        self._preview_img_ref = None  # 防止PhotoImage被GC

        # 构建界面
        self._build_sidebar()
        self._build_main_area()
        self._load_defaults()
        self._show_step(1)

    # ========== 侧边栏 ==========
    def _build_sidebar(self):
        self.sidebar = tk.Frame(self.root, bg=COLORS['bg_white'], width=200)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self.sidebar.pack_propagate(False)

        # 标题
        tk.Label(self.sidebar, text="审计报告\n报备处理工具",
                 font=FONTS['heading'], bg=COLORS['bg_white'],
                 fg=COLORS['primary'], justify=tk.LEFT,
                 pady=20, padx=15).pack(fill=tk.X)

        tk.Frame(self.sidebar, bg=COLORS['border'], height=1).pack(fill=tk.X)

        # 三个步骤按钮
        self.step_buttons = {}
        self.step_labels = {}
        for step_num, title, desc in [
            (1, "① 准备上传版", "盖章+拼接报表/附注"),
            (2, "② 等待赋码", "去注协上传赋码"),
            (3, "③ 处理赋码版", "替换盖章页+保码"),
        ]:
            btn_frame = tk.Frame(self.sidebar, bg=COLORS['bg_white'])
            btn_frame.pack(fill=tk.X, padx=8, pady=4)
            btn = tk.Label(btn_frame, text=title, font=FONTS['heading'],
                           bg=COLORS['bg_white'], fg=COLORS['text_primary'],
                           anchor='w', padx=10, pady=8, cursor='hand2')
            btn.pack(fill=tk.X)
            tk.Label(btn_frame, text=desc, font=FONTS['small'],
                     bg=COLORS['bg_white'], fg=COLORS['text_secondary'],
                     anchor='w', padx=10).pack(fill=tk.X)
            btn.bind('<Button-1>', lambda e, s=step_num: self._on_step_click(s))
            self.step_buttons[step_num] = btn

        # 底部提示
        tk.Frame(self.sidebar, bg=COLORS['border'], height=1).pack(fill=tk.X, side=tk.BOTTOM)
        tk.Label(self.sidebar, text="公共参数填一次\n两步共用",
                 font=FONTS['small'], bg=COLORS['bg_white'],
                 fg=COLORS['text_secondary'], justify=tk.LEFT,
                 pady=10, padx=15).pack(side=tk.BOTTOM, fill=tk.X)

    def _on_step_click(self, step):
        """点击侧边栏步骤。"""
        status = self.step_status[step]
        if status == 'locked':
            messagebox.showinfo("提示", "请先完成上一步。")
            return
        # 重做①:已done状态下再点①,询问是否重做
        if step == 1 and self.step_status[1] == 'done':
            if messagebox.askyesno("重做步骤①",
                                   "重做步骤①会清空步骤②③的进度。\n确定吗?"):
                self._reset_steps_after(1)
        self._show_step(step)

    # ========== 主区域 ==========
    def _build_main_area(self):
        main = tk.Frame(self.root, bg=COLORS['bg_light'])
        main.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 公共配置区(始终可见,顶部)
        self._build_common_config(main)

        # 步骤内容容器(中部,随步骤切换)
        self.content_container = tk.Frame(main, bg=COLORS['bg_white'])
        self.content_container.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        self._build_step_frames()

        # 预览区(底部)
        self._build_preview_area(main)

    def _build_common_config(self, parent):
        frame = tk.LabelFrame(parent, text="公共配置(两步共用)",
                              font=FONTS['heading'], bg=COLORS['bg_white'],
                              fg=COLORS['text_primary'], padx=12, pady=8)
        frame.pack(fill=tk.X)

        row1 = tk.Frame(frame, bg=COLORS['bg_white'])
        row1.pack(fill=tk.X, pady=4)
        tk.Label(row1, text="原始报告:", font=FONTS['body'],
                 bg=COLORS['bg_white'], width=10, anchor='w').pack(side=tk.LEFT)
        tk.Entry(row1, textvariable=self.original_pdf_path, font=FONTS['body'],
                 bg=COLORS['bg_light']).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        tk.Button(row1, text="浏览...", command=self._browse_original,
                  font=FONTS['body']).pack(side=tk.LEFT)

        row2 = tk.Frame(frame, bg=COLORS['bg_white'])
        row2.pack(fill=tk.X, pady=4)
        tk.Label(row2, text="盖章页(签字页):", font=FONTS['body'],
                 bg=COLORS['bg_white']).pack(side=tk.LEFT)
        tk.Entry(row2, textvariable=self.seal_page_var, width=5,
                 font=FONTS['body'], justify=tk.CENTER).pack(side=tk.LEFT, padx=5)
        tk.Label(row2, text="    报表页范围:", font=FONTS['body'],
                 bg=COLORS['bg_white']).pack(side=tk.LEFT)
        tk.Entry(row2, textvariable=self.report_start_var, width=5,
                 font=FONTS['body'], justify=tk.CENTER).pack(side=tk.LEFT)
        tk.Label(row2, text="~", font=FONTS['body'],
                 bg=COLORS['bg_white']).pack(side=tk.LEFT)
        tk.Entry(row2, textvariable=self.report_end_var, width=5,
                 font=FONTS['body'], justify=tk.CENTER).pack(side=tk.LEFT, padx=5)
        tk.Label(row2, text="(1基页码,附注末页步骤③自动处理)",
                 font=FONTS['small'], fg=COLORS['text_secondary'],
                 bg=COLORS['bg_white']).pack(side=tk.LEFT, padx=10)

    def _build_step_frames(self):
        """构建三个步骤的内容 Frame(初始都隐藏,_show_step 控制显示)。"""
        self.step_frames = {}

        # 步骤①内容
        f1 = tk.LabelFrame(self.content_container, text="步骤① 准备上传版",
                           font=FONTS['heading'], bg=COLORS['bg_white'], padx=12, pady=10)
        self._build_step1_content(f1)
        self.step_frames[1] = f1

        # 步骤②内容
        f2 = tk.LabelFrame(self.content_container, text="步骤② 等待赋码",
                           font=FONTS['heading'], bg=COLORS['bg_white'], padx=12, pady=10)
        self._build_step2_content(f2)
        self.step_frames[2] = f2

        # 步骤③内容
        f3 = tk.LabelFrame(self.content_container, text="步骤③ 处理赋码版",
                           font=FONTS['heading'], bg=COLORS['bg_white'], padx=12, pady=10)
        self._build_step3_content(f3)
        self.step_frames[3] = f3

    # —— 步骤①内容(占位,Task 6 填充完整) ——
    def _build_step1_content(self, parent):
        # 事务所章
        r = tk.Frame(parent, bg=COLORS['bg_white']); r.pack(fill=tk.X, pady=3)
        tk.Label(r, text="事务所章:", width=12, anchor='w',
                 bg=COLORS['bg_white'], font=FONTS['body']).pack(side=tk.LEFT)
        self.firm_seal_combo = ttk.Combobox(r, textvariable=self.firm_seal_path,
                                            font=FONTS['body'], state='readonly')
        self.firm_seal_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        tk.Button(r, text="浏览...", command=lambda: self._browse_seal('firm'),
                  font=FONTS['body']).pack(side=tk.LEFT)

        # CPA章1
        r = tk.Frame(parent, bg=COLORS['bg_white']); r.pack(fill=tk.X, pady=3)
        tk.Label(r, text="主审CPA章:", width=12, anchor='w',
                 bg=COLORS['bg_white'], font=FONTS['body']).pack(side=tk.LEFT)
        self.cpa1_combo = ttk.Combobox(r, textvariable=self.cpa1_seal_path,
                                       font=FONTS['body'], state='readonly')
        self.cpa1_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        tk.Button(r, text="浏览...", command=lambda: self._browse_seal('cpa1'),
                  font=FONTS['body']).pack(side=tk.LEFT)

        # CPA章2
        r = tk.Frame(parent, bg=COLORS['bg_white']); r.pack(fill=tk.X, pady=3)
        tk.Label(r, text="复核CPA章:", width=12, anchor='w',
                 bg=COLORS['bg_white'], font=FONTS['body']).pack(side=tk.LEFT)
        self.cpa2_combo = ttk.Combobox(r, textvariable=self.cpa2_seal_path,
                                       font=FONTS['body'], state='readonly')
        self.cpa2_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        tk.Button(r, text="浏览...", command=lambda: self._browse_seal('cpa2'),
                  font=FONTS['body']).pack(side=tk.LEFT)

        # 盖章报表PDF
        r = tk.Frame(parent, bg=COLORS['bg_white']); r.pack(fill=tk.X, pady=3)
        tk.Label(r, text="盖章报表PDF:", width=12, anchor='w',
                 bg=COLORS['bg_white'], font=FONTS['body']).pack(side=tk.LEFT)
        tk.Entry(r, textvariable=self.stamp_pdf_path, font=FONTS['body'],
                 bg=COLORS['bg_light']).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        tk.Button(r, text="浏览...", command=lambda: self._browse_file(
            self.stamp_pdf_path, [("PDF文件", "*.pdf")]), font=FONTS['body']).pack(side=tk.LEFT)

        # 盖章附注PDF
        r = tk.Frame(parent, bg=COLORS['bg_white']); r.pack(fill=tk.X, pady=3)
        tk.Label(r, text="盖章附注PDF:", width=12, anchor='w',
                 bg=COLORS['bg_white'], font=FONTS['body']).pack(side=tk.LEFT)
        tk.Entry(r, textvariable=self.appendix_pdf_path, font=FONTS['body'],
                 bg=COLORS['bg_light']).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        tk.Button(r, text="浏览...", command=lambda: self._browse_file(
            self.appendix_pdf_path, [("PDF文件", "*.pdf")]), font=FONTS['body']).pack(side=tk.LEFT)

        # 生成按钮
        tk.Button(parent, text="▶ 生成上传报告", command=self._do_step1,
                  font=FONTS['heading'], bg=COLORS['success'], fg='white',
                  activebackground='#059669', padx=20, pady=6).pack(pady=12)

    # —— 步骤②内容(纯提示) ——
    def _build_step2_content(self, parent):
        self.step2_info = tk.Label(parent, text="", font=FONTS['body'],
                                   bg=COLORS['bg_white'], fg=COLORS['text_primary'],
                                   justify=tk.LEFT, anchor='nw')
        self.step2_info.pack(fill=tk.X, pady=4)
        tk.Button(parent, text="📂 打开所在文件夹", command=self._open_output_dir,
                  font=FONTS['body'], padx=10, pady=4).pack(pady=8)
        tk.Label(parent, text="操作指引:\n"
                 "1. 登录注协系统,上传生成的报告\n"
                 "2. 等待系统赋码完成\n"
                 "3. 下载赋码后的报告\n"
                 "4. 回到这里点击侧边栏「③ 处理赋码版」",
                 font=FONTS['body'], bg=COLORS['bg_white'],
                 fg=COLORS['text_secondary'], justify=tk.LEFT).pack(pady=8, anchor='w')

    # —— 步骤③内容 ——
    def _build_step3_content(self, parent):
        # 赋码报告
        r = tk.Frame(parent, bg=COLORS['bg_white']); r.pack(fill=tk.X, pady=3)
        tk.Label(r, text="赋码报告:", width=12, anchor='w',
                 bg=COLORS['bg_white'], font=FONTS['body']).pack(side=tk.LEFT)
        tk.Entry(r, textvariable=self.cicpa_pdf_path, font=FONTS['body'],
                 bg=COLORS['bg_light']).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        tk.Button(r, text="浏览...", command=lambda: self._browse_file(
            self.cicpa_pdf_path, [("PDF文件", "*.pdf")]), font=FONTS['body']).pack(side=tk.LEFT)

        # 替换规则列表
        tk.Label(parent, text="替换规则(注协页 → 原始页):",
                 font=FONTS['body'], bg=COLORS['bg_white'],
                 anchor='w').pack(fill=tk.X, pady=(8, 2))
        list_frame = tk.Frame(parent, bg=COLORS['bg_white'])
        list_frame.pack(fill=tk.BOTH, expand=True)
        sb = tk.Scrollbar(list_frame); sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.rules_listbox = tk.Listbox(list_frame, font=FONTS['body'],
                                        bg=COLORS['bg_light'], height=4,
                                        yscrollcommand=sb.set)
        self.rules_listbox.pack(fill=tk.BOTH, expand=True)
        sb.config(command=self.rules_listbox.yview)

        btn_row = tk.Frame(parent, bg=COLORS['bg_white']); btn_row.pack(fill=tk.X, pady=4)
        tk.Button(btn_row, text="用默认规则填充", command=self._fill_default_rules,
                  font=FONTS['small']).pack(side=tk.LEFT)
        tk.Button(btn_row, text="删除选中", command=self._delete_rule,
                  font=FONTS['small'], fg=COLORS['danger']).pack(side=tk.LEFT, padx=8)

        tk.Button(parent, text="▶ 生成可打印报告", command=self._do_step3,
                  font=FONTS['heading'], bg=COLORS['primary'], fg='white',
                  activebackground=COLORS['primary_hover'], padx=20, pady=6).pack(pady=12)

    # —— 预览区 ——
    def _build_preview_area(self, parent):
        frame = tk.LabelFrame(parent, text="PDF预览",
                              font=FONTS['heading'], bg=COLORS['bg_white'],
                              fg=COLORS['text_primary'], padx=8, pady=8)
        frame.pack(fill=tk.BOTH, expand=False, pady=(10, 0))

        self.preview_canvas = tk.Canvas(frame, bg='white', height=200,
                                        highlightthickness=0)
        self.preview_canvas.pack(fill=tk.BOTH, expand=True)

        ctrl = tk.Frame(frame, bg=COLORS['bg_white']); ctrl.pack(fill=tk.X)
        tk.Button(ctrl, text="◀", command=lambda: self._change_preview(-1),
                  font=FONTS['body'], width=4).pack(side=tk.LEFT)
        self.preview_page_label = tk.Label(ctrl, text="第 0 / 0 页",
                                           font=FONTS['body'], bg=COLORS['bg_white'])
        self.preview_page_label.pack(side=tk.LEFT, padx=8)
        tk.Button(ctrl, text="▶", command=lambda: self._change_preview(1),
                  font=FONTS['body'], width=4).pack(side=tk.LEFT)

    # ========== 默认值加载 ==========
    def _load_defaults(self):
        """从 config.json 读默认页码预填;印章库下拉填充;印章选中上次。"""
        pages = self.cfg.get_default_pages()
        self.seal_page_var.set(pages['seal_page'])
        self.report_start_var.set(pages['report_start'])
        self.report_end_var.set(pages['report_end'])

        # 印章库下拉
        firm_seals = self.cfg.get_company_seals()
        cpa_seals = self.cfg.get_accountant_seals()
        firm_paths = list(firm_seals.values())
        cpa_paths = list(cpa_seals.values())
        self.firm_seal_combo['values'] = firm_paths
        self.cpa1_combo['values'] = cpa_paths
        self.cpa2_combo['values'] = cpa_paths

        # 选中上次
        last_firm = self.cfg.get_last_used_firm()
        if last_firm:
            self.firm_seal_path.set(last_firm)
        elif firm_paths:
            self.firm_seal_path.set(firm_paths[0])
        last_cpa = self.cfg.get_last_used_cpa()
        if last_cpa and cpa_paths:
            # 上次只记了一个,两个CPA分别选第一第二个
            self.cpa1_seal_path.set(last_cpa)
            others = [p for p in cpa_paths if p != last_cpa]
            if others:
                self.cpa2_seal_path.set(others[0])
        elif len(cpa_paths) >= 2:
            self.cpa1_seal_path.set(cpa_paths[0])
            self.cpa2_seal_path.set(cpa_paths[1])

    # ========== 文件浏览 ==========
    def _browse_file(self, var, filetypes):
        path = filedialog.askopenfilename(filetypes=filetypes)
        if path:
            var.set(path)

    def _browse_original(self):
        path = filedialog.askopenfilename(filetypes=[("PDF文件", "*.pdf")])
        if path:
            self.original_pdf_path.set(path)
            self._load_preview(path)

    def _browse_seal(self, which):
        path = filedialog.askopenfilename(
            filetypes=[("图片文件", "*.png *.jpg *.jpeg *.bmp")])
        if not path:
            return
        if which == 'firm':
            self.firm_seal_path.set(path)
            self.cfg.set_last_used_firm(path)
        elif which == 'cpa1':
            self.cpa1_seal_path.set(path)
            self.cfg.set_last_used_cpa(path)
        elif which == 'cpa2':
            self.cpa2_seal_path.set(path)

    # ========== 预览 ==========
    def _load_preview(self, pdf_path):
        try:
            if self.preview_doc:
                self.preview_doc.close()
            self.preview_doc = fitz.open(pdf_path)
            self.preview_total = len(self.preview_doc)
            self.preview_page_num.set(1)
            self._render_preview()
        except Exception as e:
            messagebox.showerror("错误", f"无法加载PDF预览:\n{e}")

    def _render_preview(self):
        if not self.preview_doc or self.preview_total == 0:
            return
        idx = self.preview_page_num.get() - 1
        if not (0 <= idx < self.preview_total):
            return
        page = self.preview_doc[idx]
        # 缩放至预览区高度
        zoom = 200.0 / page.rect.height if page.rect.height else 0.3
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        self._preview_img_ref = ImageTk.PhotoImage(img)
        self.preview_canvas.delete('all')
        self.preview_canvas.create_image(0, 0, anchor=tk.NW, image=self._preview_img_ref)
        self.preview_page_label.config(text=f"第 {idx+1} / {self.preview_total} 页")

    def _change_preview(self, delta):
        new = self.preview_page_num.get() + delta
        if 1 <= new <= self.preview_total:
            self.preview_page_num.set(new)
            self._render_preview()

    # ========== 步骤切换/状态 ==========
    def _show_step(self, step):
        for s, f in self.step_frames.items():
            f.pack_forget()
        self.step_frames[step].pack(fill=tk.BOTH, expand=True)
        self.current_step = step
        self._update_step_buttons()
        # 步骤②刷新提示
        if step == 2:
            self._refresh_step2_info()

    def _update_step_buttons(self):
        """根据 step_status 更新侧边栏按钮颜色。"""
        status_cfg = {
            'active': (COLORS['step_active'], 'white'),
            'done': (COLORS['step_done'], 'white'),
            'locked': (COLORS['step_locked'], COLORS['text_secondary']),
        }
        for step_num, btn in self.step_buttons.items():
            st = self.step_status[step_num]
            prefix = {'active': '● ', 'done': '✓ ', 'locked': '○ '}[st]
            titles = {1: "① 准备上传版", 2: "② 等待赋码", 3: "③ 处理赋码版"}
            btn.config(text=prefix + titles[step_num],
                       bg=status_cfg[st][0], fg=status_cfg[st][1])

    def _reset_steps_after(self, step):
        """重做:清空 step 之后的状态。重做①清空②③全部输入。"""
        if step <= 1:
            self.step_status = {1: 'active', 2: 'locked', 3: 'locked'}
            self.upload_output_path = None
            self.download_output_path = None
            self.cicpa_pdf_path.set('')
            self.replace_rules = []
            self.rules_listbox.delete(0, tk.END)
        self._update_step_buttons()

    def _refresh_step2_info(self):
        if self.upload_output_path:
            self.step2_info.config(
                text=f"✓ 上传报告已生成:\n{self.upload_output_path}\n\n"
                     "请把该文件上传到注协系统赋码,完成后下载赋码报告,再做步骤③。")
        else:
            self.step2_info.config(text="尚未生成上传报告。请先完成步骤①。")

    def _open_output_dir(self):
        path = self.upload_output_path or self.download_output_path
        if not path:
            messagebox.showinfo("提示", "还没有生成任何输出文件。")
            return
        d = os.path.dirname(path)
        try:
            os.startfile(d)
        except Exception as e:
            messagebox.showerror("错误", f"无法打开文件夹:\n{e}\n请检查路径是否存在。")

    # ========== 步骤①处理(Task 6 完整实现) ==========
    def _do_step1(self):
        """步骤①:生成上传报告。"""
        from step_upload import process_upload, PDFProcessError

        original = self.original_pdf_path.get().strip()
        firm = self.firm_seal_path.get().strip()
        cpa1 = self.cpa1_seal_path.get().strip()
        cpa2 = self.cpa2_seal_path.get().strip()
        stamp = self.stamp_pdf_path.get().strip()
        appendix = self.appendix_pdf_path.get().strip()

        # 校验
        missing = []
        if not original: missing.append("原始报告")
        if not firm: missing.append("事务所章")
        if not stamp: missing.append("盖章报表PDF")
        if not appendix: missing.append("盖章附注PDF")
        if missing:
            messagebox.showwarning("缺少文件", "请选择:" + "、".join(missing))
            return

        seal_page = self.seal_page_var.get()
        report_start = self.report_start_var.get()
        report_end = self.report_end_var.get()

        # 进度窗口
        prog = ProgressDialog(self.root, "正在生成上传报告")

        def worker():
            try:
                out = process_upload(
                    original_pdf_path=original,
                    stamp_pdf_path=stamp,
                    appendix_pdf_path=appendix,
                    company_seal_path=firm,
                    accountant_seal_paths=[cpa1 or None, cpa2 or None],
                    seal_page=seal_page,
                    stamp_start_page=report_start,
                    stamp_end_page=report_end,
                    progress_cb=lambda p, s: self.root.after(
                        0, lambda: prog.update_progress(p, s)),
                )
                self.root.after(0, lambda: self._step1_done(out, prog))
            except PDFProcessError as e:
                self.root.after(0, lambda: self._step_fail(prog, e.message, getattr(e, 'hint', '')))
            except Exception as e:
                self.root.after(0, lambda: self._step_fail(prog, friendly_error_msg(e), ''))

        threading.Thread(target=worker, daemon=True).start()

    def _step1_done(self, out_path, prog):
        prog.close()
        self.upload_output_path = out_path
        self.step_status[1] = 'done'
        self.step_status[2] = 'active'
        self._show_step(2)
        messagebox.showinfo("完成", f"上传报告已生成:\n{out_path}")

    # ========== 步骤③处理(Task 7 完整实现) ==========
    def _fill_default_rules(self):
        """用公共页码生成默认替换规则。"""
        cicpa_path = self.cicpa_pdf_path.get().strip()
        if not cicpa_path:
            messagebox.showwarning("提示", "请先选择赋码报告。")
            return
        try:
            doc = fitz.open(cicpa_path)
            cicpa_last = len(doc)
            doc.close()
        except Exception:
            cicpa_last = 0

        self.replace_rules = []
        self.rules_listbox.delete(0, tk.END)
        # 盖章页→单页替换
        sp = self.seal_page_var.get()
        self._add_rule(sp, sp, sp, sp)
        # 报表范围→区间替换
        rs, re_ = self.report_start_var.get(), self.report_end_var.get()
        if re_ > rs:
            self._add_rule(rs, re_, rs, re_)
        # 附注末页(自动追加最后一页规则)
        if cicpa_last > 0:
            # 原始报告末页(需打开)
            orig = self.original_pdf_path.get().strip()
            try:
                d2 = fitz.open(orig)
                orig_last = len(d2)
                d2.close()
            except Exception:
                orig_last = cicpa_last
            self._add_rule(cicpa_last, cicpa_last, orig_last, orig_last)

    def _add_rule(self, cs, ce, os_, oe):
        rule = {"cicpa": (cs, ce), "original": (os_, oe)}
        self.replace_rules.append(rule)
        text = f"注协第{cs}-{ce}页 → 原始第{os_}-{oe}页"
        self.rules_listbox.insert(tk.END, text)

    def _delete_rule(self):
        sel = self.rules_listbox.curselection()
        if not sel:
            messagebox.showwarning("提示", "请先选择要删除的规则。")
            return
        idx = sel[0]
        self.rules_listbox.delete(idx)
        self.replace_rules.pop(idx)

    def _do_step3(self):
        """步骤③:生成可打印报告。"""
        from step_download import process_download

        cicpa = self.cicpa_pdf_path.get().strip()
        original = self.original_pdf_path.get().strip()
        if not cicpa:
            messagebox.showwarning("缺少文件", "请选择赋码报告。")
            return
        if not original:
            messagebox.showwarning("缺少文件", "请选择原始报告(公共配置)。")
            return
        if not self.replace_rules:
            messagebox.showwarning("提示", "请先添加替换规则(可点「用默认规则填充」)。")
            return

        prog = ProgressDialog(self.root, "正在生成可打印报告")
        rules = list(self.replace_rules)  # 快照

        def worker():
            try:
                out = process_download(
                    cicpa_pdf_path=cicpa,
                    original_pdf_path=original,
                    replace_rules=rules,
                    progress_cb=lambda p, s: self.root.after(
                        0, lambda: prog.update_progress(p, s)),
                )
                self.root.after(0, lambda: self._step3_done(out, prog))
            except ValueError as e:
                self.root.after(0, lambda: self._step_fail(prog, str(e), ''))
            except Exception as e:
                self.root.after(0, lambda: self._step_fail(prog, friendly_error_msg(e), ''))

        threading.Thread(target=worker, daemon=True).start()

    def _step3_done(self, out_path, prog):
        prog.close()
        self.download_output_path = out_path
        self.step_status[3] = 'done'
        self._update_step_buttons()
        messagebox.showinfo("完成", f"可打印报告已生成:\n{out_path}")

    def _step_fail(self, prog, msg, hint):
        prog.close()
        full = msg + (f"\n\n建议排查:{hint}" if hint else "")
        messagebox.showerror("处理失败", full)

    # ========== 运行 ==========
    def run(self):
        self.root.mainloop()


class ProgressDialog:
    """简单的进度对话框(进度条 + 百分比 + 状态文本)。"""
    def __init__(self, parent, title="处理中"):
        self.top = tk.Toplevel(parent)
        self.top.title(title)
        self.top.geometry("420x180")
        self.top.transient(parent)
        self.top.grab_set()
        self.top.configure(bg=COLORS['bg_white'])
        self.top.protocol("WM_DELETE_WINDOW", lambda: None)

        c = tk.Frame(self.top, bg=COLORS['bg_white'], padx=25, pady=25)
        c.pack(fill=tk.BOTH, expand=True)
        self.label = tk.Label(c, text="准备中...", font=FONTS['body'],
                              bg=COLORS['bg_white'], fg=COLORS['text_secondary'],
                              wraplength=370, justify=tk.LEFT)
        self.label.pack(anchor='w', pady=(0, 10))
        self.progress = ttk.Progressbar(c, length=370, mode='determinate')
        self.progress.pack(fill=tk.X)
        self.percent = tk.Label(c, text="0%", font=FONTS['heading'],
                                bg=COLORS['bg_white'], fg=COLORS['primary'])
        self.percent.pack(anchor='w', pady=(8, 0))
        self.top.update()

    def update_progress(self, value, text=""):
        self.progress['value'] = max(0, min(100, value))
        self.percent.config(text=f"{int(value)}%")
        if text:
            self.label.config(text=text)
        self.top.update()

    def close(self):
        self.top.destroy()


def main():
    root = tk.Tk()
    App(root).run()


if __name__ == '__main__':
    main()
