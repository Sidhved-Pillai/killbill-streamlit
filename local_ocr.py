"""Offline OCR and deterministic parsing for the Bisleri invoice template."""

import io
import re
from difflib import get_close_matches
from datetime import datetime
from functools import lru_cache

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

from freight_master import normalize_loading_point


DATE_PATTERN = re.compile(r"(?<!\d)(\d{1,2})\s*[-./]\s*(\d{1,2})\s*[-./]\s*(\d{2,4})(?!\d)")
INVOICE_PATTERN = re.compile(r"MUMC[I1]N[0-9A-Z]{6,}", re.IGNORECASE)
CUSTOMER_PATTERN = re.compile(r"MUMC[0-9A-Z]{5,}", re.IGNORECASE)
VEHICLE_PATTERN = re.compile(r"MH\s*0?4\s*[A-Z]{1,3}\s*\d{3,4}", re.IGNORECASE)
NUMBER_PATTERN = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*$")


@lru_cache(maxsize=1)
def get_ocr_engine():
    from rapidocr import RapidOCR

    return RapidOCR(params={"Global.log_level": "error"})


def _clean_identifier(value):
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def _normalize_date(match):
    day, month, year = match.groups()
    if len(year) == 2:
        year = f"20{year}"
    try:
        return datetime(int(year), int(month), int(day)).strftime("%d-%b-%y")
    except ValueError:
        return ""


def _normalize_invoice_number(value):
    normalized = _clean_identifier(value).replace("MUMC1N", "MUMCIN")
    if not normalized.startswith("MUMCIN"):
        return normalized
    replacements = str.maketrans({"O": "0", "Q": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "G": "6", "T": "7", "B": "8"})
    digits = normalized[6:].translate(replacements)
    # Current Bisleri invoice numbers in this system consistently begin 2700;
    # OCR commonly reads that fourth digit as G/6 on faint photographs.
    if digits.startswith("270") and len(digits) >= 4:
        digits = digits[:3] + "0" + digits[4:]
    return "MUMCIN" + digits


def _find_pattern(texts, pattern, transform=_clean_identifier):
    for text in texts:
        match = pattern.search(str(text))
        if match:
            return transform(match.group())
    return ""


def _box_center(box):
    points = np.asarray(box)
    return float(points[:, 0].mean()), float(points[:, 1].mean())


def _extract_quantities(texts, boxes, image_width):
    qty_headers = [
        _box_center(box)
        for text, box in zip(texts, boxes)
        if re.fullmatch(r"Q(?:TY|ty)", str(text).strip(), re.IGNORECASE)
    ]
    total_rows = [
        _box_center(box)[1]
        for text, box in zip(texts, boxes)
        if str(text).strip().upper() == "TOTAL"
        or str(text).strip().upper().endswith("VALUE")
    ]
    if not qty_headers:
        return 0, 0

    qty_x, header_y = qty_headers[0]
    total_y = min(
        (y for y in total_rows if y > header_y),
        default=max((_box_center(box)[1] for box in boxes), default=header_y) + 1,
    )

    case_total = 0.0
    jar_total = 0.0
    for text, box in zip(texts, boxes):
        x, y = _box_center(box)
        number_match = NUMBER_PATTERN.fullmatch(str(text).replace(",", ""))
        if (
            not number_match
            or not header_y < y < total_y
            or abs(x - qty_x) > image_width * 0.075
        ):
            continue

        quantity = float(number_match.group(1).replace(",", "."))
        nearby_description = " ".join(
            str(other_text)
            for other_text, other_box in zip(texts, boxes)
            if _box_center(other_box)[0] < qty_x
            and abs(_box_center(other_box)[1] - y) < 25
        )
        normalized_description = re.sub(r"[^A-Z0-9]", "", nearby_description.upper())
        if "TOTAL" in normalized_description:
            continue
        if not any(token in normalized_description for token in ("WATER", "LTR", "BISW")):
            continue
        if "20LTR" in normalized_description or "20LTR" in normalized_description.replace("I", "1"):
            jar_total += quantity
        else:
            case_total += quantity

    def tidy(value):
        return int(value) if value == int(value) else value

    return tidy(case_total), tidy(jar_total)


