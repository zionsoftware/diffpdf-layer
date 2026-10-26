"""Japanese Tk GUI. Parsing runs in a killable subprocess, never on Tk's thread."""
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .model import ROLES, Status
from .report import (find_pair, find_row, from_json, matrix_headers, matrix_rows,
                     pair_details, row_details, save_report)

PROJECT = Path(__file__).resolve().parents[2]
TIMEOUT = 180


class Application:
    def __init__(self, root, files=()):
        self.root = root
        self.report = None
        self.process = None
        self.worker = None
        self.messages = queue.Queue()
        self.generation = 0
        self.closed = False
        self.role_vars = {r: tk.StringVar(master=root) for r in ROLES}
        root.title("PDFレイヤー同一性検証ツール")
        root.geometry("1140x840")
        root.minsize(900, 700)
        root.protocol("WM_DELETE_WINDOW", self.close)
        frame = ttk.Frame(root, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="担当・確認は必須、審査・承認は任意です。基準PDFは指定された最後の工程から自動選択します。").pack(anchor="w")
        inputs = ttk.Frame(frame)
        inputs.pack(fill="x", pady=8)
        inputs.columnconfigure(1, weight=1)
        self.edit_buttons = []
        for i, role in enumerate(ROLES):
            ttk.Label(inputs, text=f"{role} ({'必須' if i < 2 else '任意'})", width=14).grid(row=i, column=0, sticky="w", pady=3)
            entry = ttk.Entry(inputs, textvariable=self.role_vars[role])
            entry.grid(row=i, column=1, sticky="ew", padx=6)
            select = ttk.Button(inputs, text="選択", command=lambda r=role: self.select_file(r))
            select.grid(row=i, column=2, padx=3)
            clear = ttk.Button(inputs, text="解除", command=lambda r=role: self.role_vars[r].set(""))
            clear.grid(row=i, column=3, padx=3)
            self.edit_buttons.extend([entry, select, clear])
        self.reference_label = ttk.Label(frame, text="基準PDF: 未選択", wraplength=1080)
        self.reference_label.pack(anchor="w")
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=8)
        self.compare_button = ttk.Button(buttons, text="比較開始", command=self.start)
        self.compare_button.pack(side="left")
        self.cancel_button = ttk.Button(buttons, text="中止", command=self.cancel, state="disabled")
        self.cancel_button.pack(side="left", padx=6)
        self.save_button = ttk.Button(buttons, text="結果を保存", command=self.save, state="disabled")
        self.save_button.pack(side="right")
        self.output_format = tk.StringVar(master=root, value="TXT")
        ttk.Combobox(buttons, textvariable=self.output_format, values=("TXT", "PDF", "CSV", "JSON"),
                     state="readonly", width=7).pack(side="right", padx=8)
        ttk.Label(buttons, text="保存形式:").pack(side="right")
        self.status = tk.StringVar(master=root, value="待機中")
        ttk.Label(frame, textvariable=self.status, wraplength=1080).pack(anchor="w", pady=4)
        self.progress = ttk.Progressbar(frame, mode="indeterminate")
        self.progress.pack(fill="x", pady=(0, 8))
        pane = ttk.Panedwindow(frame, orient="vertical")
        pane.pack(fill="both", expand=True)
        notebook = ttk.Notebook(pane)
        matrix_frame = ttk.Frame(notebook)
        pair_frame = ttk.Frame(notebook)
        notebook.add(matrix_frame, text="基準PDFとの比較")
        notebook.add(pair_frame, text="全組合せの結果")
        self.tree = ttk.Treeview(matrix_frame, show="headings", selectmode="browse")
        self.pair_tree = ttk.Treeview(pair_frame, columns=("left", "right", "overall", "business"), show="headings", selectmode="browse")
        for key, label in (("left", "比較元"), ("right", "比較先"), ("overall", "PDF全体"), ("business", "業務判定")):
            self.pair_tree.heading(key, text=label)
            self.pair_tree.column(key, width=170)
        for widget, parent in ((self.tree, matrix_frame), (self.pair_tree, pair_frame)):
            parent.rowconfigure(0, weight=1)
            parent.columnconfigure(0, weight=1)
            vertical = ttk.Scrollbar(parent, orient="vertical", command=widget.yview)
            horizontal = ttk.Scrollbar(parent, orient="horizontal", command=widget.xview)
            widget.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
            widget.grid(row=0, column=0, sticky="nsew")
            vertical.grid(row=0, column=1, sticky="ns")
            horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.bind("<<TreeviewSelect>>", self.show_detail)
        self.pair_tree.bind("<<TreeviewSelect>>", self.show_pair_detail)
        pane.add(notebook, weight=3)
        detail_frame = ttk.Frame(pane)
        ttk.Label(detail_frame, text="詳細 (結果行を選択してください)").pack(anchor="w")
        self.detail = tk.Text(detail_frame, height=9, wrap="word", state="disabled")
        detail_scroll = ttk.Scrollbar(detail_frame, command=self.detail.yview)
        self.detail.configure(yscrollcommand=detail_scroll.set)
        self.detail.pack(side="left", fill="both", expand=True)
        detail_scroll.pack(side="right", fill="y")
        pane.add(detail_frame, weight=2)
        ttk.Label(frame, text="内容の一致と業務判定は別です。原本PDFは変更しません。保存形式: TXT / PDF / CSV / JSON。", wraplength=1080).pack(anchor="w", pady=(8, 0))
        for value in self.role_vars.values():
            value.trace_add("write", self.refresh_inputs)
        if isinstance(files, dict):
            for role, path in files.items():
                self.role_vars[role].set(str(path))
        else:
            self.add_files(files)
        self.poll_after = root.after(100, self.poll)

    @property
    def inputs(self):
        return {r: self.role_vars[r].get().strip() for r in ROLES if self.role_vars[r].get().strip()}

    @property
    def files(self):
        return list(self.inputs.values())

    def set_detail(self, text):
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text)
        self.detail.configure(state="disabled")

    def invalidate(self):
        self.report = None
        self.tree.delete(*self.tree.get_children())
        self.pair_tree.delete(*self.pair_tree.get_children())
        self.save_button.configure(state="disabled")
        self.set_detail("")
        self.status.set("待機中")

    def refresh_inputs(self, *_):
        inputs = self.inputs
        role = next(reversed(inputs)) if inputs else ""
        self.reference_label.configure(text=f"基準PDF ({role}): {inputs[role]}" if role else "基準PDF: 未選択")
        self.invalidate()

    def select_file(self, role):
        path = filedialog.askopenfilename(title=f"{role}PDFを選択", filetypes=[("PDF", "*.pdf")], parent=self.root)
        if path:
            self.role_vars[role].set(str(Path(path).resolve()))

    def add_files(self, files):
        if self.process:
            return
        remaining = [r for r in ROLES if r not in self.inputs]
        for role, path in zip(remaining, files):
            self.role_vars[role].set(str(Path(path).resolve()))

    def busy(self, active):
        for button in self.edit_buttons + [self.compare_button]:
            button.configure(state="disabled" if active else "normal")
        self.cancel_button.configure(state="normal" if active else "disabled")
        if active:
            self.progress.start(15)
        else:
            self.progress.stop()

    def start(self):
        if self.process:
            return
        if not self.inputs.get("担当") or not self.inputs.get("確認"):
            messagebox.showerror("入力エラー", "担当・確認のPDFは必須です。", parent=self.root)
            return
        for role, path in self.inputs.items():
            if Path(path).suffix.lower() != ".pdf" or not Path(path).is_file():
                messagebox.showerror("入力エラー", f"{role}: 存在するPDFを指定してください。\n{path}", parent=self.root)
                return
        self.invalidate()
        self.generation += 1
        generation = self.generation
        try:
            options = dict(zip(ROLES, ("--responsible", "--confirmation", "--review", "--approval")))
            arguments = [v for role, path in self.inputs.items() for v in (options[role], path)]
            process = subprocess.Popen([sys.executable, "-S", str(PROJECT / "main.py"), "--json", *arguments], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            self.status.set("検証不能: 比較プロセスの起動失敗")
            self.set_detail(str(exc))
            return
        self.process = process
        self.busy(True)
        self.status.set(f"比較中: {len(self.files)} ファイル / 全 {len(self.files) * (len(self.files)-1) // 2} 組 (上限 {TIMEOUT} 秒)")
        messages = self.messages  # the worker must never retain Tk objects

        def work():
            try:
                stdout, stderr = process.communicate(timeout=TIMEOUT)
                if process.returncode not in (0, 1, 2):
                    raise RuntimeError(f"比較プロセス異常終了 ({process.returncode})\n{stderr[-4000:]}")
                report = from_json(stdout)
                messages.put((generation, report, ""))
            except Exception as exc:
                if process.poll() is None:
                    process.kill()
                process.communicate()
                messages.put((generation, None, f"検証不能: {type(exc).__name__}: {exc}"))
        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def poll(self):
        if self.closed:
            return
        while True:
            try:
                generation, report, error = self.messages.get_nowait()
            except queue.Empty:
                break
            if generation != self.generation:
                continue
            self.process = None
            self.busy(False)
            if error:
                self.status.set("検証不能: 処理失敗または制限時間超過")
                self.set_detail(error)
            else:
                self.render_report(report)
        self.poll_after = self.root.after(100, self.poll)

    def render_report(self, report):
        self.report = report
        self.tree.delete(*self.tree.get_children())
        self.pair_tree.delete(*self.pair_tree.get_children())
        columns = ("component", *report.roles)
        self.tree.configure(columns=columns)
        for key, label in zip(columns, matrix_headers(report)):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=240 if key == "component" else 180, minwidth=100)
        for index, row in enumerate(matrix_rows(report)):
            self.tree.insert("", "end", iid=str(index), values=row)
        for index, pair in enumerate(report.pairs):
            self.pair_tree.insert("", "end", iid=str(index), values=(pair.left_role, pair.right_role, pair.overall, pair.business))
        self.status.set(f"比較完了 / 全 {len(report.pairs)} 組 / PASS {sum(p.business == 'PASS' for p in report.pairs)} / FAIL {sum(p.business == 'FAIL' for p in report.pairs)} / UNVERIFIABLE {sum(p.business == 'UNVERIFIABLE' for p in report.pairs)} / 解析エラー {len(report.errors)} 件")
        metadata = [f"{v.role}: {v.path}\nSHA-256: {v.short_hash} / 更新日時: {v.modified_at or '取得不能'} / {v.size_bytes} bytes" for v in report.file_info]
        self.set_detail("\n\n".join([*report.errors, *metadata]))
        self.save_button.configure(state="normal")

    def show_detail(self, event=None):
        selected = self.tree.selection()
        if not selected or not self.report:
            return
        index = int(selected[0])
        components = ["PDF全体", "PDF本体", "レイヤーなし", *["レイヤー: " + n for n in self.report.layer_names], "業務判定", *["レイヤー: " + n for n in self.report.extra_names]]
        component = components[index]
        details = []
        for role in self.report.roles[:-1]:
            pair = find_pair(self.report, role)
            if pair is None:
                continue
            if component in {"PDF全体", "業務判定"}:
                details.append(pair_details(self.report, pair))
            else:
                row = find_row(self.report, pair, component)
                if row:
                    details.append(row_details(row))
        self.set_detail("\n\n".join(details) or "比較結果を取得できません。")

    def show_pair_detail(self, event=None):
        selected = self.pair_tree.selection()
        if selected and self.report:
            self.set_detail(pair_details(self.report, self.report.pairs[int(selected[0])]))

    def cancel(self):
        if self.process:
            self.generation += 1
            if self.process.poll() is None:
                self.process.kill()
            self.process = None
            self.busy(False)
            self.status.set("中止しました。判定結果はありません。")
        if self.worker is not None:
            self.worker.join(timeout=2)
            if not self.worker.is_alive():
                self.worker = None

    def save(self):
        if not self.report:
            return
        extension = self.output_format.get().lower()
        formats = {"txt": "テキスト", "pdf": "PDF", "csv": "CSV", "json": "JSON"}
        destination = filedialog.asksaveasfilename(parent=self.root, title="結果を保存", initialfile=f"cmp.{extension}",
                        defaultextension=f".{extension}", filetypes=[(formats[extension], f"*.{extension}")])
        if destination:
            try:
                save_report(self.report, destination)
            except (OSError, ValueError) as exc:
                messagebox.showerror("保存エラー", str(exc), parent=self.root)

    def close(self):
        self.closed = True
        self.cancel()
        self.root.after_cancel(self.poll_after)
        self.root.destroy()


def launch(files=()):
    root = tk.Tk()
    Application(root, files)
    root.mainloop()
