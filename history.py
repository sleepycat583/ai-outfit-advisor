import contextlib
import json
import os
import time
from typing import Sequence

import config_data as config

if os.name == "nt":
    import msvcrt
else:
    import fcntl

from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import BaseMessage, message_to_dict, messages_from_dict

def get_history(session_id):
    return FileChatMessageHistory(session_id, config.CHAT_HISTORY_DIR)


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


class FileChatMessageHistory(BaseChatMessageHistory):
    def __init__(self, session_id: str, storage_path: str):
        self.session_id = session_id
        self.storage_path = storage_path

        self.file_path = os.path.join(self.storage_path, self.session_id)
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)

    def _read_messages_data_unlocked(self) -> list[dict]:
        if not os.path.exists(self.file_path):
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

    def _append_messages_unlocked(self, new_messages: list[dict]) -> None:
        if not new_messages:
            return
        messages_data = self._read_messages_data_unlocked()
        messages_data.extend(new_messages)
        self._atomic_write(messages_data)

    def add_messages(self, messages: Sequence[BaseMessage]) -> None:
        lock_path = f"{self.file_path}.lock"
        with _file_lock(lock_path):
            new_messages = [message_to_dict(message) for message in messages]
            self._append_messages_unlocked(new_messages)

    @property
    def messages(self) -> list[BaseMessage]:
        lock_path = f"{self.file_path}.lock"
        with _file_lock(lock_path):
            try:
                messages_data = self._read_messages_data_unlocked()
                return messages_from_dict(messages_data)
            except FileNotFoundError:
                return []

    def clear(self) -> None:
        lock_path = f"{self.file_path}.lock"
        with _file_lock(lock_path):
            self._atomic_write([])
