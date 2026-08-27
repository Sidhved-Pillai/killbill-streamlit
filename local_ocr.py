"""Lightweight, offline OCR for the fixed Bisleri invoice layout."""

import io
import re
from collections import Counter
from datetime import datetime
from difflib import get_close_matches

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from freight_master import normalize_loading_point


DATE_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[-./]\s*(\d{1,2})\s*[-./]\s*(\d{2,4})(?!\d)")
INVOICE_RE = re.compile(r"MUMC[I1]N[0-9A-Z]{6,}", re.I)
CUSTOMER_RE = re.compile(r"MUMC(?![I1]N)[0-9A-Z]{5,}", re.I)
VEHICLE_RE = re.compile(r"MH\s*0?4\s*[A-Z]{1,3}\s*\d{3,4}", re.I)


def _identifier(value):
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def _invoice_number(value):
    value = _identifier(value).replace("MUMC1N", "MUMCIN")
    tail = value[6:].translate(str.maketrans("OQILZSGTB", "001125678"))
    if tail.startswith("270") and len(tail) >= 4:
        tail = tail[:3] + "0" + tail[4:]
    return "MUMCIN" + tail


def _date(value):
    match = DATE_RE.search(value)
    if not match:
        return ""
    day, month, year = match.groups()
    year = f"20{year}" if len(year) == 2 else year
    try:
        return datetime(int(year), int(month), int(day)).strftime("%d-%b-%y")
    except ValueError:
        return ""


def _prepare(image, scale=2, contrast=2.0):
    image = ImageOps.grayscale(image)
    image = ImageOps.autocontrast(image)
    image = ImageEnhance.Contrast(image).enhance(contrast)
    image = image.filter(ImageFilter.SHARPEN)
    return image.resize((image.width * scale, image.height * scale))


def _ocr_lines(image, psm=6):
    import pytesseract
    from pytesseract import Output

    data = pytesseract.image_to_data(
        image,
        output_type=Output.DICT,
        config=f"--oem 1 --psm {psm}",
        lang="eng",
    )
    grouped = {}
    for index, text in enumerate(data["text"]):
        text = str(text).strip()
        try:
            confidence = float(data["conf"][index])
        except (TypeError, ValueError):
            confidence = -1
        if not text or confidence < 15:
            continue
        key = (data["block_num"][index], data["par_num"][index], data["line_num"][index])
        grouped.setdefault(key, []).append(
            {
                "text": text,
                "x": int(data["left"][index]),
                "y": int(data["top"][index]),
                "width": int(data["width"][index]),
                "height": int(data["height"][index]),
            }
        )
    lines = []
    for words in grouped.values():
        words.sort(key=lambda word: word["x"])
        lines.append(
            {
                "text": " ".join(word["text"] for word in words),
                "words": words,
                "y": sum(word["y"] + word["height"] / 2 for word in words) / len(words),
            }
        )
    return sorted(lines, key=lambda line: line["y"])


def _first_match(lines, pattern, transform=_identifier):
    for line in lines:
        match = pattern.search(line["text"])
        if match:
            return transform(match.group())
    return ""


def _quantities(table_lines):
    qty_x = None
    for line in table_lines:
        for word in line["words"]:
            if re.fullmatch(r"[QO0]TY", _identifier(word["text"])):
                qty_x = word["x"] + word["width"] / 2
                break
        if qty_x is not None:
            break
    if qty_x is None:
        return 0, 0

    cases = 0.0
    jars = 0.0
    for line in table_lines:
        normalized = _identifier(line["text"])
        if not any(token in normalized for token in ("WATER", "LTR", "BISW")):
            continue
        candidates = []
        for word in line["words"]:
            center = word["x"] + word["width"] / 2
            match = re.fullmatch(r"(\d+(?:[.,]\d+)?)", word["text"].replace(" ", ""))
            if match and abs(center - qty_x) < 180:
                candidates.append((abs(center - qty_x), float(match.group(1).replace(",", "."))))
        if not candidates:
            continue
        quantity = min(candidates)[1]
        if "20LTR" in normalized:
            jars += quantity
        else:
            cases += quantity

    def tidy(value):
        return int(value) if value == int(value) else value

    return tidy(cases), tidy(jars)


