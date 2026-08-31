from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import cloudflare_hubspot_order_attribution as attribution
import easystore_hubspot_schema as schema


class CCAttributionSchemaContractTests(unittest.TestCase):
    def test_order_source_never_reuses_hs_source_store(self) -> None:
        source_field = next(field for field in attribution.FIELDS if field.key == "source")
        created: list[dict[str, object]] = []

        def http_json(
            url: str,
            *,
            method: str = "GET",
            payload: dict[str, object] | None = None,
            **_: object,
        ) -> object:
            if method == "GET" and url.endswith("/crm/v3/properties/order"):
                return {
                    "results": [
                        {
                            "name": "hs_source_store",
                            "label": "Source store",
                            "type": "string",
                            "hubspotDefined": True,
                        }
                    ]
                }
            if method == "GET" and "/groups/" in url:
                return {"name": attribution.PROPERTY_GROUP}
            if method == "POST" and url.endswith("/crm/v3/properties/order"):
                assert payload is not None
                created.append(payload)
                return payload
            self.fail(f"unexpected HubSpot schema request: {method} {url}")

        report: dict[str, object] = {}
        resolved = schema.resolve_fields(
            http_json=http_json,
            access_token="token",
            object_type=attribution.ORDER_OBJECT_TYPE,
            fields=(source_field,),
            error=RuntimeError,
            report=report,
            group=attribution.PROPERTY_GROUP,
            group_label=attribution.PROPERTY_GROUP_LABEL,
        )

        self.assertEqual(resolved, {"source": "cc_order_source"})
        self.assertNotIn("hs_source_store", resolved.values())
        self.assertEqual(report["semantic_native"], {})
        self.assertEqual([item["name"] for item in created], ["cc_order_source"])


if __name__ == "__main__":
    unittest.main()
