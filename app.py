import io
import json
import os
import re
import time
from typing import List, Dict, Any, Optional

import pandas as pd
import streamlit as st
from PIL import Image

try:
    from google import genai
    from google.genai import types
except Exception:
    genai = None

# Configuration
COLUMNS = [
    "Sr No.",
    "Date",
    "Invoice No.",
    "Vehicle No.",
    "From",
    "Customer Name",
    "To",
    "Vehicle Type",
    "Case",
    "Jar",
    "Freight Charges",
]

FREIGHT_MATRIX_CSV = "FRIEGHT M1  M2 Trip matrix Master File NEW.xlsx - HIKE M2 KM TRIP MATRIX.csv"

MIME_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "pdf": "application/pdf"}


def _resolve_api_key():
    try:
        return os.getenv("GOOGLE_API_KEY") or os.getenv("GENAI_API_KEY") or st.secrets.get("GOOGLE_API_KEY", "")
    except Exception:
        return os.getenv("GOOGLE_API_KEY") or os.getenv("GENAI_API_KEY") or ""


API_KEY = _resolve_api_key()


def file_to_part(uploaded_file):
    file_bytes = uploaded_file.getvalue()
    extension = uploaded_file.name.rsplit(".", 1)[-1].lower()
    mime_type = MIME_TYPES.get(extension, "application/octet-stream")

    if extension in {"png", "jpg", "jpeg"}:
        Image.open(io.BytesIO(file_bytes))
    return types.Part.from_bytes(data=file_bytes, mime_type=mime_type)


def extract_json_text(raw_text: str) -> str:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def parse_item_quantity(item: Dict[str, Any]) -> float:
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


def _normalize_unit(unit: Any) -> str:
    if not unit:
        return ""
    return str(unit).strip().lower()


def is_jar_item(description: str) -> bool:
    normalized = description.lower().replace(" ", "")
    return "20ltr" in normalized or re.search(r"\d+\s*ltr", description.lower())


def is_case_item(description: str) -> bool:
    normalized = description.lower()
    return "ml" in normalized and not is_jar_item(description)


def _extract_items(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = record.get("items") or record.get("line_items") or record.get("details")
    if not isinstance(items, list):
        return []
    extracted = []
    for item in items:
        if not isinstance(item, dict):
            continue
        description = str(item.get("description", item.get("item", ""))).strip()
        quantity = parse_item_quantity(item)
        unit = str(item.get("unit", item.get("uom", item.get("uom_code", "")))).strip()
        extracted.append({"description": description, "quantity": quantity, "unit": unit})
    return extracted


def apply_case_jar_logic(record: Dict[str, Any]) -> Dict[str, Any]:
    case_qty = 0.0
    jar_qty = 0.0
    review_flag = False
    items = _extract_items(record)

    if items:
        for item in items:
            description = item.get("description", "")
            quantity = item.get("quantity", 0.0)
            unit = _normalize_unit(item.get("unit", ""))
            desc_low = description.lower()
            # skip footer/total lines
            if any(tok in desc_low for tok in ("total", "subtotal", "gross", "amount", "net", "balance", "round")):
                continue
            if is_jar_item(description) or "ltr" in unit or "ltr" in desc_low:
                jar_qty += quantity
            elif is_case_item(description) or "ml" in unit or "ml" in desc_low:
                case_qty += quantity
            else:
                if quantity and quantity != 0:
                    review_flag = True
    else:
        try:
            case_qty = float(record.get("Case", 0) or 0)
        except (TypeError, ValueError):
            case_qty = 0.0
        try:
            jar_qty = float(record.get("Jar", 0) or 0)
        except (TypeError, ValueError):
            jar_qty = 0.0
        if case_qty > 0 and jar_qty > 0:
            review_flag = True

    return {
        "Date": record.get("Date", ""),
        "Invoice No.": record.get("Invoice No.", record.get("Invoice No", "")),
        "Vehicle No.": record.get("Vehicle No.", record.get("Vehicle No", "")),
        "From": record.get("From", ""),
        "Customer Name": record.get("Customer Name", ""),
        "To": record.get("To", ""),
        "Vehicle Type": record.get("Vehicle Type", "") or "9MT",
        "Case": float(case_qty or 0.0),
        "Jar": float(jar_qty or 0.0),
        "requires_review": review_flag or (case_qty > 0 and jar_qty > 0),
        "raw_items": items,
    }


SYSTEM_INSTRUCTION = """
You are auditing a combined batch of logistics delivery sheets for Ubiquity Transtech.
Scan all attached documents together and extract every single distinct trip row you find across all files.

Return ONLY a single valid JSON list of objects. Each object represents one invoice trip row and must contain at least these keys:
- "Date"
- "Invoice No."
- "Vehicle No."
- "From"
- "Customer Name"
- "To"
- "Vehicle Type"
- "Case"
- "Jar"

If you can include an optional "items" array for each invoice that contains underlying line item details with quantity and unit type.
Treat all attached documents as one consolidated batch and aggregate the final result across the whole upload.
If an item mentions "LTR" treat as Jar; if an item mentions "ML" treat as Case.
Do not include any markdown; return raw JSON only.
"""


def parse_gemini_response(raw_text: str) -> List[Dict[str, Any]]:
    payload = json.loads(extract_json_text(raw_text))
    if isinstance(payload, dict):
        payload = payload.get("trips") or payload.get("records") or payload.get("data") or [payload]
    if not isinstance(payload, list):
        raise ValueError("Gemini response must be a JSON array of trip records.")
    return [apply_case_jar_logic(record) for record in payload if isinstance(record, dict)]


def build_batch_content_parts(uploaded_files):
    content_parts = []
    for uploaded_file in uploaded_files:
        content_parts.append(types.Part.from_text(text=f"Document: {uploaded_file.name}"))
        content_parts.append(file_to_part(uploaded_file))
    return content_parts


def analyze_bills(uploaded_files):
    if genai is None:
        raise RuntimeError("google-genai not installed in this environment")
    if not API_KEY:
        raise ValueError("Missing API key. Set GOOGLE_API_KEY in the environment or add it to Streamlit secrets.")
    client = genai.Client(api_key=API_KEY)
    content_parts = build_batch_content_parts(uploaded_files)

    last_error = None
    for model_name in ["gemini-flash-lite-latest", "gemini-flash-latest"]:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=content_parts,
                config=types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION),
            )
            return parse_gemini_response(response.text)
        except Exception as e:
            last_error = e
            time.sleep(1)
            continue
    if last_error is not None:
        raise last_error
    return []


