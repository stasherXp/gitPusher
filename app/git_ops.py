# -*- coding: utf-8 -*-
# Работа с git + автосоздание .gitignore и README.
import os, subprocess
from templates import GITIGNORE_TEMPLATE, README_TEMPLATE


def git_available():
    try:
        r = subprocess.run(["git", "--version"], capture_output=True, text=True,
                           timeout=5, errors="replace")
        return r.returncode == 0, ((r.stdout or "") + (r.stderr or "")).strip()
    except FileNotFoundError:
        return False, ("git не найден в PATH.\nУстановите Git for Windows: "
                       "https://git-scm.com/download/win")
    except Exception as e:
        return False, "Ошибка проверки git: " + str(e)


def run_git(args, cwd=None, timeout=120):
    try:
        r = subprocess.run(["git"] + args, cwd=cwd, capture_output=True,
                           text=True, timeout=timeout, errors="replace")
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        return r.returncode == 0, out
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT: git " + " ".join(args)
    except Exception as e:
        return False, "ОШИБКА: " + str(e)


def ensure_gitignore(folder, log):
    p = os.path.join(folder, ".gitignore")
    if os.path.exists(p):
        return p
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(GITIGNORE_TEMPLATE)
    log("[gitignore] создан: " + p)
    return p


def ensure_readme(folder, name, log, encoding="cp1251"):
    p = os.path.join(folder, "README.md")
    if os.path.exists(p):
        return p
    try:
        with open(p, "w", encoding=encoding, newline="\r\n") as f:
            f.write(README_TEMPLATE.format(name=name or os.path.basename(folder)))
        log("[readme] создан (" + encoding + "): " + p)
    except Exception as e:
        log("[readme-ERR] " + str(e))
    return p
