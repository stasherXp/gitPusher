# -*- coding: utf-8 -*-
# SQLite: config и history.
import sqlite3, time
from config import DB


def db_connect():
    con = sqlite3.connect(DB, timeout=10)
    con.execute("""CREATE TABLE IF NOT EXISTS config(
        key TEXT PRIMARY KEY, value TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS history(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL, repo TEXT, step TEXT, cmd TEXT, output TEXT, ok INT)""")
    con.commit()
    return con


def cfg_get(con, key, default=""):
    r = con.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
    return r[0] if r else default


def cfg_set(con, key, value):
    con.execute("INSERT OR REPLACE INTO config(key,value) VALUES(?,?)", (key, value))
    con.commit()


def hist_add(repo, step, cmd, ok):
    try:
        con = sqlite3.connect(DB, timeout=10)
        con.execute(
            "INSERT INTO history(ts,repo,step,cmd,output,ok) VALUES(?,?,?,?,?,?)",
            (time.time(), repo or "", step, cmd, "", 1 if ok else 0))
        con.commit()
        con.close()
    except Exception:
        pass
