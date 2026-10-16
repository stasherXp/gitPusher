# -*- coding: utf-8 -*-
# GitPusher UI v3.0 - упрощённый интерфейс.
# Меню-бар, статус-бар, отдельное окно настроек, свёрнутый лог, фильтр.
import os, threading, time, queue, subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import webbrowser

import storage
import classification
import backups
import git_ops
import config

msg_q = queue.Queue()

GIT_STATUS_NAMES = {
    "??": "новый",
    "M":  "изменён",
    "MM": "изменён+add",
    "A":  "добавлен",
    "AM": "добавлен, изменён",
    "D":  "удалён",
    "R":  "переименован",
    "C":  "скопирован",
    "U":  "конфликт",
    "!!": "игнор",
}

def _git_status_name(st):
    if not st or st == "unchanged":
        return "без изменений"
    return GIT_STATUS_NAMES.get(st, st)

FILTERS = ["Все", "Только изменённые", "Только безопасные", "Скрыть служебные"]
NOISE_REASONS = {"Служебная папка", "OS-мусор"}


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("GitPusher v3.0")
        self.root.geometry("1180x780")
        self.root.minsize(900, 600)
        self.con = storage.db_connect()
        self.plan = []
        self.plan_index = -1
        self.busy = False
        self.abort_flag = False
        self.backup_files = []
        self.git_info = "git: проверка..."
        self.status_counts = {"total": 0, "changed": 0, "danger": 0, "warn": 0}
        self.log_visible = False
        self._settings_win = None
        self._load_cfg()
        self._build_menu()
        self._build()
        self._update_statusbar()
        self._check_git_async()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close_main)
        self.root.after(config.POLL_MS, self._poll)

    def _on_close_main(self):
        if self.busy:
            if not messagebox.askyesno("Выход",
                    "Идёт выполнение плана. Прервать и выйти?"):
                return
            self.abort_flag = True
        try:
            self.con.close()
        except Exception:
            pass
        self.root.destroy()

    # ---------- меню ----------
    def _build_menu(self):
        menubar = tk.Menu(self.root)

        m_file = tk.Menu(menubar, tearoff=0)
        m_file.add_command(label="Открыть папку...", accelerator="Ctrl+O",
                           command=self._choose_folder)
        m_file.add_command(label="Открыть backups", command=self._open_logs)
        m_file.add_separator()
        m_file.add_command(label="Выход", command=self.root.destroy)
        menubar.add_cascade(label="Файл", menu=m_file)

        m_git = tk.Menu(menubar, tearoff=0)
        m_git.add_command(label="Проверить Git", command=self._check_git_async)
        m_git.add_command(label="Проверить remote", command=self.check_remote)
        m_git.add_command(label="Открыть репо в браузере", command=self.open_repo_in_browser)
        m_git.add_separator()
        m_git.add_command(label="Показать diff", command=self.show_diff)
        m_git.add_command(label="История команд", command=self._show_history)
        menubar.add_cascade(label="Git", menu=m_git)

        m_tools = tk.Menu(menubar, tearoff=0)
        m_tools.add_command(label="Настройки...", accelerator="Ctrl+,",
                            command=self._open_settings)
        m_tools.add_separator()
        m_tools.add_command(label="Редактор .gitignore", command=self._edit_gitignore)
        m_tools.add_command(label="Редактор README", command=self._edit_readme)
        menubar.add_cascade(label="Инструменты", menu=m_tools)

        m_help = tk.Menu(menubar, tearoff=0)
        m_help.add_command(label="О программе", command=self._about)
        menubar.add_cascade(label="Справка", menu=m_help)

        self.root.config(menu=menubar)
        self.root.bind("<Control-o>", lambda e: self._choose_folder())
        self.root.bind("<Control-comma>", lambda e: self._open_settings())
        self.root.bind("<F5>", lambda e: self._refresh_files())

    # ---------- главный интерфейс ----------
    def _build(self):
        f_path = tk.Frame(self.root)
        f_path.pack(fill="x", padx=8, pady=(8, 4))
        tk.Label(f_path, text="Папка:", anchor="w").pack(side="left")
        e = tk.Entry(f_path, textvariable=self.var_folder)
        e.pack(side="left", fill="x", expand=True, padx=4)
        e.bind("<Return>", lambda ev: self._refresh_files())
        tk.Button(f_path, text="...", width=3,
                  command=self._choose_folder).pack(side="left")
        tk.Button(f_path, text="Обновить", width=12,
                  command=self._refresh_files).pack(side="left", padx=4)

        f_files = tk.LabelFrame(self.root, text="Файлы для пуша")
        f_files.pack(fill="both", expand=True, padx=8, pady=4)

        bar = tk.Frame(f_files); bar.pack(fill="x")
        tk.Button(bar, text="Все", width=8,
                  command=lambda: self._set_all(True)).pack(side="left", padx=3, pady=3)
        tk.Button(bar, text="Ничего", width=8,
                  command=lambda: self._set_all(False)).pack(side="left", padx=3)
        tk.Button(bar, text="Изменённые", width=12,
                  command=self._select_modified).pack(side="left", padx=3)
        tk.Button(bar, text="Безопасные", width=12,
                  command=self._select_safe).pack(side="left", padx=3)

        tk.Label(bar, text="Фильтр:").pack(side="left", padx=(20, 3))
        cb = ttk.Combobox(bar, textvariable=self.var_filter,
                          values=FILTERS, width=22, state="readonly")
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda ev: self._on_filter_change())

        self.tree = ttk.Treeview(f_files, columns=("chk", "status", "path"),
                                 show="headings", height=10)
        self.tree.heading("chk", text="Пуш")
        self.tree.heading("status", text="Git / предупреждение")
        self.tree.heading("path", text="Путь")
        self.tree.column("chk", width=70, anchor="center", stretch=False)
        self.tree.column("status", width=300, stretch=False)
        self.tree.column("path", width=780)
        vs = ttk.Scrollbar(f_files, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Button-1>", self._on_click)
        self.tree.tag_configure("danger", background="#ffcdd2", foreground="#7f0000")
        self.tree.tag_configure("warn",   background="#fff3cd", foreground="#7f5f00")
        self.tree.tag_configure("ok",     background="")

        f_plan = tk.LabelFrame(self.root, text="План команд")
        f_plan.pack(fill="both", expand=True, padx=8, pady=4)

        bar2 = tk.Frame(f_plan); bar2.pack(fill="x")
        tk.Button(bar2, text="Составить план", bg="#1565c0", fg="white", width=16,
                  command=self._build_plan).pack(side="left", padx=3, pady=3)
        self.btn_step = tk.Button(bar2, text="Шаг", width=10,
                                  command=self._execute_one, state="disabled")
        self.btn_step.pack(side="left", padx=3)
        self.btn_all = tk.Button(bar2, text="Всё", width=10,
                                 command=self._execute_all, state="disabled")
        self.btn_all.pack(side="left", padx=3)
        self.btn_skip = tk.Button(bar2, text="Пропуск", width=10,
                                  command=self._skip_one, state="disabled")
        self.btn_skip.pack(side="left", padx=3)
        self.btn_abort = tk.Button(bar2, text="Стоп", width=10, fg="#a00",
                                   command=self._abort, state="disabled")
        self.btn_abort.pack(side="left", padx=3)
        tk.Button(bar2, text="Сброс", width=10,
                  command=self._clear_plan).pack(side="left", padx=10)

        self.tv_plan = ttk.Treeview(f_plan, columns=("n", "kind", "status", "cmd"),
                                    show="headings", height=7)
        self.tv_plan.heading("n", text="#")
        self.tv_plan.heading("kind", text="Тип")
        self.tv_plan.heading("status", text="Статус")
        self.tv_plan.heading("cmd", text="Команда")
        self.tv_plan.column("n", width=40, anchor="center", stretch=False)
        self.tv_plan.column("kind", width=110, stretch=False)
        self.tv_plan.column("status", width=110, stretch=False)
        self.tv_plan.column("cmd", width=830)
        vs2 = ttk.Scrollbar(f_plan, orient="vertical", command=self.tv_plan.yview)
        self.tv_plan.configure(yscrollcommand=vs2.set)
        vs2.pack(side="right", fill="y")
        self.tv_plan.pack(fill="both", expand=True)
        self.tv_plan.tag_configure("pending", foreground="#444")
        self.tv_plan.tag_configure("running", background="#fff59d")
        self.tv_plan.tag_configure("ok", background="#c8e6c9")
        self.tv_plan.tag_configure("fail", background="#ffcdd2")
        self.tv_plan.tag_configure("skipped", foreground="#888")

        f_log = tk.Frame(self.root)
        f_log.pack(fill="x", padx=8, pady=(4, 0))
        self.btn_log_toggle = tk.Button(f_log, text="Показать лог", width=14,
                                        command=self._toggle_log)
        self.btn_log_toggle.pack(side="left")
        tk.Button(f_log, text="Очистить", width=10,
                  command=self._clear_log).pack(side="left", padx=4)

        self.log_frame = tk.Frame(self.root)
        self.log = tk.Text(self.log_frame, height=12, wrap="word",
                           bg="#111", fg="#ddd", font=("Consolas", 9))
        vs3 = ttk.Scrollbar(self.log_frame, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=vs3.set)
        vs3.pack(side="right", fill="y")
        self.log.pack(fill="both", expand=True)

        self.statusbar = tk.Label(self.root, text="", anchor="w",
                                  relief="sunken", bd=1, padx=6, fg="#333")
        self.statusbar.pack(fill="x", side="bottom")

    # ---------- настройки ----------
    def _open_settings(self):
        if self._settings_win is not None and self._settings_win.winfo_exists():
            self._settings_win.lift()
            self._settings_win.focus_force()
            return
        win = tk.Toplevel(self.root)
        self._settings_win = win
        win.title("Настройки")
        win.geometry("620x400")
        win.transient(self.root)
        win.grab_set()

        f = tk.Frame(win, padx=12, pady=12)
        f.pack(fill="both", expand=True)

        def row(lbl, var):
            r = tk.Frame(f); r.pack(fill="x", pady=4)
            tk.Label(r, text=lbl, width=16, anchor="w").pack(side="left")
            tk.Entry(r, textvariable=var).pack(side="left", fill="x", expand=True)

        row("Ник:", self.var_name)
        row("Email:", self.var_email)
        row("Репозиторий:", self.var_repo)
        row("Ветка:", self.var_branch)
        row("Коммит:", self.var_commit)

        r = tk.Frame(f); r.pack(fill="x", pady=(14, 4))
        tk.Checkbutton(r, text="Делать бекап выбранных файлов перед add",
                       variable=self.var_backup_setting,
                       command=self._save_cfg).pack(side="left")

        r = tk.Frame(f); r.pack(fill="x", pady=14)
        def save():
            self._save_cfg()
            self._settings_win = None
            win.destroy()
            self._log("[cfg] сохранено из окна настроек")
        def cancel():
            self._settings_win = None
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", cancel)
        tk.Button(r, text="Сохранить", width=14,
                  command=save).pack(side="right", padx=4)
        tk.Button(r, text="Отмена", width=10,
                  command=cancel).pack(side="right")

    def _about(self):
        messagebox.showinfo(
            "О программе",
            "GitPusher v3.0\n\n"
            "Помощник пуша на GitHub:\n"
            "- ручное подтверждение каждого шага\n"
            "- бекап файлов перед add\n"
            "- сканер секретов\n"
            "- подсветка опасных файлов"
        )

    def _open_logs(self):
        p = os.path.join(config.BASE, "backups")
        if os.path.isdir(p):
            try:
                os.startfile(p)
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))
        else:
            messagebox.showinfo("Инфо", "Папка backups не найдена")

    def _toggle_log(self):
        if self.log_visible:
            self.log_frame.pack_forget()
            self.btn_log_toggle.config(text="Показать лог")
            self.log_visible = False
        else:
            self.log_frame.pack(fill="both", expand=True, padx=8, pady=(0, 4),
                                before=self.statusbar)
            self.btn_log_toggle.config(text="Скрыть лог")
            self.log_visible = True

    def _clear_log(self):
        self.log.delete("1.0", "end")

    def _on_filter_change(self):
        storage.cfg_set(self.con, "filter", self.var_filter.get())
        self._refresh_files()

    def _update_statusbar(self):
        c = self.status_counts
        self.statusbar.config(
            text=(self.git_info
                  + "  |  файлов: " + str(c["total"])
                  + "  |  изменено: " + str(c["changed"])
                  + "  |  опасно: " + str(c["danger"])
                  + "  |  вним: " + str(c["warn"]))
        )

    # ---------- конфиг ----------
    def _load_cfg(self):
        self.var_name = tk.StringVar()
        self.var_email = tk.StringVar()
        self.var_repo = tk.StringVar()
        self.var_folder = tk.StringVar()
        self.var_branch = tk.StringVar(value="main")
        self.var_commit = tk.StringVar(value="Update files")
        self.var_backup_setting = tk.BooleanVar(value=True)
        self.var_filter = tk.StringVar(value=FILTERS[0])

        self.var_name.set(storage.cfg_get(self.con, "name"))
        self.var_email.set(storage.cfg_get(self.con, "email"))
        self.var_repo.set(storage.cfg_get(self.con, "repo"))
        self.var_folder.set(storage.cfg_get(self.con, "folder"))
        self.var_branch.set(storage.cfg_get(self.con, "branch", "main"))
        self.var_commit.set(storage.cfg_get(self.con, "commit", "Update files"))
        self.var_backup_setting.set(storage.cfg_get(self.con, "backup", "1") != "0")
        _flt = storage.cfg_get(self.con, "filter", FILTERS[0])
        if _flt in FILTERS:
            self.var_filter.set(_flt)

    def _save_cfg(self):
        storage.cfg_set(self.con, "name", self.var_name.get().strip())
        storage.cfg_set(self.con, "email", self.var_email.get().strip())
        storage.cfg_set(self.con, "repo", self.var_repo.get().strip())
        storage.cfg_set(self.con, "folder", self.var_folder.get().strip())
        storage.cfg_set(self.con, "branch", self.var_branch.get().strip() or "main")
        storage.cfg_set(self.con, "commit", self.var_commit.get().strip() or "Update files")
        storage.cfg_set(self.con, "backup", "1" if self.var_backup_setting.get() else "0")
        storage.cfg_set(self.con, "filter", self.var_filter.get())

    def _choose_folder(self):
        d = filedialog.askdirectory()
        if d:
            self.var_folder.set(d)
            self._refresh_files()

    # ---------- файлы ----------
    def _refresh_files(self):
        folder = self.var_folder.get().strip()
        if not folder or not os.path.isdir(folder):
            self._log("[files] папка не выбрана")
            self.status_counts = {"total": 0, "changed": 0, "danger": 0, "warn": 0}
            self._update_statusbar()
            return
        for i in self.tree.get_children():
            self.tree.delete(i)
        statuses = {}
        if os.path.isdir(os.path.join(folder, ".git")):
            ok, out = git_ops.run_git(["-C", folder, "status", "--porcelain"], timeout=20)
            if ok:
                for line in out.splitlines():
                    if not line.strip():
                        continue
                    code = line[:2].strip() or "?"
                    path = line[3:].strip()
                    if " -> " in path:
                        path = path.split(" -> ", 1)[1]
                    path = path.strip('"').replace("\\", "/")
                    statuses[path] = code
        files = []
        for cur, dirs, names in os.walk(folder):
            if ".git" in dirs:
                dirs.remove(".git")
            for n in names:
                full = os.path.join(cur, n)
                rel = os.path.relpath(full, folder).replace("\\", "/")
                files.append(rel)
        files.sort()

        flt = self.var_filter.get()
        d_cnt = w_cnt = ch_cnt = 0
        shown = 0
        for rel in files:
            st = statuses.get(rel, "")
            full = os.path.join(folder, rel)
            try:
                sz = os.path.getsize(full)
            except OSError:
                sz = 0
            level, why = classification.classify_path(rel, sz)

            if level == "danger":
                d_cnt += 1
            elif level == "warn":
                w_cnt += 1
            if st and st != "??":
                ch_cnt += 1

            if flt == FILTERS[1] and not (st and st != "??"):
                continue
            if flt == FILTERS[2] and level != "ok":
                continue
            if flt == FILTERS[3] and why in NOISE_REASONS:
                continue

            mark = "[x]" if st and st != "??" else "[  ]"
            if level in ("danger", "warn"):
                mark = "[  ]"
            status_txt = _git_status_name(st)
            if why:
                status_txt = status_txt + "  (" + why + ")"
            self.tree.insert("", "end", values=(mark, status_txt, rel), tags=(level,))
            shown += 1

        self.status_counts = {"total": len(files), "changed": ch_cnt,
                              "danger": d_cnt, "warn": w_cnt}
        self._update_statusbar()
        self._log("[files] всего: " + str(len(files))
                  + " | показано: " + str(shown)
                  + " | изменено: " + str(ch_cnt)
                  + " | опасно: " + str(d_cnt)
                  + " | вним: " + str(w_cnt))

    def _on_click(self, event):
        if self.tree.identify_column(event.x) != "#1":
            return
        item = self.tree.identify_row(event.y)
        if not item:
            return
        vals = list(self.tree.item(item, "values"))
        vals[0] = "[  ]" if vals[0] == "[x]" else "[x]"
        self.tree.item(item, values=vals)

    def _set_all(self, val):
        mark = "[x]" if val else "[  ]"
        for i in self.tree.get_children():
            vals = list(self.tree.item(i, "values"))
            vals[0] = mark
            self.tree.item(i, values=vals)

    def _select_modified(self):
        for i in self.tree.get_children():
            vals = list(self.tree.item(i, "values"))
            vals[0] = "[  ]" if vals[1].startswith("без изменений") or vals[1].startswith("unchanged") else "[x]"
            self.tree.item(i, values=vals)

    def _select_safe(self):
        for i in self.tree.get_children():
            tags = self.tree.item(i, "tags")
            vals = list(self.tree.item(i, "values"))
            vals[0] = "[x]" if "danger" not in tags and "warn" not in tags else "[  ]"
            self.tree.item(i, values=vals)

    def _selected_files(self):
        out = []
        for i in self.tree.get_children():
            vals = self.tree.item(i, "values")
            if vals[0] == "[x]":
                out.append(vals[2])
        return out

    # ---------- план ----------
    def _clear_plan(self):
        if self.busy:
            return
        self.plan = []
        self.plan_index = -1
        self.abort_flag = False
        for i in self.tv_plan.get_children():
            self.tv_plan.delete(i)
        self._update_buttons()

    def _add_step(self, kind, title, args, cwd=None, timeout=120, special=None):
        self.plan.append({
            "kind": kind, "title": title, "args": args, "cwd": cwd,
            "timeout": timeout, "status": "pending", "out": "", "special": special,
        })

    def _build_plan(self):
        if self.busy:
            return
        name = self.var_name.get().strip()
        email = self.var_email.get().strip()
        repo = self.var_repo.get().strip()
        folder = self.var_folder.get().strip()
        branch = self.var_branch.get().strip() or "main"
        commit = self.var_commit.get().strip() or "Update files"
        do_backup = self.var_backup_setting.get()

        if not folder or not os.path.isdir(folder):
            messagebox.showerror("Ошибка", "Папка не выбрана или не существует")
            return
        if not name or not email:
            messagebox.showerror("Ошибка", "Заполните ник и email в Настройках")
            return
        if not repo:
            messagebox.showerror("Ошибка", "Укажите URL репозитория в Настройках")
            return

        files = self._selected_files()
        if not files:
            messagebox.showerror("Ошибка", "Не выбрано ни одного файла")
            return

        self._save_cfg()
        self._clear_plan()
        self.backup_files = files

        try:
            git_ops.ensure_gitignore(folder, lambda s: self._log(s))
            git_ops.ensure_readme(folder, name or os.path.basename(folder),
                                  lambda s: self._log(s), encoding="cp1251")
        except Exception as e:
            self._log("[auto] " + str(e))

        big = []
        for rel in files:
            try:
                if os.path.getsize(os.path.join(folder, rel)) > classification.LARGE_BLOCK_MB * 1024 * 1024:
                    big.append(rel)
            except OSError:
                pass
        if big:
            self._log("[big] исключены: " + ", ".join(big))
            messagebox.showwarning(
                "Большие файлы",
                "Файлы больше " + str(classification.LARGE_BLOCK_MB) + " МБ исключены:\n"
                + "\n".join(big[:20]))
            files = [f for f in files if f not in big]
            self.backup_files = files

        has_git = os.path.isdir(os.path.join(folder, ".git"))
        if not has_git:
            self._add_step("init", "Инициализация репозитория", ["init"], cwd=folder)
        self._add_step("config", "user.name", ["config", "user.name", name], cwd=folder)
        self._add_step("config", "user.email", ["config", "user.email", email], cwd=folder)

        ok, url = git_ops.run_git(["remote", "get-url", "origin"], cwd=folder)
        if ok:
            self._add_step("remote", "remote set-url",
                           ["remote", "set-url", "origin", repo], cwd=folder)
        else:
            self._add_step("remote", "remote add",
                           ["remote", "add", "origin", repo], cwd=folder)

        if do_backup and files:
            self._add_step("backup", "Бекап выбранных файлов",
                           [], cwd=folder, special="backup")

        if files:
            self._add_step("scan-secrets", "Сканирование на секреты",
                           [], cwd=folder, special="scan-secrets")

        self._add_step("add", "git add (выбранные файлы)",
                       ["add", "--"] + files, cwd=folder, timeout=300)
        self._add_step("commit", "git commit", ["commit", "-m", commit], cwd=folder)
        self._add_step("branch", "Переименовать ветку в " + branch,
                       ["branch", "-M", branch], cwd=folder)
        self._add_step("push", "git push -u origin " + branch,
                       ["push", "-u", "origin", branch], cwd=folder, timeout=600)

        self._render_plan()
        self.plan_index = -1
        self.abort_flag = False
        self._log("[plan] шагов: " + str(len(self.plan)))
        self._update_buttons()

    def _render_plan(self):
        for i in self.tv_plan.get_children():
            self.tv_plan.delete(i)
        for n, step in enumerate(self.plan, 1):
            if step["kind"] == "backup":
                cmd_txt = "БЕКАП -> backups/<timestamp>/"
            elif step["kind"] == "scan-secrets":
                cmd_txt = "СКАНЕР СЕКРЕТОВ"
            else:
                cmd_txt = "git " + " ".join(step["args"])
            self.tv_plan.insert("", "end", iid=str(n - 1),
                                values=(n, step["kind"], step["status"], cmd_txt),
                                tags=(step["status"],))

    def _update_row(self, idx):
        step = self.plan[idx]
        iid = str(idx)
        vals = list(self.tv_plan.item(iid, "values"))
        vals[2] = step["status"]
        self.tv_plan.item(iid, values=vals, tags=(step["status"],))
        self.tv_plan.see(iid)

    def _update_buttons(self):
        has_pending = any(s["status"] == "pending" for s in self.plan)
        if self.busy:
            self.btn_step.config(state="disabled")
            self.btn_all.config(state="disabled")
            self.btn_skip.config(state="disabled")
            self.btn_abort.config(state="normal")
        else:
            self.btn_step.config(state="normal" if has_pending else "disabled")
            self.btn_all.config(state="normal" if has_pending else "disabled")
            self.btn_skip.config(state="normal" if has_pending else "disabled")
            self.btn_abort.config(state="disabled")

    def _next_pending_idx(self):
        for i, s in enumerate(self.plan):
            if s["status"] == "pending":
                return i
        return -1

    def _execute_one(self):
        if self.busy:
            return
        idx = self._next_pending_idx()
        if idx < 0:
            messagebox.showinfo("План", "Нет ожидающих шагов")
            return
        self.plan_index = idx
        self.busy = True
        self._update_buttons()
        threading.Thread(target=self._run_step, args=(idx,), daemon=True).start()

    def _execute_all(self):
        if self.busy:
            return
        self.abort_flag = False
        self.busy = True
        self._update_buttons()
        threading.Thread(target=self._run_all, daemon=True).start()

    def _skip_one(self):
        if self.busy:
            return
        idx = self._next_pending_idx()
        if idx < 0:
            return
        self.plan[idx]["status"] = "skipped"
        self._update_row(idx)
        self._log("[skip] шаг " + str(idx + 1) + ": " + self.plan[idx]["title"])
        self._update_buttons()

    def _abort(self):
        self.abort_flag = True
        self._log("[abort] остановка после текущего шага")

    def _run_all(self):
        while not self.abort_flag:
            idx = self._next_pending_idx()
            if idx < 0:
                break
            ok = self._do_step(idx)
            if not ok:
                msg_q.put(("log", "[plan] остановлено на шаге " + str(idx + 1)))
                break
        msg_q.put(("busy_off",))

    def _run_step(self, idx):
        self._do_step(idx)
        msg_q.put(("busy_off",))

    def _do_step(self, idx):
        step = self.plan[idx]
        step["status"] = "running"
        msg_q.put(("row", idx))

        if step["kind"] == "backup":
            msg_q.put(("log", "=" * 60))
            msg_q.put(("log", "[backup] запуск"))
            try:
                dst = backups.make_backup(step["cwd"], self.backup_files,
                                          lambda s: msg_q.put(("log", s)))
                step["status"] = "ok" if dst else "fail"
                step["out"] = dst or ""
                self._hist("", step["title"], "backup -> " + str(dst), 1 if dst else 0)
            except Exception as e:
                step["status"] = "fail"
                step["out"] = str(e)
                msg_q.put(("log", "[backup-EXC] " + str(e)))
                self._hist("", step["title"], "backup", 0)
            msg_q.put(("row", idx))
            return step["status"] == "ok"

        if step["kind"] == "scan-secrets":
            msg_q.put(("log", "=" * 60))
            msg_q.put(("log", "[scan-secrets] запуск"))
            hits = classification.scan_secrets(step["cwd"], self.backup_files,
                                                lambda s: msg_q.put(("log", s)))
            if hits:
                step["status"] = "fail"
                msg_q.put(("log", "[scan-secrets] совпадений: " + str(len(hits))))
                msg_q.put(("secrets_alert", hits))
            else:
                step["status"] = "ok"
                msg_q.put(("log", "[scan-secrets] чисто"))
            self._hist(self.var_repo.get(), step["title"], "scan-secrets",
                       0 if hits else 1)
            msg_q.put(("row", idx))
            return step["status"] == "ok"

        cmd_txt = "git " + " ".join(step["args"])
        msg_q.put(("log", "=" * 60))
        msg_q.put(("log", "[step " + str(idx + 1) + "] " + step["title"]))
        msg_q.put(("log", "[cmd] " + cmd_txt))

        ok, out = git_ops.run_git(step["args"], cwd=step["cwd"], timeout=step["timeout"])
        step["out"] = out or ""
        if out:
            msg_q.put(("log", out))

        low = (out or "").lower()
        if step["kind"] == "commit" and not ok:
            if "nothing to commit" in low or "no changes added" in low:
                msg_q.put(("log", "[warn] нечего коммитить - skipped"))
                step["status"] = "skipped"
                self._hist(self.var_repo.get(), step["title"], cmd_txt, 1)
                msg_q.put(("row", idx))
                return True

        step["status"] = "ok" if ok else "fail"
        self._hist(self.var_repo.get(), step["title"], cmd_txt, 1 if ok else 0)
        msg_q.put(("row", idx))
        msg_q.put(("log", ("[ok] " if ok else "[FAIL] ") + step["title"]))
        return ok

    def _hist(self, repo, step, cmd, ok):
        storage.hist_add(repo, step, cmd, ok)

    # ---------- лог ----------
    def _log(self, text):
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.update_idletasks()

    # ---------- git-операции ----------
    def _check_git_async(self):
        def w():
            ok, info = git_ops.git_available()
            msg_q.put(("git", ok, info))
        threading.Thread(target=w, daemon=True).start()

    def check_remote(self):
        repo = self.var_repo.get().strip()
        if not repo:
            messagebox.showerror("Remote", "URL не указан в Настройках")
            return
        def w():
            try:
                r = subprocess.run(["git", "ls-remote", repo],
                                   capture_output=True, text=True,
                                   timeout=30, errors="replace")
                ok = r.returncode == 0
                out = (r.stdout or "") + (r.stderr or "")
            except Exception as e:
                ok, out = False, str(e)
            msg_q.put(("remote_check", ok, out))
        threading.Thread(target=w, daemon=True).start()

    def open_repo_in_browser(self):
        url = self.var_repo.get().strip()
        if not url:
            messagebox.showinfo("Репо", "URL не указан")
            return
        url = url.rstrip("/")
        if url.endswith(".git"):
            url = url[:-4]
        webbrowser.open(url)

    def show_diff(self):
        folder = self.var_folder.get().strip()
        if not folder or not os.path.isdir(os.path.join(folder, ".git")):
            messagebox.showinfo("Diff", "Это не git-репозиторий")
            return
        git_ops.run_git(["add", "-N", "."], cwd=folder, timeout=30)
        ok, out = git_ops.run_git(["diff", "--stat"], cwd=folder, timeout=30)
        ok2, full = git_ops.run_git(["diff"], cwd=folder, timeout=60)
        win = tk.Toplevel(self.root)
        win.title("Diff - " + folder)
        win.geometry("1100x700")
        txt = tk.Text(win, wrap="none", font=("Consolas", 9), bg="#111", fg="#ddd")
        vs = ttk.Scrollbar(win, orient="vertical", command=txt.yview)
        hs = ttk.Scrollbar(win, orient="horizontal", command=txt.xview)
        txt.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        txt.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        hs.pack(side="bottom", fill="x")
        txt.insert("1.0", (out or "") + "\n\n" + (full or "(нет изменений)"))
        txt.config(state="disabled")

    # ---------- редактор ----------
    def edit_text_file(self, path, encoding, title):
        if not os.path.exists(path):
            if not messagebox.askyesno(title, "Файл не найден:\n" + path
                                       + "\n\nСоздать пустой?"):
                return
            open(path, "w", encoding=encoding, newline="\r\n").close()
        win = tk.Toplevel(self.root)
        win.title(title + " - " + os.path.basename(path))
        win.geometry("900x600")
        bar = tk.Frame(win); bar.pack(side="top", fill="x")
        txt = tk.Text(win, wrap="none", font=("Consolas", 10), undo=True)
        vs = ttk.Scrollbar(win, orient="vertical", command=txt.yview)
        hs = ttk.Scrollbar(win, orient="horizontal", command=txt.xview)
        txt.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        txt.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        hs.pack(side="bottom", fill="x")
        try:
            with open(path, "r", encoding=encoding, errors="replace") as f:
                txt.insert("1.0", f.read())
        except Exception as e:
            messagebox.showerror("Ошибка чтения", str(e))

        def save():
            try:
                with open(path, "w", encoding=encoding, newline="\r\n") as f:
                    f.write(txt.get("1.0", "end-1c"))
                self._log("[save] " + path + " (" + encoding + ")")
                messagebox.showinfo("OK", "Сохранено: " + encoding)
            except Exception as e:
                messagebox.showerror("Ошибка записи", str(e))

        def reload_from_disk():
            try:
                with open(path, "r", encoding=encoding, errors="replace") as f:
                    txt.delete("1.0", "end")
                    txt.insert("1.0", f.read())
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))

        tk.Button(bar, text="Сохранить", command=save).pack(side="left", padx=4, pady=3)
        tk.Button(bar, text="Перечитать", command=reload_from_disk).pack(side="left", padx=4, pady=3)
        tk.Label(bar, text="Кодировка: " + encoding).pack(side="left", padx=12)

    def _edit_gitignore(self):
        folder = self.var_folder.get().strip()
        if not folder:
            messagebox.showerror("Редактор", "Сначала выберите папку")
            return
        git_ops.ensure_gitignore(folder, lambda s: self._log(s))
        self.edit_text_file(os.path.join(folder, ".gitignore"),
                            "utf-8", "Редактор .gitignore")

    def _edit_readme(self):
        folder = self.var_folder.get().strip()
        if not folder:
            messagebox.showerror("Редактор", "Сначала выберите папку")
            return
        git_ops.ensure_readme(folder, os.path.basename(folder),
                              lambda s: self._log(s), encoding="cp1251")
        self.edit_text_file(os.path.join(folder, "README.md"),
                            "cp1251", "Редактор README")

    # ---------- опрос очереди ----------
    def _poll(self):
        try:
            while True:
                m = msg_q.get_nowait()
                if m[0] == "git":
                    ok, info = m[1], m[2]
                    self.git_info = info
                    self._update_statusbar()
                    self._log(("[git] " if ok else "[git-ERROR] ") + info)
                elif m[0] == "log":
                    self._log(m[1])
                elif m[0] == "row":
                    self._update_row(m[1])
                elif m[0] == "busy_off":
                    self.busy = False
                    self._update_buttons()
                elif m[0] == "secrets_alert":
                    hits = m[1]
                    top = "\n".join(r + ":" + str(n) + "  " + s for r, n, s in hits[:15])
                    if messagebox.askyesno(
                        "Найдены возможные секреты",
                        "Совпадений: " + str(len(hits)) + "\n\n" + top
                        + "\n\nПродолжить?"):
                        for i, s in enumerate(self.plan):
                            if s["kind"] == "scan-secrets" and s["status"] == "fail":
                                s["status"] = "skipped"
                                self._update_row(i)
                    else:
                        self.abort_flag = True
                elif m[0] == "remote_check":
                    ok, out = m[1], m[2]
                    if ok:
                        messagebox.showinfo("Remote", "OK - репозиторий доступен")
                    else:
                        messagebox.showerror("Remote", "Ошибка:\n" + (out or "")[:800])
        except queue.Empty:
            pass
        self.root.after(config.POLL_MS, self._poll)

    def _show_history(self):
        try:
            rows = self.con.execute(
                "SELECT ts,step,ok,cmd FROM history ORDER BY id DESC LIMIT 100").fetchall()
        except Exception as e:
            messagebox.showerror("История", str(e)); return
        if not rows:
            messagebox.showinfo("История", "Пусто"); return
        lines = []
        for ts, step, ok, cmd in rows:
            mark = "OK " if ok else "ERR"
            lines.append(mark + "  " + time.strftime("%Y-%m-%d %H:%M:%S",
                                                     time.localtime(ts))
                         + "  " + step + "\n    " + cmd)
        messagebox.showinfo("История (100)", "\n".join(lines))
