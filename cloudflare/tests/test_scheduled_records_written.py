from __future__ import annotations

import sys
import unittest
from pathlib import Path

SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_DIR))

from scheduled import _fast_refresh_records_written  # noqa: E402


class FastRefreshRecordsWrittenTest(unittest.TestCase):
    def test_counts_each_successful_write_result(self) -> None:
        steps = {
            "otec_delayed": {"found": True},
            "otec_eod": {"status": "ok"},
            "otec_activity": {"written": 2},
            "bmob3_eod": {"status": "ok"},
            "bmob3_delayed": {"status": "ok"},
            "newsweb_history": {"archived": 3},
            "newsweb_buybacks": {"ingested": 4},
            "otello_reports": {"applied": 5},
            "otello_interest": {"written": 6},
            "norges_bank_fx_repair": {"repaired": True, "rows_written": 7},
            "life360_lif_repair": {"rows_written": 8},
            "bemobi_distribution_cash": {
                "rows_written": 9,
                "rows_updated": 10,
            },
            "dirty_nav": {"dirty_layers": ["CORE", "FULL"]},
        }

        self.assertEqual(_fast_refresh_records_written(steps), 60)

    def test_ignores_results_that_do_not_represent_a_write(self) -> None:
        steps = {
            "otec_delayed": {"found": False},
            "otec_eod": {"status": "skipped"},
            "bmob3_eod": {"status": "error"},
            "bmob3_delayed": {"status": "skipped"},
            "norges_bank_fx_repair": {"repaired": False, "rows_written": 7},
            "dashboard_hot_snapshot": {"status": "ok", "rows_written": 20},
        }

        self.assertEqual(_fast_refresh_records_written(steps), 0)


if __name__ == "__main__":
    unittest.main()
