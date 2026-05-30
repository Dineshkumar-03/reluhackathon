"""
Flask Backend — Company Enrichment API
Serves the frontend at / and provides:
  POST /enrich  → { "url": "...", "website_name": "..." }
  GET  /results → all enriched companies
"""

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests
import json
import re
import time
import os

from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from rapidfuzz import fuzz
from google import genai

# ── Config ───────────────────────────────────────────────────
app = Flask(__name__, static_folder="static")
CORS(app)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY_HERE")
client = genai.Client(api_key=GEMINI_API_KEY)

RESULTS_FILE = "results.json"

# ── Persistence ───────────────────────────────────────────────

def load_results():
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE) as f:
            return json.load(f)
    return []

def save_results(data):
    with open(RESULTS_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ── Scraping ─────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

RELEVANT_KEYWORDS = [
    "about", "contact", "services", "service",
    "solutions", "solution", "team", "company",
    "what-we-do", "who-we-are", "our-work"
]


def scrape_page(url, retries=2):
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=12)
            if r.status_code == 200:
                return _parse_html(r.text)
        except Exception as e:
            print(f"  Attempt {attempt+1} failed for {url}: {e}")
            time.sleep(1)
    return ""


def _parse_html(html):
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header",
                     "noscript", "iframe", "form", "aside"]):
        tag.decompose()
    for tag in soup.find_all(True):
        cls = " ".join(tag.get("class", []))
        tid = tag.get("id", "")
        noise = ["cookie", "popup", "modal", "banner", "overlay",
                 "newsletter", "subscribe", "gdpr"]
        if any(n in cls.lower() or n in tid.lower() for n in noise):
            tag.decompose()
    return soup.get_text(separator=" ", strip=True)


def clean_text(text, max_chars=6000):
    text = re.sub(r'\s+', ' ', text)
    return text.replace('\xa0', ' ').strip()[:max_chars]


def extract_emails(text):
    emails = re.findall(
        r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}', text
    )
    filtered = [
        e for e in set(emails)
        if not any(x in e.lower() for x in
                   ["example.com", "domain.com", "youremail", "test@"])
    ]
    return list(filtered)[:5]


def extract_phone(text):
    phones = re.findall(r'(\+?[\d][\d\s\-\(\)\.]{8,20})', text)
    for phone in phones:
        digits = re.sub(r"\D", "", phone)
        if 10 <= len(digits) <= 15:
            if not re.match(r'^(19|20)\d{2}$', digits[:4]):
                return phone.strip()
    return ""


def get_relevant_links(base_url, max_links=4):
    found = set()

    # Sitemap first
    try:
        sitemap_url = base_url.rstrip("/") + "/sitemap.xml"
        r = requests.get(sitemap_url, timeout=8, headers=HEADERS)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "lxml-xml")
            for loc in [l.text for l in soup.find_all("loc")]:
                path = urlparse(loc).path.lower().strip("/")
                for kw in RELEVANT_KEYWORDS:
                    if fuzz.partial_ratio(kw, path) >= 80:
                        found.add(loc)
                        break
    except Exception:
        pass

    # Homepage link extraction
    try:
        r = requests.get(base_url, timeout=10, headers=HEADERS)
        soup = BeautifulSoup(r.text, "lxml")
        base_domain = urlparse(base_url).netloc
        for a in soup.find_all("a", href=True):
            full_url = urljoin(base_url, a["href"].strip())
            if base_domain not in urlparse(full_url).netloc:
                continue
            path = urlparse(full_url).path.lower().strip("/")
            combined = path + " " + a.get_text(strip=True).lower()
            for kw in RELEVANT_KEYWORDS:
                if fuzz.partial_ratio(kw, combined) >= 75:
                    found.add(full_url)
                    break
    except Exception:
        pass

    return list(found)[:max_links]


