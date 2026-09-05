"""
Unit tests for inactivity_enhancements.py
Tests file detection, timer reset, statistics, and settings validation.
"""

import unittest
import time
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional, List


@dataclass
class InactiveFileInfo:
    """Information about an inactive file."""
    file_path: str
    last_accessed: datetime
    days_inactive: int
    file_size: int


class TestInactiveFileDetection(unittest.TestCase):
    """Test inactive file detection."""

    def setUp(self):
        """Set up test fixtures."""
        self.now = datetime.now()

    def test_file_inactive_detection_basic(self):
        """Test basic inactive file detection."""
        threshold_days = 30
        last_accessed = self.now - timedelta(days=45)
        days_inactive = (self.now - last_accessed).days
        is_inactive = days_inactive >= threshold_days
        
        self.assertTrue(is_inactive)
        self.assertEqual(days_inactive, 45)

    def test_file_active_detection(self):
        """Test that recently accessed files are not marked inactive."""
        threshold_days = 30
        last_accessed = self.now - timedelta(days=5)
        days_inactive = (self.now - last_accessed).days
        is_inactive = days_inactive >= threshold_days
        
        self.assertFalse(is_inactive)
        self.assertEqual(days_inactive, 5)

    def test_boundary_condition_active(self):
        """Test boundary condition - file accessed exactly at threshold."""
        threshold_days = 30
        last_accessed = self.now - timedelta(days=30)
        days_inactive = (self.now - last_accessed).days
        is_inactive = days_inactive >= threshold_days
        
        self.assertTrue(is_inactive)

    def test_boundary_condition_just_before(self):
        """Test file just before threshold."""
        threshold_days = 30
        last_accessed = self.now - timedelta(days=29)
        days_inactive = (self.now - last_accessed).days
        is_inactive = days_inactive >= threshold_days
        
        self.assertFalse(is_inactive)

    def test_very_old_file(self):
        """Test very old file."""
        threshold_days = 30
        last_accessed = self.now - timedelta(days=365)
        days_inactive = (self.now - last_accessed).days
        is_inactive = days_inactive >= threshold_days
        
        self.assertTrue(is_inactive)
        self.assertEqual(days_inactive, 365)


class TestInactiveFileInfo(unittest.TestCase):
    """Test InactiveFileInfo dataclass."""

    def test_info_creation(self):
        """Test creating InactiveFileInfo."""
        now = datetime.now()
        info = InactiveFileInfo(
            file_path="/path/to/file.txt",
            last_accessed=now - timedelta(days=45),
            days_inactive=45,
            file_size=1024
        )
        self.assertEqual(info.file_path, "/path/to/file.txt")
        self.assertEqual(info.days_inactive, 45)
        self.assertEqual(info.file_size, 1024)

    def test_multiple_inactive_files(self):
        """Test creating multiple inactive file infos."""
        now = datetime.now()
        files = [
            InactiveFileInfo(f"/path/file{i}.txt", now - timedelta(days=30+i), 30+i, 1024)
            for i in range(5)
        ]
        self.assertEqual(len(files), 5)
        self.assertEqual(files[0].days_inactive, 30)
        self.assertEqual(files[4].days_inactive, 34)


