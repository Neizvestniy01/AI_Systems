import os
import queue
import threading
import tkinter as tk
from argparse import Namespace
from contextlib import redirect_stdout
from tkinter import filedialog, scrolledtext, ttk
import photo_tagger as pt

os.chdir(os.path.dirname(os.path.abspath(__file__)))

class QueueWriter:
    def __init__(self, q: queue.Queue):
        self.q = q

    def write(self, s: str) -> int:
        if s:
            self.q.put(s)
        return len(s)

    def flush(self) -> None:
        pass

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Photo Tagger ({pt.MODEL})")
        self.geometry("820x600")
        self.q: queue.Queue = queue.Queue()
        self.buttons: list = []

        row1 = ttk.Frame(self, padding=(10, 10, 10, 0))
        row1.pack(fill="x")
        ttk.Label(row1, text="Папка з фото:").pack(side="left")
        self.folder_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.folder_var).pack(
            side="left", fill="x", expand=True, padx=6
        )
        self._button(row1, "Огляд…", self.browse)
        self._button(row1, "Описати", self.describe)
        self.force_var = tk.BooleanVar()
        ttk.Checkbutton(row1, text="переописати", variable=self.force_var).pack(
            side="left", padx=(6, 0)
        )

        row2 = ttk.Frame(self, padding=(10, 8, 10, 0))
        row2.pack(fill="x")
        ttk.Label(row2, text="Пошук:").pack(side="left")
        self.query_var = tk.StringVar()
        entry = ttk.Entry(row2, textvariable=self.query_var)
        entry.pack(side="left", fill="x", expand=True, padx=6)
        entry.bind("<Return>", lambda _e: self.search())
        self.all_var = tk.BooleanVar()
        ttk.Checkbutton(row2, text="усі слова", variable=self.all_var).pack(
            side="left", padx=(0, 6)
        )
        self._button(row2, "Шукати", self.search)
        self._button(row2, "Статистика", self.stats)

        row3 = ttk.Frame(self, padding=(10, 8, 10, 0))
        row3.pack(fill="x")
        self.status = ttk.Label(row3, text="Готово до роботи")
        self.status.pack(side="left")
        self.progress = ttk.Progressbar(row3, mode="indeterminate", length=150)
        self.progress.pack(side="right")

        self.output = scrolledtext.ScrolledText(self, wrap="word", font=("Consolas", 10))
        self.output.pack(fill="both", expand=True, padx=10, pady=10)
        self.show("Вкажи папку з фото і натисни «Описати», потім шукай за словами.\n")
        self.after(100, self.poll)

    def _button(self, parent, text, command):
        b = ttk.Button(parent, text=text, command=command)
        b.pack(side="left", padx=2)
        self.buttons.append(b)
        return b

    def show(self, text: str) -> None:
        self.output.insert("end", text)
        self.output.see("end")

    def set_busy(self, busy: bool, text: str = "") -> None:
        state = "disabled" if busy else "normal"
        for b in self.buttons:
            b.config(state=state)
        if busy:
            self.progress.start(12)
            self.status.config(text=text)
        else:
            self.progress.stop()
            self.status.config(text="Готово до роботи")

    def poll(self) -> None:
        try:
            while True:
                item = self.q.get_nowait()
                if item is None:
                    self.set_busy(False)
                else:
                    self.show(item)
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def run_task(self, func, args: Namespace, status: str, intro: str = "") -> None:
        self.output.delete("1.0", "end")
        if intro:
            self.show(intro)
        self.set_busy(True, status)

        def worker():
            with redirect_stdout(QueueWriter(self.q)):
                try:
                    func(args)
                except SystemExit as e:
                    if e.code:
                        print(e.code)
                except Exception as e:
                    print(f"Помилка: {e}")
            self.q.put(None)
        threading.Thread(target=worker, daemon=True).start()

    def browse(self) -> None:
        folder = filedialog.askdirectory()
        if folder:
            self.folder_var.set(folder)

    def describe(self) -> None:
        folder = self.folder_var.get().strip()
        if not folder:
            self.show("Спочатку вкажи папку.\n")
            return
        self.run_task(
            pt.cmd_describe,
            Namespace(folder=folder, force=self.force_var.get()),
            "Модель аналізує фото…",
            "Починаю. Перше фото може йти 1-2 хв (завантажується модель), "
            "далі швидше.\n\n",
        )

    def search(self) -> None:
        query = self.query_var.get().strip()
        if not query:
            self.show("Введи слово для пошуку.\n")
            return
        self.run_task(
            pt.cmd_search,
            Namespace(query=query, top=10, all=self.all_var.get()),
            "Шукаю…",
        )

    def stats(self) -> None:
        self.run_task(pt.cmd_stats, Namespace(), "Рахую статистику…")

if __name__ == "__main__":
    App().mainloop()