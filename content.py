"""Тексты, кнопки и материалы бота хранятся в content.json.

Заказчик правит этот файл сам (без программиста), а админ применяет
изменения командой /reload — перезапускать бота не нужно.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Material:
    id: str
    button: str
    type: str  # "document" | "video" | "photo" | "link"
    caption: str = ""
    file: str = ""  # путь к файлу (для document / video / photo)
    url: str = ""  # ссылка (для link)


@dataclass
class Link:
    button: str
    url: str


@dataclass
class Content:
    texts: dict[str, str]
    materials: list[Material]
    links: list[Link] = field(default_factory=list)
    welcome_video_note: str = ""
    base_dir: Path = Path(".")

    def text(self, key: str, **kwargs) -> str:
        template = self.texts.get(key, f"[нет текста «{key}» в content.json]")
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError):
            return template

    def material(self, material_id: str) -> Material | None:
        return next((m for m in self.materials if m.id == material_id), None)

    def file_path(self, relative: str) -> Path:
        return (self.base_dir / relative).resolve()


REQUIRED_TEXTS = ("welcome", "choose", "need_subscribe", "not_subscribed", "after_material", "links")
ALLOWED_TYPES = {"document", "video", "photo", "link"}


def load_content(path: Path) -> Content:
    """Читает и проверяет content.json. При ошибке бросает ValueError с понятным текстом."""
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"Файл {path} не найден")
    except json.JSONDecodeError as e:
        raise ValueError(f"Ошибка в {path.name}, строка {e.lineno}: {e.msg}")

    texts = raw.get("texts", {})
    missing = [k for k in REQUIRED_TEXTS if k not in texts]
    if missing:
        raise ValueError("В content.json не хватает текстов: " + ", ".join(missing))

    materials: list[Material] = []
    seen: set[str] = set()
    for i, m in enumerate(raw.get("materials", []), start=1):
        try:
            mat = Material(**m)
        except TypeError as e:
            raise ValueError(f"Материал №{i}: {e}")
        if mat.type not in ALLOWED_TYPES:
            raise ValueError(f"Материал «{mat.id}»: тип должен быть одним из {sorted(ALLOWED_TYPES)}")
        if mat.type == "link" and not mat.url:
            raise ValueError(f"Материал «{mat.id}»: для типа link нужен url")
        if mat.type != "link" and not mat.file:
            raise ValueError(f"Материал «{mat.id}»: укажите file")
        if mat.id in seen:
            raise ValueError(f"Материал «{mat.id}» встречается дважды")
        seen.add(mat.id)
        materials.append(mat)
    if not materials:
        raise ValueError("В content.json нет ни одного материала")

    links = [Link(**l) for l in raw.get("links", [])]
    return Content(
        texts=texts,
        materials=materials,
        links=links,
        welcome_video_note=raw.get("welcome_video_note", ""),
        base_dir=path.parent,
    )


class ContentStore:
    """Хранит текущий контент и умеет перечитать его на лету."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.current = load_content(self.path)

    def reload(self) -> Content:
        self.current = load_content(self.path)  # при ошибке старый контент остаётся
        return self.current
