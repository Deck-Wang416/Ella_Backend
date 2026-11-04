import unittest
from datetime import date
from unittest.mock import patch

from app.services.daily_content_service import DailyContentService


class WeeklyProgressTests(unittest.TestCase):
    def setUp(self):
        self.service = object.__new__(DailyContentService)
        self.day = date(2026, 11, 4)
        self.week_start = date(2026, 11, 1)
        self.week_end = date(2026, 11, 7)

    def test_parent_progress_uses_unrounded_minutes(self):
        for seconds in (0, 1, 59, 60, 119, 5399, 5400):
            with self.subTest(seconds=seconds):
                with patch.object(
                    self.service, "_resolve_condition_week_range", return_value=(self.week_start, self.week_end)
                ), patch.object(self.service, "_sum_parent_recording_seconds", return_value=seconds):
                    progress = self.service.get_weekly_progress(1, self.day, "parent")

                self.assertEqual(progress.currentValue, seconds / 60)
                self.assertEqual(progress.targetValue, 90)
                self.assertEqual(progress.unit, "min")
                self.assertEqual(progress.currentValue >= progress.targetValue, seconds >= 5400)

    def test_robot_progress_is_unchanged(self):
        class StoryProgress:
            def get_week_total_for_date(self, caregiver_id, target_date):
                return 3

        self.service.robot_story_progress_service = StoryProgress()
        with patch.object(
            self.service, "_resolve_condition_week_range", return_value=(self.week_start, self.week_end)
        ):
            progress = self.service.get_weekly_progress(1, self.day, "robot")

        self.assertEqual((progress.currentValue, progress.targetValue, progress.unit), (3, 15, "stories"))


if __name__ == "__main__":
    unittest.main()
