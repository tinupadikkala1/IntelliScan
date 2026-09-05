"""File Organizer Service — Content-Based Automatic & User-Directed Folder Organization.

Detects relationships between files based strictly on multi-modal content similarity (50% threshold).
Groups related files into N relation folders and independent files into M dedicated folders.
Automatically generates meaningful folder names based on core content topics and safely moves files.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from graph.file_graph_builder import FileGraphBuilder

logger = logging.getLogger(__name__)


@dataclass
class OrganizationCandidate:
    """A file candidate for folder organization."""

    file_path: str
    file_name: str
    score: float  # 0.0 to 1.0
    match_percentage: int  # 0 to 100
    reason: str
    category: str = "general"
    selected: bool = True

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "file_name": self.file_name,
            "score": round(self.score, 4),
            "match_percentage": self.match_percentage,
            "reason": self.reason,
            "category": self.category,
            "selected": self.selected,
        }


@dataclass
class ProposedFolderCluster:
    """A proposed folder cluster containing related or independent files."""

    folder_name: str
    is_relation_cluster: bool  # True for N relation clusters, False for M independent items
    similarity_percentage: int
    files: List[str] = field(default_factory=list)
    reason: str = ""
    selected: bool = True

    def to_dict(self) -> dict:
        return {
            "folder_name": self.folder_name,
            "is_relation_cluster": self.is_relation_cluster,
            "similarity_percentage": self.similarity_percentage,
            "files": self.files,
            "reason": self.reason,
            "selected": self.selected,
        }


@dataclass
class MoveResult:
    """Outcome of file organization moves."""
    total: int = 0
    successful: int = 0
    failed: int = 0
    cancelled: bool = False
    created_folders: List[str] = field(default_factory=list)
    moved_files: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class FileOrganizerService:
    """Handles content-based automatic folder clustering and bulk file organization."""

    def __init__(
        self,
        retrieval=None,
        reverse_image_service=None,
        classifier=None,
        session_factory=None,
        db_store=None,
    ) -> None:
        self._retrieval = retrieval
        self._reverse_image = reverse_image_service
        self._classifier = classifier
        self._session_factory = session_factory
        self._db_store = db_store

    # ------------------------------------------------------------------ #
    # Automatic Content Clustering (N Relation Folders + M Independent Folders)
    # ------------------------------------------------------------------ #
    def auto_cluster_folder(
        self,
        folder_path: str,
        min_similarity: int = 50,
        only_relation_clusters: bool = False,
    ) -> List[ProposedFolderCluster]:
        """Scans folder files, detects pairwise content relationships (>= min_similarity threshold),
        and partitions files into N relation clusters + M independent file items.
        """
        if not folder_path or not os.path.isdir(folder_path):
            return []

        abs_folder = os.path.abspath(folder_path)
        evidence_map = getattr(self._retrieval, "_evidence", {}) if self._retrieval else {}
        graph_data = FileGraphBuilder.build_file_graph(abs_folder, evidence_map=evidence_map, min_percentage=min_similarity)

        nodes = graph_data.get("entities", [])
        relationships = graph_data.get("relationships", [])

        if not nodes:
            return []

        # Map node ID to entity dict & path
        node_map: Dict[int, dict] = {n["id"]: n for n in nodes}
        path_node_map: Dict[str, int] = {n["file_path"]: n["id"] for n in nodes}

        # Build pairwise similarity lookup
        sim_matrix: Dict[Tuple[int, int], int] = {}
        for rel in relationships:
            pct = rel.get("percentage", 0)
            if pct >= min_similarity:
                src = rel["source_id"]
                tgt = rel["target_id"]
                sim_matrix[(src, tgt)] = pct
                sim_matrix[(tgt, src)] = pct

        def get_edge_pct(u: int, v: int) -> int:
            return sim_matrix.get((u, v), 0)

        # Complete-linkage clustering: every pair in a cluster must have similarity >= min_similarity
        active_clusters: List[List[int]] = [[n["id"]] for n in nodes]

        while True:
            best_pair = None
            best_sim = -1

            for i in range(len(active_clusters)):
                for j in range(i + 1, len(active_clusters)):
                    c1, c2 = active_clusters[i], active_clusters[j]
                    min_pair_sim = min(get_edge_pct(u, v) for u in c1 for v in c2)
                    if min_pair_sim >= min_similarity and min_pair_sim > best_sim:
                        best_sim = min_pair_sim
                        best_pair = (i, j)

            if best_pair is None:
                break

            i, j = best_pair
            active_clusters[i].extend(active_clusters[j])
            del active_clusters[j]

        clusters: List[ProposedFolderCluster] = []
        for c_nodes in active_clusters:
            component_files = [node_map[nid]["file_path"] for nid in c_nodes]

            if len(c_nodes) > 1:
                # N Relation Cluster (all members have >= min_similarity with each other)
                pair_sims = [
                    get_edge_pct(c_nodes[a], c_nodes[b])
                    for a in range(len(c_nodes))
                    for b in range(a + 1, len(c_nodes))
                ]
                avg_pct = int(round(sum(pair_sims) / max(len(pair_sims), 1))) if pair_sims else min_similarity
                folder_name = self._generate_cluster_folder_name(
                    component_files, default_suffix="Collection", evidence_map=evidence_map
                )
                clusters.append(
                    ProposedFolderCluster(
                        folder_name=folder_name,
                        is_relation_cluster=True,
                        similarity_percentage=max(avg_pct, min_similarity),
                        files=component_files,
                        reason=f"Content relationship match ({max(avg_pct, min_similarity)}% overlap across {len(component_files)} files)",
                        selected=True,
                    )
                )
            elif not only_relation_clusters:
                # M Independent Item
                fpath = component_files[0]
                folder_name = self._generate_single_file_folder_name(fpath, evidence_map=evidence_map)
                clusters.append(
                    ProposedFolderCluster(
                        folder_name=folder_name,
                        is_relation_cluster=False,
                        similarity_percentage=0,
                        files=[fpath],
                        reason="Independent content topic (<50% overlap with other files)",
                        selected=False,
                    )
                )

        # Sort clusters: N relation clusters first (by similarity/size), then M independent items
        clusters.sort(key=lambda c: (c.is_relation_cluster, c.similarity_percentage, len(c.files)), reverse=True)
        return clusters

    def execute_auto_clustering(
        self,
        clusters: List[ProposedFolderCluster],
        destination_parent_dir: str,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        cancel_flag: Optional[threading.Event] = None,
    ) -> dict:
        """Create the N+M target folders and move approved files into them."""
        import threading
        dest_parent = os.path.abspath(destination_parent_dir)

        if not os.path.exists(dest_parent):
            try:
                os.makedirs(dest_parent, exist_ok=True)
            except Exception as exc:
                return {"ok": False, "error": f"Failed to create destination directory: {exc}"}

        if not os.path.isdir(dest_parent):
            return {"ok": False, "error": f"Destination path is not a directory: {dest_parent}"}

        if not os.access(dest_parent, os.W_OK):
            return {"ok": False, "error": f"Destination folder is not writable (permission denied): {dest_parent}"}

        selected_clusters = [c for c in clusters if c.selected and c.files]
        total_files = sum(len(c.files) for c in selected_clusters)

        created_folders = []
        moved_count = 0
        failed_count = 0
        moved_files = []
        errors = []

        for cluster in selected_clusters:
            if cancel_flag and cancel_flag.is_set():
                break

            # Create sanitized target folder
            safe_name = re.sub(r'[\\/*?:"<>|]', '_', cluster.folder_name.strip())
            if not safe_name:
                safe_name = "Organized_Group"
            target_dir = os.path.join(dest_parent, safe_name)
            try:
                os.makedirs(target_dir, exist_ok=True)
                if target_dir not in created_folders:
                    created_folders.append(target_dir)
            except Exception as exc:
                errors.append(f"Cannot create folder '{safe_name}': {exc}")
                continue

            for src_path in cluster.files:
                if cancel_flag and cancel_flag.is_set():
                    break

                src_path = os.path.abspath(src_path)
                if not os.path.exists(src_path):
                    failed_count += 1
                    errors.append(f"File not found: {src_path}")
                    continue

                if os.path.dirname(src_path) == target_dir:
                    # Already in the target folder
                    continue

                dest_file_path = os.path.join(target_dir, os.path.basename(src_path))
                if os.path.exists(dest_file_path) and dest_file_path != src_path:
                    base, ext = os.path.splitext(os.path.basename(src_path))
                    dest_file_path = os.path.join(target_dir, f"{base}_organized{ext}")
                    counter = 1
                    while os.path.exists(dest_file_path) and dest_file_path != src_path:
                        dest_file_path = os.path.join(target_dir, f"{base}_organized_{counter}{ext}")
                        counter += 1

                try:
                    shutil.move(src_path, dest_file_path)

                    # Update all database layers if session factory is available
                    if self._session_factory is not None:
                        try:
                            from services.sqlite_indexer import IndexedFile
                            from database.models import Evidence, VectorMap, FileRelationship, CollectionItem
                            with self._session_factory() as session:
                                row = session.query(IndexedFile).filter(IndexedFile.absolute_path == src_path).first()
                                if row:
                                    row.absolute_path = dest_file_path
                                    row.file_name = os.path.basename(dest_file_path)
                                session.query(Evidence).filter(Evidence.file_path == src_path).update(
                                    {"file_path": dest_file_path}, synchronize_session=False
                                )
                                session.query(VectorMap).filter(VectorMap.file_path == src_path).update(
                                    {"file_path": dest_file_path}, synchronize_session=False
                                )
                                session.query(FileRelationship).filter(FileRelationship.source_path == src_path).update(
                                    {"source_path": dest_file_path}, synchronize_session=False
                                )
                                session.query(FileRelationship).filter(FileRelationship.target_path == src_path).update(
                                    {"target_path": dest_file_path}, synchronize_session=False
                                )
                                session.query(CollectionItem).filter(CollectionItem.file_path == src_path).update(
                                    {"file_path": dest_file_path}, synchronize_session=False
                                )
                                session.commit()
                        except Exception as db_exc:
                            logger.debug("DB path update skipped: %s", db_exc)

                    # Update in-memory retrieval evidence
                    if self._retrieval is not None:
                        try:
                            ev_map = getattr(self._retrieval, "_evidence", {})
                            for chunk in ev_map.values():
                                if getattr(chunk, "file_path", None) == src_path:
                                    chunk.file_path = dest_file_path
                        except Exception:
                            pass

                    moved_count += 1
                    moved_files.append(dest_file_path)

                    if progress_callback:
                        progress_callback(
                            moved_count,
                            total_files,
                            f"Moved {os.path.basename(src_path)} → {safe_name}"
                        )
                except Exception as exc:
                    failed_count += 1
                    errors.append(f"{os.path.basename(src_path)}: {exc}")

        logger.info("Auto-clustered %d files into %d folders", moved_count, len(created_folders))
        return {
            "ok": True,
            "created_folders": created_folders,
            "folder_count": len(created_folders),
            "moved_count": moved_count,
            "failed_count": failed_count,
            "moved_files": moved_files,
            "errors": errors,
        }

    # ------------------------------------------------------------------ #
    # Helper Naming Methods
    # ------------------------------------------------------------------ #
    def _generate_cluster_folder_name(
        self,
        file_paths: List[str],
        default_suffix: str = "Collection",
        evidence_map: Optional[dict] = None,
    ) -> str:
        """Extract top shared topic keywords across a cluster of files to build a descriptive folder name representing the relation."""
        from collections import Counter
        content_words: List[str] = []
        filename_words: List[str] = []
        modality_hints = set()

        _IGNORED = {
            'the', 'and', 'for', 'with', 'from', 'this', 'that', 'these', 'those',
            'file', 'files', 'test', 'copy', 'new', 'doc', 'docs', 'image', 'images',
            'video', 'videos', 'audio', 'data', 'temp', 'tmp', 'item', 'items',
            'page', 'chapter', 'section', 'content', 'normalized', 'extracted',
            'jpg', 'png', 'jpeg', 'pdf', 'txt', 'mp3', 'mp4', 'size', 'bytes',
            'photo', 'picture', 'photograph', 'document', 'text', 'format',
            'sample', 'example', 'untitled', 'default'
        }

        # 1. Extract substantive content from evidence chunks
        evidence_map = evidence_map or (getattr(self._retrieval, "_evidence", {}) if self._retrieval else {})
        if evidence_map:
            for fp in file_paths:
                norm_p = os.path.abspath(fp)
                for chunk in evidence_map.values():
                    if getattr(chunk, "file_path", None) and os.path.abspath(chunk.file_path) == norm_p:
                        st = getattr(chunk, "source_type", "") or ""
                        if st in ("image_filename", "clip_visual", "image_caption"):
                            continue
                        txt = getattr(chunk, "text", "") or ""
                        if "Extracted Content:" in txt:
                            txt = txt.split("Extracted Content:")[-1]
                        words = re.findall(r'\b[A-Za-z]{3,}\b', txt)
                        for w in words:
                            if w.lower() not in _IGNORED:
                                content_words.append(w.capitalize())

        # Fallback reading small text files
        if not content_words:
            for fp in file_paths:
                ext = os.path.splitext(fp)[1].lower()
                if ext in ('.txt', '.md', '.csv', '.json') and os.path.isfile(fp):
                    try:
                        with open(fp, 'r', encoding='utf-8', errors='ignore') as f:
                            raw_data = f.read(2000)
                            # In structured CSV or JSON, lines often contain file paths or paths of images — filter them out
                            if ext in ('.csv', '.json'):
                                clean_lines = [ln for ln in raw_data.splitlines() if '/' not in ln and '\\' not in ln]
                                raw_data = " ".join(clean_lines)
                            words = re.findall(r'\b[A-Za-z]{3,}\b', raw_data)
                            for w in words:
                                if w.lower() not in _IGNORED:
                                    content_words.append(w.capitalize())
                    except Exception:
                        pass

        # 2. Extract words from file names & modality
        for fp in file_paths:
            base = os.path.splitext(os.path.basename(fp))[0]
            ext = os.path.splitext(fp)[1].lower()
            if ext in ('.png', '.jpg', '.jpeg', '.bmp', '.webp'):
                modality_hints.add('Photos')
            elif ext in ('.pdf', '.doc', '.docx'):
                modality_hints.add('Documents')
            elif ext in ('.csv', '.tsv', '.json', '.parquet', '.db', '.sqlite'):
                modality_hints.add('Data')
            elif ext in ('.txt', '.md'):
                modality_hints.add('Notes')
            elif ext in ('.mp3', '.wav', '.flac', '.m4a'):
                modality_hints.add('Audio')
            elif ext in ('.mp4', '.mkv', '.avi', '.mov'):
                modality_hints.add('Videos')

            clean = re.sub(r'([a-z])([A-Z])', r'\1 \2', base)
            clean = re.sub(r'[\-_0-9.]', ' ', clean)
            w_list = []
            for w in clean.split():
                w_low = w.lower()
                # Skip stopwords, short tokens, or random consonant strings
                if len(w) >= 3 and w_low not in _IGNORED and any(c in 'aeiou' for c in w_low):
                    if not re.search(r'[bcdfghjklmnpqrstvwxyz]{4,}', w_low):
                        w_list.append(w.capitalize())
            filename_words.extend(w_list)

        title_parts: List[str] = []

        _PRIORITY_TERMS = {
            'student', 'students', 'portrait', 'portraits', 'multicultural', 'children', 'child',
            'school', 'highway', 'highways', 'street', 'streets', 'road', 'roads', 'scene', 'scenes',
            'traffic', 'speed', 'limit', 'nature', 'invoice', 'invoices', 'report', 'reports',
            'document', 'documents', 'financial', 'billing', 'conversation', 'park', 'market', 'outdoor',
            'metadata', 'timeline', 'dataset', 'records', 'database', 'tables', 'objects', 'collage', 'signs'
        }

        # Filename keywords are the most explicit signal of identity
        fn_priority = [w for w in filename_words if w.lower() in _PRIORITY_TERMS]
        if fn_priority:
            fn_counts = Counter(fn_priority)
            sorted_fn = sorted(fn_counts.keys(), key=lambda w: fn_counts[w], reverse=True)
            title_parts.extend(sorted_fn[:2])

        # Fill with substantive content words if needed
        if len(title_parts) < 2 and content_words:
            counts = Counter(content_words)
            sorted_cw = sorted(counts.keys(), key=lambda w: (w.lower() in _PRIORITY_TERMS, counts[w]), reverse=True)
            for w in sorted_cw:
                if w not in title_parts:
                    title_parts.append(w)
                if len(title_parts) >= 2:
                    break

        # Fill with general filename words if still needed
        if len(title_parts) < 2 and filename_words:
            fn_counts = Counter(filename_words)
            sorted_fn = sorted(fn_counts.keys(), key=lambda w: (w.lower() in _PRIORITY_TERMS, fn_counts[w]), reverse=True)
            for w in sorted_fn:
                if w not in title_parts:
                    title_parts.append(w)
                if len(title_parts) >= 2:
                    break

        if modality_hints and len(title_parts) < 3:
            hint = list(modality_hints)[0]
            if hint not in title_parts:
                title_parts.append(hint)

        if not title_parts:
            first_base = os.path.splitext(os.path.basename(file_paths[0]))[0].title()
            first_clean = re.sub(r'[\-_0-9]', ' ', first_base).strip()
            title_parts.append(first_clean if first_clean else "Group")

        title_str = " ".join(title_parts) + f" {default_suffix}"
        title_str = re.sub(r'[\\/*?:"<>|]', '_', title_str).strip()
        if len(title_str) > 50:
            title_str = title_str[:50].rsplit(' ', 1)[0]
        return title_str.strip()

    def _generate_single_file_folder_name(self, file_path: str, evidence_map: Optional[dict] = None) -> str:
        """Extract core content topic name for an independent single file up to 50 characters."""
        base = os.path.splitext(os.path.basename(file_path))[0]
        clean = re.sub(r'([a-z])([A-Z])', r'\1 \2', base)
        clean = re.sub(r'[\-_.]', ' ', clean)
        words = []
        for w in clean.split():
            if re.match(r'^\d+x\d+$', w.lower()) or re.match(r'^\d+[a-z]$', w.lower()) or re.match(r'^\d+$', w):
                continue
            if len(w) >= 2 and any(c in 'aeiouy' for c in w.lower()):
                words.append(w.capitalize())
        clean_name = " ".join(words).strip()
        full_title = f"{clean_name} Folder" if clean_name else f"{base.capitalize()} Folder"
        full_title = re.sub(r'[\\/*?:"<>|]', '_', full_title).strip()
        if len(full_title) > 50:
            full_title = full_title[:50].rsplit(' ', 1)[0]
        return full_title.strip()


    # ------------------------------------------------------------------ #
    # Legacy / Single Query Search Methods
    # ------------------------------------------------------------------ #
    def find_candidates(
        self,
        query: str,
        mode: str = "content",
        scope_dir: Optional[str] = None,
        min_confidence: float = 0.35,
        max_results: int = 100,
    ) -> List[OrganizationCandidate]:
        candidates: List[OrganizationCandidate] = []
        seen_paths = set()
        query_clean = query.strip()
        if not query_clean:
            return []

        scope_dir = os.path.abspath(scope_dir) if scope_dir else None

        if mode == "category":
            return self._find_by_category(query_clean, scope_dir, max_results)

        if self._retrieval is not None:
            try:
                response = self._retrieval.smart_retrieve(
                    query_clean, top_k=max_results * 2, threshold=min_confidence
                )
                for r in response.results:
                    path = os.path.abspath(r.file_path)
                    if scope_dir and not path.startswith(scope_dir + os.sep) and path != scope_dir:
                        continue
                    if path in seen_paths or not os.path.isfile(path):
                        continue
                    seen_paths.add(path)
                    score = min(1.0, max(0.0, float(r.score)))
                    pct = int(round(score * 100))
                    candidates.append(
                        OrganizationCandidate(
                            file_path=path,
                            file_name=os.path.basename(path),
                            score=score,
                            match_percentage=pct,
                            reason=f"Semantic content match ({pct}%)",
                            category=self._get_category(path),
                        )
                    )
            except Exception as exc:
                logger.debug("Semantic candidate retrieval failed: %s", exc)

        kw_terms = [w.lower() for w in query_clean.split() if len(w) > 2]
        if kw_terms:
            search_paths = []
            if scope_dir and os.path.isdir(scope_dir):
                for root, _, files in os.walk(scope_dir):
                    for fn in files:
                        search_paths.append(os.path.abspath(os.path.join(root, fn)))
            else:
                search_paths = self._all_indexed_paths()

            for full_path in search_paths:
                if full_path in seen_paths or not os.path.isfile(full_path):
                    continue
                fn = os.path.basename(full_path)
                fn_lower = fn.lower()
                matches = sum(1 for kw in kw_terms if kw in fn_lower)
                if matches > 0:
                    score = min(0.95, 0.50 + 0.20 * matches)
                    pct = int(round(score * 100))
                    seen_paths.add(full_path)
                    candidates.append(
                        OrganizationCandidate(
                            file_path=full_path,
                            file_name=fn,
                            score=score,
                            match_percentage=pct,
                            reason=f"Filename keyword match '{query_clean}' ({pct}%)",
                            category=self._get_category(full_path),
                        )
                    )

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates[:max_results]

    def _find_by_category(
        self, category_query: str, scope_dir: Optional[str], max_results: int
    ) -> List[OrganizationCandidate]:
        candidates: List[OrganizationCandidate] = []
        cat_lower = category_query.lower().strip()

        paths = self._all_indexed_paths()
        if scope_dir and os.path.isdir(scope_dir):
            for root, _, files in os.walk(scope_dir):
                for fn in files:
                    p = os.path.abspath(os.path.join(root, fn))
                    if p not in paths:
                        paths.append(p)

        for path in paths:
            if scope_dir and not path.startswith(scope_dir + os.sep) and path != scope_dir:
                continue
            if not os.path.isfile(path):
                continue

            file_cat = self._get_category(path)
            ext = os.path.splitext(path)[1].lower()

            match = False
            if cat_lower in file_cat.lower() or cat_lower in ext:
                match = True
            elif cat_lower in ("img", "images", "photos", "pictures") and file_cat == "image":
                match = True
            elif cat_lower in ("doc", "docs", "documents", "pdfs") and file_cat in ("document", "text"):
                match = True
            elif cat_lower in ("audio", "music", "songs") and file_cat == "audio":
                match = True
            elif cat_lower in ("video", "videos", "movies") and file_cat == "video":
                match = True

            if match:
                score = 0.90
                pct = 90
                candidates.append(
                    OrganizationCandidate(
                        file_path=path,
                        file_name=os.path.basename(path),
                        score=score,
                        match_percentage=pct,
                        reason=f"Category match '{file_cat}' ({pct}%)",
                        category=file_cat,
                    )
                )

        return candidates[:max_results]

    def execute_organization(
        self,
        target_folder_name: str,
        destination_parent_dir: str,
        file_paths: List[str],
    ) -> dict:
        dest_parent = os.path.abspath(destination_parent_dir)
        if not os.path.isdir(dest_parent):
            return {"ok": False, "error": f"Destination directory does not exist: {dest_parent}"}

        target_dir = os.path.join(dest_parent, target_folder_name.strip())
        os.makedirs(target_dir, exist_ok=True)

        moved_count = 0
        failed_count = 0
        moved_files = []
        errors = []

        for src_path in file_paths:
            src_path = os.path.abspath(src_path)
            if not os.path.exists(src_path):
                failed_count += 1
                errors.append(f"File not found: {src_path}")
                continue

            if os.path.dirname(src_path) == target_dir:
                continue

            dest_file_path = os.path.join(target_dir, os.path.basename(src_path))
            if os.path.exists(dest_file_path) and dest_file_path != src_path:
                base, ext = os.path.splitext(os.path.basename(src_path))
                dest_file_path = os.path.join(target_dir, f"{base}_organized{ext}")

            try:
                shutil.move(src_path, dest_file_path)
                if self._session_factory is not None:
                    try:
                        from services.sqlite_indexer import IndexedFile
                        with self._session_factory() as session:
                            row = session.query(IndexedFile).filter(IndexedFile.absolute_path == src_path).first()
                            if row:
                                row.absolute_path = dest_file_path
                                row.file_name = os.path.basename(dest_file_path)
                                session.commit()
                    except Exception as db_exc:
                        logger.debug("DB path update skipped: %s", db_exc)

                moved_count += 1
                moved_files.append(dest_file_path)
            except Exception as exc:
                failed_count += 1
                errors.append(f"{os.path.basename(src_path)}: {exc}")

        return {
            "ok": True,
            "target_dir": target_dir,
            "moved_count": moved_count,
            "failed_count": failed_count,
            "moved_files": moved_files,
            "errors": errors,
        }

    def _get_category(self, path: str) -> str:
        if self._classifier is not None:
            try:
                return self._classifier.category_for_path(path) or "general"
            except Exception:
                pass
        from services.classification_engine import category_from_extension
        return category_from_extension(path) or "general"

    def _all_indexed_paths(self) -> List[str]:
        if self._session_factory is None:
            return []
        try:
            from services.sqlite_indexer import IndexedFile
            with self._session_factory() as session:
                rows = session.query(IndexedFile.absolute_path).all()
                return [r[0] for r in rows if r[0]]
        except Exception:
            return []
