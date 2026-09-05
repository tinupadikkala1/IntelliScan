"""Tests for the streamlined Organize Files Into Folders feature and UI dialog."""

import os
import tempfile
import pytest
from PySide6.QtWidgets import QApplication

from services.file_organizer_service import FileOrganizerService, ProposedFolderCluster
from ui.dialogs.organize_dialog import OrganizeDialog


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_organize_dialog_initialization(qapp, tmp_path):
    svc = FileOrganizerService()
    dlg = OrganizeDialog(
        organizer_service=svc,
        current_dir=str(tmp_path),
        open_file_callback=lambda p: None,
    )
    assert dlg is not None
    assert dlg.source_edit.text() == str(tmp_path)
    assert dlg.dest_edit.text() == str(tmp_path)
    assert dlg.start_btn is not None
    assert dlg.start_btn.text() == "📁 Start Organizing Files"
    assert hasattr(dlg, "organization_completed")
    assert hasattr(dlg, "folder_name_edit")


def test_organize_dialog_validation_empty_source(qapp, tmp_path):
    empty_src = tmp_path / "empty_folder"
    empty_src.mkdir()
    svc = FileOrganizerService()
    dlg = OrganizeDialog(
        organizer_service=svc,
        current_dir=str(empty_src),
    )
    valid, err_msg = dlg._validate_inputs()
    assert not valid
    assert "No files found in source folder" in err_msg


def test_organize_dialog_validation_valid_folder(qapp, tmp_path):
    valid_src = tmp_path / "src"
    valid_src.mkdir()
    (valid_src / "test.txt").write_text("sample content here for testing")

    svc = FileOrganizerService()
    dlg = OrganizeDialog(
        organizer_service=svc,
        current_dir=str(valid_src),
    )
    valid, err_msg = dlg._validate_inputs()
    assert valid
    assert err_msg == ""


def test_auto_cluster_and_execute_organization(tmp_path):
    src = tmp_path / "source"
    dest = tmp_path / "destination"
    src.mkdir()
    dest.mkdir()

    # Two related financial invoice files
    f1 = src / "client_invoice_march.txt"
    f2 = src / "client_invoice_april.txt"
    f1.write_text("Invoice march billing total payment due vendor amount services quarterly statement balance")
    f2.write_text("Invoice april billing total payment due vendor amount services quarterly statement balance")

    # One unrelated file
    f3 = src / "baking_recipes.txt"
    f3.write_text("Sourdough bread flour yeast salt warm water oven loaf baking crust")

    svc = FileOrganizerService()
    clusters = svc.auto_cluster_folder(str(src), min_similarity=40, only_relation_clusters=True)

    assert len(clusters) == 1
    rel_cluster = clusters[0]
    assert rel_cluster.is_relation_cluster is True
    assert len(rel_cluster.files) == 2
    assert "Collection" in rel_cluster.folder_name

    # Execute move into destination
    res = svc.execute_auto_clustering(clusters, str(dest))
    assert res["ok"] is True
    assert res["moved_count"] == 2
    assert res["folder_count"] == 1
    assert os.path.isdir(res["created_folders"][0])

    # Check files arrived in target folder
    target_files = os.listdir(res["created_folders"][0])
    assert "client_invoice_march.txt" in target_files
    assert "client_invoice_april.txt" in target_files

    # Unrelated file was untouched in source
    assert f3.exists()
