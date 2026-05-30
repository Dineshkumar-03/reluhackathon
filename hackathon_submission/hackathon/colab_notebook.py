# ============================================================
# CELL 1 — Install Dependencies
# ============================================================
# !pip install requests beautifulsoup4 rapidfuzz lxml google-genai

# ============================================================
# CELL 2 — Imports
# ============================================================
import requests
import json
import re
import time

from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from rapidfuzz import fuzz

# ============================================================
# CELL 3 — Gemini Setup
# ============================================================
from google import genai

# ⚠️  PASTE YOUR GEMINI API KEY HERE
GEMINI_API_KEY = "YOUR_GEMINI_API_KEY_HERE"

client = genai.Client(api_key=GEMINI_API_KEY)

# ============================================================
# CELL 4 — Scraping Helpers
# ============================================================

def scrape_page(url, retries=2):
    """Fetch a page and return cleaned text. Falls back through 3 strategies."""

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    for attempt in range(retries):
        try:
            # Strategy 1: Normal GET
            response = requests.get(url, headers=headers, timeout=12)
            if response.status_code == 200:
                return _parse_html(response.text)

            # Strategy 2: Try with session
            session = requests.Session()
            session.headers.update(headers)
            response = session.get(url, timeout=12)
            if response.status_code == 200:
                return _parse_html(response.text)

        except Exception as e:
            print(f"  Attempt {attempt+1} failed for {url}: {e}")
            time.sleep(1)

    # Strategy 3: Try stripping to bare domain
    try:
        parsed = urlparse(url)
        bare = f"{parsed.scheme}://{parsed.netloc}"
        r = requests.get(bare, headers=headers, timeout=10)
        return _parse_html(r.text)
    except Exception as e:
        print(f"  All strategies failed for {url}: {e}")
        return ""


def _parse_html(html):
    """Strip boilerplate and return readable text."""
    soup = BeautifulSoup(html, "lxml")

    # Remove noise elements
    for tag in soup(["script", "style", "nav", "footer", "header",
                     "noscript", "iframe", "form", "aside"]):
        tag.decompose()

    # Remove cookie banners / overlays by common class/id patterns
    for tag in soup.find_all(True):
        cls = " ".join(tag.get("class", []))
        tid = tag.get("id", "")
        noise = ["cookie", "popup", "modal", "banner", "overlay",
                 "newsletter", "subscribe", "gdpr"]
        if any(n in cls.lower() or n in tid.lower() for n in noise):
            tag.decompose()

    return soup.get_text(separator=" ", strip=True)


def clean_text(text, max_chars=6000):
    """Normalize whitespace and truncate for token efficiency."""
    text = re.sub(r'\s+', ' ', text)
    text = text.replace('\xa0', ' ').strip()
    return text[:max_chars]


def extract_emails(text):
    """Regex-based email extraction."""
    emails = re.findall(
        r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}',
        text
    )
    # Filter out obviously fake/placeholder emails
    filtered = [
        e for e in set(emails)
        if not any(x in e.lower() for x in
                   ["example.com", "domain.com", "youremail", "test@"])
    ]
    return list(filtered)[:5]   # cap at 5


def extract_phone(text):
    """Extract the most plausible phone number."""
    phones = re.findall(
        r'(\+?[\d][\d\s\-\(\)\.]{8,20})',
        text
    )
    for phone in phones:
        digits = re.sub(r"\D", "", phone)
        if 10 <= len(digits) <= 15:
            # Skip years (1900-2099)
            if not re.match(r'^(19|20)\d{2}$', digits[:4]):
                return phone.strip()
    return ""


# ============================================================
# CELL 5 — Smart Link Discovery
# ============================================================

RELEVANT_KEYWORDS = [
    "about", "contact", "services", "service",
    "solutions", "solution", "team", "company",
    "what-we-do", "who-we-are", "our-work", "careers"
]


