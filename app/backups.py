# -*- coding: utf-8 -*-
# Бекапы файлов перед пушем.
import os, json, shutil, time, hashlib
from config import BACKUP_ROOT


def file_hash(p):
    h = hashlib.blake2b(digest_size=16)
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def make_backup(folder, files, log):
    if not files:
        return None
    ts = time.strftime("%Y-%m-%d_%H-%M-%S")
    dst = os.path.join(BACKUP_ROOT, ts)
    os.makedirs(dst, exist_ok=True)
    manifest = {"created": time.time(), "folder": folder, "files": []}
    for rel in files:
        src = os.path.join(folder, rel)
        if not os.path.isfile(src):
            log("[backup] пропуск (нет файла): " + rel)
            continue
        out_path = os.path.join(dst, rel)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        try:
            shutil.copy2(src, out_path)
            st = os.stat(src)
            manifest["files"].append({
                "rel": rel, "size": st.st_size, "mtime": st.st_mtime,
                "blake2b": file_hash(src),
            })
            log("[backup] " + rel + "  (" + str(st.st_size) + " B)")
        except Exception as e:
            log("[backup-ERR] " + rel + ": " + str(e))
    with open(os.path.join(dst, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    log("[backup] сохранено в " + dst)
    return dst
