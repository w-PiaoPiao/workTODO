"""测试便签模型与存储"""

import json

import pytest

from app.models.note import Note, NoteStore
from app.models.todo_item import StoreError


@pytest.fixture
def note_store(tmp_path, monkeypatch):
    """使用临时目录的 NoteStore"""
    monkeypatch.setattr("app.config.AppConfig.DATA_DIR", tmp_path)
    return NoteStore()


class TestNote:
    def test_create(self):
        note = Note(content="第一条便签")
        assert note.content == "第一条便签"
        assert note.id is not None
        assert note.color == "yellow"

    def test_title_first_line(self):
        note = Note(content="标题行\n第二行内容")
        assert note.title == "标题行"

    def test_round_trip(self):
        note = Note(content="内容", color="blue")
        d = note.to_dict()
        assert d["color"] == "blue"
        restored = Note.from_dict(d)
        assert restored.id == note.id
        assert restored.content == "内容"
        assert restored.color == "blue"

    def test_from_dict_missing_fields(self):
        note = Note.from_dict({"content": "只有内容"})
        assert note.id is not None
        assert note.color == "yellow"


class TestNoteStore:
    def test_empty(self, note_store):
        assert note_store.load_notes() == []

    def test_add_and_load(self, note_store):
        note = Note(content="便签A")
        note_store.add_note(note)
        notes = note_store.load_notes()
        assert len(notes) == 1
        assert notes[0].content == "便签A"

    def test_update(self, note_store):
        note = Note(content="旧内容")
        note_store.add_note(note)
        note.content = "新内容"
        note.color = "pink"
        note_store.update_note(note)
        notes = note_store.load_notes()
        assert notes[0].content == "新内容"
        assert notes[0].color == "pink"

    def test_update_nonexistent(self, note_store):
        with pytest.raises(StoreError):
            note_store.update_note(Note(content="不存在"))

    def test_delete(self, note_store):
        note = Note(content="待删除")
        note_store.add_note(note)
        assert note_store.delete_note(note.id) is True
        assert note_store.load_notes() == []
        assert note_store.delete_note(note.id) is False

    def test_persistence(self, note_store, tmp_path):
        note_store.add_note(Note(content="持久化"))
        new_store = NoteStore()
        notes = new_store.load_notes()
        assert len(notes) == 1
        assert notes[0].content == "持久化"

    def test_corrupted_file(self, note_store, tmp_path):
        notes_file = tmp_path / "notes.json"
        notes_file.write_text("坏数据", encoding="utf-8")
        assert note_store.load_notes() == []
        assert (tmp_path / "notes.json.bak").exists()

    def test_from_dict_unknown_color_fallback(self):
        note = Note.from_dict({"content": "未知颜色", "color": "red"})
        assert note.color == "yellow"

    def test_load_unknown_color_safe(self, note_store, tmp_path):
        notes_file = tmp_path / "notes.json"
        notes_file.write_text(json.dumps([
            {"id": "n1", "content": "正常", "color": "blue"},
            {"id": "n2", "content": "未知色", "color": "red"},
        ], ensure_ascii=False), encoding="utf-8")
        notes = note_store.load_notes()
        assert len(notes) == 2
        assert notes[0].color == "blue"
        assert notes[1].color == "yellow"