def load_freight_matrix(path: str) -> Optional[pd.DataFrame]:
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path)
        return df
    except Exception:
        try:
            return pd.read_excel(path)
        except Exception:
            return None


def find_customer_column(df: pd.DataFrame) -> str:
    candidates = [c for c in df.columns if re.search(r"customer|distributor|name", c, re.I)]
    return candidates[0] if candidates else df.columns[0]


def find_depot_column(df: pd.DataFrame, from_value: str) -> Optional[str]:
    # find column whose name appears in from_value
    if not isinstance(from_value, str):
        return None
    from_low = from_value.lower()
    depot_cols = [c for c in df.columns if c not in [find_customer_column(df)]]
    # prefer exact substring match
    for c in depot_cols:
        if c.lower() in from_low:
            return c
    # fallback: try tokens
    for token in ["thane", "mumbai", "vasai", "palghar"]:
        for c in depot_cols:
            if token in c.lower() and token in from_low:
                return c
    return None


def lookup_freight_for_row(master_df: pd.DataFrame, customer: str, from_loc: str) -> Optional[float]:
    if master_df is None or master_df.empty:
        return None
    cust_col = find_customer_column(master_df)
    # case-insensitive match exact or contains
    mask = master_df[cust_col].astype(str).str.strip().str.lower() == str(customer).strip().lower()
    if not mask.any():
        mask = master_df[cust_col].astype(str).str.lower().str.contains(str(customer).strip().lower(), na=False)
    if not mask.any():
        return None
    row = master_df[mask].iloc[0]
    depot_col = find_depot_column(master_df, from_loc)
    if depot_col is None:
        return None
    val = row.get(depot_col)
    if pd.isna(val) or val == "":
        return None
    try:
        return float(val)
    except Exception:
        return None


st.set_page_config(page_title="Project Kill Bill", layout="wide")

st.title("Project Kill Bill — Freight-aware Invoice Aggregator")

st.markdown("Upload bills (images or PDFs), process, and download an Excel report with Freight Charges.")

uploaded_files = st.file_uploader("Upload one or more bill images or PDFs", type=["png", "jpg", "jpeg", "pdf"], accept_multiple_files=True)

master_df = load_freight_matrix(FREIGHT_MATRIX_CSV)
if master_df is None:
    st.warning(f"Freight matrix file not found: {FREIGHT_MATRIX_CSV}. Freight lookups will be blank.")
else:
    st.success(f"Loaded freight matrix with {len(master_df)} rows from {FREIGHT_MATRIX_CSV}")

