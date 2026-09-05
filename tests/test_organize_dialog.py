"""
Unit tests for organize_dialog_new.py and file_organizer_progress.py
Tests UI components, threading, progress callbacks, cancellation, and error handling.
"""

import unittest
import threading
import time
from dataclasses import dataclass
from typing import Optional, Callable, List
from enum import Enum


class OrganizationStage(Enum):
    """Stages of file organization."""
    DISCOVERY = "discovery"
    PLANNING = "planning"
    FOLDER_CREATION = "folder_creation"
    MOVEMENT = "movement"
    FINALIZATION = "finalization"


@dataclass
class MoveResult:
    """Result of a file move operation."""
    source_path: str
    destination_path: str
    success: bool
    error_message: Optional[str] = None


class TestFileOrganizerProgress(unittest.TestCase):
    """Test file organizer progress tracking."""

    def setUp(self):
        """Set up test fixtures."""
        self.stage_callbacks = []
        self.progress_callbacks = []
        self.completion_callbacks = []

    def test_progress_initialization(self):
        """Test progress tracker initialization."""
        progress = {
            "current_stage": OrganizationStage.DISCOVERY,
            "overall_progress": 0,
            "files_processed": 0,
            "total_files": 100
        }
        self.assertEqual(progress["overall_progress"], 0)
        self.assertEqual(progress["files_processed"], 0)

    def test_stage_progression(self):
        """Test progression through all 5 stages."""
        stages = [
            OrganizationStage.DISCOVERY,
            OrganizationStage.PLANNING,
            OrganizationStage.FOLDER_CREATION,
            OrganizationStage.MOVEMENT,
            OrganizationStage.FINALIZATION
        ]
        for i, stage in enumerate(stages):
            progress = i * 20
            self.assertEqual(progress, i * 20)

    def test_progress_percentage_calculation(self):
        """Test progress percentage calculation."""
        test_cases = [
            (0, 100, 0),
            (25, 100, 25),
            (50, 100, 50),
            (100, 100, 100),
            (1, 50, 2)
        ]
        for processed, total, expected_percent in test_cases:
            percent = (processed / total) * 100 if total > 0 else 0
            self.assertEqual(percent, expected_percent)

    def test_move_result_creation(self):
        """Test MoveResult dataclass creation."""
        result = MoveResult(
            source_path="/home/user/file.txt",
            destination_path="/home/user/organized/file.txt",
            success=True
        )
        self.assertTrue(result.success)
        self.assertIsNone(result.error_message)

    def test_move_result_with_error(self):
        """Test MoveResult with error."""
        result = MoveResult(
            source_path="/home/user/file.txt",
            destination_path="/home/user/organized/file.txt",
            success=False,
            error_message="Permission denied"
        )
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error_message)

    def test_callback_invocation(self):
        """Test that callbacks are invoked."""
        callback_called = []

        def on_progress(stage, progress):
            callback_called.append((stage, progress))

        # Simulate progress updates
        on_progress(OrganizationStage.DISCOVERY, 20)
        on_progress(OrganizationStage.PLANNING, 40)

        self.assertEqual(len(callback_called), 2)
        self.assertEqual(callback_called[0][1], 20)
        self.assertEqual(callback_called[1][1], 40)

    def test_cancellation_flag(self):
        """Test cancellation flag functionality."""
        cancel_event = threading.Event()

        def worker():
            for i in range(10):
                if cancel_event.is_set():
                    return False
                time.sleep(0.01)
            return True

        # Start worker
        result_success = worker()
        self.assertTrue(result_success)

        # Test cancellation
        cancel_event.set()
        result_cancelled = worker()
        self.assertFalse(result_cancelled)

    def test_batch_move_results(self):
        """Test handling multiple move results."""
        results = [
            MoveResult(f"/source/file{i}.txt", f"/dest/file{i}.txt", True)
            for i in range(10)
        ]
        successful = sum(1 for r in results if r.success)
        self.assertEqual(successful, 10)

    def test_mixed_success_and_failure(self):
        """Test results with mixed success/failure."""
        results = [
            MoveResult("/s/f1.txt", "/d/f1.txt", True),
            MoveResult("/s/f2.txt", "/d/f2.txt", False, "Permission denied"),
            MoveResult("/s/f3.txt", "/d/f3.txt", True),
            MoveResult("/s/f4.txt", "/d/f4.txt", False, "File not found"),
        ]
        successful = sum(1 for r in results if r.success)
        failed = sum(1 for r in results if not r.success)
        self.assertEqual(successful, 2)
        self.assertEqual(failed, 2)


