"""Batch 6 §6.8 — image caption generation tests (B6-01 / #7).

VisionEngine calls are faked; persistence is exercised against a real
SQLite DB. Covers: valid image, unsupported type, missing file, model
unavailable, empty caption, persistence, regeneration and rename/move
identity (caption keyed by SHA-256).
"""

import os
import sys
from contextlib import contextmanager

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


@contextmanager
def _db_session_factory(tmp_path, name="test_b6_caption.db"):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from database.models import Base
    from database.migrations import run_migrations

    engine = create_engine(f"sqlite:///{tmp_path / name}", echo=False)
    Base.metadata.create_all(engine)
    run_migrations(engine)
    Session = sessionmaker(bind=engine)

    def session_ctx():
        return Session()

    yield session_ctx
    engine.dispose()


class _FakeVision:
    """Deterministic VisionEngine stand-in."""

    def __init__(self, caption="A test image caption.", available=True, model="fake-vision"):
        self._caption = caption
        self._available = available
        self._model = model
        self.calls = 0

    def is_available(self):
        return self._available

    def caption_image(self, image_path):
        self.calls += 1
        if self._caption is None:
            return None
        from vision.vision_engine import VisionResult
        return VisionResult(caption=self._caption, objects=[], confidence=0.7)


def _png_file(path):
    """Write a real, decodable PNG (QImage will reject fake headers)."""
    from PySide6.QtGui import QImage

    img = QImage(4, 4, QImage.Format_RGB32)
    img.fill(0xFF3366CC)
    img.save(str(path), "PNG")
    return str(path)


class TestCaptionService:
    def test_generate_and_persist(self, tmp_path):
        from services.caption_service import CaptionService

        with _db_session_factory(tmp_path) as sf:
            vision = _FakeVision(caption="A sunset over the ocean.")
            svc = CaptionService(session_factory=sf, vision_engine=vision)
            img = _png_file(tmp_path / "photo.png")
            caption = svc.generate_caption(img)
            assert caption == "A sunset over the ocean."
            assert svc.get_caption(img) == caption
            assert vision.calls == 1

    def test_regeneration_replaces(self, tmp_path):
        from services.caption_service import CaptionService

        with _db_session_factory(tmp_path) as sf:
            img = _png_file(tmp_path / "photo.png")
            svc1 = CaptionService(session_factory=sf, vision_engine=_FakeVision(caption="first"))
            assert svc1.generate_caption(img) == "first"
            svc2 = CaptionService(session_factory=sf, vision_engine=_FakeVision(caption="second"))
            assert svc2.generate_caption(img) == "second"
            assert svc2.get_caption(img) == "second"

    def test_rename_preserves_caption(self, tmp_path):
        from services.caption_service import CaptionService

        with _db_session_factory(tmp_path) as sf:
            img = tmp_path / "a.png"
            _png_file(img)
            svc = CaptionService(session_factory=sf, vision_engine=_FakeVision(caption="kept"))
            svc.generate_caption(str(img))
            renamed = tmp_path / "b.png"
            os.rename(img, renamed)
            # Same content → same hash → caption still associated.
            assert svc.get_caption(str(renamed)) == "kept"

    def test_content_change_loses_caption(self, tmp_path):
        from services.caption_service import CaptionService

        with _db_session_factory(tmp_path) as sf:
            img = tmp_path / "a.png"
            _png_file(img)
            svc = CaptionService(session_factory=sf, vision_engine=_FakeVision(caption="old"))
            svc.generate_caption(str(img))
            img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x99" * 64)  # different content
            assert svc.get_caption(str(img)) is None

    def test_unsupported_type_raises(self, tmp_path):
        from services.caption_service import CaptionError, CaptionService

        with _db_session_factory(tmp_path) as sf:
            svc = CaptionService(session_factory=sf, vision_engine=_FakeVision())
            f = tmp_path / "notes.txt"
            f.write_text("hello")
            with pytest.raises(CaptionError):
                svc.generate_caption(str(f))

    def test_missing_file_raises(self, tmp_path):
        from services.caption_service import CaptionError, CaptionService

        with _db_session_factory(tmp_path) as sf:
            svc = CaptionService(session_factory=sf, vision_engine=_FakeVision())
            with pytest.raises(CaptionError):
                svc.generate_caption(str(tmp_path / "nope.png"))

    def test_model_unavailable(self, tmp_path):
        from services.caption_service import CaptionError, CaptionService

        with _db_session_factory(tmp_path) as sf:
            svc = CaptionService(
                session_factory=sf, vision_engine=_FakeVision(available=False)
            )
            img = _png_file(tmp_path / "photo.png")
            with pytest.raises(CaptionError):
                svc.generate_caption(img)

    def test_empty_caption_response(self, tmp_path):
        from services.caption_service import CaptionError, CaptionService

        with _db_session_factory(tmp_path) as sf:
            svc = CaptionService(
                session_factory=sf, vision_engine=_FakeVision(caption=None)
            )
            img = _png_file(tmp_path / "photo.png")
            with pytest.raises(CaptionError):
                svc.generate_caption(img)

    def test_is_supported(self, tmp_path):
        from services.caption_service import CaptionService

        svc = CaptionService(session_factory=lambda: None)
        assert svc.is_supported("/x/y.png")
        assert svc.is_supported("/x/y.JPG")
        assert not svc.is_supported("/x/y.pdf")
        assert not svc.is_supported("/x/y.mp3")


class TestCaptionDialog:
    def test_dialog_renders(self, qapp, qtbot, tmp_path):
        from ui.dialogs.caption_dialog import CaptionDialog

        img = tmp_path / "photo.png"
        _png_file(img)
        dlg = CaptionDialog(str(img))
        qtbot.addWidget(dlg)
        dlg.set_caption("A fake caption", model="fake")
        assert "A fake caption" in dlg.caption_label.text()
        dlg.set_error("model unavailable")
        assert "Error" in dlg.status_label.text()
        dlg.close()

    def test_dialog_error_state(self, qapp, qtbot, tmp_path):
        from ui.dialogs.caption_dialog import CaptionDialog

        img = tmp_path / "photo.png"
        _png_file(img)
        dlg = CaptionDialog(str(img))
        qtbot.addWidget(dlg)
        dlg.set_error("Ollama unavailable")
        assert "Ollama unavailable" in dlg.status_label.text()
        assert dlg.regenerate_btn.isEnabled()
        dlg.close()
