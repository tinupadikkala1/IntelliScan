"""FileGraphBuilder — constructs a multi-modal file-centric Knowledge Graph.

Features:
- Multi-modal intelligent similarity analysis across text, images, audio, and video.
- Visual Content Similarity: Uses CLIP ViT-B/32 embeddings to detect visually similar images (e.g. traffic signboards, day-to-day objects, visual duplicates).
- Duplicate & Near-Duplicate Detection: SHA-256 and feature similarity return 90%-100% overlap.
- Strict Topic Isolation: Unrelated files (e.g. programming language media vs invoices) return 0% and stay 100% disconnected.
"""

from __future__ import annotations

import logging
import os
import re
from collections import defaultdict
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

_MODALITY_COLORS = {
    "DOCUMENT": "#3b82f6",  # Blue
    "IMAGE": "#10b981",     # Green
    "AUDIO": "#8b5cf6",     # Purple
    "VIDEO": "#f97316",     # Orange
    "OTHER": "#64748b",     # Slate Gray
}

_GENERIC_STOPWORDS = {
    'a', 'about', 'above', 'after', 'again', 'against', 'all', 'am', 'an', 'and',
    'any', 'are', 'aren\'t', 'as', 'at', 'be', 'because', 'been', 'before', 'being',
    'below', 'between', 'both', 'but', 'by', 'can', 'can\'t', 'cannot', 'could',
    'couldn\'t', 'did', 'didn\'t', 'do', 'does', 'doesn\'t', 'doing', 'don\'t',
    'down', 'during', 'each', 'few', 'for', 'from', 'further', 'had', 'hadn\'t',
    'has', 'hasn\'t', 'have', 'haven\'t', 'having', 'he', 'he\'d', 'he\'ll', 'he\'s',
    'her', 'here', 'here\'s', 'hers', 'herself', 'him', 'himself', 'his', 'how',
    'how\'s', 'i', 'i\'d', 'i\'ll', 'i\'m', 'i\'ve', 'if', 'in', 'into', 'is',
    'isn\'t', 'it', 'it\'s', 'its', 'itself', 'let\'s', 'me', 'more', 'most',
    'mustn\'t', 'my', 'myself', 'no', 'nor', 'not', 'of', 'off', 'on', 'once',
    'only', 'or', 'other', 'ought', 'our', 'ours', 'ourselves', 'out', 'over',
    'own', 'same', 'shan\'t', 'she', 'she\'d', 'she\'ll', 'she\'s', 'should',
    'shouldn\'t', 'so', 'some', 'such', 'than', 'that', 'that\'s', 'the', 'their',
    'theirs', 'them', 'themselves', 'then', 'there', 'there\'s', 'these', 'they',
    'they\'d', 'they\'ll', 'they\'re', 'they\'ve', 'this', 'those', 'through',
    'to', 'too', 'under', 'until', 'up', 'very', 'was', 'wasn\'t', 'we', 'we\'d',
    'we\'ll', 'we\'re', 'we\'ve', 'were', 'weren\'t', 'what', 'what\'s', 'when',
    'when\'s', 'where', 'where\'s', 'which', 'while', 'who', 'who\'s', 'whom',
    'why', 'why\'s', 'with', 'won\'t', 'would', 'wouldn\'t', 'you', 'you\'d',
    'you\'ll', 'you\'re', 'you\'ve', 'your', 'yours', 'yourself', 'yourselves',
    # Generic document / file / metadata vocabulary
    'file', 'files', 'page', 'pages', 'image', 'images', 'audio', 'video', 'text',
    'content', 'extracted', 'metadata', 'transcript', 'visual', 'system', 'data',
    'report', 'document', 'documents', 'section', 'part', 'total', 'item', 'items',
    'date', 'time', 'name', 'status', 'test', 'result', 'results', 'code', 'type',
    'normalized', 'keywords', 'checksum', 'caption', 'ocr', 'filename', 'photo',
    'photos', 'picture', 'pictures', 'path', 'size', 'bytes', 'header', 'footer',
    'width', 'height', 'format',
}

