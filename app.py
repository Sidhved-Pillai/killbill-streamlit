import io
import html
import importlib
import json
import os
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

import pandas as pd
import pypdf
import streamlit as st
from google import genai
from google.genai import types
from PIL import Image, ImageOps

from customer_master import (
    apply_customer_master_lookup,
    build_customer_lookup,
    load_customer_master,
)
from excel_export import build_excel_workbook, excel_export_filename

# Streamlit Cloud can hot-reload this entrypoint while retaining the previous
# local module in the worker. Refresh it before importing newly added APIs.
import freight_master

importlib.reload(freight_master)

from freight_master import (
    apply_freight_lookup,
    apply_freight_rate_revision,
    apply_freight_rate_revision_to_dataframe,
    build_freight_lookup,
    normalize_loading_point,
    short_origin,
)
from invoice_reference import apply_invoice_billing_reference

# Streamlit Cloud can hot-reload this entrypoint while retaining an older
# imported module in the worker process. Reload the local history module before
# importing its API so app.py and invoice_history.py cannot get out of sync.
import invoice_history

importlib.reload(invoice_history)

from invoice_history import (
    get_processed_invoice,
    init_invoice_history_database,
    log_gemini_usage,
    search_processed_invoices,
    store_new_invoice_records,
    store_processed_invoice,
    store_processed_uploads,
    upload_digest,
)
from billing_statement import (
    SUMMARY_COLUMNS,
    billing_statement_filename,
    build_billing_statement,
    build_billing_statement_workbook,
)

try:
    streamlit_api_key = st.secrets.get("GOOGLE_API_KEY", "")
except st.errors.StreamlitSecretNotFoundError:
    streamlit_api_key = ""

API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GENAI_API_KEY") or streamlit_api_key
MODEL_FALLBACKS = [
    "gemini-3.8-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
]
MAX_RETRIES = 1
INITIAL_BACKOFF_SECONDS = 4
GEMINI_TOTAL_TIMEOUT_SECONDS = 60
DATABASE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "billing_history.db")
PROCESSING_STATE_KEY = "invoice_processing_batch"
INVOICE_SCAN_WORKERS = 2