def get_relevant_links(base_url, max_links=4):
    """
    Discover the most relevant internal pages via:
    1) Sitemap parsing
    2) Homepage link extraction + fuzzy matching
    """
    found = set()

    # --- Approach 1: sitemap.xml ---
    try:
        sitemap_url = base_url.rstrip("/") + "/sitemap.xml"
        r = requests.get(sitemap_url, timeout=8,
                         headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "lxml-xml")
            locs = [loc.text for loc in soup.find_all("loc")]
            for loc in locs:
                path = urlparse(loc).path.lower().strip("/")
                for kw in RELEVANT_KEYWORDS:
                    if fuzz.partial_ratio(kw, path) >= 80:
                        found.add(loc)
                        break
    except Exception:
        pass

    # --- Approach 2: Homepage anchor tags ---
    try:
        r = requests.get(base_url, timeout=10,
                         headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(r.text, "lxml")
        base_domain = urlparse(base_url).netloc

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            full_url = urljoin(base_url, href)
            link_domain = urlparse(full_url).netloc

            # Only same-domain links
            if base_domain not in link_domain:
                continue

            path = urlparse(full_url).path.lower().strip("/")
            link_text = a.get_text(strip=True).lower()
            combined = path + " " + link_text

            for kw in RELEVANT_KEYWORDS:
                if fuzz.partial_ratio(kw, combined) >= 75:
                    found.add(full_url)
                    break
    except Exception:
        pass

    links = list(found)[:max_links]
    print(f"  Relevant links: {links}")
    return links


# ============================================================
# CELL 6 — AI Insight Generation via Gemini
# ============================================================

def generate_insights(combined_text, url):
    """
    Send cleaned text to Gemini and get structured business insights.
    Returns a dict with all required fields.
    """

    prompt = f"""You are a B2B sales research analyst. Analyze the following company website text and extract business insights.

Website URL: {url}

Website Content:
{combined_text}

Return ONLY a valid JSON object with exactly these keys (no markdown, no explanation, no code fences):
{{
  "company_name": "Official company name (string, not N/A unless truly unknown)",
  "core_service": "Primary product or service offering in one concise sentence",
  "target_customer": "Description of their ideal customer segment",
  "probable_pain_point": "The most likely business problem their customers face that this company solves",
  "outreach_opener": "A 2-sentence personalized cold outreach opener referencing specific details from their website"
}}

Rules:
- Do NOT invent contact details (emails, phones, addresses) — those are extracted separately
- Do NOT use placeholder values like "Company Name" — use the actual name from the content
- If a field truly cannot be determined from the content, use "N/A"
- Keep each value concise (under 100 words)
- The outreach_opener must mention the company by name and reference a real detail from their site"""

    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        raw = response.text.strip()

        # Strip markdown code fences if present
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)

        data = json.loads(raw)

        # Validate all keys present
        required = ["company_name", "core_service", "target_customer",
                    "probable_pain_point", "outreach_opener"]
        for key in required:
            if key not in data:
                data[key] = "N/A"

        return data

    except json.JSONDecodeError as e:
        print(f"  JSON parse error from Gemini: {e}")
        print(f"  Raw response: {raw[:300]}")
        return {k: "N/A" for k in ["company_name", "core_service",
                                    "target_customer", "probable_pain_point",
                                    "outreach_opener"]}
    except Exception as e:
        print(f"  Gemini error: {e}")
        return {k: "N/A" for k in ["company_name", "core_service",
                                    "target_customer", "probable_pain_point",
                                    "outreach_opener"]}


# ============================================================
# CELL 7 — Main Enrichment Function
# ============================================================

def enrich_company(url):
    """
    Full enrichment pipeline for a single company URL.
    Returns a dict matching the required JSON schema.
    """
    print(f"\nProcessing: {url}")

    # --- Derive website_name ---
    try:
        domain = urlparse(url).netloc
        website_name = domain.replace("www.", "")
    except Exception:
        website_name = url

    # --- Collect text from homepage + relevant pages ---
    all_texts = []

    # Homepage
    home_text = scrape_page(url)
    if home_text:
        all_texts.append(clean_text(home_text, max_chars=3000))

    # Relevant sub-pages
    links = get_relevant_links(url)
    for link in links:
        time.sleep(0.5)   # polite crawling
        page_text = scrape_page(link)
        if page_text:
            all_texts.append(clean_text(page_text, max_chars=2000))

    combined = " ".join(all_texts)

    # --- Extract contacts directly from raw text (more reliable than AI) ---
    emails = extract_emails(combined)
    phone  = extract_phone(combined)

    # --- Extract address: look in contact-page text first ---
    address = ""
    address_patterns = [
        r'\d{1,5}\s+\w[\w\s,\.]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Way|Court|Ct|Place|Pl)[,\s]+[\w\s,\.]{5,60}',
        r'[A-Z][a-z]+(?:\s[A-Z][a-z]+)*,\s*[A-Z]{2}\s+\d{5}',   # City, ST 12345
    ]
    for pattern in address_patterns:
        match = re.search(pattern, combined)
        if match:
            address = match.group(0).strip()
            break

    # If regex failed, check for lines with address keywords
    if not address:
        for line in combined.split("  "):
            lower = line.lower()
            if any(kw in lower for kw in ["address:", "headquarters", "hq:", "located at"]):
                cleaned = line.strip()
                if 10 < len(cleaned) < 250:
                    address = cleaned
                    break

    # --- AI Insights ---
    # Limit combined text to ~5000 chars to save tokens
    ai_input = clean_text(combined, max_chars=5000)
    ai_data = generate_insights(ai_input, url)

    # --- Assemble final result ---
    result = {
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

    print(f"  Done: {website_name}")
    return result


# ============================================================
# CELL 8 — Main Runner (this cell is what judges will run)
# ============================================================

if __name__ == "__main__":

    user_input = input(
        'Enter URL array (e.g. ["https://zoho.com", "https://freshworks.com"]): '
    ).strip()

    try:
        urls = json.loads(user_input)
        if isinstance(urls, str):
            urls = [urls]
        if not isinstance(urls, list):
            raise ValueError("Input must be a JSON array of URLs")
    except Exception:
        print("Invalid input. Please enter a JSON array like:")
        print('["https://example.com", "https://another.com"]')
        raise

    results = []

    for url in urls:
        try:
            data = enrich_company(url)
            results.append(data)
        except Exception as e:
            print(f"Error processing {url}: {e}")
            results.append({
                "website_name":        url,
                "company_name":        "N/A",
                "address":             "",
                "mobile_number":       "",
                "mail":                [],
                "core_service":        "N/A",
                "target_customer":     "N/A",
                "probable_pain_point": "N/A",
                "outreach_opener":     "N/A",
            })

    # Save to results.json
    with open("results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("\n" + "="*50)
    print("FINAL OUTPUT")
    print("="*50)
    print(json.dumps(results, indent=2))
    print("\nSaved to results.json ✅")
