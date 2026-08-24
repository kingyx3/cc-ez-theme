from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import easystore_hubspot_schema as schema


class CustomerPaginationBoundaryTests(unittest.TestCase):
    def test_repeated_full_customer_page_is_terminal_not_fatal(self) -> None:
        # Exactly 50 customers fills page 1; EasyStore then repeats it for page 2.
        records = [{"id": str(index)} for index in range(1, 51)]
        calls: list[int] = []

        def fetch(page: int) -> list[dict[str, str]]:
            calls.append(page)
            return records

        with self.assertWarnsRegex(
            RuntimeWarning,
            r"customers\.json repeated page 2",
        ):
            actual = list(
                schema.iter_easystore_pages(
                    fetch,
                    page_size=50,
                    what="customers.json",
                    error=RuntimeError,
                )
            )

        self.assertEqual(actual, records)
        self.assertEqual(calls, [1, 2])

    def test_repeated_non_customer_page_still_fails_closed(self) -> None:
        records = [{"id": str(index)} for index in range(1, 51)]

        def fetch(_page: int) -> list[dict[str, str]]:
            return records

        with self.assertRaisesRegex(RuntimeError, "page parameter does nothing"):
            list(
                schema.iter_easystore_pages(
                    fetch,
                    page_size=50,
                    what="orders.json",
                    error=RuntimeError,
                )
            )


if __name__ == "__main__":
    unittest.main()
