"""
Module for enhanced execute_organization with progress tracking
Add this to file_organizer_service.py
"""

from dataclasses import dataclass
from typing import Callable, Optional
import os
import shutil
import logging
import threading

logger = logging.getLogger(__name__)


@dataclass
class MoveResult:
    """Result of move operation"""
    total: int
    successful: int
    failed: int
    cancelled: bool = False


def execute_organization_with_progress(
    self,
    folder_path: str,
    auto_cluster: bool = True,
    progress_callback: Optional[Callable] = None,
    cancel_flag: Optional[threading.Event] = None
) -> MoveResult:
    """
    Execute file organization with progress tracking
    
    Args:
        folder_path: Folder to organize
        auto_cluster: Whether to auto-cluster by category
        progress_callback: Called with (current, total, status_message)
        cancel_flag: threading.Event to signal cancellation
    
    Returns:
        MoveResult with statistics
    """
    
    if not folder_path or not os.path.isdir(folder_path):
        if progress_callback:
            progress_callback(0, 0, "Invalid folder path")
        return MoveResult(total=0, successful=0, failed=0)
    
    try:
        # Step 1: Discover files
        if progress_callback:
            progress_callback(0, 100, "Discovering files...")
        
        if cancel_flag and cancel_flag.is_set():
            return MoveResult(total=0, successful=0, failed=0, cancelled=True)
        
        # Count total files
        total_files = sum(
            1 for root, dirs, files in os.walk(folder_path)
            for f in files
        )
        
        if total_files == 0:
            if progress_callback:
                progress_callback(0, 0, "No files to organize")
            return MoveResult(total=0, successful=0, failed=0)
        
        # Step 2: Generate organization plan
        if progress_callback:
            progress_callback(10, 100, "Generating organization plan...")
        
        if cancel_flag and cancel_flag.is_set():
            return MoveResult(total=total_files, successful=0, failed=0, cancelled=True)
        
        if auto_cluster:
            clusters = self.auto_cluster_folder(folder_path)
        else:
            clusters = []
        
        total_moves = sum(len(c.files) for c in clusters)
        
        # Step 3: Create folders
        if progress_callback:
            progress_callback(25, 100, "Creating folders...")
        
        if cancel_flag and cancel_flag.is_set():
            return MoveResult(total=total_moves, successful=0, failed=0, cancelled=True)
        
        successful = 0
        failed = 0
        
        # Step 4: Move files
        for i, cluster in enumerate(clusters):
            if cancel_flag and cancel_flag.is_set():
                if progress_callback:
                    progress_callback(successful, total_moves, "Organization cancelled")
                return MoveResult(
                    total=total_moves,
                    successful=successful,
                    failed=failed,
                    cancelled=True
                )
            
            # Create target folder
            try:
                os.makedirs(cluster.folder_name, exist_ok=True)
            except Exception as e:
                logger.error(f"Error creating folder {cluster.folder_name}: {e}")
                failed += len(cluster.files)
                continue
            
            # Move files in this cluster
            for file_path in cluster.files:
                if cancel_flag and cancel_flag.is_set():
                    if progress_callback:
                        progress_callback(successful, total_moves, "Organization cancelled")
                    return MoveResult(
                        total=total_moves,
                        successful=successful,
                        failed=failed,
                        cancelled=True
                    )
                
                try:
                    dest_path = os.path.join(
                        cluster.folder_name,
                        os.path.basename(file_path)
                    )
                    
                    # Handle collisions
                    if os.path.exists(dest_path):
                        base, ext = os.path.splitext(os.path.basename(file_path))
                        dest_path = os.path.join(
                            cluster.folder_name,
                            f"{base}_organized{ext}"
                        )
                    
                    shutil.move(file_path, dest_path)
                    successful += 1
                    
                    # Update progress
                    if progress_callback:
                        pct = 25 + int((successful / total_moves) * 65)
                        progress_callback(
                            pct,
                            100,
                            f"Moving files: {successful}/{total_moves}"
                        )
                
                except Exception as e:
                    logger.error(f"Error moving {file_path}: {e}")
                    failed += 1
                    continue
        
        # Step 5: Finalize
        if progress_callback:
            progress_callback(95, 100, "Finalizing...")
        
        if progress_callback:
            progress_callback(100, 100, "Organization complete!")
        
        return MoveResult(
            total=total_moves,
            successful=successful,
            failed=failed
        )
    
    except Exception as e:
        if progress_callback:
            progress_callback(0, 100, f"Error: {str(e)}")
        logger.error(f"Organization error: {e}")
        raise


# Add this method to FileOrganizerService class:
#
# def execute_organization(self, folder_path, auto_cluster=True,
#                         progress_callback=None, cancel_flag=None):
#     return execute_organization_with_progress(
#         self, folder_path, auto_cluster, progress_callback, cancel_flag
#     )