PREMIUM_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

    html, body, [data-testid="stAppViewContainer"] {
        background-color: #F8F9FA;
        color: #111111;
        font-family: 'Inter', 'Helvetica Neue', sans-serif;
    }

    [data-testid="stSidebar"],
    [data-testid="collapsedControl"] {
        display: none !important;
    }

    /* Hide Streamlit's toolbar and hosted viewer badge. */
    [data-testid="stHeader"],
    [data-testid="stDecoration"],
    [data-testid="stToolbar"],
    [data-testid="stAppDeployButton"],
    [data-testid="stStatusWidget"],
    #MainMenu,
    [data-testid="stAppViewerBadge"],
    [class*="StatusWidget"],
    [class*="viewerBadge_container"],
    [class*="viewerBadge_link"],
    [data-testid="stAppViewContainer"] > footer {
        display: none !important;
    }

    .main .block-container {
        max-width: 1180px;
        padding-top: 2rem;
        padding-bottom: 2rem;
    }

    .premium-title-wrap {
        margin: 0 auto 1.2rem;
        text-align: center;
    }

    .title-kicker {
        font-size: 0.78rem;
        font-weight: 700;
        letter-spacing: 0.18em;
        color: #D32F2F;
        text-transform: uppercase;
        margin-bottom: 0.35rem;
    }

    .premium-title {
        margin: 0;
        font-size: 3rem;
        line-height: 1.05;
        font-weight: 800;
        color: #111111;
        letter-spacing: -0.03em;
    }

    .premium-title span {
        color: #D32F2F;
    }

    .landing-hero { max-width: 760px; margin: .75rem auto 1.5rem; text-align: center; }
    .invoice-illustration { position: relative; width: 280px; height: 180px; margin: 0 auto .75rem; border-radius: 50%; background: radial-gradient(circle, rgba(211,47,47,.12), rgba(211,47,47,0) 68%); }
    .invoice-sheet { position: absolute; bottom: 5px; left: 50%; width: 120px; height: 145px; padding-top: 25px; transform: translateX(-50%); background: linear-gradient(#fff, #fafafa); border: 3px solid #e5e7eb; border-radius: 15px; box-shadow: 0 14px 30px rgba(17,17,17,.10); color: #00866a; font-size: 1.3rem; font-style: italic; font-weight: 800; z-index: 2; }
    .invoice-sheet::after { content: ''; display: block; width: 75%; height: 56px; margin: 18px auto 0; background: repeating-linear-gradient(to bottom, #d9dde5 0 6px, transparent 6px 14px); }
    .invoice-sheet.left, .invoice-sheet.right { bottom: 4px; height: 125px; opacity: .72; z-index: 1; }
    .invoice-sheet.left { transform: translateX(-112%) rotate(-12deg); }
    .invoice-sheet.right { transform: translateX(12%) rotate(12deg); }
    .landing-hero h2 { margin: 0; color: #0c111b; font-size: clamp(2.2rem, 5vw, 3.4rem); line-height: 1.08; letter-spacing: -.04em; }
    .landing-hero p { margin: .8rem auto 0; color: #596170; font-size: 1.08rem; line-height: 1.55; }
    .upload-heading { margin: 1rem 0 .4rem; color: #111; font-size: 1.45rem; font-weight: 800; text-align: center; }
    .upload-support { margin: .6rem 0 1.1rem; color: #6b7280; font-size: .86rem; text-align: center; }

    .onboarding-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 1rem;
        margin: 1.4rem 0 1.8rem;
    }

    .onboarding-card {
        background: #FFFFFF;
        border: 1px solid rgba(17, 17, 17, 0.08);
        border-radius: 18px;
        padding: 1rem 1.05rem;
        box-shadow: 0 10px 28px rgba(17, 17, 17, 0.08);
    }

    .onboarding-step {
        display: inline-block;
        margin-bottom: 0.65rem;
        padding: 0.28rem 0.55rem;
        border-radius: 999px;
        background: rgba(211, 47, 47, 0.1);
        color: #D32F2F;
        font-size: 0.82rem;
        font-weight: 700;
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }

    .onboarding-card h4 {
        margin: 0 0 0.4rem 0;
        color: #111111;
        font-size: 1.05rem;
        font-weight: 700;
    }

    .onboarding-card p {
        margin: 0;
        color: #111111;
        font-size: 0.95rem;
        line-height: 1.55;
    }

    [data-testid="stFileUploader"] section {
        max-width: 700px;
        margin: 0 auto;
        background: #FFFFFF;
        border: 1px solid rgba(17, 17, 17, 0.12);
        border-radius: 16px;
        box-shadow: 0 8px 24px rgba(17, 17, 17, 0.08);
        transition: border-color 180ms ease, box-shadow 180ms ease, transform 180ms ease;
    }

    [data-testid="stFileUploader"] section:hover {
        border-color: #D32F2F;
        box-shadow: 0 12px 30px rgba(211, 47, 47, 0.14);
        transform: translateY(-1px);
    }

    [data-testid="stFileUploader"] button,
    [data-testid="stBaseButton-secondary"] button,
    div[data-testid="stButton"] > button,
    button[kind="primary"] {
        background: #D32F2F !important;
        color: #FFFFFF !important;
        border: 1px solid #D32F2F !important;
        border-radius: 12px;
        font-weight: 700;
        letter-spacing: 0.01em;
        padding: 0.75rem 1.15rem;
        box-shadow: 0 10px 24px rgba(211, 47, 47, 0.18);
        transition: all 180ms ease;
    }

    [data-testid="stFileUploader"] button:hover,
    [data-testid="stBaseButton-secondary"] button:hover,
    div[data-testid="stButton"] > button:hover,
    button[kind="primary"]:hover {
        background: #B71C1C !important;
        border-color: #B71C1C !important;
        box-shadow: 0 14px 30px rgba(183, 28, 28, 0.3);
        transform: translateY(-1px);
    }

    [data-testid="stFileUploader"] div[data-testid="stFileUploaderFileLink"] {
        color: #111111 !important;
        background: #FFFFFF !important;
        border: 1px solid rgba(17, 17, 17, 0.12);
        border-radius: 10px;
        padding: 0.25rem 0.5rem;
    }

    [data-testid="stFileUploader"] div[data-testid="stFileUploaderFileLink"] span,
    [data-testid="stFileUploader"] div[data-testid="stFileUploaderFileLink"] p,
    [data-testid="stFileUploader"] div[data-testid="stFileUploaderFileLink"] * {
        color: #111111 !important;
    }

    [data-testid="stFileUploader"] [data-testid="stWidgetLabel"],
    [data-testid="stFileUploader"] .st-emotion-cache-1h9usn1,
    [data-testid="stFileUploader"] .st-emotion-cache-17rjhe1,
    [data-testid="stFileUploader"] .st-emotion-cache-1xsdgfe,
    [data-testid="stFileUploader"] .st-emotion-cache-1v0mbdj,
    [data-testid="stFileUploader"] .st-emotion-cache-1ya1qef,
    [data-testid="stFileUploader"] p,
    [data-testid="stFileUploader"] span,
    [data-testid="stFileUploader"] div {
        color: #111111 !important;
    }

    [data-testid="stFileUploader"] button,
    [data-testid="stFileUploader"] button * {
        color: #FFFFFF !important;
    }

    [data-testid="stDataFrame"],
    [data-testid="stDataEditor"] {
        border: 1px solid rgba(17, 17, 17, 0.10);
        border-radius: 16px;
        overflow: hidden;
        box-shadow: 0 10px 28px rgba(17, 17, 17, 0.08);
        background: #FFFFFF;
    }

    [data-testid="stDataFrame"] > div,
    [data-testid="stDataEditor"] > div {
        border-radius: 16px;
    }

    [data-testid="stDataFrame"] table,
    [data-testid="stDataEditor"] table,
    [data-testid="stDataFrame"] th,
    [data-testid="stDataEditor"] th,
    [data-testid="stDataFrame"] td,
    [data-testid="stDataEditor"] td {
        background: #f7f8fa !important;
        color: #111111 !important;
        border-color: rgba(17, 17, 17, 0.08) !important;
    }

    [data-testid="stDataFrame"] th {
        background: #e8eaed !important;
        color: #111111 !important;
    }

    [data-testid="stDataFrame"] tr:nth-child(odd) td,
    [data-testid="stDataEditor"] tr:nth-child(odd) td {
        background: #f7f8fa !important;
    }

    [data-testid="stDataFrame"] tr:nth-child(even) td,
    [data-testid="stDataEditor"] tr:nth-child(even) td {
        background: #ffffff !important;
    }

    div[data-testid="stDownloadButton"] > button,
    [data-testid="stDownloadButton"] button {
        background: #2E7D32 !important;
        color: #FFFFFF !important;
        border: 1px solid #2E7D32 !important;
        border-radius: 8px !important;
    }

    div[data-testid="stDownloadButton"] > button *,
    [data-testid="stDownloadButton"] button * {
        color: #FFFFFF !important;
    }

    .section-label {
        margin: 0.9rem 0 0.5rem;
        color: #111111;
        font-size: 1.08rem;
        font-weight: 700;
        letter-spacing: 0.01em;
    }

    .upload-status {
        margin: 0 0 1.35rem 0;
        padding: 0.85rem 1rem;
        background: #1B5E20;
        border: 1px solid #2E7D32;
        border-left: 4px solid #2E7D32;
        border-radius: 12px;
        color: #FFFFFF;
        font-weight: 700;
        box-shadow: 0 8px 22px rgba(17, 17, 17, 0.08);
    }

    div[data-testid="stNotification"] {
        background: #1B5E20;
        border: 1px solid #2E7D32;
        border-left: 4px solid #2E7D32;
        border-radius: 12px;
        box-shadow: 0 8px 22px rgba(17, 17, 17, 0.08);
    }

    div[data-testid="stNotification"] * {
        color: #FFFFFF !important;
    }

    div[data-testid="stDialog"] button[kind="tertiary"] {
        background: transparent !important;
        color: #D32F2F !important;
        border: 0 !important;
        box-shadow: none !important;
        padding: 0.25rem 0 !important;
        white-space: nowrap;
    }

    div[data-testid="stDialog"] button[kind="tertiary"]:hover {
        background: transparent !important;
        color: #B71C1C !important;
        border: 0 !important;
        box-shadow: none !important;
        transform: none;
        text-decoration: underline;
    }

    .scan-panel {
        margin: 1rem 0;
        padding: 1.4rem;
        background: #FFFFFF;
        border: 1px solid rgba(17, 17, 17, 0.09);
        border-radius: 20px;
        box-shadow: 0 12px 32px rgba(17, 17, 17, 0.08);
    }

    .scan-heading {
        margin: 0;
        color: #111111;
        font-size: 1.75rem;
        font-weight: 800;
        text-align: center;
    }

    .scan-subtitle {
        margin: 0.35rem 0 1rem;
        color: #596170;
        text-align: center;
    }

    .current-file-card, .processing-error-card, .duplicate-card {
        margin: 0.9rem 0;
        padding: 1rem 1.1rem;
        border-radius: 14px;
        background: #FFF5F5;
        border: 1px solid rgba(211, 47, 47, 0.18);
    }

    .current-file-card strong, .processing-error-card strong {
        color: #B71C1C;
    }

    .duplicate-card {
        background: #FFF9E8;
        border-color: rgba(245, 158, 11, 0.28);
    }

    .processing-stats {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 0.8rem;
        margin: 1rem 0;
    }

    .processing-stat {
        padding: 1rem;
        background: #FFFFFF;
        border: 1px solid rgba(17, 17, 17, 0.08);
        border-radius: 16px;
        text-align: center;
    }

    .processing-stat span {
        display: block;
        color: #596170;
        font-size: 0.85rem;
    }

    .processing-stat strong {
        display: block;
        margin-top: 0.2rem;
        color: #111111;
        font-size: 1.75rem;
    }

    .progress-summary {
        display: grid;
        grid-template-columns: 1fr auto 1fr;
        align-items: center;
        gap: 1rem;
        margin: 1rem 0 .45rem;
        color: #111111;
        font-weight: 800;
    }

    .progress-summary .progress-percent { text-align: right; }
    .eta-pill {
        padding: .5rem .9rem;
        border-radius: 999px;
        background: #f0f1f5;
        color: #111827;
        font-size: .92rem;
        white-space: nowrap;
    }

    .eta-clock { margin-right: .4rem; font-size: 1.05rem; }

    @media (max-width: 760px) {
        .processing-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .progress-summary { grid-template-columns: 1fr auto; }
        .eta-pill { grid-column: 1 / -1; grid-row: 2; text-align: center; }
        .premium-title { font-size: 2.35rem; }
        .invoice-illustration { transform: scale(.86); margin-bottom: 0; }
    }
</style>
"""

COLUMNS = [
    "Date",
    "Invoice No.",
    "Vehicle No.",
    "From",
    "Customer Code",
    "Customer Name",
    "To",
    "Vehicle Type",
    "Case",
    "Jar",
    "Freight Charge",
    "Lookup Status",
]

MIME_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "pdf": "application/pdf",
}

SYSTEM_INSTRUCTION = """
Read this single Bisleri logistics invoice only. Perform targeted extraction for the
spreadsheet fields below. Ignore prices, taxes, totals, GST calculations, signatures,
terms, bank details, and all other invoice content.

Return ONLY a single valid JSON list of objects. Each object represents one invoice trip row and must contain exactly these keys:
- "Date" (format: DD-MMM-YY, e.g. 25-May-26)
- "Invoice No."
- "Vehicle No."
- "From"
- "Loading Point"
- "Customer Code"
- "Customer Name"
- "To"
- "Vehicle Type"
- "Case"
- "Jar"
- "items" (an array of product-line objects)

Rules:
- Return one object for each invoice visible in the supplied file. Normally there is exactly one.
- Extract the "Shipped To" section in this exact order: Customer Code, Customer Name, address lines, then administrative fields.
- "Loading Point": extract the invoice origin from the "Shipped From" section only. Normalize it to exactly one of Thane, Vasai, Andheri, Vidya Vihar, Bhiwandi, Kandivali, PRPL, Wada, Mahul, Khopoli, Kamshet, or Ambernath. Use null when it cannot be determined.
- "Customer Code": extract only the value after "Customer Code :" (or "Customer Code:") in the "Shipped To" section. Do not use any other identifier.
- "Customer Name": extract ONLY the first text line immediately after Customer Code. It must be exactly one business/company name and must not contain any address text.
- "To": begin immediately AFTER the Customer Name. Concatenate every subsequent physical-address line, in order, into one value. Stop before the first administrative field: State Code, GSTIN, PAN, Phone, Email, FSSAI, Payment Terms, or any tax identifier.
- "To" must contain delivery-address text only. Never include Customer Name, Customer Code, GSTIN, or any administrative field or value.
- Example: for "Customer Code : MUMCO02703" followed by "SANTKRIPA DUGDHALAYA(KALYAN-E)", then "GODAVARI BLDG SHOP NO 4 LOKGRAM", "KALYAN CITY NETIVALI KALYAN EAST", "THANE 421306", and then "State Code : MH": Customer Name is "SANTKRIPA DUGDHALAYA(KALYAN-E)" and To is "GODAVARI BLDG SHOP NO 4 LOKGRAM, KALYAN CITY, NETIVALI, KALYAN EAST, THANE 421306".
- In the product table, read only the product description and quantity columns. Return them in "items"; each item must contain exactly "description" and "qty".
- Keep every product row separate. Never combine rows, total quantities, or classify any item as Case or Jar.
- Always include "Case" and "Jar" with a value of 0. Do not calculate their totals; their values will be calculated from "items" after extraction.
- Vehicle Type should default to "9MT" when it is not clearly visible.
- Do not include any markdown fences, commentary, or notes. Return raw JSON only.
""".strip()


class GeminiBillingError(RuntimeError):
    """The configured Gemini project cannot make requests until billing is restored."""


def is_gemini_billing_error(error):
    error_text = f"{type(error).__name__}: {error}".lower()
    return "prepayment credits are depleted" in error_text or (
        "402" in error_text and "resource_exhausted" in error_text
    )


def file_to_part(uploaded_file):
    file_bytes = uploaded_file.getvalue()
    extension = str(uploaded_file.name).rsplit(".", 1)[-1].lower()
    mime_type = MIME_TYPES[extension]

    if extension in {"png", "jpg", "jpeg"}:
        with Image.open(io.BytesIO(file_bytes)) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail((1800, 1800), Image.Resampling.LANCZOS)
            if image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
            optimized = io.BytesIO()
            image.save(optimized, format="JPEG", quality=85, optimize=True)
            file_bytes = optimized.getvalue()
            mime_type = "image/jpeg"
    elif extension == "pdf":
        pypdf.PdfReader(io.BytesIO(file_bytes))

    return types.Part.from_bytes(data=file_bytes, mime_type=mime_type)


def extract_json_text(raw_text):
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def is_jar_item(description):
    normalized = str(description).upper()
    return bool(re.search(r"(?<!\d)20[\s.\-]*LTR", normalized))


def parse_item_quantity(item):
    quantity = item.get("quantity") if item.get("quantity") is not None else item.get("qty")
    if quantity is None:
        return 0.0

    if isinstance(quantity, (int, float)):
        return float(quantity)

    if isinstance(quantity, str):
        cleaned = quantity.replace(",", "")
        match = re.search(r"[-+]?\d*\.?\d+", cleaned)
        if match:
            try:
                return float(match.group())
            except ValueError:
                return 0.0
    return 0.0


def apply_case_jar_logic(record):
    case_qty = 0.0
    jar_qty = 0.0

    items = record.get("items", [])
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue

            description = str(item.get("description", ""))
            quantity = parse_item_quantity(item)

            if is_jar_item(description):
                jar_qty += quantity
            else:
                case_qty += quantity

    case_value = 0
    jar_value = 0
    if case_qty:
        case_value = int(case_qty) if case_qty == int(case_qty) else case_qty
    if jar_qty:
        jar_value = int(jar_qty) if jar_qty == int(jar_qty) else jar_qty

    record["Case"] = case_value
    record["Jar"] = jar_value
    record.pop("items", None)

    customer_code = record.get("Customer Code", "")
    if customer_code is None:
        customer_code = ""
    else:
        customer_code = str(customer_code).strip().upper().replace(" ", "")

    loading_point = normalize_loading_point(record.get("Loading Point"))

    return {
        "Date": record.get("Date", ""),
        "Invoice No.": record.get("Invoice No.", record.get("Invoice No", "")),
        "Vehicle No.": record.get("Vehicle No.", record.get("Vehicle No", "")),
        "From": short_origin(record.get("From", ""), loading_point),
        "Loading Point": loading_point,
        "Customer Code": customer_code,
        "Customer Name": record.get("Customer Name", ""),
        "To": record.get("To", ""),
        "Vehicle Type": record.get("Vehicle Type", "") or "9MT",
        "Case": case_value,
        "Jar": jar_value,
    }


def parse_gemini_response(raw_text):
    payload = json.loads(extract_json_text(raw_text))
    if isinstance(payload, dict):
        payload = payload.get("trips") or payload.get("records") or payload.get("data") or [payload]
    if not isinstance(payload, list):
        raise ValueError("Gemini response must be a JSON array of trip records.")

    processed_records = []
    for record in payload:
        if not isinstance(record, dict):
            continue

        items = record.get("items", [])
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    print(
                        f'description="{item.get("description", "")}" '
                        f'qty={item.get("qty", item.get("quantity", ""))}'
                    )
        processed_record = apply_case_jar_logic(record)
        print(
            "DEBUG recalculated quantities after apply_case_jar_logic "
            f"(invoice={processed_record.get('Invoice No.', '')}): "
            f"Case={processed_record.get('Case', 0)}, Jar={processed_record.get('Jar', 0)}"
        )
        processed_records.append(processed_record)

    return processed_records


def build_batch_content_parts(uploaded_files):
    content_parts = []
    for uploaded_file in uploaded_files:
        content_parts.append(
            types.Part.from_text(text=f"Document: {uploaded_file.name}")
        )
        content_parts.append(file_to_part(uploaded_file))
    return content_parts


def is_retryable_error(error):
    error_text = f"{type(error).__name__}: {error}".lower()
    retry_tokens = [
        "503",
        "service unavailable",
        "temporarily unavailable",
        "overloaded",
        "429",
        "resource exhausted",
        "too many requests",
        "rate limit",
        "502",
        "504",
        "500",
        "backend error",
    ]
    return any(token in error_text for token in retry_tokens)


def analyze_bills(uploaded_files):
    if not API_KEY:
        raise ValueError(
            "Missing API key. Set GOOGLE_API_KEY in the environment or add it to Streamlit secrets."
        )
    gemini_started_at = time.monotonic()
    gemini_deadline = gemini_started_at + GEMINI_TOTAL_TIMEOUT_SECONDS
    client = genai.Client(api_key=API_KEY)
    content_parts = build_batch_content_parts(uploaded_files)

    last_error = None
    for model_name in MODEL_FALLBACKS:
        for attempt in range(1, MAX_RETRIES + 1):
            remaining_seconds = gemini_deadline - time.monotonic()
            if remaining_seconds <= 0:
                last_error = TimeoutError(
                    f"Gemini exceeded the {GEMINI_TOTAL_TIMEOUT_SECONDS}-second limit."
                )
                break
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=content_parts,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        response_mime_type="application/json",
                        http_options=types.HttpOptions(
                            timeout=max(1, int(remaining_seconds * 1000)),
                            retry_options=types.HttpRetryOptions(attempts=1),
                        ),
                    ),
                )
                if time.monotonic() >= gemini_deadline:
                    last_error = TimeoutError(
                        f"Gemini exceeded the {GEMINI_TOTAL_TIMEOUT_SECONDS}-second limit."
                    )
                    break
            except Exception as e:
                last_error = e
                error_text = str(e).lower()

                if is_gemini_billing_error(e):
                    raise GeminiBillingError(
                        "The Gemini API project has no available billing credit."
                    ) from e

                if "not_found" in error_text or "not found" in error_text:
                    print(f"Gemini model unavailable: {model_name}")
                    break

                if not is_retryable_error(e):
                    print(f"Gemini model failed: {model_name} ({type(e).__name__})")
                    break

                if attempt < MAX_RETRIES:
                    remaining_seconds = gemini_deadline - time.monotonic()
                    if remaining_seconds <= 0:
                        break
                    print(f"Gemini model busy; retrying: {model_name}")
                    time.sleep(min(INITIAL_BACKOFF_SECONDS, remaining_seconds))
                    continue

                print(f"Gemini retries exhausted: {model_name}")
                break

            log_gemini_usage(
                model_name,
                getattr(response, "model_version", ""),
                len(uploaded_files),
                getattr(response, "usage_metadata", None),
                DATABASE_PATH,
            )
            try:
                records = parse_gemini_response(response.text)
            except (json.JSONDecodeError, TypeError, ValueError) as error:
                last_error = error
                print(f"Gemini returned unusable JSON: {model_name}")
                break
            if records:
                return records
            last_error = ValueError(f"Gemini model {model_name} returned zero records.")
            print(f"Gemini returned no records: {model_name}")
            break

        if time.monotonic() >= gemini_deadline:
            break

    if isinstance(last_error, TimeoutError):
        raise RuntimeError(
            "Gemini did not finish this invoice within 1 minute. You can retry "
            "this invoice or skip it and continue with the remaining bills."
        ) from last_error
    raise RuntimeError(
        "Gemini could not read this invoice with the available models. You can "
        "retry this invoice or skip it and continue with the remaining bills."
    ) from last_error


def init_database():
    """Create the lightweight invoice-processing history store when needed."""
    with sqlite3.connect(DATABASE_PATH) as connection:
        existing_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(billing_history)").fetchall()
        }
        if existing_columns and "id" not in existing_columns:
            connection.execute(
                "ALTER TABLE billing_history RENAME TO billing_history_legacy"
            )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS billing_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_no TEXT NOT NULL,
                processed_timestamp TEXT NOT NULL
            )
            """
        )
        if existing_columns and "id" not in existing_columns:
            connection.execute(
                """
                INSERT INTO billing_history (invoice_no, processed_timestamp)
                SELECT invoice_no, processed_timestamp
                FROM billing_history_legacy
                """
            )
            connection.execute("DROP TABLE billing_history_legacy")


def log_processed_invoice(invoice_no, database_path=DATABASE_PATH):
    """Record one successful processing event for dashboard reporting."""
    normalized_invoice_no = str(invoice_no or "").strip()
    if not normalized_invoice_no:
        return

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO billing_history (invoice_no, processed_timestamp)
            VALUES (?, ?)
            """,
            (normalized_invoice_no, datetime.now().isoformat(timespec="seconds")),
        )


def processing_batch_signature(uploaded_files):
    """Identify the exact ordered upload selection across Streamlit reruns."""
    return "|".join(
        f"{str(uploaded_file.name)}:{upload_digest(uploaded_file)}"
        for uploaded_file in uploaded_files
    )


def create_processing_state(uploaded_files):
    """Create resumable per-file processing state for one upload selection."""
    return {
        "signature": processing_batch_signature(uploaded_files),
        "file_names": [str(uploaded_file.name) for uploaded_file in uploaded_files],
        "statuses": ["pending"] * len(uploaded_files),
        "current_index": 0,
        "records": [],
        "duplicates": [],
        "errors": {},
        "current_error": None,
        "status": "running",
        "duplicate_decision": None,
        "show_results": False,
        "scan_elapsed_seconds": 0.0,
        "scan_attempts_completed": 0,
    }


def enrich_invoice_records(records):
    """Apply the established customer, freight, and dated-rate rules."""
    master_data = load_customer_master()
    records = apply_customer_master_lookup(records, build_customer_lookup(master_data))
    records = apply_freight_lookup(records, build_freight_lookup(master_data))
    records = apply_invoice_billing_reference(records)
    return apply_freight_rate_revision(records)


def _advance_processing_cursor(state):
    pending_indexes = [
        index for index, status in enumerate(state["statuses"])
        if status == "pending"
    ]
    state["current_index"] = pending_indexes[0] if pending_indexes else len(state["statuses"])
    if not pending_indexes and state.get("status") == "running":
        state["status"] = "complete"


def _store_extracted_invoice(uploaded_file, index, state, records):
    if not records:
        raise ValueError("No invoice data was found in this file.")
    records = enrich_invoice_records(records)
    accepted_records, duplicates = store_new_invoice_records(records, DATABASE_PATH)
    store_processed_uploads([uploaded_file], DATABASE_PATH)
    for accepted_record in accepted_records:
        log_processed_invoice(
            accepted_record.get("Invoice No.", accepted_record.get("Invoice No", "")),
            DATABASE_PATH,
        )
    for duplicate in duplicates:
        duplicate_entry = duplicate.copy()
        duplicate_entry["filename"] = str(uploaded_file.name)
        duplicate_entry["file_index"] = index
        state["duplicates"].append(duplicate_entry)
    state["records"].extend(accepted_records)
    state["statuses"][index] = (
        "duplicate" if duplicates and not accepted_records else "processed"
    )
    state["errors"].pop(str(index), None)
    state["current_error"] = None


def _record_invoice_failure(uploaded_file, index, state, error):
    if isinstance(error, GeminiBillingError):
        print(f"Gemini billing unavailable: {str(error)[:500]}")
        state["statuses"][index] = "pending"
        state["current_error"] = {
            "file_index": index,
            "filename": str(uploaded_file.name),
            "message": "Gemini API credits are depleted.",
        }
        state["status"] = "service_error"
        return

    print(
        f"Invoice processing failed for {uploaded_file.name}: "
        f"{type(error).__name__}: {str(error)[:500]}"
    )
    state["statuses"][index] = "failed"
    state["errors"][str(index)] = {
        "file_index": index,
        "filename": str(uploaded_file.name),
        "message": (
            "We couldn't read this invoice. The image may be unclear, cropped, "
            "or Gemini may be temporarily busy."
        ),
    }
    state["current_error"] = None


def process_invoice_window(uploaded_files, state, worker_count=INVOICE_SCAN_WORKERS):
    """Extract a small window concurrently, then persist results in file order."""
    pending_indexes = [
        index for index, status in enumerate(state["statuses"])
        if status == "pending"
    ][:worker_count]
    if not pending_indexes:
        state["status"] = "complete"
        _advance_processing_cursor(state)
        return state

    for index in pending_indexes:
        state["statuses"][index] = "processing"

    def extract(index):
        try:
            return analyze_bills([uploaded_files[index]]), None
        except Exception as error:
            return None, error

    window_started_at = time.monotonic()
    with ThreadPoolExecutor(max_workers=len(pending_indexes)) as executor:
        futures = {index: executor.submit(extract, index) for index in pending_indexes}
        outcomes = {index: futures[index].result() for index in pending_indexes}
    window_elapsed = time.monotonic() - window_started_at
    state["scan_elapsed_seconds"] = (
        float(state.get("scan_elapsed_seconds", 0.0)) + window_elapsed
    )
    state["scan_attempts_completed"] = (
        int(state.get("scan_attempts_completed", 0)) + len(pending_indexes)
    )

    for index in pending_indexes:
        records, error = outcomes[index]
        uploaded_file = uploaded_files[index]
        if error is None:
            try:
                _store_extracted_invoice(uploaded_file, index, state, records)
            except Exception as storage_error:
                _record_invoice_failure(uploaded_file, index, state, storage_error)
        else:
            _record_invoice_failure(uploaded_file, index, state, error)
        if state["status"] == "service_error":
            for remaining_index in pending_indexes:
                if state["statuses"][remaining_index] == "processing":
                    state["statuses"][remaining_index] = "pending"
            break

    _advance_processing_cursor(state)
    return state


def process_next_invoice(uploaded_files, state):
    """Compatibility helper that processes one pending invoice."""
    return process_invoice_window(uploaded_files, state, worker_count=1)


def estimated_time_remaining_text(state, remaining_invoices):
    """Return a stable, active-processing ETA for the progress display."""
    completed_attempts = int(state.get("scan_attempts_completed", 0))
    elapsed_seconds = float(state.get("scan_elapsed_seconds", 0.0))
    if remaining_invoices <= 0:
        return "Complete"
    if completed_attempts <= 0 or elapsed_seconds <= 0:
        return "Calculating…"
    remaining_seconds = elapsed_seconds / completed_attempts * remaining_invoices
    remaining_minutes = max(1, int((remaining_seconds + 59) // 60))
    return f"~ {remaining_minutes} min"


def retry_failed_invoices(state):
    """Queue every failed invoice for another pass without repeating successes."""
    failed_indexes = sorted(int(index) for index in state.get("errors", {}))
    if not failed_indexes:
        return state
    for index in failed_indexes:
        state["statuses"][index] = "pending"
    state["errors"] = {}
    state["current_error"] = None
    state["current_index"] = failed_indexes[0]
    state["status"] = "running"
    state["results_published"] = False
    state["show_results"] = False
    return state


def retry_current_invoice(state):
    """Clear the current error so the same file is attempted again."""
    error = state["current_error"]
    failed_index = error["file_index"]
    state["statuses"][failed_index] = "pending"
    state["current_error"] = None
    state["status"] = "running"
    return state


def skip_current_invoice(state, total_files):
    """Record the failed file as skipped and advance without losing results."""
    error = state["current_error"]
    failed_index = error["file_index"]
    state["statuses"][failed_index] = "skipped"
    state["current_index"] += 1
    state["current_error"] = None
    state["status"] = (
        "complete" if state["current_index"] >= total_files else "running"
    )
    return state


def include_duplicate_records(state):
    """Explicitly include duplicate invoices after the scan has completed."""
    if state.get("duplicate_decision") is not None:
        return state
    for duplicate in state["duplicates"]:
        record = duplicate["record"]
        store_processed_invoice(record, DATABASE_PATH)
        log_processed_invoice(
            record.get("Invoice No.", record.get("Invoice No", "")),
            DATABASE_PATH,
        )
        state["records"].append(record)
    state["duplicate_decision"] = "include"
    return state


def publish_processing_results(state):
    """Expose the finalized records to the established editor/export workflow."""
    st.session_state["bill_data"] = pd.DataFrame(state["records"], columns=COLUMNS)
    st.session_state["processing_new_count"] = len(state["records"])
    st.session_state["duplicate_invoices"] = []
    st.session_state["show_processing_results"] = False
    state["results_published"] = True


def _get_processed_count(start_date, end_date):
    with sqlite3.connect(DATABASE_PATH) as connection:
        result = connection.execute(
            """
            SELECT COUNT(*)
            FROM billing_history
            WHERE DATE(processed_timestamp) BETWEEN ? AND ?
            """,
            (start_date.isoformat(), end_date.isoformat()),
        ).fetchone()
    return result[0]


def get_today_count():
    today = date.today()
    return _get_processed_count(today, today)


def get_week_count():
    today = date.today()
    return _get_processed_count(today - timedelta(days=today.weekday()), today)


def get_month_count():
    today = date.today()
    return _get_processed_count(today.replace(day=1), today)


def get_custom_count(start_date, end_date):
    if start_date > end_date:
        return 0
    return _get_processed_count(start_date, end_date)


def format_processed_timestamp(timestamp):
    try:
        return datetime.fromisoformat(timestamp).strftime("%d-%b-%Y %I:%M %p")
    except (TypeError, ValueError):
        return str(timestamp or "")


def format_history_freight_charge(value):
    if value in (None, ""):
        return ""
    try:
        return f"₹ {float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


@st.dialog("Processed Invoice Details")
def show_processed_invoice_dialog(invoice):
    details = (
        ("Date Processed", format_processed_timestamp(invoice["processed_timestamp"])),
        ("Invoice Date", invoice["invoice_date"]),
        ("Invoice Number", invoice["invoice_number"]),
        ("Vehicle Number", invoice["vehicle_number"]),
        ("Customer Code", invoice["customer_code"]),
        ("Customer Name", invoice["customer_name"]),
        ("From", invoice["origin"]),
        ("To", invoice["destination"]),
        ("Vehicle Type", invoice["vehicle_type"]),
        ("Cases", invoice["cases"]),
        ("Jars", invoice["jars"]),
        ("Freight Charge", format_history_freight_charge(invoice["freight_charge"])),
        ("Lookup Status", invoice["lookup_status"]),
    )
    for label, value in details:
        label_column, value_column = st.columns([0.38, 0.62])
        label_column.markdown(f"**{label}**")
        value_column.write("" if value is None else value)

    if st.button("Close", key="close_processed_invoice_dialog"):
        st.session_state["selected_history_invoice_id"] = None
        st.rerun()


def render_processed_invoice_history(database_path):
    search_query = st.text_input(
        "Search invoice history",
        placeholder="Search by invoice number or customer name",
        key="processed_invoice_history_search",
    )
    history_rows = search_processed_invoices(search_query, database_path)

    with st.container(height=360, border=True):
        header_columns = st.columns([1.5, 1.5, 2.2, 1.2, 0.7])
        for column, label in zip(
            header_columns,
            (
                "Date Processed",
                "Invoice Number",
                "Customer Name",
                "Freight Charge",
                "Actions",
            ),
        ):
            column.markdown(f"**{label}**")

        if not history_rows:
            st.caption("No processed invoices found.")

        for row in history_rows:
            columns = st.columns([1.5, 1.5, 2.2, 1.2, 0.7])
            columns[0].write(format_processed_timestamp(row["processed_timestamp"]))
            columns[1].write(row["invoice_number"] or "")
            columns[2].write(row["customer_name"] or "")
            columns[3].write(format_history_freight_charge(row["freight_charge"]))
            if columns[4].button("View", key=f"view_processed_invoice_{row['id']}"):
                st.session_state["selected_history_invoice_id"] = row["id"]

    selected_history_id = st.session_state.get("selected_history_invoice_id")
    if selected_history_id is not None:
        selected_invoice = get_processed_invoice(selected_history_id, database_path)
        if selected_invoice is not None:
            show_processed_invoice_dialog(selected_invoice)


@st.dialog("Duplicate Invoices", width="large")
def show_duplicate_invoice_dialog(database_path):
    duplicates = st.session_state.get("duplicate_invoices", [])

    if duplicates:
        _, reupload_all_column = st.columns([4.8, 1.2])
        if reupload_all_column.button(
            "Re-Upload All",
            key="reupload_all_duplicates",
            type="primary",
        ):
            records = [duplicate["record"] for duplicate in duplicates]
            for record in records:
                store_processed_invoice(record, database_path)
                log_processed_invoice(
                    record.get("Invoice No.", record.get("Invoice No", "")),
                    database_path,
                )

            reuploaded_data = pd.DataFrame(records, columns=COLUMNS)
            current_bill_data = st.session_state.get("bill_data")
            if current_bill_data is None or current_bill_data.empty:
                st.session_state["bill_data"] = reuploaded_data
            else:
                st.session_state["bill_data"] = pd.concat(
                    [current_bill_data, reuploaded_data],
                    ignore_index=True,
                )

            st.session_state["processing_new_count"] = (
                st.session_state.get("processing_new_count", 0) + len(records)
            )
            st.session_state["duplicate_invoices"] = []
            st.session_state["show_duplicate_invoice_details"] = False
            st.rerun()

    header_columns = st.columns([1.5, 2.2, 1.7, 1.2])
    for column, label in zip(
        header_columns,
        (
            "Invoice Number",
            "Customer Name",
            "Previously Processed On",
            "Action",
        ),
    ):
        column.markdown(f"**{label}**")

    for index, duplicate in enumerate(duplicates):
        record = duplicate["record"]
        previous = duplicate["previous"]
        columns = st.columns([1.5, 2.2, 1.7, 1.2])
        columns[0].write(record.get("Invoice No.", record.get("Invoice No", "")))
        columns[1].write(record.get("Customer Name", ""))
        columns[2].write(format_processed_timestamp(previous["processed_timestamp"]))
        if columns[3].button(
            "Re-upload anyway",
            key=f"reupload_duplicate_{index}",
            type="tertiary",
        ):
            store_processed_invoice(record, database_path)
            log_processed_invoice(
                record.get("Invoice No.", record.get("Invoice No", "")),
                database_path,
            )
            current_bill_data = st.session_state.get("bill_data")
            reuploaded_data = pd.DataFrame([record], columns=COLUMNS)
            if current_bill_data is None or current_bill_data.empty:
                st.session_state["bill_data"] = reuploaded_data
            else:
                st.session_state["bill_data"] = pd.concat(
                    [current_bill_data, reuploaded_data],
                    ignore_index=True,
                )
            st.session_state["processing_new_count"] += 1
            del st.session_state["duplicate_invoices"][index]
            st.rerun()

    if not duplicates:
        st.caption("No skipped duplicate invoices remain.")

    if st.button("Close", key="close_duplicate_invoice_dialog"):
        st.session_state["show_duplicate_invoice_details"] = False
        st.rerun()


def render_processing_summary(database_path):
    if "processing_new_count" not in st.session_state:
        return

    duplicate_count = len(st.session_state.get("duplicate_invoices", []))
    st.markdown('<div class="section-label">Processing Complete</div>', unsafe_allow_html=True)
    st.write(f"New invoices processed: {st.session_state['processing_new_count']}")
    st.write(f"Duplicate invoices skipped: {duplicate_count}")

    if duplicate_count and st.button("View Details", key="view_duplicate_invoice_details"):
        st.session_state["show_duplicate_invoice_details"] = True

    if st.session_state.get("show_duplicate_invoice_details", False):
        show_duplicate_invoice_dialog(database_path)


st.set_page_config(
    page_title="Project Kill Bill",
    page_icon="",
    layout="wide",
)

st.markdown(PREMIUM_CSS, unsafe_allow_html=True)

st.markdown(
    """
    <div class="premium-title-wrap">
        <div class="title-kicker">Billing Operations Suite</div>
        <h1 class="premium-title">Project <span>Kill Bill</span></h1>
    </div>
    """,
    unsafe_allow_html=True,
)

init_database()
init_invoice_history_database(DATABASE_PATH)

st.markdown(
    """
    <div class="landing-hero">
        <div class="invoice-illustration" aria-hidden="true">
            <div class="invoice-sheet left">Bisleri</div>
            <div class="invoice-sheet right">Bisleri</div>
            <div class="invoice-sheet">Bisleri</div>
        </div>
        <h2>Upload Your Bisleri Bills</h2>
        <p>Add your Bisleri bills and let us do the rest.<br>
        We’ll scan, extract and create the invoices for you.</p>
    </div>
    <div class="upload-heading">Upload Bills</div>
    """,
    unsafe_allow_html=True,
)

uploaded_files = st.file_uploader(
    "Upload one or more bill images or PDFs",
    type=["png", "jpg", "jpeg", "pdf"],
    accept_multiple_files=True,
    label_visibility="collapsed",
)
st.markdown(
    '<div class="upload-support">Supports JPG, PNG, PDF &nbsp;•&nbsp; Up to 200MB per file</div>',
    unsafe_allow_html=True,
)

if uploaded_files:
    file_count = len(uploaded_files)
    st.markdown(
        f"""
        <div class="upload-status">
            {file_count} file{'s' if file_count != 1 else ''} uploaded successfully.
        </div>
        """,
        unsafe_allow_html=True,
    )
    preview_files = uploaded_files[:5]
    preview_columns = st.columns(len(preview_files) + (1 if file_count > 5 else 0))
    for preview_column, uploaded_file in zip(preview_columns, preview_files):
        with preview_column:
            extension = uploaded_file.name.rsplit(".", 1)[-1].lower()
            if extension in {"png", "jpg", "jpeg"}:
                st.image(uploaded_file, use_container_width=True)
            else:
                st.markdown("### PDF")
            st.caption(uploaded_file.name)
    if file_count > 5:
        with preview_columns[-1]:
            st.markdown(f"### +{file_count - 5}")
            st.caption("more bills")

current_signature = processing_batch_signature(uploaded_files) if uploaded_files else ""
processing_state = st.session_state.get(PROCESSING_STATE_KEY)
selection_matches = bool(
    processing_state
    and uploaded_files
    and processing_state.get("signature") == current_signature
)

if processing_state and uploaded_files and not selection_matches:
    st.info(
        "The uploaded file selection changed. Start a new scan to process this selection."
    )

show_start_button = not processing_state or not selection_matches
start_clicked = False
if show_start_button:
    _, start_button_column, _ = st.columns([1, 3, 1])
    with start_button_column:
        start_clicked = st.button(
            "Start Scanning Bills",
            disabled=not uploaded_files,
            type="primary",
            use_container_width=True,
            key="start_invoice_processing",
        )

if start_clicked:
    processing_state = create_processing_state(uploaded_files)
    st.session_state[PROCESSING_STATE_KEY] = processing_state
    for key in (
        "bill_data",
        "processing_new_count",
        "duplicate_invoices",
        "show_processing_results",
    ):
        st.session_state.pop(key, None)
    st.rerun()

if selection_matches:
    processing_state = st.session_state[PROCESSING_STATE_KEY]
    total_files = len(uploaded_files)
    # Continue sessions created by the previous pause-on-error workflow.
    if processing_state.get("status") == "error" and processing_state.get("current_error"):
        legacy_error = processing_state["current_error"]
        failed_index = legacy_error["file_index"]
        processing_state["statuses"][failed_index] = "failed"
        processing_state["errors"][str(failed_index)] = legacy_error
        processing_state["current_error"] = None
        processing_state["current_index"] = failed_index + 1
        processing_state["status"] = (
            "complete" if processing_state["current_index"] >= total_files else "running"
        )
        st.session_state[PROCESSING_STATE_KEY] = processing_state
        st.rerun()
    scanned_files = sum(
        status not in {"pending", "processing"}
        for status in processing_state["statuses"]
    )
    progress_value = scanned_files / total_files if total_files else 0

    st.markdown('<div class="scan-panel">', unsafe_allow_html=True)
    if processing_state["status"] in {"running", "error", "service_error", "cancelled"}:
        heading = (
            "Processing Invoices..."
            if processing_state["status"] == "running"
            else "Processing Paused"
        )
        st.markdown(f'<h2 class="scan-heading">{heading}</h2>', unsafe_allow_html=True)
        st.markdown(
            '<p class="scan-subtitle">Scanning and extracting each Bisleri bill individually</p>',
            unsafe_allow_html=True,
        )
        eta_text = estimated_time_remaining_text(
            processing_state,
            total_files - scanned_files,
        )
        st.markdown(
            f"""
            <div class="progress-summary">
                <span>{scanned_files} of {total_files} bills processed</span>
                <span class="eta-pill"><span class="eta-clock">◷</span>Estimated time remaining: {eta_text}</span>
                <span class="progress-percent">{round(progress_value * 100)}%</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.progress(progress_value)

    if processing_state["status"] == "running":
        current_index = processing_state["current_index"]
        if current_index < total_files:
            active_indexes = [
                index for index, status in enumerate(processing_state["statuses"])
                if status == "pending"
            ][:INVOICE_SCAN_WORKERS]
            safe_current_filenames = "<br>".join(
                html.escape(str(uploaded_files[index].name or "Invoice"))
                for index in active_indexes
            )
            active_label = (
                f"bills {active_indexes[0] + 1}–{active_indexes[-1] + 1}"
                if len(active_indexes) > 1
                else f"bill {active_indexes[0] + 1}"
            )
            st.markdown(
                f"""
                <div class="current-file-card">
                    <strong>Currently scanning {active_label} of {total_files}</strong><br>
                    {safe_current_filenames}
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button(
                "Stop After Current Bill",
                key=f"cancel_processing_{current_index}",
            ):
                processing_state["status"] = "cancelled"
                st.session_state[PROCESSING_STATE_KEY] = processing_state
                st.rerun()

            processing_state = process_invoice_window(uploaded_files, processing_state)
            st.session_state[PROCESSING_STATE_KEY] = processing_state
            st.rerun()

    elif processing_state["status"] == "service_error":
        st.error(
            "Invoice scanning is temporarily unavailable because the configured "
            "Gemini API project has depleted its prepaid credits. No bills were "
            "skipped. Restore the Gemini balance or replace GOOGLE_API_KEY in "
            "Streamlit secrets, reboot the app, and then retry this batch."
        )
        if st.button(
            "Retry Batch",
            type="primary",
            use_container_width=True,
            key="retry_after_gemini_billing_error",
        ):
            processing_state["current_error"] = None
            processing_state["status"] = "running"
            st.session_state[PROCESSING_STATE_KEY] = processing_state
            st.rerun()

    elif processing_state["status"] == "error":
        error = processing_state["current_error"]
        safe_error_filename = html.escape(str(error.get("filename") or "Invoice"))
        safe_error_message = html.escape(
            str(error.get("message") or "This invoice could not be read.")
        )
        st.markdown(
            f"""
            <div class="processing-error-card">
                <strong>Error at bill {error['file_index'] + 1} of {total_files}</strong><br>
                {safe_error_filename}<br>
                {safe_error_message}
            </div>
            """,
            unsafe_allow_html=True,
        )
        if processing_state["records"]:
            with st.expander(
                f"View {len(processing_state['records'])} invoices processed so far"
            ):
                st.dataframe(
                    pd.DataFrame(processing_state["records"], columns=COLUMNS),
                    use_container_width=True,
                    hide_index=True,
                )
        retry_column, skip_column = st.columns(2)
        if retry_column.button(
            f"Retry Bill {error['file_index'] + 1}",
            type="primary",
            use_container_width=True,
            key="retry_failed_invoice",
        ):
            processing_state = retry_current_invoice(processing_state)
            st.session_state[PROCESSING_STATE_KEY] = processing_state
            st.rerun()
        if skip_column.button(
            "Skip This Bill",
            use_container_width=True,
            key="skip_failed_invoice",
        ):
            processing_state = skip_current_invoice(processing_state, total_files)
            st.session_state[PROCESSING_STATE_KEY] = processing_state
            st.rerun()

    elif processing_state["status"] == "cancelled":
        st.info(
            f"Scanning paused after {scanned_files} of {total_files} bills. "
            "Your completed results are preserved."
        )
        if st.button(
            "Resume Scanning",
            type="primary",
            use_container_width=True,
            key="resume_invoice_processing",
        ):
            processing_state["status"] = "running"
            st.session_state[PROCESSING_STATE_KEY] = processing_state
            st.rerun()

    elif processing_state["status"] == "complete":
        duplicate_count = len(processing_state["duplicates"])
        error_count = len(processing_state["errors"])
        processed_count = sum(
            status == "processed" for status in processing_state["statuses"]
        )
        completion_title = (
            "All Bills Processed Successfully"
            if error_count == 0
            else "Processing Complete"
        )
        st.markdown(f'<h2 class="scan-heading">{completion_title}</h2>', unsafe_allow_html=True)
        st.markdown(
            f'<p class="scan-subtitle">All {total_files} uploaded bills have been reviewed.</p>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f"""
            <div class="processing-stats">
                <div class="processing-stat"><span>Total Bills</span><strong>{total_files}</strong></div>
                <div class="processing-stat"><span>Processed</span><strong>{processed_count}</strong></div>
                <div class="processing-stat"><span>Duplicates</span><strong>{duplicate_count}</strong></div>
                <div class="processing-stat"><span>Failed</span><strong>{error_count}</strong></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if error_count:
            failed_files = [
                error.get("filename", "Invoice")
                for error in processing_state["errors"].values()
            ]
            st.warning(
                f"{error_count} invoice{'s' if error_count != 1 else ''} could not be read. "
                "The rest of the batch finished without interruption."
            )
            with st.expander(f"Review Failed Bills ({error_count})"):
                for failed_file in failed_files:
                    st.write(f"• {failed_file}")
            if st.button(
                "Retry Failed Bills",
                type="primary",
                use_container_width=True,
                key="retry_all_failed_invoices",
            ):
                processing_state = retry_failed_invoices(processing_state)
                st.session_state[PROCESSING_STATE_KEY] = processing_state
                st.session_state.pop("show_processing_results", None)
                st.rerun()

        if duplicate_count and processing_state["duplicate_decision"] is None:
            st.markdown(
                f"""
                <div class="duplicate-card">
                    <strong>{duplicate_count} duplicate invoice{'s' if duplicate_count != 1 else ''} detected</strong><br>
                    Choose whether to include them in the spreadsheets or use unique invoices only.
                </div>
                """,
                unsafe_allow_html=True,
            )
            with st.expander(f"Review Duplicates ({duplicate_count})"):
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "File": duplicate.get("filename", ""),
                                "Invoice Number": duplicate["record"].get("Invoice No.", ""),
                                "Customer": duplicate["record"].get("Customer Name", ""),
                                "Previously Processed": duplicate["previous"].get(
                                    "processed_timestamp", ""
                                ),
                            }
                            for duplicate in processing_state["duplicates"]
                        ]
                    ),
                    use_container_width=True,
                    hide_index=True,
                )
            include_column, unique_column = st.columns(2)
            if include_column.button(
                "Include Duplicates",
                type="primary",
                use_container_width=True,
                key="include_all_duplicates",
            ):
                processing_state = include_duplicate_records(processing_state)
                publish_processing_results(processing_state)
                st.session_state[PROCESSING_STATE_KEY] = processing_state
                st.rerun()
            if unique_column.button(
                "Skip All Duplicates",
                use_container_width=True,
                key="skip_all_duplicates",
            ):
                processing_state["duplicate_decision"] = "skip"
                publish_processing_results(processing_state)
                st.session_state[PROCESSING_STATE_KEY] = processing_state
                st.rerun()
        else:
            if processing_state["duplicate_decision"] is None:
                processing_state["duplicate_decision"] = "none"
            if not processing_state.get("results_published"):
                publish_processing_results(processing_state)
                st.session_state[PROCESSING_STATE_KEY] = processing_state

            create_column, view_column = st.columns([1.5, 1])
            if create_column.button(
                "Create Excel Spreadsheets",
                type="primary",
                use_container_width=True,
                disabled=not processing_state["records"],
                key="create_processing_spreadsheets",
            ):
                processing_state["show_results"] = True
                st.session_state["show_processing_results"] = True
                st.session_state[PROCESSING_STATE_KEY] = processing_state
                st.rerun()
            if view_column.button(
                "View Processed Bills",
                use_container_width=True,
                disabled=not processing_state["records"],
                key="view_completed_bills",
            ):
                processing_state["show_results"] = True
                st.session_state["show_processing_results"] = True
                st.session_state[PROCESSING_STATE_KEY] = processing_state
                st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)

if (
    st.session_state.get("show_processing_results", False)
    and "bill_data" in st.session_state
    and not st.session_state["bill_data"].empty
):
    st.subheader("Review & Edit Extracted Data")

    # Sessions can survive a Streamlit Cloud code redeploy. Refresh any table
    # built under the previous tariff before it is shown or downloaded.
    st.session_state["bill_data"] = apply_freight_rate_revision_to_dataframe(
        st.session_state["bill_data"]
    )

    edited_df = st.data_editor(
        st.session_state["bill_data"],
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key=(
            "billing_review_"
            + st.session_state.get(PROCESSING_STATE_KEY, {}).get(
                "signature", "legacy"
            )[:12]
        ),
    )

    st.session_state["bill_data"] = edited_df

    missing_freight = pd.to_numeric(edited_df["Freight Charge"], errors="coerce").isna()
    if missing_freight.any():
        st.warning(
            f"{int(missing_freight.sum())} invoice(s) have no freight rate. "
            "Check invoice Date, Customer Code, From, and the customer/rate master before billing. "
            "Unmatched customers retain the extracted address; statement totals "
            "exclude missing charges."
        )

    st.download_button(
        label="Download Excel",
        data=build_excel_workbook(edited_df),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        file_name=excel_export_filename(),
    )

    st.subheader("Billing Statement")
    billing_statement = build_billing_statement(edited_df)
    if billing_statement.empty:
        st.caption("No invoice entries are available for the billing statement.")
    else:
        st.dataframe(
            billing_statement[SUMMARY_COLUMNS],
            use_container_width=True,
            hide_index=True,
            height=360,
        )
        statement_month_count = billing_statement["_bill_month"].nunique(
            dropna=False
        )
        if statement_month_count > 1:
            st.caption(
                f"The downloaded statement contains all {len(billing_statement)} "
                f"invoices across {statement_month_count} monthly tabs and opens on "
                "the tab with the most invoices."
            )
        st.download_button(
            label="Download Billing Statement",
            data=build_billing_statement_workbook(billing_statement),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            file_name=billing_statement_filename(billing_statement),
        )