def extract_invoice(uploaded_file):
    image = Image.open(io.BytesIO(uploaded_file.getvalue())).convert("RGB")
    if image.width > image.height:
        image = image.rotate(90, expand=True)
    width, height = image.size

    header = _prepare(image.crop((int(width * 0.40), 0, int(width * 0.92), int(height * 0.26))), 3)
    address = _prepare(image.crop((0, int(height * 0.14), width, int(height * 0.44))), 2)
    table = _prepare(image.crop((int(width * 0.03), int(height * 0.32), int(width * 0.97), int(height * 0.72))), 3, 2.4)

    header_lines = _ocr_lines(header)
    address_lines = _ocr_lines(address)
    table_lines = _ocr_lines(table)
    all_lines = header_lines + address_lines

    invoice = _first_match(header_lines, INVOICE_RE, _invoice_number)
    vehicle = _first_match(header_lines, VEHICLE_RE)
    customer_lines = [line for line in address_lines if "CUSTOMER" in line["text"].upper()]
    customer = _first_match(customer_lines or address_lines, CUSTOMER_RE)
    invoice_date = ""
    for line in header_lines:
        if "DATE" in line["text"].upper():
            invoice_date = _date(line["text"])
            if invoice_date:
                break
    origin = normalize_loading_point(" ".join(line["text"] for line in address_lines)) or ""
    cases, jars = _quantities(table_lines)

    record = {
        "Date": invoice_date,
        "Invoice No.": invoice,
        "Vehicle No.": vehicle,
        "From": origin,
        "Loading Point": origin or None,
        "Customer Code": customer,
        "Customer Name": "",
        "To": "",
        "Vehicle Type": "9MT",
        "Case": cases,
        "Jar": jars,
    }
    return record


def _merge_pages(records, customer_codes=None):
    merged = {}
    order = []
    for record in records:
        key = record["Invoice No."] or f"__unknown_{len(order)}"
        if key not in merged:
            merged[key] = record.copy()
            order.append(key)
            continue
        target = merged[key]
        if record.get("Date") and target.get("Date"):
            try:
                current_date = datetime.strptime(target["Date"], "%d-%b-%y")
                candidate_date = datetime.strptime(record["Date"], "%d-%b-%y")
                if candidate_date.year > current_date.year:
                    target["Date"] = record["Date"]
            except ValueError:
                pass
        for field in ("Date", "Vehicle No.", "From", "Loading Point", "Customer Code"):
            target[field] = target.get(field) or record.get(field)
        target["Case"] += record.get("Case", 0)
        target["Jar"] += record.get("Jar", 0)

    result = [merged[key] for key in order]
    years = []
    for record in result:
        try:
            years.append(datetime.strptime(record["Date"], "%d-%b-%y").year)
        except (TypeError, ValueError):
            pass
    if years:
        year = Counter(years).most_common(1)[0][0]
        for record in result:
            try:
                parsed = datetime.strptime(record["Date"], "%d-%b-%y")
                if parsed.year != year:
                    record["Date"] = parsed.replace(year=year).strftime("%d-%b-%y")
            except (TypeError, ValueError):
                pass
    if customer_codes:
        for record in result:
            code = record["Customer Code"]
            if code and code not in customer_codes:
                matches = get_close_matches(code, customer_codes, n=1, cutoff=0.82)
                if matches:
                    record["Customer Code"] = matches[0]
    return result


def extract_invoices(uploaded_files, progress_callback=None, customer_codes=None):
    records, processed, failed = [], [], []
    for index, uploaded_file in enumerate(uploaded_files, 1):
        try:
            records.append(extract_invoice(uploaded_file))
            processed.append(uploaded_file)
        except Exception as error:
            failed.append((uploaded_file, error))
        if progress_callback:
            progress_callback(index, len(uploaded_files), uploaded_file.name)
    merged = _merge_pages(records, customer_codes)
    warnings = []
    return merged, processed, warnings, failed
