from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import easystore_hubspot_products as products


class EasyStoreProductVisibilityPaginationRepeatTests(unittest.TestCase):
    """products.json has started repeating pages like checkouts.json and orders.json.

    These pin the recovery path added alongside that failure: a repeated page
    under the normal limit is not immediately fatal if one larger-limit
    request can prove the visibility bucket complete, and it still fails
    loudly when even that larger request cannot prove completeness.
    """

    def test_repeated_page_recovers_via_larger_limit_when_it_proves_complete(self) -> None:
        page_one = [{"id": str(index)} for index in range(1, products.EASYSTORE_PAGE_SIZE + 1)]
        # A larger single request answers with the whole bucket, including
        # records a 50-per-page fetch never reached before it started
        # repeating page 1.
        large_limit_answer = page_one + [{"id": "extra-1"}, {"id": "extra-2"}]
        large_limit_calls: list[str] = []

        def fake_http(url: str, **kwargs):
            query = parse_qs(urlparse(url).query)
            self.assertEqual(query["visibility"][0], "unpublished")
            limit = int(query["limit"][0])
            page = int(query["page"][0])
            if limit == products.EASYSTORE_PAGE_SIZE:
                # Every page comes back identical: the page parameter does
                # nothing, exactly like checkouts.json and orders.json.
                return {"products": page_one}
            large_limit_calls.append(f"page={page}&limit={limit}")
            self.assertEqual(page, 1)
            self.assertEqual(limit, products._LARGE_PRODUCT_PAGE_LIMIT)
            return {"products": large_limit_answer}

        stderr = io.StringIO()
        with patch.object(products, "_http_json", side_effect=fake_http):
            with redirect_stderr(stderr):
                found = list(
                    products._fetch_product_visibility_bucket(
                        "shop.easy.co",
                        "easy-token",
                        "unpublished",
                    )
                )

        self.assertEqual(len(large_limit_calls), 1)
        self.assertEqual(
            [product["id"] for product in found],
            [str(index) for index in range(1, products.EASYSTORE_PAGE_SIZE + 1)]
            + ["extra-1", "extra-2"],
        )
        self.assertIn("recovered the complete bucket", stderr.getvalue())

    def test_repeated_page_still_fails_when_larger_limit_is_also_saturated(self) -> None:
        page_one = [{"id": str(index)} for index in range(1, products.EASYSTORE_PAGE_SIZE + 1)]
        saturated_large_answer = [
            {"id": str(index)}
            for index in range(1, products._LARGE_PRODUCT_PAGE_LIMIT + 1)
        ]

        def fake_http(url: str, **kwargs):
            query = parse_qs(urlparse(url).query)
            limit = int(query["limit"][0])
            if limit == products.EASYSTORE_PAGE_SIZE:
                return {"products": page_one}
            return {"products": saturated_large_answer}

        with patch.object(products, "_http_json", side_effect=fake_http):
            with self.assertRaisesRegex(
                products.SyncError,
                "cannot be proven",
            ):
                list(
                    products._fetch_product_visibility_bucket(
                        "shop.easy.co",
                        "easy-token",
                        "unpublished",
                    )
                )

    def test_recovered_bucket_still_flows_through_iter_easystore_products(self) -> None:
        # iter_easystore_products loops both visibility buckets; confirm the
        # recovery path for one bucket doesn't break the published-flag
        # backfill applied to whatever it yields.
        published_page = [{"id": "1"}]
        unpublished_page_one = [
            {"id": str(index)} for index in range(1, products.EASYSTORE_PAGE_SIZE + 1)
        ]
        unpublished_recovered = unpublished_page_one + [{"id": "extra-1"}]

        def fake_http(url: str, **kwargs):
            query = parse_qs(urlparse(url).query)
            visibility = query["visibility"][0]
            limit = int(query["limit"][0])
            if visibility == "published":
                return {"products": published_page if limit == products.EASYSTORE_PAGE_SIZE else []}
            if limit == products.EASYSTORE_PAGE_SIZE:
                return {"products": unpublished_page_one}
            return {"products": unpublished_recovered}

        with patch.object(products, "_http_json", side_effect=fake_http):
            with redirect_stderr(io.StringIO()):
                found = list(products.iter_easystore_products("shop.easy.co", "easy-token"))

        self.assertEqual(len(found), len(published_page) + len(unpublished_recovered))
        self.assertTrue(all("published" in p for p in found))


if __name__ == "__main__":
    unittest.main()
