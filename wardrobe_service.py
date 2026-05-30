import base64
import io
import json
import os
import re
import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from PIL import Image

import config_data as config
import dashscope
from prompts import VLM_ANALYZE_PROMPT
from supabase_config import WARDROBE_BUCKET, get_supabase_client

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


def _item_to_text(item: dict) -> str:
    item_id = item.get("id", "")
    category = item.get("category", "")
    sub_category = item.get("sub_category", "")
    color = item.get("color", "")
    material = item.get("material", "")
    season = _season_to_str(item.get("season", []))
    return f"- id:{item_id} 类别:{category}/{sub_category} 颜色:{color} 材质:{material} 适季:{season}"


class WardrobeService:
    """衣橱服务（Supabase PostgreSQL + Storage 持久化）

    数据存储在 Supabase wardrobe_items 表，图片存储在 Supabase Storage
    wardrobe-images bucket。
    """

    def __init__(
        self,
        user_id: str,
        db_path: str | None = None,
        vector_wardrobe: Optional["VectorWardrobeService"] = None,
    ) -> None:
        # db_path 参数保留用于向后兼容
        _ = db_path
        self.user_id = user_id
        self.supabase = get_supabase_client()
        self.vector_wardrobe = vector_wardrobe

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _storage_path(self, item_id: str) -> str:
        """Supabase Storage 中的图片路径。"""
        return f"{self.user_id}/{item_id}.jpg"

    def _get_public_url(self, storage_path: str) -> str:
        """获取 Supabase Storage 图片的公开 URL。"""
        return (
            self.supabase.storage.from_(WARDROBE_BUCKET)
            .get_public_url(storage_path)
        )

    def _row_to_dict(self, row: dict) -> dict:
        """将 Supabase 返回的行数据转为业务层 dict。"""
        item = dict(row)
        item["season"] = _season_to_list(item.get("season", ""))
        # 将 storage path 转换为公开 URL
        if item.get("image_path"):
            item["image_path"] = self._get_public_url(item["image_path"])
        return item

    def _upload_image(self, item_id: str, image_bytes: bytes) -> str:
        """上传图片到 Supabase Storage，返回 storage path。"""
        storage_path = self._storage_path(item_id)
        self.supabase.storage.from_(WARDROBE_BUCKET).upload(
            storage_path,
            image_bytes,
            {"content-type": "image/jpeg"},
        )
        return storage_path

    def _delete_image(self, item_id: str) -> None:
        """从 Supabase Storage 中删除图片。"""
        storage_path = self._storage_path(item_id)
        try:
            self.supabase.storage.from_(WARDROBE_BUCKET).remove([storage_path])
        except Exception:
            pass  # 图片可能不存在，忽略

    # ------------------------------------------------------------------
    # VLM 图像分析（纯计算，不涉及存储）
    # ------------------------------------------------------------------

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
            print("[WARN] VLM 返回内容无法解析为 JSON，已使用兜底默认值。")
            return fallback

        if isinstance(parsed, dict):
            parsed = [parsed]
        if not isinstance(parsed, list):
            print("[WARN] VLM 返回内容不是预期的 JSON 结构，已使用兜底默认值。")
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
            print("[WARN] VLM 返回内容无法识别出有效单品，已使用兜底默认值。")
            return fallback

        return normalized

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def get_all_items(self) -> list[dict]:
        result = (
            self.supabase.table("wardrobe_items")
            .select("*")
            .eq("user_id", self.user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return [self._row_to_dict(r) for r in (result.data or [])]

    def add_item(self, item_data: dict, image_bytes: bytes = None) -> dict:
        new_id = str(uuid.uuid4())
        storage_path = ""

        if image_bytes:
            storage_path = self._upload_image(new_id, image_bytes)

        created_at = datetime.now().isoformat(timespec="seconds")
        season_str = _season_to_str(item_data.get("season", []))

        self.supabase.table("wardrobe_items").insert(
            {
                "id": new_id,
                "user_id": self.user_id,
                "category": item_data.get("category", ""),
                "sub_category": item_data.get("sub_category", ""),
                "color": item_data.get("color", ""),
                "material": item_data.get("material", ""),
                "season": season_str,
                "image_path": storage_path,
                "created_at": created_at,
            }
        ).execute()

        new_item = {
            "id": new_id,
            "category": item_data.get("category", ""),
            "sub_category": item_data.get("sub_category", ""),
            "color": item_data.get("color", ""),
            "material": item_data.get("material", ""),
            "season": item_data.get("season", []),
            "image_path": self._get_public_url(storage_path) if storage_path else "",
            "created_at": created_at,
        }

        if self.vector_wardrobe:
            self.vector_wardrobe.add_items([(new_id, _item_to_text(new_item))])

        return new_item

    def update_item(self, item_id: str, new_data: dict, image_bytes: bytes = None) -> dict | None:
        """更新指定 ID 的单品数据。image_bytes 不为 None 时替换图片。"""
        # 检查是否存在
        existing = (
            self.supabase.table("wardrobe_items")
            .select("*")
            .eq("id", item_id)
            .eq("user_id", self.user_id)
            .execute()
        )
        if not existing.data:
            return None

        updates = {}
        for field in ["category", "sub_category", "color", "material"]:
            if field in new_data:
                updates[field] = new_data[field]
        if "season" in new_data:
            updates["season"] = _season_to_str(new_data["season"])

        # 处理图片更新
        if image_bytes:
            storage_path = self._upload_image(item_id, image_bytes)
            updates["image_path"] = storage_path

        if updates:
            self.supabase.table("wardrobe_items").update(updates).eq("id", item_id).execute()

        # 获取更新后的数据
        result = (
            self.supabase.table("wardrobe_items")
            .select("*")
            .eq("id", item_id)
            .execute()
        )
        if not result.data:
            return None
        updated_item = self._row_to_dict(result.data[0])

        if self.vector_wardrobe:
            self.vector_wardrobe.update_items([(item_id, _item_to_text(updated_item))])

        return updated_item

    def delete_item(self, item_id: str) -> None:
        self._delete_image(item_id)
        self.supabase.table("wardrobe_items").delete().eq("id", item_id).execute()

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

        if mode == "replace":
            # 删除当前用户所有记录
            self.supabase.table("wardrobe_items").delete().eq("user_id", self.user_id).execute()
            # 批量插入
            rows = [
                {
                    "id": item["id"],
                    "user_id": self.user_id,
                    "category": item["category"],
                    "sub_category": item["sub_category"],
                    "color": item["color"],
                    "material": item["material"],
                    "season": _season_to_str(item["season"]),
                    "image_path": "",
                    "created_at": item["created_at"],
                }
                for item in new_items
            ]
            self.supabase.table("wardrobe_items").insert(rows).execute()
            count = len(new_items)
        else:
            # 获取已存在的 id
            existing_result = (
                self.supabase.table("wardrobe_items")
                .select("id")
                .eq("user_id", self.user_id)
                .execute()
            )
            existing_ids = {r["id"] for r in (existing_result.data or [])}
            truly_new = [item for item in new_items if item["id"] not in existing_ids]
            if not truly_new:
                return 0
            rows = [
                {
                    "id": item["id"],
                    "user_id": self.user_id,
                    "category": item["category"],
                    "sub_category": item["sub_category"],
                    "color": item["color"],
                    "material": item["material"],
                    "season": _season_to_str(item["season"]),
                    "image_path": "",
                    "created_at": item["created_at"],
                }
                for item in truly_new
            ]
            self.supabase.table("wardrobe_items").insert(rows).execute()
            count = len(truly_new)

        if self.vector_wardrobe and count > 0:
            sync_items = [(item["id"], _item_to_text(item)) for item in new_items]
            self.vector_wardrobe.update_items(sync_items)

        return count
