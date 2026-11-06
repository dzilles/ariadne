from __future__ import annotations

import copy
import dataclasses
import json
import math
import os
from pathlib import Path
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from .errors import Error

MAX_INT = 2**63 - 1


def new_id(prefix: str = "") -> str:
    return f"{prefix}-{uuid4().hex}" if prefix else uuid4().hex


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def to_data(value):
    if isinstance(value, Enum):
        return value.value
    if dataclasses.is_dataclass(value):
        return {f.name: to_data(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Error):
        return value.to_dict()
    if isinstance(value, dict):
        return {k: to_data(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_data(v) for v in value]
    return value


def dumps(value, *, pretty=False) -> str:
    return json.dumps(to_data(value), ensure_ascii=False, allow_nan=False, sort_keys=True,
                      indent=2 if pretty else None, separators=None if pretty else (",", ":"))


def loads(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON number")))
    except (ValueError, TypeError, UnicodeError) as exc:
        raise Error.invalid(f"Invalid JSON: {exc}") from exc


class JsonModel:
    def to_dict(self):
        return to_data(self)

    @classmethod
    def from_dict(cls, value):
        fields = dataclasses.fields(cls)
        required = [f.name for f in fields if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING]
        data = object_fields(value, required, [f.name for f in fields if f.name not in required])
        try:
            return cls(**copy.deepcopy(data))
        except (TypeError, ValueError) as exc:
            raise Error.invalid(f"Invalid {cls.__name__}: {exc}") from exc


def object_fields(value, required=(), optional=()) -> dict:
    if not isinstance(value, dict) or not all(isinstance(k, str) for k in value):
        raise Error.invalid("Expected an object with string keys")
    missing, extra = set(required) - value.keys(), value.keys() - set(required) - set(optional)
    if missing or extra:
        raise Error.invalid(f"Missing fields: {sorted(missing)}; unknown fields: {sorted(extra)}")
    return value


def text(value, name="text", *, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise Error.invalid(f"{name} must be a {'string' if empty else 'nonempty string'}")
    return value


def integer(value, name="integer", minimum=0, maximum=MAX_INT):
    if type(value) is not int or not minimum <= value <= maximum:
        raise Error.invalid(f"{name} must be an integer between {minimum} and {maximum}")
    return value


def strings(value, name="values", *, unique=False):
    if not isinstance(value, list):
        raise Error.invalid(f"{name} must be a list")
    for item in value:
        text(item, name)
    if unique and len(set(value)) != len(value):
        raise Error.invalid(f"Duplicate {name}")
    return value


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
        raise Error.invalid("IDs must use 1–128 letters, digits, '_' or '-', starting with a letter/digit")
    return value


def optional_text(value, name="text"):
    return None if value is None else text(value, name, empty=True)


def enum_value(value, allowed, name="value"):
    if isinstance(allowed, type) and issubclass(allowed, Enum):
        allowed = tuple(item.value for item in allowed)
    if not isinstance(value, str) or value not in allowed:
        raise Error.invalid(f"Invalid {name}: {value!r}")
    return value


def finite(value, name="number"):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise Error.invalid(f"{name} must be a finite number")
    return value


def connect(path):
    try:
        db = sqlite3.connect(str(path), isolation_level=None, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        return db
    except sqlite3.Error as exc:
        raise Error("DATABASE_ERROR", str(exc)) from exc


@contextmanager
def transaction(db):
    try:
        db.execute("BEGIN IMMEDIATE")
        yield db
        db.commit()
    except BaseException as exc:
        db.rollback()
        if isinstance(exc, sqlite3.Error):
            raise Error("DATABASE_ERROR", str(exc)) from exc
        raise


class FileLock:
    """OS-owned lock, released explicitly rather than by deleting its file."""

    def __init__(self, path, code="BUSY"):
        self.file = open(path, "a+b")
        try:
            if os.name == "posix":
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                import msvcrt
                self.file.seek(0)
                if not self.file.read(1):
                    self.file.write(b"\0")
                    self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            self.file.close()
            raise Error(code, "Another process is using this resource; retry later") from exc

    def close(self):
        if self.file.closed:
            return
        try:
            if os.name == "posix":
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_UN)
            else:
                import msvcrt
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self.file.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def sync_directory(path):
    if os.name == "posix":
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def atomic_write(path, data):
    path = Path(path)
    temporary = path.parent / f".config-{new_id()}.tmp"
    try:
        with open(temporary, "xb") as stream:
            stream.write(data.encode("utf-8") if isinstance(data, str) else data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)