def _extract_stamped_cases(texts, boxes, image_height):
    case_labels = [
        _box_center(box)
        for text, box in zip(texts, boxes)
        if _clean_identifier(text).startswith("CASE")
        and _box_center(box)[1] > image_height * 0.70
    ]
    candidates = []
    for label_x, label_y in case_labels:
        for text, box in zip(texts, boxes):
            x, y = _box_center(box)
            match = re.fullmatch(r"\s*(\d{1,4})\s*", str(text))
            if match and label_x - 280 < x < label_x and abs(y - label_y) < 65:
                candidates.append((abs(y - label_y) + abs(x - label_x) / 5, int(match.group(1))))
    return min(candidates)[1] if candidates else 0


def parse_ocr_result(
    texts,
    boxes,
    image_size,
    header_texts=(),
    table_texts=None,
    table_boxes=None,
    table_width=None,
):
    """Convert positioned OCR lines into one invoice record."""
    texts = tuple(str(text) for text in texts)
    combined_header = tuple(str(text) for text in header_texts) + texts

    invoice_number = _find_pattern(combined_header, INVOICE_PATTERN, _normalize_invoice_number)
    vehicle_number = _find_pattern(combined_header, VEHICLE_PATTERN)
    customer_lines = [text for text in texts if "CUSTOMER" in text.upper() and "CODE" in text.upper()]
    customer_code = _find_pattern(customer_lines, CUSTOMER_PATTERN)
    if not customer_code:
        customer_candidates = [
            text for text in texts if "MUMCIN" not in _clean_identifier(text)
        ]
        customer_code = _find_pattern(customer_candidates, CUSTOMER_PATTERN)

    invoice_date = ""
    prioritized_dates = [text for text in header_texts if "DATE" in str(text).upper()]
    for text in prioritized_dates + list(header_texts):
        match = DATE_PATTERN.search(str(text))
        if match:
            invoice_date = _normalize_date(match)
            if invoice_date:
                break

    joined_text = " ".join(texts)
    loading_point = normalize_loading_point(joined_text)
    case_quantity, jar_quantity = _extract_quantities(
        table_texts if table_texts is not None else texts,
        table_boxes if table_boxes is not None else boxes,
        table_width if table_width is not None else image_size[0],
    )
    stamped_cases = _extract_stamped_cases(texts, boxes, image_size[1])
    if stamped_cases:
        case_quantity = stamped_cases

    missing = []
    for label, value in (
        ("invoice number", invoice_number),
        ("invoice date", invoice_date),
        ("vehicle number", vehicle_number),
        ("customer code", customer_code),
        ("loading point", loading_point),
    ):
        if not value:
            missing.append(label)
    if not case_quantity and not jar_quantity:
        missing.append("item quantities")

    return {
        "Date": invoice_date,
        "Invoice No.": invoice_number,
        "Vehicle No.": vehicle_number,
        "From": loading_point or "",
        "Loading Point": loading_point,
        "Customer Code": customer_code,
        "Customer Name": "",
        "To": "",
        "Vehicle Type": "9MT",
        "Case": case_quantity,
        "Jar": jar_quantity,
    }, missing