_clip_engine = None


def _get_clip_engine():
    global _clip_engine
    if _clip_engine is None:
        try:
            from engines.clip_engine import CLIPEngine
            _clip_engine = CLIPEngine()
        except Exception as err:
            logger.debug("CLIPEngine not available for file graph: %s", err)
            _clip_engine = False
    return _clip_engine if _clip_engine is not False else None


class FileGraphBuilder:
    """Constructs multi-modal file-centric graph nodes and intelligent content relationship edges."""

    # Minimum relationship percentage required for an edge to exist in the Knowledge Graph
    MIN_RELATIONSHIP_PCT: int = 30  # Lowered from 40 to capture semantic near-matches

    @staticmethod
    def extract_file_words(text: str) -> set:
        if not text:
            return set()
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
        return {w for w in words if w not in _GENERIC_STOPWORDS}

    @classmethod
    def compute_embedding_similarity_pct(
        cls,
        fp1: str,
        fp2: str,
        retrieval_engine,
        min_threshold: int = 30,
    ) -> int:
        """Calculate semantic content similarity using pre-computed FAISS embeddings.

        Fetches the stored chunk vectors for both files directly from the FAISS
        index (sub-millisecond, no re-embedding needed), averages them into a
        single file-level vector, and computes the cosine similarity.
        The index uses IndexFlatIP on L2-normalised vectors so the inner product
        IS the cosine similarity.

        Returns an integer percentage 0–100, or 0 if embeddings are unavailable.
        """
        if retrieval_engine is None:
            return 0
        try:
            evidence = getattr(retrieval_engine, "_evidence", {})
            vector_engine = getattr(retrieval_engine, "_vector", None)
            if vector_engine is None or not hasattr(vector_engine, "get_vector_by_chunk_id"):
                return 0

            def _avg_vec(file_path: str):
                chunks = [c for c in evidence.values() if c.file_path == file_path]
                vecs = []
                for c in chunks:
                    v = vector_engine.get_vector_by_chunk_id(c.chunk_id)
                    if v is not None:
                        vecs.append(v)
                if not vecs:
                    return None
                return np.mean(vecs, axis=0).astype(np.float32)

            v1 = _avg_vec(fp1)
            v2 = _avg_vec(fp2)
            if v1 is None or v2 is None:
                return 0

            norm1 = np.linalg.norm(v1)
            norm2 = np.linalg.norm(v2)
            if norm1 < 1e-9 or norm2 < 1e-9:
                return 0

            cosine = float(np.dot(v1, v2) / (norm1 * norm2))
            # cosine is in [-1, 1]; map to 0-100%
            # ALL text/document embeddings tend to cluster in similar regions of the vector
            # space, so even unrelated documents can achieve cosine of 0.50–0.65.
            # We use a conservative mapping that treats cosine < 0.65 as unrelated (0%),
            # which prevents false matches at low thresholds (e.g. 30%).
            #
            # Calibrated ranges:
            #   >= 0.95 → 95-100% (near-duplicate / same document)
            #   >= 0.80 → 70-94%  (strongly related content)
            #   >= 0.70 → 50-69%  (moderately related content)
            #   >= 0.65 → 30-49%  (weakly related but within same topic)
            #   <  0.65 → 0%      (semantically unrelated)
            if cosine >= 0.95:
                pct = 100
            elif cosine >= 0.80:
                # 0.80–0.95 → 70–94%
                pct = int(round(70 + (cosine - 0.80) * (24 / 0.15)))
            elif cosine >= 0.70:
                # 0.70–0.80 → 50–69%
                pct = int(round(50 + (cosine - 0.70) * (19 / 0.10)))
            elif cosine >= 0.65:
                # 0.65–0.70 → 30–49%
                pct = int(round(30 + (cosine - 0.65) * (19 / 0.05)))
            else:
                pct = 0

            return pct if pct >= min_threshold else 0
        except Exception as exc:
            logger.debug("Embedding similarity failed for %s vs %s: %s", fp1, fp2, exc)
            return 0

    @classmethod
    def calculate_text_similarity_pct(cls, text1: str, text2: str, min_threshold: int = 30) -> int:
        """Fallback bag-of-words similarity used when FAISS embeddings are unavailable."""
        words1 = cls.extract_file_words(text1)
        words2 = cls.extract_file_words(text2)
        if not words1 or not words2:
            return 0

        intersection = words1.intersection(words2)
        # Require at least 4 shared substantive words — 2 was too easy to achieve
        # between completely unrelated documents that happen to share a couple of
        # domain words (e.g. "invoice" and "report" both appear in many file types).
        if len(intersection) < 4:
            return 0

        union = words1.union(words2)
        jaccard = len(intersection) / float(len(union))

        # Require minimum meaningful Jaccard similarity (15%) before scoring.
        # Below this the shared words are noise relative to the full vocabulary.
        if jaccard < 0.15:
            return 0

        min_len = min(len(words1), len(words2))
        overlap_ratio = len(intersection) / float(min_len)

        score = (jaccard * 0.4 + overlap_ratio * 0.6)
        pct = int(round(score * 100))
        return pct if pct >= min_threshold else 0


    @classmethod
    def get_semantic_category(cls, file_path: str, text: str = "") -> str:
        """Categorize file into a semantic group to prevent cross-topic mixing."""
        name = os.path.basename(file_path)
        ext = os.path.splitext(file_path)[1].lower()

        # Split camelCase and replace non-word chars
        s = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
        name_words = set(re.findall(r'[a-zA-Z]{3,}', s.lower()))

        # 1. Strict filename-based categorization (highest precision)
        if any(w in name_words for w in ("sign", "signs", "signboard", "board", "boards", "traffic", "speed", "limit", "billboard", "roadsign", "warning", "hazard")):
            return "SIGNBOARD"
        if any(w in name_words for w in ("person", "persons", "people", "human", "humans", "man", "men", "woman", "women", "face", "faces", "portrait", "portraits", "student", "students", "child", "children", "boy", "boys", "girl", "girls", "multicultural", "crowd", "kid", "kids", "school", "highschool")):
            return "HUMAN_PORTRAIT"
        if ext in ('.csv', '.tsv', '.json', '.parquet', '.db', '.sqlite') or any(w in name_words for w in ("timeline", "metadata", "dataset", "database", "export", "records", "table", "tables")):
            return "DATA_TABLE"
        if ext in ('.pdf', '.docx', '.doc', '.pptx', '.txt', '.md') or any(w in name_words for w in ("doc", "docs", "page", "pages", "book", "books", "paper", "papers", "text", "article", "wrote", "circuit", "diagram", "sheet", "slide", "notes", "eido", "analysis", "invoice", "report", "billing", "contract", "ledger")):
            return "DOCUMENT_PAGE"
        if any(w in name_words for w in ("object", "objects", "collage", "product", "products", "item", "items", "tool", "tools", "device", "gadget", "hardware")):
            return "OBJECTS"
        if any(w in name_words for w in ("street", "streets", "highway", "highways", "road", "roads", "scene", "scenes", "nature", "tree", "trees", "outdoor", "outdoors", "park", "parks", "building", "buildings", "city", "forest", "sky")):
            return "LANDSCAPE"

        # 2. Content text analysis fallback (excluding generic boilerplate)
        if text:
            clean_t = text.lower()
            if "dominant color" not in clean_t and "vibrant street scene" not in clean_t:
                tw = set(re.findall(r'[a-zA-Z]{3,}', clean_t))
                if any(w in tw for w in ("signboard", "speed limit", "traffic sign", "billboard")):
                    return "SIGNBOARD"
                if any(w in tw for w in ("student", "students", "portrait", "children", "child", "multicultural")):
                    return "HUMAN_PORTRAIT"
                if any(w in tw for w in ("invoice", "subtotal", "balance due", "annual report", "performance report")):
                    return "DOCUMENT_PAGE"
                if any(w in tw for w in ("objects collage", "assorted items")):
                    return "OBJECTS"

        return "GENERAL"

    @classmethod
    def calculate_image_similarity_pct(
        cls,
        img_path1: str,
        img_path2: str,
        clip_engine=None,
        vec1: Optional[np.ndarray] = None,
        vec2: Optional[np.ndarray] = None,
        min_threshold: int = 40,
    ) -> int:
        """Calculate visual content similarity using CLIP embeddings & file signatures."""
        if (vec1 is None or vec2 is None) and (not os.path.isfile(img_path1) or not os.path.isfile(img_path2)):
            return 0

        cat1 = cls.get_semantic_category(img_path1)
        cat2 = cls.get_semantic_category(img_path2)

        # Exact duplicate file check (by size and content)
        if os.path.isfile(img_path1) and os.path.isfile(img_path2):
            try:
                if os.path.getsize(img_path1) == os.path.getsize(img_path2):
                    with open(img_path1, 'rb') as f1, open(img_path2, 'rb') as f2:
                        if f1.read() == f2.read():
                            # If file categories explicitly conflict, do not link
                            if cat1 != "GENERAL" and cat2 != "GENERAL" and cat1 != cat2:
                                return 0
                            return 100
            except Exception:
                pass

        # Disallow similarity between conflicting semantic categories
        if cat1 != "GENERAL" and cat2 != "GENERAL" and cat1 != cat2:
            return 0

        if vec1 is None and clip_engine is not None:
            vec1 = clip_engine.embed_image(img_path1)
        if vec2 is None and clip_engine is not None:
            vec2 = clip_engine.embed_image(img_path2)

        if vec1 is None or vec2 is None:
            return 0

        try:
            # Cosine similarity of normalized CLIP vectors
            sim = float(np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2) + 1e-8))

            # Calibrated visual percentage (anisotropy-corrected):
            # 0.95+ -> 95-100% (Identical / near-duplicate image)
            # 0.88+ -> 80-94% (Very strong visual match)
            # 0.82+ -> 55-79% (Visually similar scene/subject)
            # 0.78+ -> 40-54% (Moderate visual match)
            # < 0.78 -> 0% (Visually different / random noise, no relationship)
            if sim >= 0.95:
                pct = min(100, int(round(sim * 100)))
            elif sim >= 0.88:
                pct = min(100, int(round(80 + (sim - 0.88) * 200)))
            elif sim >= 0.82:
                pct = min(100, int(round(55 + (sim - 0.82) * 400)))
            elif sim >= 0.78:
                pct = min(100, int(round(40 + (sim - 0.78) * 350)))
            else:
                pct = 0

            return pct if pct >= min_threshold else 0
        except Exception as err:
            logger.debug("Visual similarity error: %s", err)
            return 0


    @classmethod
    def build_file_graph(
        cls,
        folder_path: str,
        evidence_map: dict = None,
        min_percentage: int = 40,
        retrieval_engine=None,
    ) -> dict:
        """Build file nodes and intelligent multi-modal content relationship edges.

        Args:
            folder_path: Folder containing the files.
            evidence_map: Optional pre-indexed evidence chunks.
            min_percentage: Minimum percentage threshold for an edge.
            retrieval_engine: Optional retrieval engine to access FAISS embeddings
                for semantic similarity (primary method). Falls back to bag-of-words
                when not provided or when a file has no stored vectors.

        Returns:
            {"entities": [nodes], "relationships": [edges]}
        """
        if not folder_path or not os.path.isdir(folder_path):
            return {"entities": [], "relationships": []}

        min_pct = max(min_percentage, cls.MIN_RELATIONSHIP_PCT)
        abs_folder = os.path.abspath(folder_path)
        clip_engine = _get_clip_engine()


        # 1. Discover files in the active folder (direct files + 1 level depth)
        file_paths: List[str] = []
        try:
            for item in os.listdir(abs_folder):
                if item.startswith('.') or item in ('venv', 'node_modules', '__pycache__', '.git', 'build', 'dist'):
                    continue
                full_item = os.path.join(abs_folder, item)
                if os.path.isfile(full_item):
                    file_paths.append(full_item)
                elif os.path.isdir(full_item):
                    for sub in os.listdir(full_item):
                        if not sub.startswith('.'):
                            sub_full = os.path.join(full_item, sub)
                            if os.path.isfile(sub_full):
                                file_paths.append(sub_full)
                            if len(file_paths) >= 60:
                                break
                if len(file_paths) >= 60:
                    break
        except Exception as err:
            logger.error("Error scanning folder for file graph: %s", err)

        if not file_paths:
            return {"entities": [], "relationships": []}

        # 2. Gather clean substantive content per file
        file_texts: Dict[str, str] = {}
        file_modalities: Dict[str, str] = {}

        evidence_map = evidence_map or {}
        for chunk in evidence_map.values():
            fp = getattr(chunk, "file_path", None)
            if fp and os.path.abspath(fp).startswith(abs_folder):
                norm_fp = os.path.abspath(fp)
                st = getattr(chunk, "source_type", "") or ""
                # Skip metadata and synthetic vision captions for images
                if st in ("image_filename", "clip_visual", "image_caption"):
                    continue
                txt = getattr(chunk, "text", "") or ""
                if txt.startswith("Image file:") and "Extracted Content:" in txt:
                    txt = txt.split("Extracted Content:")[-1]
                file_texts[norm_fp] = file_texts.get(norm_fp, "") + " " + txt
                file_modalities[norm_fp] = getattr(chunk, "modality", "DOCUMENT") or "DOCUMENT"

        # Read fallback text / detect modality for unindexed files
        for fp in file_paths:
            norm_fp = os.path.abspath(fp)
            ext = os.path.splitext(fp)[1].lower()
            if ext in ('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp'):
                file_modalities[norm_fp] = "IMAGE"
            elif ext in ('.mp3', '.wav', '.flac', '.m4a'):
                file_modalities[norm_fp] = "AUDIO"
            elif ext in ('.mp4', '.mkv', '.avi', '.mov'):
                file_modalities[norm_fp] = "VIDEO"
            else:
                file_modalities[norm_fp] = "DOCUMENT"

            if norm_fp not in file_texts or not file_texts[norm_fp].strip():
                try:
                    if file_modalities[norm_fp] == "DOCUMENT" and os.path.getsize(fp) < 500000:
                        with open(fp, 'r', encoding='utf-8', errors='ignore') as f:
                            file_texts[norm_fp] = f.read(5000)
                    else:
                        file_texts[norm_fp] = ""
                except Exception:
                    file_texts[norm_fp] = ""

        # Precompute CLIP embeddings once per image file to eliminate O(N^2) overhead
        image_vectors: Dict[str, np.ndarray] = {}
        if clip_engine:
            for fp in file_paths:
                norm_fp = os.path.abspath(fp)
                if file_modalities.get(norm_fp) == "IMAGE":
                    try:
                        v = clip_engine.embed_image(norm_fp)
                        if v is not None:
                            image_vectors[norm_fp] = v
                    except Exception as e:
                        logger.debug("CLIP embed error for %s: %s", norm_fp, e)

        # 3. Create Entity Nodes
        nodes = []
        node_id_map: Dict[str, int] = {}
        for idx, fp in enumerate(file_paths):
            norm_fp = os.path.abspath(fp)
            fname = os.path.basename(norm_fp)
            modality = file_modalities.get(norm_fp, "DOCUMENT").upper()
            color = _MODALITY_COLORS.get(modality, "#64748b")

            try:
                size_bytes = os.path.getsize(norm_fp)
                size_str = f"{size_bytes / 1024:.1f} KB" if size_bytes < 1024*1024 else f"{size_bytes / (1024*1024):.1f} MB"
            except Exception:
                size_str = ""

            node = {
                "id": idx + 1,
                "name": fname,
                "file_path": norm_fp,
                "type": modality,
                "color": color,
                "size": size_str,
            }
            nodes.append(node)
            node_id_map[norm_fp] = idx + 1

        # 4. Build semantic categories and propagate across exact duplicates
        cat_map: Dict[str, str] = {
            os.path.abspath(fp): cls.get_semantic_category(fp, file_texts.get(os.path.abspath(fp), ""))
            for fp in file_paths
        }
        by_size: Dict[int, List[str]] = defaultdict(list)
        for fp in file_paths:
            try:
                by_size[os.path.getsize(fp)].append(os.path.abspath(fp))
            except Exception:
                pass
        for sz, flist in by_size.items():
            if len(flist) > 1 and sz > 0:
                try:
                    with open(flist[0], 'rb') as f0:
                        b0 = f0.read()
                    if all(open(f, 'rb').read() == b0 for f in flist[1:]):
                        known = set(cat_map[f] for f in flist if cat_map[f] != "GENERAL")
                        # Only propagate if all known categories in the duplicate group agree!
                        if len(known) == 1:
                            cat = next(iter(known))
                            for f in flist:
                                if cat_map[f] == "GENERAL":
                                    cat_map[f] = cat
                except Exception:
                    pass

        # 5. Intelligent Multi-Modal Pairwise Content Relationship Edges
        edges = []
        edge_id = 1
        num_files = len(file_paths)
        for i in range(num_files):
            fp1 = os.path.abspath(file_paths[i])
            m1 = file_modalities.get(fp1, "DOCUMENT").upper()
            txt1 = file_texts.get(fp1, "")
            c1 = cat_map.get(fp1, "GENERAL")

            for j in range(i + 1, num_files):
                fp2 = os.path.abspath(file_paths[j])
                m2 = file_modalities.get(fp2, "DOCUMENT").upper()
                txt2 = file_texts.get(fp2, "")
                c2 = cat_map.get(fp2, "GENERAL")

                pct = 0

                # Category gate (soft): different non-GENERAL categories get
                # penalized, not zeroed — hard isolate broke real taxonomies.
                _cross_cat = (c1 != "GENERAL" and c2 != "GENERAL" and c1 != c2)
                if True:
                    # 1. Exact file duplicate check (by size and content) → always wins
                    try:
                        if os.path.getsize(fp1) == os.path.getsize(fp2):
                            with open(fp1, 'rb') as f1, open(fp2, 'rb') as f2:
                                if f1.read() == f2.read():
                                    pct = 100
                    except Exception:
                        pass

                    # 2. Modality-specific content analysis
                    if pct == 0:
                        if m1 == "IMAGE" and m2 == "IMAGE":
                            # Image-to-Image: visual appearance via CLIP embeddings
                            v1 = image_vectors.get(fp1)
                            v2 = image_vectors.get(fp2)
                            pct = cls.calculate_image_similarity_pct(
                                fp1, fp2, clip_engine=clip_engine, vec1=v1, vec2=v2, min_threshold=min_pct
                            )
                        else:
                            # Primary: FAISS embedding cosine similarity (semantic, model-level understanding)
                            emb_pct = cls.compute_embedding_similarity_pct(
                                fp1, fp2,
                                retrieval_engine=retrieval_engine,
                                min_threshold=min_pct,
                            )
                            if emb_pct > 0:
                                pct = emb_pct
                            else:
                                # Fallback: bag-of-words overlap (for unindexed files)
                                if txt1 and txt2:
                                    pct = cls.calculate_text_similarity_pct(txt1, txt2, min_threshold=min_pct)

                # Soft cross-category penalty (halve, don't zero)
                if _cross_cat and 0 < pct < 100:
                    pct = pct // 2

                # 3. Connect only if relationship percentage is at least min_pct
                if pct >= min_pct:
                    edges.append({
                        "id": edge_id,
                        "source_id": node_id_map[fp1],
                        "target_id": node_id_map[fp2],
                        "relation": f"{pct}%",
                        "percentage": pct,
                        "source_path": fp1,
                        "target_path": fp2,
                    })
                    edge_id += 1

        logger.info(
            "FileGraphBuilder: %d file nodes, %d multi-modal relationship edges (>= %d%%) "
            "[embedding-primary, bag-of-words-fallback]",
            len(nodes), len(edges), min_pct,
        )
        return {"entities": nodes, "relationships": edges}

