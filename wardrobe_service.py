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

    def _read_items_unlocked(self) -> list[dict]:
        if not os.path.exists(self.file_path):
            return []
        if os.path.getsize(self.file_path) == 0:
            return []
        with open(self.file_path, "r", encoding="utf-8") as f:
            return json.load(f)

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
        match = re.search(r"(\{[\s\S]*\})", raw_text)
        if match:
            return match.group(1).strip()
        return raw_text.strip()

    def analyze_clothing_image(self, image_bytes: bytes) -> dict:
        image_b64 = self.preprocess_image(image_bytes)
        system_prompt = (
            "你是一位专业时尚分析师，只能输出 JSON。"
            "JSON 必须包含字段：category、sub_category、color、material、season。"
            f"category 必须是以下之一：{config.WARDROBE_CATEGORIES}。"
            "season 为数组，元素只能是 春/夏/秋/冬。"
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
        fallback = {
            "category": "外套",
            "sub_category": "未识别单品",
            "color": "未知颜色",
            "material": "未知材质",
            "season": ["春季", "秋季"],
        }
        try:
            parsed = json.loads(cleaned_text)
        except json.JSONDecodeError:
            print("⚠️ VLM 返回内容无法解析为 JSON，已使用兜底默认值。")
            return fallback

        if not isinstance(parsed, dict):
            print("⚠️ VLM 返回内容不是字典结构，已使用兜底默认值。")
            return fallback

        for key, value in fallback.items():
            parsed.setdefault(key, value)
        return parsed

    def get_all_items(self) -> list:
        lock_path = f"{self.file_path}.lock"
        with _file_lock(lock_path):
            return self._read_items_unlocked()

    def add_item(self, item_data: dict) -> dict:
        lock_path = f"{self.file_path}.lock"
        with _file_lock(lock_path):
            items = self._read_items_unlocked()
            new_item = dict(item_data)
            new_item["id"] = str(uuid.uuid4())
            new_item["created_at"] = datetime.now().isoformat(timespec="seconds")
            items.append(new_item)
            self._atomic_write(items)
            return new_item

    def delete_item(self, item_id: str) -> None:
        lock_path = f"{self.file_path}.lock"
        with _file_lock(lock_path):
            items = self._read_items_unlocked()
            filtered_items = [item for item in items if item.get("id") != item_id]
            self._atomic_write(filtered_items)
