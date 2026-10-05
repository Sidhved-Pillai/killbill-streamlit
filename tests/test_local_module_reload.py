"""Protect imports added during Streamlit Cloud hot reloads."""

from pathlib import Path


def test_freight_module_is_reloaded_before_new_api_import():
    source = (Path(__file__).parents[1] / "app.py").read_text()
    reload_position = source.index("importlib.reload(freight_master)")
    api_import_position = source.index("from freight_master import (")
    reference_import_position = source.index(
        "from invoice_reference import apply_invoice_billing_reference"
    )

    assert reload_position < api_import_position < reference_import_position