def generate_insights(combined_text, url):
    prompt = f"""You are a B2B sales research analyst. Analyze the following company website text and extract business insights.

Website URL: {url}

Website Content:
{combined_text}

Return ONLY a valid JSON object with exactly these keys (no markdown, no explanation, no code fences):
{{
  "company_name": "Official company name",
  "core_service": "Primary product or service offering in one concise sentence",
  "target_customer": "Description of their ideal customer segment",
  "probable_pain_point": "The most likely business problem their customers face that this company solves",
  "outreach_opener": "A 2-sentence personalized cold outreach opener referencing specific details from their website"
}}

Rules:
- Do NOT invent contact details (emails, phones, addresses) - those are extracted separately
- Use the actual company name from the content, not a placeholder
- If a field truly cannot be determined, use "N/A"
- Keep each value under 100 words
- The outreach_opener must mention the company by name and reference a real detail from their site"""

    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        raw = response.text.strip()
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        data = json.loads(raw)
        for key in ["company_name", "core_service", "target_customer",
                    "probable_pain_point", "outreach_opener"]:
            if key not in data:
                data[key] = "N/A"
        return data
    except Exception as e:
        print(f"  Gemini error: {e}")
        return {k: "N/A" for k in ["company_name", "core_service",
                                    "target_customer", "probable_pain_point",
                                    "outreach_opener"]}


def enrich_company(url, website_name_override=""):
    print(f"\n[Enriching] {url}")

    try:
        domain = urlparse(url).netloc
        website_name = website_name_override or domain.replace("www.", "")
    except Exception:
        website_name = website_name_override or url

    all_texts = []
    home_text = scrape_page(url)
    if home_text:
        all_texts.append(clean_text(home_text, max_chars=3000))

    links = get_relevant_links(url)
    for link in links:
        time.sleep(0.4)
        page_text = scrape_page(link)
        if page_text:
            all_texts.append(clean_text(page_text, max_chars=2000))

    combined = " ".join(all_texts)

    emails = extract_emails(combined)
    phone  = extract_phone(combined)

    address = ""
    address_patterns = [
        r'\d{1,5}\s+\w[\w\s,\.]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Way|Court|Ct|Place|Pl)[,\s]+[\w\s,\.]{5,60}',
        r'[A-Z][a-z]+(?:\s[A-Z][a-z]+)*,\s*[A-Z]{2}\s+\d{5}',
    ]
    for pattern in address_patterns:
        m = re.search(pattern, combined)
        if m:
            address = m.group(0).strip()
            break
    if not address:
        for line in combined.split("  "):
            lower = line.lower()
            if any(kw in lower for kw in ["address:", "headquarters", "hq:", "located at"]):
                cleaned = line.strip()
                if 10 < len(cleaned) < 250:
                    address = cleaned
                    break

    ai_data = generate_insights(clean_text(combined, max_chars=5000), url)

    return {
        "website_name":        website_name,
        "company_name":        ai_data.get("company_name", "N/A"),
        "address":             address or "",
        "mobile_number":       phone or "",
        "mail":                emails,
        "core_service":        ai_data.get("core_service", "N/A"),
        "target_customer":     ai_data.get("target_customer", "N/A"),
        "probable_pain_point": ai_data.get("probable_pain_point", "N/A"),
        "outreach_opener":     ai_data.get("outreach_opener", "N/A"),
    }


# ── Routes ────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/enrich", methods=["POST"])
def enrich():
    body = request.get_json(silent=True) or {}
    url  = (body.get("url") or "").strip()
    name = (body.get("website_name") or "").strip()

    if not url:
        return jsonify({"error": "url is required"}), 400
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        result = enrich_company(url, website_name_override=name)
        all_results = load_results()
        idx = next(
            (i for i, r in enumerate(all_results)
             if r.get("website_name") == result["website_name"]),
            None
        )
        if idx is not None:
            all_results[idx] = result
        else:
            all_results.append(result)
        save_results(all_results)
        return jsonify(result), 200
    except Exception as e:
        print(f"[Error] {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/results", methods=["GET"])
def results():
    return jsonify(load_results()), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
