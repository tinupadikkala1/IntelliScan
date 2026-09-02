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
    ) -> List[ProposedFolderCluster]:
        """Scans folder files, detects pairwise content relationships (>= min_similarity threshold),
        and partitions files into N relation clusters + M independent file items.
        """
        if not folder_path or not os.path.isdir(folder_path):
            return []

        abs_folder = os.path.abspath(folder_path)
        evidence_map = getattr(self._retrieval, "_evidence", {}) if self._retrieval else {}
        graph_data = FileGraphBuilder.build_file_graph(abs_folder, evidence_map=evidence_map)

        nodes = graph_data.get("entities", [])
        relationships = graph_data.get("relationships", [])

        if not nodes:
            return []

        # Map node ID to entity dict & path
        node_map: Dict[int, dict] = {n["id"]: n for n in nodes}
        path_node_map: Dict[str, int] = {n["file_path"]: n["id"] for n in nodes}

        # Build adjacency graph of edges with similarity >= min_similarity
        adj: Dict[int, List[Tuple[int, int]]] = {n["id"]: [] for n in nodes}
        for rel in relationships:
            pct = rel.get("percentage", 0)
            if pct >= min_similarity:
                src = rel["source_id"]
                tgt = rel["target_id"]
                adj[src].append((tgt, pct))
                adj[tgt].append((src, pct))

        # Find connected components (N relation clusters vs M independent items)
        visited: Set[int] = set()
        clusters: List[ProposedFolderCluster] = []

        for node_id, entity in node_map.items():
            if node_id in visited:
                continue

            # BFS / DFS traversal to find all connected nodes in this component
            component_nodes: List[int] = []
            component_pcts: List[int] = []
            queue = [node_id]
            visited.add(node_id)

            while queue:
                curr = queue.pop(0)
                component_nodes.append(curr)
                for neighbor, pct in adj[curr]:
                    component_pcts.append(pct)
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(neighbor)

            component_files = [node_map[nid]["file_path"] for nid in component_nodes]
            avg_pct = int(round(sum(component_pcts) / max(len(component_pcts), 1))) if component_pcts else 0

            if len(component_nodes) > 1:
                # N Relation Cluster
                folder_name = self._generate_cluster_folder_name(component_files, default_suffix="Collection")
                clusters.append(
                    ProposedFolderCluster(
                        folder_name=folder_name,
                        is_relation_cluster=True,
                        similarity_percentage=max(avg_pct, min_similarity),
                        files=component_files,
                        reason=f"Content relationship match ({max(avg_pct, min_similarity)}% overlap across {len(component_files)} files)",
                    )
                )
            else:
                # M Independent Item
                fpath = component_files[0]
                folder_name = self._generate_single_file_folder_name(fpath)
                clusters.append(
                    ProposedFolderCluster(
                        folder_name=folder_name,
                        is_relation_cluster=False,
                        similarity_percentage=0,
                        files=[fpath],
                        reason="Independent content topic (<50% overlap with other files)",
                    )
                )

        # Sort clusters: N relation clusters first (by similarity/size), then M independent items
        clusters.sort(key=lambda c: (c.is_relation_cluster, c.similarity_percentage, len(c.files)), reverse=True)
        return clusters

    def execute_auto_clustering(
        self,
        clusters: List[ProposedFolderCluster],
        destination_parent_dir: str,
    ) -> dict:
        """Create the N+M target folders and move approved files into them."""
        dest_parent = os.path.abspath(destination_parent_dir)
        if not os.path.isdir(dest_parent):
            return {"ok": False, "error": f"Destination directory does not exist: {dest_parent}"}

        created_folders = []
        moved_count = 0
        failed_count = 0
        moved_files = []
        errors = []

        for cluster in clusters:
            if not cluster.selected or not cluster.files:
                continue

            # Create sanitized target folder
            safe_name = re.sub(r'[\\/*?:"<>|]', '_', cluster.folder_name.strip())
            target_dir = os.path.join(dest_parent, safe_name)
            os.makedirs(target_dir, exist_ok=True)
            created_folders.append(target_dir)

            for src_path in cluster.files:
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
                    # Update SQLite database record if available
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
    def _generate_cluster_folder_name(self, file_paths: List[str], default_suffix: str = "Collection") -> str:
        """Extract top shared topic keywords across a cluster of files to build a descriptive folder name up to 50 characters."""
        words: List[str] = []
        modality_hints = set()

        for fp in file_paths:
            base = os.path.splitext(os.path.basename(fp))[0]
            ext = os.path.splitext(fp)[1].lower()
            if ext in ('.png', '.jpg', '.jpeg', '.bmp', '.webp'):
                modality_hints.add('Photos')
            elif ext in ('.pdf', '.doc', '.docx', '.txt', '.md'):
                modality_hints.add('Documents')
            elif ext in ('.mp3', '.wav', '.flac', '.m4a'):
                modality_hints.add('Audio')
            elif ext in ('.mp4', '.mkv', '.avi', '.mov'):
                modality_hints.add('Videos')

            clean = re.sub(r'[\-_0-9]', ' ', base)
            w_list = [w.capitalize() for w in clean.split() if len(w) >= 3 and w.lower() not in (
                'file', 'test', 'copy', 'new', 'doc', 'image', 'video', 'audio', 'data', 'temp', 'tmp'
            )]
            words.extend(w_list)

        title_parts = []
        if words:
            from collections import Counter
            counts = Counter(words)
            top_words = [w for w, _ in counts.most_common(3)]
            title_parts.extend(top_words)

        if modality_hints and len(title_parts) < 3:
            title_parts.append(list(modality_hints)[0])

        if not title_parts:
            first_base = os.path.splitext(os.path.basename(file_paths[0]))[0].title()
            title_parts.append(first_base)

        title_str = " ".join(title_parts) + f" {default_suffix}"
        # Ensure meaningful length up to 50 characters cleanly
        if len(title_str) > 50:
            title_str = title_str[:50].rsplit(' ', 1)[0]
        return title_str.strip()

    def _generate_single_file_folder_name(self, file_path: str) -> str:
        """Extract core content topic name for an independent single file up to 50 characters."""
        base = os.path.splitext(os.path.basename(file_path))[0]
        clean_name = re.sub(r'[\-_]', ' ', base).title().strip()
        full_title = f"{clean_name} Folder"
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
