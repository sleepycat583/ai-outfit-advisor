import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime


class UserService:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or "./data/users.db"
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=20)
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    created_at TEXT DEFAULT ''
                )
            """)
            try:
                conn.execute("ALTER TABLE users ADD COLUMN profile TEXT DEFAULT '{}'")
            except sqlite3.OperationalError:
                pass  # Column already exists from previous migration
            conn.commit()

    @staticmethod
    def _hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
        if salt is None:
            salt = os.urandom(32).hex()
        hash_bytes = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000
        )
        return hash_bytes.hex(), salt

    def register(self, username: str, password: str) -> tuple[bool, str]:
        username = username.strip()
        if not username or not password:
            return False, "用户名和密码不能为空"
        if len(username) < 2:
            return False, "用户名至少需要2个字符"
        if len(password) < 4:
            return False, "密码至少需要4个字符"

        password_hash, salt = self._hash_password(password)
        user_id = uuid.uuid4().hex

        with self._get_conn() as conn:
            try:
                conn.execute(
                    "INSERT INTO users (id, username, password_hash, salt, created_at) VALUES (?, ?, ?, ?, ?)",
                    (user_id, username, password_hash, salt, datetime.now().isoformat(timespec="seconds")),
                )
                conn.commit()
                return True, user_id
            except sqlite3.IntegrityError:
                return False, "用户名已存在，请换一个"

    def login(self, username: str, password: str) -> tuple[bool, str]:
        username = username.strip()
        if not username or not password:
            return False, "请输入用户名和密码"

        with self._get_conn() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()

            if row is None:
                return False, "用户名不存在"

            user = dict(row)
            password_hash, _ = self._hash_password(password, user["salt"])

            if password_hash != user["password_hash"]:
                return False, "密码错误"

            return True, user["id"]

    def save_profile(self, user_id: str, profile: dict) -> bool:
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE users SET profile = ? WHERE id = ?",
                (json.dumps(profile, ensure_ascii=False), user_id),
            )
            conn.commit()
            return True

    def get_profile(self, user_id: str) -> dict:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT profile FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            if row and row[0]:
                return json.loads(row[0])
            return {}

    def get_user(self, user_id: str) -> dict | None:
        with self._get_conn() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT id, username, created_at FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            return dict(row) if row else None
