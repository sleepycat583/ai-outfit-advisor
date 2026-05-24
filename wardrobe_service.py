import base64
import io
import json
import os
import re
import sqlite3
import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from PIL import Image

import config_data as config
import dashscope
from prompts import VLM_ANALYZE_PROMPT

if TYPE_CHECKING:
    from vector_store_service import VectorWardrobeService


def _season_to_str(season) -> str:
    if isinstance(season, list):
        return ",".join(season)
    return str(season) if season else ""


def _season_to_list(season_str: str) -> list[str]:
    if not season_str:
        return []
    return [s.strip() for s in season_str.split(",") if s.strip()]


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["season"] = _season_to_list(d.get("season", ""))
    return d


def _item_to_text(item: dict) -> str:
    item_id = item.get("id", "")
    category = item.get("category", "")
    sub_category = item.get("sub_category", "")
    color = item.get("color", "")
    material = item.get("material", "")
    season = _season_to_str(item.get("season", []))
    return f"- id:{item_id} 类别:{category}/{sub_category} 颜色:{color} 材质:{material} 适季:{season}"


class WardrobeService:
    def __init__(
        self,
        db_path: str | None = None,
        vector_wardrobe: Optional["VectorWardrobeService"] = None,
    ) -> None:
        self.db_path = db_path or "./data/wardrobe.db"
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.image_dir = config.WARDROBE_IMAGE_DIR
        os.makedirs(self.image_dir, exist_ok=True)
        self.vector_wardrobe = vector_wardrobe
        self._init_db()

    # [并发修复] 统一数据库连接入口，开启 WAL 模式 + 20s 超时，解决高并发下 database is locked 崩溃
    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接。
        - timeout=20：写锁等待最长 20 秒，避免瞬时并发写立即报错。
        - PRAGMA journal_mode=WAL：预写式日志，允许多个读操作与一个写操作并发执行。
        """
        conn = sqlite3.connect(self.db_path, timeout=20)
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _init_db(self) -> None:
        # [并发修复] 使用 _get_conn() 替代裸 sqlite3.connect()
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS wardrobe_items (
                    id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    sub_category TEXT DEFAULT '',
                    color TEXT DEFAULT '',
                    material TEXT DEFAULT '',
                    season TEXT DEFAULT '',
                    image_path TEXT DEFAULT '',
                    created_at TEXT DEFAULT ''
                )
            """)
            conn.commit()

    def preprocess_image(self, image_bytes: bytes) -> str:
        image = Image.open(io.BytesIO(image_bytes))
        image = image.convert("RGB")
        image.thumbnail((800, 800))
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=85)
        jpeg_bytes = output.getvalue()
        return base64.b64encode(jpeg_bytes).decode("utf-8")

    def _clean_and_extract_json(self, raw_text: str) -> str:
        match = re.search(r"(\[[\s\S]*\])", raw_text)
        if not match:
            match = re.search(r"(\{[\s\S]*\})", raw_text)
        if match:
            return match.group(1).strip()
        return raw_text.strip()

    def analyze_clothing_image(self, image_bytes: bytes) -> list[dict]:
        image_b64 = self.preprocess_image(image_bytes)
        system_prompt = VLM_ANALYZE_PROMPT
        messages = [
            {"role": "system", "content": [{"text": system_prompt}]},
            {
                "role": "user",
                "content": [
                    {"image": f"data:image/jpeg;base64,{image_b64}"},
                    {"text": "请分析这件衣服并返回 JSON。"},
                ],
            },
        ]
        response = dashscope.MultiModalConversation.call(
            model=config.VISUAL_MODEL_NAME,
            messages=messages,
        )
        try:
            content = response.output["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("VLM 返回结构不符合预期") from exc

        if isinstance(content, list):
            text_parts = [part.get("text", "") for part in content if isinstance(part, dict)]
            content_text = "".join(text_parts).strip()
        else:
            content_text = str(content).strip()

        cleaned_text = self._clean_and_extract_json(content_text)
        fallback = [
            {
                "category": "外套",
                "sub_category": "未识别",
                "color": "未知",
                "material": "未知",
                "season": ["春", "秋"],
            }
        ]
        try:
            parsed = json.loads(cleaned_text)
        except json.JSONDecodeError:
            print("⚠️ VLM 返回内容无法解析为 JSON，已使用兜底默认值。")
            return fallback

        if isinstance(parsed, dict):
            parsed = [parsed]
        if not isinstance(parsed, list):
            print("⚠️ VLM 返回内容不是预期的 JSON 结构，已使用兜底默认值。")
            return fallback

        normalized: list[dict] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            season_value = item.get("season")
            if isinstance(season_value, str):
                item = dict(item)
                item["season"] = [season_value]
            normalized.append(item)

        if not normalized:
            print("⚠️ VLM 返回内容无法识别出有效单品，已使用兜底默认值。")
            return fallback

        return normalized

    def get_all_items(self) -> list[dict]:
        # [并发修复] 使用 _get_conn() 替代裸 sqlite3.connect()
        with self._get_conn() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM wardrobe_items ORDER BY created_at DESC").fetchall()
            return [_row_to_dict(r) for r in rows]

    def add_item(self, item_data: dict, image_bytes: bytes = None) -> dict:
        new_id = str(uuid.uuid4())
        image_path = ""
        if image_bytes:
            image_path = os.path.join(self.image_dir, f"{new_id}.jpg")
            with open(image_path, "wb") as f:
                f.write(image_bytes)
        created_at = datetime.now().isoformat(timespec="seconds")
        season_str = _season_to_str(item_data.get("season", []))

        # [并发修复] 使用 _get_conn() 替代裸 sqlite3.connect()
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO wardrobe_items (id, category, sub_category, color, material, season, image_path, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    new_id,
                    item_data.get("category", ""),
                    item_data.get("sub_category", ""),
                    item_data.get("color", ""),
                    item_data.get("material", ""),
                    season_str,
                    image_path,
                    created_at,
                ),
            )
            conn.commit()

        new_item = {
            "id": new_id,
            "category": item_data.get("category", ""),
            "sub_category": item_data.get("sub_category", ""),
            "color": item_data.get("color", ""),
            "material": item_data.get("material", ""),
            "season": item_data.get("season", []),
            "image_path": image_path,
            "created_at": created_at,
        }

        if self.vector_wardrobe:
            self.vector_wardrobe.add_items([(new_id, _item_to_text(new_item))])

        return new_item

    def update_item(self, item_id: str, new_data: dict) -> dict | None:
        """更新指定 ID 的单品数据，返回更新后的 dict 或 None。"""
        # [并发修复] 使用 _get_conn() 替代裸 sqlite3.connect()
        with self._get_conn() as conn:
            conn.row_factory = sqlite3.Row
            existing = conn.execute(
                "SELECT * FROM wardrobe_items WHERE id = ?", (item_id,)
            ).fetchone()
            if existing is None:
                return None

            updates = {}
            for field in ["category", "sub_category", "color", "material", "image_path"]:
                if field in new_data:
                    updates[field] = new_data[field]
            if "season" in new_data:
                updates["season"] = _season_to_str(new_data["season"])

            if updates:
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                values = list(updates.values()) + [item_id]
                conn.execute(
                    f"UPDATE wardrobe_items SET {set_clause} WHERE id = ?", values
                )
                conn.commit()

            row = conn.execute(
                "SELECT * FROM wardrobe_items WHERE id = ?", (item_id,)
            ).fetchone()
            updated_item = _row_to_dict(row)

        if self.vector_wardrobe:
            self.vector_wardrobe.update_items([(item_id, _item_to_text(updated_item))])

        return updated_item

    def delete_item(self, item_id: str) -> None:
        # [并发修复] 使用 _get_conn() 替代裸 sqlite3.connect()
        with self._get_conn() as conn:
            conn.execute("DELETE FROM wardrobe_items WHERE id = ?", (item_id,))
            conn.commit()

        if self.vector_wardrobe:
            self.vector_wardrobe.delete_items([item_id])

    def export_to_csv(self) -> str:
        """将衣橱数据导出为 CSV 字符串。"""
        import csv as csv_module

        items = self.get_all_items()
        output = io.StringIO()
        fieldnames = ["id", "category", "sub_category", "color", "material", "season", "created_at"]
        writer = csv_module.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for item in items:
            row = {k: item.get(k, "") for k in fieldnames}
            if isinstance(row.get("season"), list):
                row["season"] = "|".join(row["season"])
            writer.writerow(row)
        return output.getvalue()

    def import_from_csv(self, csv_text: str, mode: str = "append") -> int:
        """从 CSV 文本导入单品。mode='append' 追加，'replace' 覆盖。返回导入数量。"""
        import csv as csv_module

        reader = csv_module.DictReader(io.StringIO(csv_text))
        if not reader.fieldnames or "category" not in reader.fieldnames:
            raise ValueError("CSV 缺少必要字段 'category'")

        new_items = []
        seen_ids = set()
        for row in reader:
            cat = (row.get("category") or "").strip()
            if not cat:
                continue
            item_id = (row.get("id") or str(uuid.uuid4())).strip()
            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)
            season_raw = (row.get("season") or "").strip()
            season_list = [s.strip() for s in season_raw.split("|") if s.strip()] if season_raw else []
            new_items.append({
                "id": item_id,
                "category": cat,
                "sub_category": (row.get("sub_category") or "").strip(),
                "color": (row.get("color") or "").strip(),
                "material": (row.get("material") or "").strip(),
                "season": season_list,
                "created_at": (row.get("created_at") or datetime.now().isoformat(timespec="seconds")).strip(),
            })

        if not new_items:
            return 0

        # [并发修复] 使用 _get_conn() 替代裸 sqlite3.connect()
        with self._get_conn() as conn:
            if mode == "replace":
                conn.execute("DELETE FROM wardrobe_items")
                conn.executemany(
                    """INSERT INTO wardrobe_items (id, category, sub_category, color, material, season, image_path, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, '', ?)""",
                    [
                        (
                            item["id"],
                            item["category"],
                            item["sub_category"],
                            item["color"],
                            item["material"],
                            _season_to_str(item["season"]),
                            item["created_at"],
                        )
                        for item in new_items
                    ],
                )
                conn.commit()
                count = len(new_items)
            else:
                existing_ids = {
                    row[0]
                    for row in conn.execute("SELECT id FROM wardrobe_items").fetchall()
                }
                truly_new = [item for item in new_items if item["id"] not in existing_ids]
                if not truly_new:
                    return 0
                conn.executemany(
                    """INSERT INTO wardrobe_items (id, category, sub_category, color, material, season, image_path, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, '', ?)""",
                    [
                        (
                            item["id"],
                            item["category"],
                            item["sub_category"],
                            item["color"],
                            item["material"],
                            _season_to_str(item["season"]),
                            item["created_at"],
                        )
                        for item in truly_new
                    ],
                )
                conn.commit()
                count = len(truly_new)

        if self.vector_wardrobe and count > 0:
            sync_items = [(item["id"], _item_to_text(item)) for item in new_items]
            self.vector_wardrobe.update_items(sync_items)

        return count
