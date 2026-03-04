"""Dict and object utilities: recursive mutation, persistent storage, and attribute traversal."""

import json
from pathlib import Path


def set_key_to_value(obj: dict, target_key: str, new_value) -> None:
    """Recursively set every occurrence of *target_key* in a nested dict to *new_value*."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == target_key:
                obj[key] = new_value
            else:
                set_key_to_value(value, target_key, new_value)
    elif isinstance(obj, list):
        for item in obj:
            set_key_to_value(item, target_key, new_value)


def _get_method(obj, method_path: str):
    """Traverse dotted *method_path* on *obj* and return the final attribute."""
    for part in method_path.split("."):
        obj = getattr(obj, part)
    return obj


class PersistentDict:
    """A dict-like object that automatically persists its contents to a JSON file."""

    def __init__(self, file_path):
        self.file_path = Path(file_path)
        self._data = self._load_or_initialize()

    def _load_or_initialize(self):
        if self.file_path.exists():
            with self.file_path.open("r", encoding="utf-8") as f:
                return json.load(f)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._save({})
        return {}

    def _save(self, data):
        with self.file_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        self._data[key] = value
        self._save(self._data)

    def __delitem__(self, key):
        del self._data[key]
        self._save(self._data)

    def __contains__(self, key):
        return key in self._data

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)

    def __repr__(self):
        return repr(self._data)

    def keys(self):
        return self._data.keys()

    def values(self):
        return self._data.values()

    def items(self):
        return self._data.items()

    def get(self, key, default=None):
        return self._data.get(key, default)

    def update(self, *args, **kwargs):
        self._data.update(*args, **kwargs)
        self._save(self._data)

    def clear(self):
        self._data.clear()
        self._save(self._data)
