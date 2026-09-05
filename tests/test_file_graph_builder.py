import os
import numpy as np
import pytest
from graph.file_graph_builder import FileGraphBuilder


def test_min_relationship_threshold_constant():
    assert FileGraphBuilder.MIN_RELATIONSHIP_PCT == 40


def test_calculate_text_similarity_below_threshold():
    # Insufficient substantive words or low overlap
    s1 = "hello world"
    s2 = "hello there"
    # Too few words (< 4 substantive words)
    assert FileGraphBuilder.calculate_text_similarity_pct(s1, s2, min_threshold=40) == 0


def test_calculate_text_similarity_high_overlap():
    s1 = "quarterly financial revenue profit margins balance sheet statement audit"
    s2 = "quarterly revenue profit margins balance sheet quarterly statement"
    pct = FileGraphBuilder.calculate_text_similarity_pct(s1, s2, min_threshold=40)
    assert pct >= 40


def test_calculate_text_similarity_boilerplate_ignored():
    # Files sharing only metadata / boilerplate terms should produce 0
    s1 = "image normalized keywords caption ocr width height format dimensions"
    s2 = "image normalized keywords caption dimensions footer header checksum"
    pct = FileGraphBuilder.calculate_text_similarity_pct(s1, s2, min_threshold=40)
    assert pct == 0


def test_calculate_image_similarity_pct():
    # Unit vectors
    # Exact same vector -> 1.0 cos sim -> 100%
    v1 = np.ones(512, dtype=np.float32)
    v1 /= np.linalg.norm(v1)
    assert FileGraphBuilder.calculate_image_similarity_pct("a.jpg", "b.jpg", vec1=v1, vec2=v1) == 100

    # Orthogonal vectors -> 0.0 cos sim -> 0% (< 40%)
    v2 = np.zeros(512, dtype=np.float32)
    v2[0] = 1.0
    v3 = np.zeros(512, dtype=np.float32)
    v3[1] = 1.0
    assert FileGraphBuilder.calculate_image_similarity_pct("a.jpg", "b.jpg", vec1=v2, vec2=v3) == 0


def test_build_file_graph_isolated_and_duplicate(tmp_path):
    # Create two identical files (100% match)
    f1 = tmp_path / "doc1.txt"
    f2 = tmp_path / "doc2.txt"
    f1.write_text("Unique text with machine learning transformers deep neural network artificial intelligence algorithms", encoding="utf-8")
    f2.write_text("Unique text with machine learning transformers deep neural network artificial intelligence algorithms", encoding="utf-8")

    # Create an unrelated file
    f3 = tmp_path / "unrelated.txt"
    f3.write_text("Cooking recipes for delicious homemade sourdough bread flour yeast salt water oven baking", encoding="utf-8")

    graph = FileGraphBuilder.build_file_graph(str(tmp_path), min_percentage=40)
    entities = graph["entities"]
    relationships = graph["relationships"]

    assert len(entities) == 3
    # Exactly one relationship between doc1 and doc2 (100%), unrelated is disconnected
    assert len(relationships) == 1
    rel = relationships[0]
    assert rel["percentage"] == 100
    assert {rel["source_path"], rel["target_path"]} == {str(f1), str(f2)}