if st.button("Process Bills", disabled=(not uploaded_files)):
    with st.spinner("Processing bills and computing freight..."):
        try:
            records = analyze_bills(uploaded_files)
            if not records:
                st.error("No records extracted from the uploaded files.")
            df = pd.DataFrame(records)

            # ensure numeric
            for c in ("Case", "Jar"):
                if c not in df.columns:
                    df[c] = 0.0
                df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

            # normalize invoice
            df["Invoice No."] = df.get("Invoice No.", "").astype(str).str.strip()

            # Build invoice grouping key: trailing digits
            df["invoice_digits"] = df["Invoice No."].str.findall(r"\d+").apply(lambda parts: "".join(parts))
            df["invoice_group_key"] = df["invoice_digits"].str[-8:]
            df.loc[~df["invoice_group_key"].astype(bool), "invoice_group_key"] = (
                df.loc[~df["invoice_group_key"].astype(bool), "Invoice No."].str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)
            )

            # aggregate by invoice_group_key but merge raw_items
            agg_rows = []
            for key, group in df.groupby("invoice_group_key", dropna=False):
                first = group.iloc[0]
                merged_items = []
                for sub in group.get("raw_items", []):
                    if isinstance(sub, list):
                        merged_items.extend(sub)
                # sum Case/Jar from merged_items when possible
                case_sum = 0.0
                jar_sum = 0.0
                review_flag = False
                if merged_items:
                    for it in merged_items:
                        desc = str(it.get("description", "")).strip()
                        qty = parse_item_quantity(it)
                        u = _normalize_unit(it.get("unit", ""))
                        dlow = desc.lower()
                        if any(tok in dlow for tok in ("total", "subtotal", "gross", "amount", "net", "balance", "round")):
                            continue
                        if is_jar_item(desc) or "ltr" in u or "ltr" in dlow:
                            jar_sum += qty
                        elif is_case_item(desc) or "ml" in u or "ml" in dlow:
                            case_sum += qty
                        else:
                            if qty and qty != 0:
                                review_flag = True
                else:
                    case_sum = group["Case"].sum()
                    jar_sum = group["Jar"].sum()
                    review_flag = group["requires_review"].any() if "requires_review" in group.columns else False

                agg_rows.append({
                    "Date": first.get("Date", ""),
                    "Invoice No.": first.get("Invoice No.", ""),
                    "Vehicle No.": first.get("Vehicle No.", ""),
                    "From": first.get("From", ""),
                    "Customer Name": first.get("Customer Name", ""),
                    "To": first.get("To", ""),
                    "Vehicle Type": first.get("Vehicle Type", "") or "9MT",
                    "Case": case_sum,
                    "Jar": jar_sum,
                    "requires_review": review_flag or (case_sum > 0 and jar_sum > 0),
                    "raw_items": merged_items,
                })

            agg = pd.DataFrame(agg_rows)

            # lookup freight per aggregated row
            freight_vals = []
            for _, r in agg.iterrows():
                cust = r.get("Customer Name", "")
                from_loc = r.get("From", "")
                val = lookup_freight_for_row(master_df, cust, from_loc) if master_df is not None else None
                freight_vals.append(val)
            agg["Freight Charges"] = freight_vals

            # ensure Sr No.
            if "Sr No." not in agg.columns:
                agg.insert(0, "Sr No.", range(1, len(agg) + 1))

            # reorder to required COLUMNS
            final_cols = [c for c in COLUMNS if c in agg.columns]
            result_df = agg[final_cols].copy()

            # show styled dataframe highlighting blank freight
            def highlight_freight_missing(row):
                return ["background-color: #fff3b0" if (pd.isna(row.get("Freight Charges")) or row.get("Freight Charges") == "") else "" for _ in row]

            st.markdown("**Review & Edit Extracted Data**")
            styled = result_df.style.apply(highlight_freight_missing, axis=1)
            st.dataframe(styled, use_container_width=True)

            # editable grid (keeps same data)
            edited = st.data_editor(result_df, num_rows="dynamic", use_container_width=True, hide_index=True)
            st.session_state["bill_data"] = edited

            # Download as XLSX
            def to_xlsx_bytes(df_export: pd.DataFrame) -> bytes:
                out = io.BytesIO()
                try:
                    with pd.ExcelWriter(out, engine="openpyxl") as writer:
                        df_export.to_excel(writer, index=False, sheet_name="Bisleri Report")
                    return out.getvalue()
                except Exception:
                    return df_export.to_csv(index=False).encode("utf-8")

            st.download_button(label="Download Excel (.xlsx)", data=to_xlsx_bytes(edited), mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", file_name="Bisleri Report.xlsx")

            st.success("Processing complete. Blank Freight Charges rows are highlighted for manual entry.")

        except json.JSONDecodeError:
            st.error("Gemini returned invalid JSON. Please try processing again.")
        except Exception as error:
            st.error(f"Failed to process bills: {error}")

else:
    st.info("Upload files then click 'Process Bills' to begin.")
