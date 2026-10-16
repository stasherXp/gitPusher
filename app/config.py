# -*- coding: utf-8 -*-
# Общие пути и константы GitPusher.
import os

APP_DIR = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(APP_DIR)
DB = os.path.join(BASE, "gitpusher.db")
BACKUP_ROOT = os.path.join(BASE, "backups")
POLL_MS = 120
