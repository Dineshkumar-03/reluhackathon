# 🚀 Company Enrichment Tool — Hackathon Submission

## Project Structure

```
hackathon/
├── colab_notebook.py        ← Subtask 1: paste cells into Colab
├── backend/
│   ├── app_final.py         ← Flask app (serves frontend + APIs)
│   ├── requirements.txt
│   └── static/
│       └── index.html       ← Frontend UI (copy from frontend/)
└── frontend/
    └── index.html           ← Source frontend
```

---

## ✅ STEP 1 — Get a Gemini API Key

1. Go to https://aistudio.google.com/app/apikey
2. Click "Create API Key"
3. Copy the key — you'll use it in both Colab and the backend

---

## ✅ STEP 2 — Set Up the Colab Notebook (Subtask 1)

1. Open the required Colab link from the contest
2. Copy all cells from `colab_notebook.py` into the notebook in order
3. In **CELL 3**, replace `"YOUR_GEMINI_API_KEY_HERE"` with your actual key
4. Run all cells top to bottom
5. The last cell will prompt: `Enter URL array:`
6. Paste: `["https://zoho.com", "https://freshworks.com"]`
7. It will print the enriched JSON and save `results.json`

---

## ✅ STEP 3 — Run the Backend Locally (Subtask 2)

### Install dependencies
```bash
cd backend
pip install -r requirements.txt
```

### Set up folder structure
```bash
mkdir static
cp ../frontend/index.html static/index.html
cp app_final.py app.py
```

### Set your Gemini API key
**Option A — environment variable (recommended):**
```bash
# Mac/Linux
export GEMINI_API_KEY="your_key_here"

# Windows CMD
set GEMINI_API_KEY=your_key_here

# Windows PowerShell
$env:GEMINI_API_KEY="your_key_here"
```

**Option B — edit directly in app.py:**
Find line: `GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY_HERE")`
Replace the fallback string with your key.

### Start the server
```bash
python app.py
```

You should see:
```
* Running on http://0.0.0.0:5000
```

Open http://localhost:5000 in your browser ✅

---

## ✅ STEP 4 — Deploy to Render (Free, ~5 min)

1. Push your code to a GitHub repo
   - The repo should contain: `app.py`, `requirements.txt`, `static/index.html`

2. Go to https://render.com → New → Web Service

3. Connect your GitHub repo

4. Set:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app`
   - **Environment Variable:** `GEMINI_API_KEY` = your key

5. Click Deploy — get your public URL (e.g. `https://myapp.onrender.com`)

---

## API Reference

### POST /enrich
```json
Request:  { "url": "https://zoho.com", "website_name": "Zoho" }
Response: { "website_name": "zoho.com", "company_name": "Zoho Corporation", ... }
```

### GET /results
```json
Response: [ { ...company1 }, { ...company2 } ]
```

---

## 🧪 Test URLs (pre-enriched for demo)
- https://zoho.com
- https://freshworks.com
- https://chargebee.com
- https://postman.com

---

## Notes
- If a website blocks scraping, the system gracefully returns `"N/A"` / `""` — it will never crash
- Contact data (emails, phones) is extracted via regex — never hallucinated by AI
- AI only generates: company_name, core_service, target_customer, probable_pain_point, outreach_opener
