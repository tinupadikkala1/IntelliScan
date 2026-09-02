"""Unit tests for User-Directed File Organization Service and Workspace Near-Duplicate scanning."""

import os
import tempfile
import pytest

from services.file_organizer_service import FileOrganizerService, OrganizationCandidate
from services.file_similarity import FileSimilarityService
from services.batch5_models import SimilarFileResult


def test_organization_candidate_to_dict():
    cand = OrganizationCandidate(
        file_path="/tmp/car.jpg",
        file_name="car.jpg",
        score=0.9234,
        match_percentage=92,
        reason="Visual similarity match (92%)",
        category="image",
    )
    d = cand.to_dict()
    assert d["file_name"] == "car.jpg"
    assert d["score"] == 0.9234
    assert d["match_percentage"] == 92
    assert d["selected"] is True


def test_file_organizer_find_by_filename():
    organizer = FileOrganizerService()
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create test files
        dsa_file = os.path.join(tmpdir, "dsa_cheatsheet.pdf")
        car_file = os.path.join(tmpdir, "red_car.jpg")
        with open(dsa_file, "w") as f:
            f.write("Data structures and algorithms cheatsheet notes")
        with open(car_file, "w") as f:
            f.write("Red sports car image data")

        candidates = organizer.find_candidates(
            query="DSA Cheatsheet",
            mode="content",
            scope_dir=tmpdir,
        )

        assert len(candidates) >= 1
        top = candidates[0]
        assert "dsa_cheatsheet" in top.file_name.lower()
        assert top.match_percentage >= 50


def test_file_organizer_execute_organization():
    organizer = FileOrganizerService()
    with tempfile.TemporaryDirectory() as tmpdir:
        src_file = os.path.join(tmpdir, "sample_invoice.pdf")
        with open(src_file, "w") as f:
            f.write("Samsung Electronics Invoice #12345")

        res = organizer.execute_organization(
            target_folder_name="Samsung Invoices",
            destination_parent_dir=tmpdir,
            file_paths=[src_file],
        )

        assert res["ok"] is True
        assert res["moved_count"] == 1
        expected_target_dir = os.path.join(tmpdir, "Samsung Invoices")
        assert os.path.isdir(expected_target_dir)
        assert os.path.isfile(os.path.join(expected_target_dir, "sample_invoice.pdf"))
        assert not os.path.exists(src_file)


def test_file_similarity_percentage_reason():
    class DummyRetrieval:
        indexed_count = 0

    similarity_service = FileSimilarityService(retrieval=DummyRetrieval())
    reason = similarity_service._reason(0.942, 4)
    assert "94%" in reason
    assert "4 highly similar content chunks" in reason