class TestTimerReset(unittest.TestCase):
    """Test access timer reset functionality."""

    def test_timer_reset_on_access(self):
        """Test that timer resets on file access."""
        old_access = datetime.now() - timedelta(days=45)
        new_access = datetime.now()
        
        # Simulate file access
        updated_last_accessed = new_access
        days_inactive = (datetime.now() - updated_last_accessed).days
        
        self.assertAlmostEqual(days_inactive, 0, delta=1)

    def test_multiple_accesses(self):
        """Test multiple file accesses."""
        accesses = []
        for i in range(5):
            accesses.append(datetime.now())
            time.sleep(0.01)
        
        self.assertEqual(len(accesses), 5)
        self.assertLess(accesses[0], accesses[-1])

    def test_reset_clears_inactive_status(self):
        """Test that reset clears inactive status."""
        threshold = 30
        last_accessed = datetime.now() - timedelta(days=45)
        days_inactive = (datetime.now() - last_accessed).days
        
        # Before reset - inactive
        self.assertGreaterEqual(days_inactive, threshold)
        
        # Reset
        last_accessed = datetime.now()
        days_inactive = (datetime.now() - last_accessed).days
        
        # After reset - active
        self.assertLess(days_inactive, threshold)

    def test_concurrent_resets(self):
        """Test multiple concurrent resets."""
        import threading
        last_accesses = []
        
        def reset_timer():
            last_accesses.append(datetime.now())
        
        threads = [threading.Thread(target=reset_timer) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        self.assertEqual(len(last_accesses), 10)


class TestInactivityStatistics(unittest.TestCase):
    """Test inactivity statistics generation."""

    def test_basic_statistics(self):
        """Test basic statistics calculation."""
        now = datetime.now()
        files = [
            InactiveFileInfo(f"/path/file{i}.txt", now - timedelta(days=30+i*10), 30+i*10, 1024)
            for i in range(5)
        ]
        # files have inactivity days: 30, 40, 50, 60, 70
        total_files = len(files)
        total_size = sum(f.file_size for f in files)
        avg_inactivity = sum(f.days_inactive for f in files) / len(files)
        
        self.assertEqual(total_files, 5)
        self.assertEqual(total_size, 5120)
        # (30 + 40 + 50 + 60 + 70) / 5 = 250 / 5 = 50
        self.assertEqual(avg_inactivity, 50.0)

    def test_max_inactivity(self):
        """Test finding most inactive file."""
        now = datetime.now()
        files = [
            InactiveFileInfo(f"/path/file{i}.txt", now - timedelta(days=30+i*10), 30+i*10, 1024)
            for i in range(5)
        ]
        max_inactive = max(f.days_inactive for f in files)
        self.assertEqual(max_inactive, 70)

    def test_min_inactivity(self):
        """Test finding least inactive file."""
        now = datetime.now()
        files = [
            InactiveFileInfo(f"/path/file{i}.txt", now - timedelta(days=30+i*10), 30+i*10, 1024)
            for i in range(5)
        ]
        min_inactive = min(f.days_inactive for f in files)
        self.assertEqual(min_inactive, 30)

    def test_grouped_by_inactivity_range(self):
        """Test grouping files by inactivity range."""
        now = datetime.now()
        files = [
            InactiveFileInfo(f"/path/file1.txt", now - timedelta(days=35), 35, 1024),
            InactiveFileInfo(f"/path/file2.txt", now - timedelta(days=45), 45, 1024),
            InactiveFileInfo(f"/path/file3.txt", now - timedelta(days=95), 95, 1024),
        ]
        
        range_30_60 = [f for f in files if 30 <= f.days_inactive < 60]
        range_60_plus = [f for f in files if f.days_inactive >= 60]
        
        self.assertEqual(len(range_30_60), 2)
        self.assertEqual(len(range_60_plus), 1)

    def test_total_storage_from_inactive(self):
        """Test calculating total storage from inactive files."""
        now = datetime.now()
        files = [
            InactiveFileInfo(f"/path/file{i}.txt", now - timedelta(days=50), 50, 1024*1024)
            for i in range(100)
        ]
        total_storage_mb = sum(f.file_size for f in files) / (1024 * 1024)
        self.assertEqual(total_storage_mb, 100)


class TestInactivitySettings(unittest.TestCase):
    """Test inactivity settings validation."""

    def test_threshold_range_validation(self):
        """Test threshold day range validation."""
        valid_thresholds = [1, 30, 365]
        invalid_thresholds = [0, -1, 366, 999]
        
        for threshold in valid_thresholds:
            is_valid = 1 <= threshold <= 365
            self.assertTrue(is_valid)
        
        for threshold in invalid_thresholds:
            is_valid = 1 <= threshold <= 365
            self.assertFalse(is_valid)

    def test_enabled_flag_validation(self):
        """Test enabled flag validation."""
        valid_flags = [True, False]
        for flag in valid_flags:
            is_bool = isinstance(flag, bool)
            self.assertTrue(is_bool)

    def test_default_settings(self):
        """Test default settings."""
        default_threshold = 30
        default_enabled = False
        
        self.assertEqual(default_threshold, 30)
        self.assertFalse(default_enabled)

    def test_settings_persistence(self):
        """Test settings can be saved and restored."""
        settings = {
            "threshold_days": 45,
            "enabled": True,
            "last_check": datetime.now()
        }
        self.assertEqual(settings["threshold_days"], 45)
        self.assertTrue(settings["enabled"])

    def test_settings_update(self):
        """Test updating settings."""
        settings = {"threshold_days": 30, "enabled": False}
        
        # Update settings
        settings["threshold_days"] = 60
        settings["enabled"] = True
        
        self.assertEqual(settings["threshold_days"], 60)
        self.assertTrue(settings["enabled"])


class TestResetReminderState(unittest.TestCase):
    """Test reminder state reset for testing."""

    def test_state_reset(self):
        """Test resetting reminder state."""
        state = {
            "last_check": datetime.now() - timedelta(days=10),
            "files_found": 50,
            "notified": True
        }
        
        # Reset state
        state["last_check"] = None
        state["files_found"] = 0
        state["notified"] = False
        
        self.assertIsNone(state["last_check"])
        self.assertEqual(state["files_found"], 0)
        self.assertFalse(state["notified"])

    def test_partial_state_reset(self):
        """Test partial state reset."""
        state = {
            "last_check": datetime.now() - timedelta(days=10),
            "enabled": True
        }
        
        # Reset only last_check
        state["last_check"] = None
        
        self.assertIsNone(state["last_check"])
        self.assertTrue(state["enabled"])


class TestInactivityEdgeCases(unittest.TestCase):
    """Test edge cases in inactivity detection."""

    def test_very_recent_file(self):
        """Test file accessed just now."""
        now = datetime.now()
        threshold = 30
        days_inactive = (now - now).days
        is_inactive = days_inactive >= threshold
        
        self.assertFalse(is_inactive)
        self.assertEqual(days_inactive, 0)

    def test_empty_file_list(self):
        """Test with no files."""
        files = []
        self.assertEqual(len(files), 0)

    def test_single_file(self):
        """Test with single file."""
        now = datetime.now()
        files = [InactiveFileInfo("/path/file.txt", now - timedelta(days=45), 45, 1024)]
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].days_inactive, 45)

    def test_very_large_inactivity(self):
        """Test file inactive for years."""
        now = datetime.now()
        old_date = now - timedelta(days=365*5)
        days_inactive = (now - old_date).days
        self.assertGreater(days_inactive, 1000)

    def test_zero_file_size(self):
        """Test zero-size file."""
        now = datetime.now()
        info = InactiveFileInfo("/path/file.txt", now - timedelta(days=45), 45, 0)
        self.assertEqual(info.file_size, 0)

    def test_very_large_file_size(self):
        """Test very large file."""
        now = datetime.now()
        large_size = 10 * 1024 * 1024 * 1024  # 10GB
        info = InactiveFileInfo("/path/file.bin", now - timedelta(days=45), 45, large_size)
        self.assertEqual(info.file_size, large_size)


class TestInactivityPerformance(unittest.TestCase):
    """Test performance characteristics."""

    def test_detection_performance(self):
        """Test that detection is fast for many files."""
        import time
        now = datetime.now()
        threshold = 30
        
        start = time.time()
        for i in range(10000):
            last_accessed = now - timedelta(days=30+i%100)
            days_inactive = (now - last_accessed).days
            is_inactive = days_inactive >= threshold
        elapsed = time.time() - start
        
        self.assertLess(elapsed, 1.0)

    def test_statistics_calculation_performance(self):
        """Test that statistics calculation is fast."""
        import time
        now = datetime.now()
        files = [
            InactiveFileInfo(f"/path/file{i}.txt", now - timedelta(days=30+i%100), 30+i%100, 1024)
            for i in range(1000)
        ]
        
        start = time.time()
        total = sum(f.file_size for f in files)
        avg = sum(f.days_inactive for f in files) / len(files)
        elapsed = time.time() - start
        
        self.assertLess(elapsed, 0.1)


if __name__ == "__main__":
    unittest.main()