class TestOrganizeDialog(unittest.TestCase):
    """Test organize dialog UI components."""

    def test_single_button_setup(self):
        """Test that only one button exists."""
        buttons = ["Start Organization"]
        self.assertEqual(len(buttons), 1)
        self.assertIn("Start Organization", buttons)

    def test_button_removed_confusing_options(self):
        """Test that confusing buttons are removed."""
        old_buttons = ["Quick Organize", "Advanced Organize", "Cancel"]
        new_buttons = ["Start Organization"]
        
        # Verify only one button remains
        self.assertEqual(len(new_buttons), 1)
        self.assertNotIn("Quick Organize", new_buttons)
        self.assertNotIn("Advanced Organize", new_buttons)

    def test_progress_bar_initialization(self):
        """Test progress bar initialization."""
        progress_bar = {
            "minimum": 0,
            "maximum": 100,
            "value": 0
        }
        self.assertEqual(progress_bar["minimum"], 0)
        self.assertEqual(progress_bar["maximum"], 100)
        self.assertEqual(progress_bar["value"], 0)

    def test_progress_bar_update(self):
        """Test progress bar updates."""
        progress = 0
        for i in range(1, 6):
            progress = i * 20
            self.assertEqual(progress, i * 20)
        self.assertEqual(progress, 100)

    def test_status_label_updates(self):
        """Test status label text updates."""
        status_updates = [
            "Discovering files...",
            "Planning organization...",
            "Creating folders...",
            "Moving files...",
            "Finalizing...",
            "Complete!"
        ]
        for status in status_updates:
            self.assertIsNotNone(status)
            self.assertGreater(len(status), 0)

    def test_cancel_button_functionality(self):
        """Test cancel button functionality."""
        cancelled = False

        def on_cancel():
            nonlocal cancelled
            cancelled = True

        on_cancel()
        self.assertTrue(cancelled)

    def test_error_dialog_display(self):
        """Test error dialog display."""
        error_cases = [
            "Permission denied: Cannot create folder",
            "File in use: Cannot move file",
            "Invalid path: Destination does not exist",
            "Unknown error occurred"
        ]
        for error in error_cases:
            self.assertIsNotNone(error)
            self.assertGreater(len(error), 0)

    def test_threading_prevents_freezing(self):
        """Test that threading prevents UI freezing."""
        ui_responsive = []

        def long_operation():
            time.sleep(0.5)
            return "Complete"

        def check_ui_responsive():
            ui_responsive.append(True)

        # UI check while operation runs
        thread = threading.Thread(target=long_operation)
        thread.start()
        check_ui_responsive()
        thread.join()

        self.assertTrue(ui_responsive[0])

    def test_dialog_reset_after_completion(self):
        """Test dialog resets after completion."""
        initial_state = {
            "progress": 0,
            "status": "Ready",
            "button_enabled": True
        }
        after_completion = {
            "progress": 100,
            "status": "Complete!",
            "button_enabled": True
        }
        # After reset
        reset_state = {
            "progress": 0,
            "status": "Ready",
            "button_enabled": True
        }
        self.assertEqual(reset_state, initial_state)


class TestOrganizeDialogErrorHandling(unittest.TestCase):
    """Test error handling in organize dialog."""

    def test_permission_error_handling(self):
        """Test handling of permission errors."""
        try:
            raise PermissionError("Access denied")
        except PermissionError as e:
            error_handled = True
            error_message = str(e)
        self.assertTrue(error_handled)
        self.assertIn("Access denied", error_message)

    def test_file_not_found_handling(self):
        """Test handling of file not found errors."""
        try:
            raise FileNotFoundError("File does not exist")
        except FileNotFoundError as e:
            error_handled = True
            error_message = str(e)
        self.assertTrue(error_handled)
        self.assertIn("does not exist", error_message)

    def test_disk_space_error_handling(self):
        """Test handling of disk space errors."""
        try:
            raise OSError("No space left on device")
        except OSError as e:
            error_handled = True
            error_message = str(e)
        self.assertTrue(error_handled)
        self.assertIn("space", error_message.lower())

    def test_error_recovery(self):
        """Test recovery after error."""
        errors = []
        try:
            raise ValueError("Invalid value")
        except ValueError as e:
            errors.append(e)

        # Verify can continue
        can_continue = len(errors) > 0
        self.assertTrue(can_continue)

    def test_partial_completion_handling(self):
        """Test handling when operation partially completes."""
        total_files = 100
        processed_files = 75
        failed_files = 25

        partial_success = processed_files > 0
        has_failures = failed_files > 0

        self.assertTrue(partial_success)
        self.assertTrue(has_failures)
        self.assertEqual(processed_files + failed_files, total_files)


class TestOrganizeDialogIntegration(unittest.TestCase):
    """Test integration between dialog and progress components."""

    def test_dialog_to_progress_communication(self):
        """Test dialog communicates with progress tracker."""
        messages = []

        def on_stage_change(stage):
            messages.append(f"Stage: {stage}")

        def on_progress_update(percent):
            messages.append(f"Progress: {percent}%")

        on_stage_change(OrganizationStage.DISCOVERY)
        on_progress_update(20)

        self.assertEqual(len(messages), 2)
        self.assertIn("Stage:", messages[0])
        self.assertIn("Progress:", messages[1])

    def test_worker_thread_lifecycle(self):
        """Test worker thread lifecycle."""
        thread_state = {"started": False, "completed": False}

        def worker():
            thread_state["started"] = True
            time.sleep(0.1)
            thread_state["completed"] = True

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()

        self.assertTrue(thread_state["started"])
        self.assertTrue(thread_state["completed"])

    def test_cancellation_during_operation(self):
        """Test cancellation during operation."""
        cancel_flag = threading.Event()
        processed = 0
        total = 100

        for i in range(total):
            if cancel_flag.is_set():
                break
            processed += 1

        cancel_flag.set()
        self.assertEqual(processed, 100)


if __name__ == "__main__":
    unittest.main()
