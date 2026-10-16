"""Japanese Tk GUI. Parsing runs in a killable subprocess, never on Tk's thread."""
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .model import Status
from .report import from_json, row_details, save_report

PROJECT = Path(__file__).resolve().parents[2]
TIMEOUT = 180


class Application:
    def __init__(self, root, files=()):
        self.root = root
        self.files = []
        self.report = None
        self.process = None
        self.messages = queue.Queue()
        self.generation = 0
        self.closed = False
        root.title("PDFレイヤー同一性検証ツール")
        root.geometry("1100x760")
        root.minsize(800, 600)
        root.protocol("WM_DELETE_WINDOW", self.close)
        frame = ttk.Frame(root, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="PDF を 2～4 個指定してください。1番目が基準PDFです。上へ・下へで基準と入力順を変更できます。").pack(anchor="w")
        self.reference_label = ttk.Label(frame, text="基準PDF: 未選択", wraplength=1020)
        self.reference_label.pack(anchor="w")
        self.file_list = tk.Listbox(frame, height=5, selectmode="extended", exportselection=False)
        self.file_list.pack(fill="x", pady=(8, 4))
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x")
        self.edit_buttons = []
        for label, command in (("PDF を追加", self.add_dialog), ("選択を削除", self.remove), ("上へ", lambda: self.move(-1)), ("下へ", lambda: self.move(1))):
            button = ttk.Button(buttons, text=label, command=command)
            button.pack(side="left", padx=(0, 6))
            self.edit_buttons.append(button)
        self.compare_button = ttk.Button(buttons, text="比較開始", command=self.start)
        self.compare_button.pack(side="left", padx=12)
        self.cancel_button = ttk.Button(buttons, text="中止", command=self.cancel, state="disabled")
        self.cancel_button.pack(side="left")
        self.save_button = ttk.Button(buttons, text="結果を保存", command=self.save, state="disabled")
        self.save_button.pack(side="right")
        self.status = tk.StringVar(value="待機中")
        ttk.Label(frame, textvariable=self.status, wraplength=1020).pack(anchor="w", pady=8)
        self.progress = ttk.Progressbar(frame, mode="indeterminate")
        self.progress.pack(fill="x", pady=(0, 8))
        pane = ttk.Panedwindow(frame, orient="vertical")
        pane.pack(fill="both", expand=True)
        result_frame = ttk.Frame(pane)
        self.tree = ttk.Treeview(result_frame, columns=("left", "right", "part", "status"), show="headings", selectmode="browse")
        for key, label, width in (("left", "基準PDF", 230), ("right", "比較対象PDF", 230), ("part", "対象", 230), ("status", "判定", 250)):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=80)
        scrollbar = ttk.Scrollbar(result_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        for tag, color in ((Status.MATCH, "#205c30"), (Status.FONT_ONLY, "#205c30"), (Status.DIFFERENT, "#9c2b20"), (Status.ADDED, "#205880"), (Status.REMOVED, "#9c2b20"), (Status.UNKNOWN, "#805600")):
            self.tree.tag_configure(tag, foreground=color)
        self.tree.bind("<<TreeviewSelect>>", self.show_detail)
        pane.add(result_frame, weight=3)
        detail_frame = ttk.Frame(pane)
        ttk.Label(detail_frame, text="詳細 (結果行を選択してください)").pack(anchor="w")
        self.detail = tk.Text(detail_frame, height=9, wrap="word", state="disabled")
        detail_scroll = ttk.Scrollbar(detail_frame, command=self.detail.yview)
        self.detail.configure(yscrollcommand=detail_scroll.set)
        self.detail.pack(side="left", fill="both", expand=True)
        detail_scroll.pack(side="right", fill="y")
        pane.add(detail_frame, weight=2)
        ttk.Label(frame, text="グループごとに独立して比較します。フォントのみ変更した一致は字幅や見た目の完全一致を保証しません。原本は変更しません。", wraplength=1020).pack(anchor="w", pady=(8, 0))
        self.add_files(files)
        root.after(100, self.poll)

    def set_detail(self, text):
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text)
        self.detail.configure(state="disabled")

    def invalidate(self):
        self.report = None
        self.tree.delete(*self.tree.get_children())
        self.save_button.configure(state="disabled")
        self.set_detail("")
        self.status.set("待機中")

    def refresh_files(self):
        self.file_list.delete(0, "end")
        for i, path in enumerate(self.files, 1):
            self.file_list.insert("end", f"{i}. {'[基準PDF]' if i == 1 else '[比較対象]'} {path}")
        self.reference_label.configure(text=f"基準PDF: {self.files[0] if self.files else '未選択'}")
        self.invalidate()

    def add_files(self, files):
        if self.process:
            return
        rejected = []
        for path in files:
            path = Path(path).resolve()
            if len(self.files) >= 4 or path.suffix.lower() != ".pdf" or not path.is_file():
                rejected.append(str(path))
                continue
            self.files.append(str(path))
        self.refresh_files()
        if rejected:
            messagebox.showerror("追加できません", "PDF は最大 4 個です。存在する PDF を指定してください。\n" + "\n".join(rejected), parent=self.root)

    def add_dialog(self):
        self.add_files(filedialog.askopenfilenames(title="比較する PDF を選択", filetypes=[("PDF", "*.pdf")], parent=self.root))

    def remove(self):
        if self.process:
            return
        for index in reversed(self.file_list.curselection()):
            del self.files[index]
        self.refresh_files()

    def move(self, delta):
        selected = self.file_list.curselection()
        if self.process or len(selected) != 1:
            return
        i = selected[0]
        j = i + delta
        if 0 <= j < len(self.files):
            self.files[i], self.files[j] = self.files[j], self.files[i]
            self.refresh_files()
            self.file_list.selection_set(j)

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
        if not 2 <= len(self.files) <= 4:
            messagebox.showerror("入力エラー", "PDF を 2～4 個指定してください。", parent=self.root)
            return
        self.invalidate()
        self.generation += 1
        generation = self.generation
        try:
            process = subprocess.Popen([sys.executable, "-S", str(PROJECT / "main.py"), "--json", *self.files], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            self.status.set("検証不能: 比較プロセスの起動失敗")
            self.set_detail(str(exc))
            return
        self.process = process
        self.busy(True)
        self.status.set(f"比較中: 基準PDF 対 {len(self.files)-1} ファイル (上限 {TIMEOUT} 秒)")
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
        threading.Thread(target=work, daemon=True).start()

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
        self.root.after(100, self.poll)

    def render_report(self, report):
        self.report = report
        self.status.set(f"比較完了 / グループ別結果 {len(report.results)} 行 / ファイル解析エラー {len(report.errors)} 件")
        for index, row in enumerate(report.results):
            left = f"{report.files.index(row.left) + 1}. {Path(row.left).name}"
            right = f"{report.files.index(row.right) + 1}. {Path(row.right).name}"
            self.tree.insert("", "end", iid=str(index), values=(left, right, row.component, row.status), tags=(row.status,))
        self.set_detail("\n\n".join(report.errors) if report.errors else "結果行を選択すると、内容判定・差異と注釈の作成者名（PDF記録値）・件数を表示します。")
        self.save_button.configure(state="normal")

    def show_detail(self, event=None):
        selected = self.tree.selection()
        if not selected or not self.report:
            return
        row = self.report.results[int(selected[0])]
        self.set_detail(row_details(row))

    def cancel(self):
        if self.process:
            self.generation += 1
            if self.process.poll() is None:
                self.process.kill()
            self.process = None
            self.busy(False)
            self.status.set("中止しました。判定結果はありません。")

    def save(self):
        if not self.report:
            return
        destination = filedialog.asksaveasfilename(parent=self.root, title="結果を保存", defaultextension=".txt", filetypes=[("テキスト", "*.txt"), ("CSV", "*.csv"), ("JSON", "*.json")])
        if destination:
            try:
                save_report(self.report, destination)
            except (OSError, ValueError) as exc:
                messagebox.showerror("保存エラー", str(exc), parent=self.root)

    def close(self):
        self.closed = True
        self.cancel()
        self.root.destroy()


def launch(files=()):
    root = tk.Tk()
    Application(root, files)
    root.mainloop()
