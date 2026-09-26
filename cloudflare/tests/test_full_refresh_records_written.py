from __future__ import annotations

import sys
import unittest
from pathlib import Path

SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE_DIR))

from full_refresh import _records_written  # noqa: E402


class FullRefreshRecordsWrittenTest(unittest.TestCase):
    def test_counts_every_write_result(self) -> None:
        results = {
            "norges_bank": {"rows_written": 1},
            "life360": {"rows_written": 2},
            "b3": {"status": "ok"},
            "cvm": {"archived": 4},
            "bemobi_web": {"rows_written": 5},
            "newsweb": {
                "history": {"archived": 6},
                "buybacks": {"ingested": 7},
            },
            "newsweb_attachments": {"daily_rows_written": 8},
            "otello_reports": {"applied": 9},
            "otec_recovery": {"recovery_used": True, "status": "ok"},
        }
        nav = {"dirty_layers": ["CORE", "FULL"]}

        self.assertEqual(_records_written(results, nav), 46)

    def test_ignores_missing_values_and_unsuccessful_conditional_results(self) -> None:
        results = {
            "norges_bank": {"rows_written": None},
            "b3": {"status": "error"},
            "newsweb": {"history": None},
            "otec_recovery": {"recovery_used": True, "status": "error"},
        }

        self.assertEqual(_records_written(results, {}), 0)


if __name__ == "__main__":
    unittest.main()
