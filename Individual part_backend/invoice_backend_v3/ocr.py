import json
import requests
import re

ocr_model = None


# ================================
# OCR FUNCTION
# ================================
def perform_ocr(image_path):

    global ocr_model

    if ocr_model is None:
        from paddleocr import PaddleOCR
        ocr_model = PaddleOCR(use_angle_cls=True, lang='en', show_log=False)

    print("\n📄 Reading Invoice:", image_path)

    import cv2
    img = cv2.imread(image_path)

    if img is None:
        print("❌ Image Not Found!")
        return ""

    result = ocr_model.ocr(img, cls=True)

    extracted_text = ""

    for line in result:
        for word in line:
            extracted_text += word[1][0] + " "

    print("\n🔍 PADDLE OCR TEXT:\n", extracted_text)

    return extracted_text


# ================================
# TOTAL ANCHOR PICKER
# ================================
def extract_total_from_keywords(text):

    patterns = [
        r"(NET\s*AMOUNT)[^\d]*(\d{2,7}\.\d{2})",
        r"(GRAND\s*TOTAL)[^\d]*(\d{2,7}\.\d{2})",
        r"(AMOUNT\s*PAYABLE)[^\d]*(\d{2,7}\.\d{2})",
        r"(FINAL\s*AMOUNT)[^\d]*(\d{2,7}\.\d{2})",
        r"(BILL\s*AMOUNT)[^\d]*(\d{2,7}\.\d{2})",
        r"\b(Sub)[^\d]*(\d{2,7}\.\d{2})",
        r"(TOTAL)[^\d]*(\d{2,7}\.\d{2})"
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(2)

    return None


# ================================
# MISTRAL EXTRACTION
# ================================
def run_mistral(text):

    prompt = f"""
Extract:

Vendor
Invoice Number
Date
CGST
SGST
GST

STRICTLY RESPOND ONLY IN VALID JSON FORMAT:

{{
"Vendor":"",
"Invoice Number":"",
"Date":"",
"CGST":"",
"SGST":"",
"GST":""
}}

OCR TEXT:
{text}
"""

    url = "http://127.0.0.1:11434/api/generate"

    payload = {
        "model": "mistral",
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0
        }
    }

    response = requests.post(url, json=payload, timeout=120)

    raw_output = response.json()["response"]

    print("\n🧠 MISTRAL RAW OUTPUT:\n", raw_output)

    try:
        start = raw_output.find("{")
        end = raw_output.rfind("}") + 1
        json_text = raw_output[start:end]
        return json.loads(json_text)
    except:
        return {}


# ================================
# MAIN FUNCTION
# ================================
def extract_invoice_details(text):

    data = run_mistral(text)

    vendor = data.get("Vendor")
    invoice = data.get("Invoice Number")
    date = data.get("Date")

    total = extract_total_from_keywords(text)

    cgst = data.get("CGST")
    sgst = data.get("SGST")
    gst = data.get("GST")

    try:
        if cgst and sgst:
            tax = str(float(cgst) + float(sgst))
        elif gst:
            tax = gst
        else:
            tax = "N/A"
    except:
        tax = "N/A"

    final_data = {
        "Vendor": vendor,
        "Invoice Number": invoice,
        "Date": date,
        "Total Amount": total,
        "Tax": tax
    }

    print("\n✅ FINAL EXTRACTED DATA:\n", final_data)

    return final_data