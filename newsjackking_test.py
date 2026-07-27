# -*- coding: utf-8 -*-
import json
import logging
import os
from datetime import datetime
import feedparser
import requests

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


class RegulatoryIngestionEngine:
    def __init__(self, bls_api_key: str = None):
        self.bls_api_key = bls_api_key
        self.normalized_signals = []

    def _add_signal(self, source: str, category: str, title: str, url: str, date: str, raw_content: str = ""):
        self.normalized_signals.append({
            "source": source,
            "category": category,
            "title": title,
            "url": url,
            "published_at": date,
            "content": raw_content[:500],
            "ingested_at": datetime.utcnow().isoformat()
        })

    def fetch_cms_updates(self):
        logging.info("Fetching CMS Federal Register updates...")
        url = (
            "https://www.federalregister.gov/api/v1/documents.json"
            "?conditions[agencies][]=centers-for-medicare-medicaid-services"
            "&per_page=5&order=newest"
        )
        try:
            res = requests.get(url, timeout=10).json()
            for doc in res.get("results", []):
                self._add_signal(
                    source="CMS / Federal Register",
                    category="Policy & Regulatory",
                    title=doc.get("title"),
                    url=doc.get("html_url"),
                    date=doc.get("publication_date"),
                    raw_content=doc.get("abstract", "")
                )
        except Exception as e:
            logging.error(f"Error fetching CMS updates: {e}")

    def fetch_rss_feeds(self):
        logging.info("Fetching RSS industry news feeds...")
        rss_urls = {
            "Healthcare Dive": "https://www.healthcaredive.com/feeds/news/",
            "HHS OIG News": "https://oig.hhs.gov/rss/newsroom.xml",
            "NIC MAP Vision News": "https://www.nic.org/feed/"  # Added NIC feed target
        }
        for source_name, feed_url in rss_urls.items():
            try:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries[:5]:
                    self._add_signal(
                        source=source_name,
                        category="Industry & Operational Trends",
                        title=entry.title,
                        url=entry.link,
                        date=entry.get("published", datetime.utcnow().isoformat()),
                        raw_content=entry.get("summary", "")
                    )
            except Exception as e:
                logging.error(f"Error fetching RSS for {source_name}: {e}")

    def fetch_bls_labor_data(self):
        logging.info("Fetching BLS labor series metrics...")
        url = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
        headers = {"Content-Type": "application/json"}
        payload = json.dumps({
            "seriesid": ["CES6562311003"],
            "startyear": "2025",
            "endyear": "2026",
            **({"registrationkey": self.bls_api_key} if self.bls_api_key else {})
        })
        try:
            res = requests.post(url, data=payload, headers=headers, timeout=10).json()
            if res.get("status") == "REQUEST_SUCCEEDED":
                for series in res["Results"]["series"]:
                    s_id = series["seriesID"]
                    for data in series["data"][:1]:
                        self._add_signal(
                            source="Bureau of Labor Statistics",
                            category="Labor Market",
                            title=f"BLS Series {s_id} Metric Update: {data['value']}",
                            url="https://www.bls.gov/data/",
                            date=f"{data['year']}-{data['period']}",
                            raw_content=f"Period: {data['periodName']} {data['year']}, Value: {data['value']}"
                        )
        except Exception as e:
            logging.error(f"Error fetching BLS metrics: {e}")

    def run_all(self):
        self.fetch_cms_updates()
        self.fetch_rss_feeds()
        self.fetch_bls_labor_data()
        return self.normalized_signals


def synthesize_digest_with_ai(signals, openai_api_key):
    """
    Uses OpenAI to analyze raw signals and generate an Executive Intelligence Signal.
    """
    if not openai_api_key:
        logging.warning("No OPENAI_API_KEY provided. Falling back to simple formatting.")
        return fallback_generate_digest(signals)

    prompt = f"""
You are a senior healthcare analyst. Synthesize the following raw market signals into a concise Executive Intelligence Signal digest.

Raw Signals Data:
{json.dumps(signals, indent=2)}

Format the output EXACTLY like this template:

📢 Executive Intelligence Signal
* **Metric/Update:** [Key occupancy/market metric, e.g., NIC MAP Vision metrics]
* **Regulatory Context:** [Summary of primary CMS or regulatory update]
* **Labor Signal:** [Key BLS labor metric or wage trend]
* **Compliance Alert:** [HHS-OIG or compliance flag]
* **Action Item:** [1 strategic recommendation based on these combined signals]
"""

    headers = {
        "Authorization": f"Bearer {openai_api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2
    }

    try:
        response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=20)
        res_json = response.json()
        return res_json["choices"][0]["message"]["content"]
    except Exception as e:
        logging.error(f"AI synthesis failed: {e}")
        return fallback_generate_digest(signals)


def fallback_generate_digest(signals):
    if not signals:
        return "No new intelligence signals retrieved."
    digest_md = "## 📢 Executive Intelligence Signal Digest\n\n"
    for sig in signals[:5]:
        digest_md += f"* **[{sig['title']}]({sig['url']})** ({sig['source']})\n"
    return digest_md


if __name__ == "__main__":
    engine = RegulatoryIngestionEngine()
    signals = engine.run_all()

    # Get OpenAI API Key from environment variable
    openai_key = os.getenv("OPENAI_API_KEY")

    # Synthesize with AI layer
    digest_output = synthesize_digest_with_ai(signals, openai_key)

    print("\n" + "="*50)
    print(digest_output)
    print("="*50 + "\n")

    # Save report
    os.makedirs("reports", exist_ok=True)
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    report_filename = f"reports/Executive_Digest_{today_str}.md"

    with open(report_filename, "w", encoding="utf-8") as f:
        f.write(digest_output)

    logging.info(f"✅ Saved synthesized report to {report_filename}")
