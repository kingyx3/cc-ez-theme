import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "sync_easystore_customers_to_hubspot.py"
SPEC = importlib.util.spec_from_file_location("customer_sync", SCRIPT)
assert SPEC and SPEC.loader
customer_sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(customer_sync)


def test_customer_list_accepts_supported_shapes():
    assert customer_sync.customer_list([{"email": "a@example.com"}]) == [
        {"email": "a@example.com"}
    ]
    assert customer_sync.customer_list({"customers": [{"email": "b@example.com"}]}) == [
        {"email": "b@example.com"}
    ]
    assert customer_sync.customer_list({"data": [{"email": "c@example.com"}]}) == [
        {"email": "c@example.com"}
    ]


def test_hubspot_mapping_uses_email_identifier():
    result = customer_sync.to_hubspot_input(
        {
            "email": " Person@Example.com ",
            "first_name": "Ada",
            "last_name": "Lovelace",
            "phone": "+65 1234 5678",
        }
    )
    assert result == {
        "id": "person@example.com",
        "idProperty": "email",
        "properties": {
            "email": "person@example.com",
            "firstname": "Ada",
            "lastname": "Lovelace",
            "phone": "+65 1234 5678",
        },
    }


def test_customer_without_email_is_skipped():
    assert customer_sync.to_hubspot_input({"first_name": "No Email"}) is None


def test_csv_export_headers_are_normalized(tmp_path):
    csv_file = tmp_path / "customers.csv"
    csv_file.write_text(
        "Email Address,First Name,Last Name,Mobile\nAda@Example.com,Ada,Lovelace,1234\n",
        encoding="utf-8",
    )
    assert customer_sync.get_csv_customers(csv_file) == [
        {
            "email": "Ada@Example.com",
            "first_name": "Ada",
            "last_name": "Lovelace",
            "phone": "1234",
        }
    ]


def test_dry_run_does_not_require_network():
    synced, skipped = customer_sync.sync_to_hubspot(
        [{"email": "a@example.com"}, {"first_name": "Missing"}],
        "unused-token",
        dry_run=True,
    )
    assert (synced, skipped) == (1, 1)
