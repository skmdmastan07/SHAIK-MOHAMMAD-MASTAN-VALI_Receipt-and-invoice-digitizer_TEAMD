import json
import requests
import re
import cv2
import numpy as np
from paddleocr import PaddleOCR


# ================================
# LOAD OCR MODEL
# ================================
ocr_model = PaddleOCR(use_angle_cls=True, lang='en')


# ================================
# PDF → IMAGE CONVERSION
# ================================
def pdf_to_image(pdf_path):
    """Convert first page of PDF to a cv2 image array."""
    try:
        import fitz  # pip install pymupdf
        doc = fitz.open(pdf_path)
        page = doc[0]
        pix = page.get_pixmap(dpi=300)
        img_array = np.frombuffer(pix.tobytes(), dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        doc.close()
        return img
    except ImportError:
        print("❌ PyMuPDF not installed. Run: pip install pymupdf")
        return None
    except Exception as e:
        print(f"❌ PDF conversion error: {e}")
        return None


# ================================
# PARSE PADDLEOCR RESULT
# Handles PaddleOCR 3.x (rec_texts dict) and 2.x (nested list) formats
# ================================
def parse_ocr_result(result):
    text = ""

    if not result:
        return text

    try:
        for item in result:

            # ---- PaddleOCR 3.x format ----
            if isinstance(item, dict) and "rec_texts" in item:
                for t in item["rec_texts"]:
                    text += str(t).strip() + "\n"

            # ---- PaddleOCR 2.x format ----
            elif isinstance(item, list):
                for word in item:
                    if isinstance(word, (list, tuple)) and len(word) >= 2:
                        part = word[1]
                        if isinstance(part, (list, tuple)) and len(part) >= 1:
                            text += str(part[0]) + "\n"
                        elif isinstance(part, str):
                            text += part + "\n"

    except Exception as e:
        print("OCR PARSE ERROR:", e)

    return text.strip()


# ================================
# OCR FUNCTION
# ================================
def perform_ocr(image_path):

    print(f"\n📄 Reading Invoice: {image_path}")

    if image_path.lower().endswith(".pdf"):
        img = pdf_to_image(image_path)
        if img is None:
            print("❌ Could not convert PDF to image")
            return ""
        result = ocr_model.ocr(img)
    else:
        result = ocr_model.ocr(image_path)

    text = parse_ocr_result(result)

    print("\n🔍 PADDLE OCR TEXT:\n", text)
    return text


# ================================
# TOTAL DETECTION
# Supports comma-formatted numbers like 48,085.00
# ================================
def extract_total_from_keywords(text):
    patterns = [
        r"(TOTAL\s*AMOUNT)[^\d]*([\d,]+(?:\.\d{2})?)",
        r"(NET\s*AMOUNT)[^\d]*([\d,]+(?:\.\d{2})?)",
        r"(GRAND\s*TOTAL)[^\d]*([\d,]+(?:\.\d{2})?)",
        r"(AMOUNT\s*PAYABLE)[^\d]*([\d,]+(?:\.\d{2})?)",
        r"(FINAL\s*AMOUNT)[^\d]*([\d,]+(?:\.\d{2})?)",
        r"(BILL\s*AMOUNT)[^\d]*([\d,]+(?:\.\d{2})?)",
        r"(SUB\s*TOTAL)[^\d]*([\d,]+(?:\.\d{2})?)",
        r"(TOTAL)[^\d]*([\d,]+(?:\.\d{2})?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(2).replace(",", "")
    return None


# ================================
# TAX DETECTION FROM RAW OCR TEXT
# Handles both same-line and split-line bill formats
# ================================
def extract_tax_from_text(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    number_pattern = re.compile(r"^[\d,]+(?:\.\d{2})?$")
    tax_label_pattern = re.compile(r"(CGST|SGST|GST|TAX)", re.IGNORECASE)

    # Pattern 1: label and value on the SAME line (no newline crossing)
    # e.g. "CGST: 450.00" or "GST: 7,355.00"
    # Uses re.MULTILINE so ^ and $ match line boundaries;
    # does NOT use re.DOTALL so . won't cross newlines
    same_line = re.search(
        r"(?:CGST|SGST|GST|TAX)[^:\n]*:\s*([0-9][0-9,]*(?:\.[0-9]{2})?)\s*$",
        text,
        re.IGNORECASE | re.MULTILINE
    )
    if same_line:
        print(f"🧾 Tax (same-line): {same_line.group(1)}")
        return same_line.group(1).replace(",", "")

    # Pattern 2: value is on the line BEFORE the label (split-line format)
    # e.g.:
    #   "7,355.00"   ← tax value
    #   "GST @ 18%:" ← label on next line
    for i, line in enumerate(lines):
        if tax_label_pattern.search(line) and i > 0:
            prev = lines[i - 1]
            if number_pattern.match(prev):
                print(f"🧾 Tax (split-line, line before '{line}'): {prev}")
                return prev.replace(",", "")

    return None


# ================================
# MISTRAL EXTRACTION
# ================================
def run_mistral(text):

    if not text or not text.strip():
        print("⚠️  Skipping Mistral — OCR text is empty")
        return {}

    prompt = f"""
You are an invoice data extractor. Extract ONLY these fields from the invoice text.

FIELD DEFINITIONS:
- Vendor: The business/company name only. Pick the clearest single name (e.g. "Kajaria Ceramics"). Do NOT repeat or combine multiple lines.
- Invoice Number: The bill/invoice number. Look for labels like "Bill No", "Invoice No", "Receipt No".
- Date: The invoice date. Look for labels like "Date:". Format as found.
- Total Amount: The FINAL payable amount. Look for "Total Amount", "Grand Total", "Net Amount", "Amount Payable". Do NOT use Subtotal.
- CGST: CGST tax amount only. Null if not present.
- SGST: SGST tax amount only. Null if not present.
- GST: The GST amount only. Null if not present.

RULES:
- Return ONLY valid JSON. No explanation, no markdown, no extra text.
- If a field is not found, use null.
- Numbers may have commas (e.g. 48,085.00) — extract as-is.
- Vendor must be a SHORT clean name, not a concatenation of multiple lines.
- Note: In some bills the value appears on the line BEFORE its label. Read carefully.

{{
  "Vendor": "",
  "Invoice Number": "",
  "Date": "",
  "Total Amount": "",
  "CGST": "",
  "SGST": "",
  "GST": ""
}}

INVOICE TEXT (each line is a separate OCR-detected text block):
{text}
"""

    url = "http://127.0.0.1:11434/api/generate"

    payload = {
        "model": "mistral",
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0}
    }

    try:
        response = requests.post(url, json=payload, timeout=120)
        raw_output = response.json()["response"]

        print("\n🧠 MISTRAL RAW OUTPUT:\n", raw_output)

        start = raw_output.find("{")
        end = raw_output.rfind("}") + 1
        json_text = raw_output[start:end]

        return json.loads(json_text)

    except requests.exceptions.ConnectionError:
        print("❌ Mistral error — Ollama not running. Start with: ollama serve")
        return {}

    except Exception as e:
        print(f"❌ Mistral extraction error: {e}")
        return {}


# ================================
# MAIN EXTRACTION FUNCTION
# ================================
def extract_invoice_details(text):

    data = run_mistral(text)

    vendor  = data.get("Vendor")
    invoice = data.get("Invoice Number")
    date    = data.get("Date")

    # Total: prefer Mistral, fall back to regex
    mistral_total = data.get("Total Amount")
    if mistral_total:
        total = str(mistral_total).replace(",", "")
    else:
        total = extract_total_from_keywords(text)

    # Tax: always use regex on raw OCR text as source of truth
    # Avoids Mistral hallucinating tax values on split-line bills
    tax_from_text = extract_tax_from_text(text)

    if tax_from_text:
        tax = tax_from_text
    else:
        cgst = data.get("CGST")
        sgst = data.get("SGST")
        gst  = data.get("GST")
        try:
            if cgst and sgst:
                tax = str(float(str(cgst).replace(",", "")) + float(str(sgst).replace(",", "")))
            elif gst:
                tax = str(gst).replace(",", "")
            else:
                tax = "N/A"
        except Exception:
            tax = "N/A"

    final_data = {
        "Vendor":         vendor,
        "Invoice Number": invoice,
        "Date":           date,
        "Total Amount":   total,
        "Tax":            tax
    }

    print("\n✅ FINAL EXTRACTED DATA:\n", final_data)
    return final_data