def extract_invoice(uploaded_file):
    """OCR one uploaded invoice locally without network access."""
    image = Image.open(io.BytesIO(uploaded_file.getvalue())).convert("RGB")
    if image.width > image.height:
        image = image.rotate(90, expand=True)
    engine = get_ocr_engine()
    full_result = engine(np.asarray(image))
    if not full_result.txts:
        raise ValueError("No printed text could be read from this image.")

    width, height = image.size
    header = image.crop((int(width * 0.42), 0, int(width * 0.90), int(height * 0.25)))
    header = header.resize((header.width * 4, header.height * 4))
    header = ImageEnhance.Contrast(header).enhance(1.8).filter(ImageFilter.SHARPEN)
    header_result = engine(np.asarray(header))

    table = image.crop(
        (int(width * 0.05), int(height * 0.34), int(width * 0.95), int(height * 0.55))
    )
    table = table.resize((table.width * 3, table.height * 3))
    table = ImageEnhance.Contrast(table).enhance(2).filter(ImageFilter.SHARPEN)
    table_result = engine(np.asarray(table))

    return parse_ocr_result(
        full_result.txts,
        full_result.boxes,
        image.size,
        header_result.txts or (),
        table_result.txts or (),
        table_result.boxes if table_result.txts else (),
        table.width,
    )


def merge_invoice_pages(records, customer_codes=None):
    """Merge multiple photographed pages belonging to the same invoice."""
    merged = {}
    order = []
    for record in records:
        key = record.get("Invoice No.") or f"__page_{len(order)}"
        if key not in merged:
            merged[key] = record.copy()
            order.append(key)
            continue
        target = merged[key]
        for field in ("Date", "Vehicle No.", "From", "Loading Point", "Customer Code"):
            if not target.get(field) and record.get(field):
                target[field] = record[field]
        if customer_codes:
            target_code = target.get("Customer Code", "")
            record_code = record.get("Customer Code", "")
            if target_code not in customer_codes and record_code in customer_codes:
                target["Customer Code"] = record_code
        target["Case"] = (target.get("Case") or 0) + (record.get("Case") or 0)
        target["Jar"] = (target.get("Jar") or 0) + (record.get("Jar") or 0)

    merged_records = [merged[key] for key in order]
    years = []
    for record in merged_records:
        try:
            years.append(datetime.strptime(record["Date"], "%d-%b-%y").year)
        except (KeyError, TypeError, ValueError):
            pass
    if years:
        modal_year = max(set(years), key=years.count)
        for record in merged_records:
            try:
                parsed = datetime.strptime(record["Date"], "%d-%b-%y")
            except (KeyError, TypeError, ValueError):
                continue
            if parsed.year != modal_year:
                record["Date"] = parsed.replace(year=modal_year).strftime("%d-%b-%y")
    if customer_codes:
        for record in merged_records:
            code = record.get("Customer Code", "")
            if code and code not in customer_codes:
                matches = get_close_matches(code, customer_codes, n=1, cutoff=0.82)
                if matches:
                    record["Customer Code"] = matches[0]
    return merged_records


def extract_invoices(uploaded_files, progress_callback=None, customer_codes=None):
    records = []
    processed_files = []
    failed_files = []
    total = len(uploaded_files)
    for index, uploaded_file in enumerate(uploaded_files, start=1):
        try:
            record, missing = extract_invoice(uploaded_file)
            record["_source_file"] = uploaded_file
            records.append(record)
            processed_files.append(uploaded_file)
        except Exception as error:
            failed_files.append((uploaded_file, error))
        if progress_callback:
            progress_callback(index, total, uploaded_file.name)
    merged_records = merge_invoice_pages(records, customer_codes)
    warnings = []
    for record in merged_records:
        source_file = record.pop("_source_file", None)
        missing = [
            label
            for label, value in (
                ("invoice number", record.get("Invoice No.")),
                ("invoice date", record.get("Date")),
                ("vehicle number", record.get("Vehicle No.")),
                ("customer code", record.get("Customer Code")),
                ("loading point", record.get("Loading Point")),
            )
            if not value
        ]
        if not record.get("Case") and not record.get("Jar"):
            missing.append("item quantities")
        if missing and source_file is not None:
            warnings.append((source_file, missing))
    return merged_records, processed_files, warnings, failed_files
