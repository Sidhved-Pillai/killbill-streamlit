import io
import json
import os
import re
import time

import pandas as pd
import pypdf
import streamlit as st
from google import genai
from google.genai import types
from PIL import Image

API_KEY = (
    os.getenv("GOOGLE_API_KEY")
    or os.getenv("GENAI_API_KEY")
    or st.secrets.get("GOOGLE_API_KEY", "")
)
MODEL_FALLBACKS = [
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
    "gemini-3.1-flash-lite",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash-lite-001",
]
MAX_RETRIES = 5
INITIAL_BACKOFF_SECONDS = 4

PREMIUM_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

    html, body, [data-testid="stAppViewContainer"] {
        background-color: #F8F9FA;
        color: #111111;
        font-family: 'Inter', 'Helvetica Neue', sans-serif;
    }

    .main .block-container {
        max-width: 1180px;
        padding-top: 2rem;
        padding-bottom: 2rem;
    }

    .premium-title-wrap {
        margin-bottom: 1.2rem;
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

    [data-testid="stDataFrame"] th,
    [data-testid="stDataEditor"] th {
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
        background: #D32F2F !important;
        color: #FFFFFF !important;
        border: 1px solid #D32F2F !important;
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
]

MIME_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "pdf": "application/pdf",
}

SYSTEM_INSTRUCTION = """
You are auditing a combined batch of logistics delivery sheets for Ubiquity Transtech.
Scan all attached documents together and extract every single distinct trip row you find across all files.

Return ONLY a single valid JSON list of objects. Each object represents one invoice trip row and must contain exactly these keys:
- "Date" (format: DD-MMM-YY, e.g. 25-May-26)
- "Invoice No."
- "Vehicle No."
- "From"
- "Customer Code"
- "Customer Name"
- "To"
- "Vehicle Type"
- "Case"
- "Jar"
- "items" (an array of product-line objects)

Rules:
- Treat all attached documents as one consolidated batch and aggregate the final result across the whole upload.
- Extract the "Shipped To" section in this exact order: Customer Code, Customer Name, address lines, then administrative fields.
- "Customer Code": extract only the value after "Customer Code :" (or "Customer Code:") in the "Shipped To" section. Do not use any other identifier.
- "Customer Name": extract ONLY the first text line immediately after Customer Code. It must be exactly one business/company name and must not contain any address text.
- "To": begin immediately AFTER the Customer Name. Concatenate every subsequent physical-address line, in order, into one value. Stop before the first administrative field: State Code, GSTIN, PAN, Phone, Email, FSSAI, Payment Terms, or any tax identifier.
- "To" must contain delivery-address text only. Never include Customer Name, Customer Code, GSTIN, or any administrative field or value.
- Example: for "Customer Code : MUMCO02703" followed by "SANTKRIPA DUGDHALAYA(KALYAN-E)", then "GODAVARI BLDG SHOP NO 4 LOKGRAM", "KALYAN CITY NETIVALI KALYAN EAST", "THANE 421306", and then "State Code : MH": Customer Name is "SANTKRIPA DUGDHALAYA(KALYAN-E)" and To is "GODAVARI BLDG SHOP NO 4 LOKGRAM, KALYAN CITY, NETIVALI, KALYAN EAST, THANE 421306".
- Extract EVERY product line exactly as printed on the invoice into "items". Each item must contain exactly "description" (the complete printed product description) and "qty" (the printed quantity).
- Keep every product row separate. Never combine rows, total quantities, or classify any item as Case or Jar.
- Always include "Case" and "Jar" with a value of 0. Do not calculate their totals; their values will be calculated from "items" after extraction.
- Vehicle Type should default to "9MT" when it is not clearly visible.
- Do not include any markdown fences, commentary, or notes. Return raw JSON only.
""".strip()


def file_to_part(uploaded_file):
    file_bytes = uploaded_file.getvalue()
    extension = uploaded_file.name.rsplit(".", 1)[-1].lower()
    mime_type = MIME_TYPES[extension]

    if extension in {"png", "jpg", "jpeg"}:
        Image.open(io.BytesIO(file_bytes))
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
    normalized = re.sub(r"[\s.\-]", "", str(description).upper())
    return bool(re.search(r"(?<!\d)(?:10|20)LTR(?!\d)", normalized))


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

    return {
        "Date": record.get("Date", ""),
        "Invoice No.": record.get("Invoice No.", record.get("Invoice No", "")),
        "Vehicle No.": record.get("Vehicle No.", record.get("Vehicle No", "")),
        "From": record.get("From", ""),
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

    return [apply_case_jar_logic(record) for record in payload if isinstance(record, dict)]


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

    client = genai.Client(api_key=API_KEY)
    content_parts = build_batch_content_parts(uploaded_files)

    last_error = None
    for model_name in MODEL_FALLBACKS:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=content_parts,
                    config=types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION),
                )
                return parse_gemini_response(response.text)
            except Exception as e:
                last_error = e
                error_text = str(e).lower()

                if "not_found" in error_text or "not found" in error_text:
                    st.warning(f"Model {model_name} unavailable; switching to next available model.")
                    break

                if attempt < MAX_RETRIES:
                    st.warning(
                        f"Google servers busy on {model_name}; retrying in 4 seconds... ({attempt}/{MAX_RETRIES})"
                    )
                    time.sleep(INITIAL_BACKOFF_SECONDS)
                    continue

                st.warning(f"Exhausted retries for {model_name}; trying the next available model.")
                break

    if last_error is not None:
        raise last_error

    return []


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

st.markdown(
    """
    <div class="onboarding-grid">
        <div class="onboarding-card">
            <div class="onboarding-step">Step 1</div>
            <h4>Upload Bills</h4>
            <p>Drag and drop up to 30 hard-copy Bisleri invoice photos or a single combined PDF document.</p>
        </div>
        <div class="onboarding-card">
            <div class="onboarding-step">Step 2</div>
            <h4>System Audit</h4>
            <p>Click <strong>Process Bills</strong> to let the AI scan, analyze, and sort quantities into Cases and Jars automatically.</p>
        </div>
        <div class="onboarding-card">
            <div class="onboarding-step">Step 3</div>
            <h4>Review & Export</h4>
            <p>Live-edit any values directly inside the data grid below and click <strong>Download</strong> to save your final production Excel sheet.</p>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown('<div class="section-label">Upload Bisleri Bills</div>', unsafe_allow_html=True)

uploaded_files = st.file_uploader(
    "Upload one or more bill images or PDFs",
    type=["png", "jpg", "jpeg", "pdf"],
    accept_multiple_files=True,
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

if st.button("Process Bills", disabled=not uploaded_files):
    with st.spinner("AI is analyzing documents..."):
        try:
            records = analyze_bills(uploaded_files)
            st.session_state["bill_data"] = pd.DataFrame(records, columns=COLUMNS)
        except json.JSONDecodeError:
            st.error("Gemini returned invalid JSON. Please try processing again.")
        except Exception as error:
            st.error(f"Failed to process bills: {error}")

if "bill_data" in st.session_state and not st.session_state["bill_data"].empty:
    st.subheader("Review & Edit Extracted Data")

    edited_df = st.data_editor(
        st.session_state["bill_data"],
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
    )

    st.session_state["bill_data"] = edited_df

    st.download_button(
        label="Download CSV",
        data=edited_df.to_csv(index=False).encode("utf-8"),
        mime="text/csv",
        file_name="bisleri_billing_data.csv",
    )
