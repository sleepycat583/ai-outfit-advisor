import base64
import contextlib
import io
import json
import os
import re
import time
import uuid
from datetime import datetime

from PIL import Image

import config_data as config
import dashscope

if os.name == "nt":
    import msvcrt
else:
    import fcntl


@contextlib.contextmanager
def _file_lock(lock_path: str, retry_delay: float = 0.05):
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        while True:
            try:
                if os.name == "nt":
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                break
            except OSError:
                time.sleep(retry_delay)
        try:
            yield
        finally:
            if os.name == "nt":
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


class WardrobeService:
    def __init__(self, file_path: str | None = None) -> None:
        self.file_path = file_path or config.WARDROBE_FILE_PATH
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        self.image_dir = config.WARDROBE_IMAGE_DIR
        os.makedirs(self.image_dir, exist_ok=True)

    def _read_items_unlocked(self) -> list[dict]:
        if not os.path.exists(self.file_path):
            return []
        if os.path.getsize(self.file_path) == 0:
            return []
        with open(self.file_path, "r", encoding="utf-8") as f:
            items = json.load(f)
        # 兜底去重：按 id 去重，保留首次出现的条目
        seen = set()
        deduped = []
        for item in items:
            iid = item.get("id")
            if iid and iid in seen:
                continue
            if iid:
                seen.add(iid)
            deduped.append(item)
        return deduped

    def _atomic_write(self, data: list[dict]) -> None:
        temp_path = f"{self.file_path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, self.file_path)

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
        system_prompt = (
            "你是一位专业时尚分析师，只能输出 JSON。"
            "请识别图片中所有可见的服饰单品（例如上衣、裤子、鞋子等），并以 JSON 数组的形式返回。"
            "每个单品必须包含字段：category、sub_category、color、material、season。"
            "category 必须是以下之一：['外套', '内搭', '下装', '鞋履', '配饰']。"
            "season 为数组，元素只能是 春/夏/秋/冬。"
            '示例：[{"category": "内搭", "sub_category": "衬衫", "color": "蓝色", "material": "棉", "season": ["春", "秋"]}, '
            '{"category": "下装", "sub_category": "休闲裤", "color": "黑色", "material": "聚酯纤维", "season": ["春", "夏", "秋"]}]'
        )
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

    def get_all_items(self) -> list:
        lock_path = f"{self.file_path}.lock"
        with _file_lock(lock_path):
            return self._read_items_unlocked()

    def add_item(self, item_data: dict, image_bytes: bytes = None) -> dict:
        lock_path = f"{self.file_path}.lock"
        with _file_lock(lock_path):
            items = self._read_items_unlocked()
            new_item = dict(item_data)
            new_item["id"] = str(uuid.uuid4())
            if image_bytes:
                image_path = os.path.join(self.image_dir, f"{new_item['id']}.jpg")
                with open(image_path, "wb") as f:
                    f.write(image_bytes)
                new_item["image_path"] = image_path
            new_item["created_at"] = datetime.now().isoformat(timespec="seconds")
            items.append(new_item)
            self._atomic_write(items)
            return new_item

    def update_item(self, item_id: str, new_data: dict) -> dict | None:
        """更新指定 ID 的单品数据，返回更新后的 dict 或 None。"""
        lock_path = f"{self.file_path}.lock"
        with _file_lock(lock_path):
            items = self._read_items_unlocked()
            for item in items:
                if item.get("id") == item_id:
                    item.update(new_data)
                    self._atomic_write(items)
                    return item
        return None

    def delete_item(self, item_id: str) -> None:
        lock_path = f"{self.file_path}.lock"
        with _file_lock(lock_path):
            items = self._read_items_unlocked()
            filtered_items = [item for item in items if item.get("id") != item_id]
            self._atomic_write(filtered_items)

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
        for row in reader:
            cat = (row.get("category") or "").strip()
            if not cat:
                continue
            season_raw = (row.get("season") or "").strip()
            season_list = [s.strip() for s in season_raw.split("|") if s.strip()] if season_raw else []
            new_items.append({
                "id": (row.get("id") or str(uuid.uuid4())).strip(),
                "category": cat,
                "sub_category": (row.get("sub_category") or "").strip(),
                "color": (row.get("color") or "").strip(),
                "material": (row.get("material") or "").strip(),
                "season": season_list,
                "created_at": (row.get("created_at") or datetime.now().isoformat(timespec="seconds")).strip(),
            })

        if not new_items:
            return 0

        # CSV 内部去重（同 ID 只保留第一条）
        seen_ids = set()
        deduped = []
        for item in new_items:
            iid = item["id"]
            if iid in seen_ids:
                continue
            seen_ids.add(iid)
            deduped.append(item)
        new_items = deduped

        lock_path = f"{self.file_path}.lock"
        with _file_lock(lock_path):
            if mode == "replace":
                self._atomic_write(new_items)
                return len(new_items)
            else:
                items = self._read_items_unlocked()
                existing_ids = {item.get("id") for item in items}
                truly_new = [item for item in new_items if item["id"] not in existing_ids]
                if not truly_new:
                    return 0
                items.extend(truly_new)
                self._atomic_write(items)
                return len(truly_new)
