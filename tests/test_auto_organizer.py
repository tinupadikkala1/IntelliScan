"""Tests for Automatic Content-Based Folder Organization (N Relation Folders + M Independent Folders)."""

import os
import shutil
import tempfile
import pytest

from services.file_organizer_service import FileOrganizerService, ProposedFolderCluster


def test_auto_cluster_folder_partitioning():
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create related file group 1 (Traffic Signboards)
        f1 = os.path.join(tmp_dir, "speed_limit_sign.txt")
        f2 = os.path.join(tmp_dir, "traffic_highway_sign.txt")
        with open(f1, "w") as f:
            f.write("traffic signboard speed limit highway road warning sign caution speed 60 kmh")
        with open(f2, "w") as f:
            f.write("traffic signboard speed limit highway road warning sign intersection caution speed 60 kmh")

        # Create independent file item M1 (Mojo Programming Language)
        f3 = os.path.join(tmp_dir, "mojo_language_guide.txt")
        with open(f3, "w") as f:
            f.write("mojo language futuristic programming language compiler syntax AI developers python alternative")

        organizer = FileOrganizerService()
        clusters = organizer.auto_cluster_folder(tmp_dir, min_similarity=50)

        assert len(clusters) >= 2

        # Verify N relation cluster exists for traffic signboards
        rel_clusters = [c for c in clusters if c.is_relation_cluster]
        assert len(rel_clusters) >= 1
        assert len(rel_clusters[0].files) == 2
        assert rel_clusters[0].similarity_percentage >= 50

        # Verify M independent item exists for Mojo language
        ind_clusters = [c for c in clusters if not c.is_relation_cluster]
        assert len(ind_clusters) >= 1
        assert len(ind_clusters[0].files) == 1
        assert ind_clusters[0].similarity_percentage == 0


def test_execute_auto_clustering():
    with tempfile.TemporaryDirectory() as tmp_dir:
        src_dir = os.path.join(tmp_dir, "source")
        dest_dir = os.path.join(tmp_dir, "dest")
        os.makedirs(src_dir, exist_ok=True)
        os.makedirs(dest_dir, exist_ok=True)

        f1 = os.path.join(src_dir, "doc1.txt")
        f2 = os.path.join(src_dir, "doc2.txt")
        with open(f1, "w") as f:
            f.write("alpha beta gamma")
        with open(f2, "w") as f:
            f.write("delta epsilon zeta")

        clusters = [
            ProposedFolderCluster(
                folder_name="Group Alpha",
                is_relation_cluster=True,
                similarity_percentage=75,
                files=[f1],
                selected=True,
            ),
            ProposedFolderCluster(
                folder_name="Group Delta",
                is_relation_cluster=False,
                similarity_percentage=0,
                files=[f2],
                selected=True,
            ),
        ]

        organizer = FileOrganizerService()
        result = organizer.execute_auto_clustering(clusters, dest_dir)

        assert result["ok"] is True
        assert result["moved_count"] == 2
        assert result["folder_count"] == 2
        assert os.path.exists(os.path.join(dest_dir, "Group Alpha", "doc1.txt"))
        assert os.path.exists(os.path.join(dest_dir, "Group Delta", "doc2.txt"))
