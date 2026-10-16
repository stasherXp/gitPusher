# -*- coding: utf-8 -*-
# Классификация файлов (danger/warn/ok) и сканер секретов.
import os, re

DANGER_RULES = [
    (re.compile(r"\.(db|db-wal|db-shm|sqlite|sqlite3)$", re.I), "danger", "БД - может содержать личные данные"),
    (re.compile(r"\.(env|pem|key|p12|pfx|jks|keystore|ppk)$", re.I), "danger", "Секреты/ключи"),
    (re.compile(r"^id_(rsa|dsa|ecdsa|ed25519)", re.I), "danger", "SSH-ключ"),
    (re.compile(r"(secret|password|passwd|token|api[_-]?key|credential)", re.I), "danger", "Возможно секрет"),
    (re.compile(r"\.(exe|msi|dll|so|dylib|bin)$", re.I), "danger", "Бинарник"),
    (re.compile(r"\.(zip|rar|7z|tar|gz|bz2|xz)$", re.I), "warn", "Архив"),
    (re.compile(r"[-._](log|tmp|cache|bak|orig|swp|swo)([-._]|$)", re.I), "warn", "Временный файл"),
    (re.compile(r"(^|/)(backups?|logs?|__pycache__|\.venv|venv|node_modules|"
                r"\.idea|\.vs|\.vscode|\.pytest_cache|\.mypy_cache)(/|$)", re.I),
     "warn", "Служебная папка"),
    (re.compile(r"^(Thumbs\.db|desktop\.ini|\.DS_Store)$", re.I), "warn", "OS-мусор"),
]

LARGE_WARN_MB  = 50
LARGE_BLOCK_MB = 100

SECRET_RE = re.compile(
    r"(?i)("
    r"api[_-]?key\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}"
    r"|secret\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{8,}"
    r"|password\s*[:=]\s*['\"]?\S{6,}"
    r"|token\s*[:=]\s*['\"]?[A-Za-z0-9_\-\.]{20,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|ghp_[A-Za-z0-9]{36}"
    r"|github_pat_[A-Za-z0-9_]{60,}"
    r"|xox[baprs]-[A-Za-z0-9-]{10,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|sk-[A-Za-z0-9]{32,}"
    r")"
)
SECRET_EXT = {".py", ".js", ".ts", ".txt", ".md", ".json", ".yml", ".yaml",
              ".ini", ".cfg", ".conf", ".env", ".bat", ".cmd", ".ps1", ".sh",
              ".html", ".css", ".xml", ".toml"}
SECRET_MAX_BYTES = 1_000_000


def classify_path(rel, size=0):
    lvl, why = None, ""
    for rx, level, reason in DANGER_RULES:
        if rx.search(rel):
            if level == "danger":
                return "danger", reason
            if lvl is None:
                lvl, why = "warn", reason
    if size >= LARGE_BLOCK_MB * 1024 * 1024:
        return "danger", "Файл больше " + str(LARGE_BLOCK_MB) + " МБ"
    if size >= LARGE_WARN_MB * 1024 * 1024 and lvl is None:
        return "warn", "Файл больше " + str(LARGE_WARN_MB) + " МБ"
    return (lvl or "ok"), why


def scan_secrets(folder, files, log):
    hits = []
    for rel in files:
        ext = os.path.splitext(rel)[1].lower()
        base = os.path.basename(rel)
        if ext not in SECRET_EXT and base != ".env":
            continue
        p = os.path.join(folder, rel)
        try:
            if os.path.getsize(p) > SECRET_MAX_BYTES:
                continue
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                for ln, line in enumerate(f, 1):
                    if SECRET_RE.search(line):
                        hits.append((rel, ln, line.strip()[:140]))
        except OSError:
            continue
    for rel, ln, snip in hits:
        log("[SECRET] " + rel + ":" + str(ln) + "  " + snip)
    return hits
