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
            "content": raw_content[:500],  # Truncated sample
            "ingested_at": datetime.utcnow().isoformat()
        })

    # A. CMS via Federal Register API
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

    # B. Healthcare Dive & Becker's via RSS
    def fetch_rss_feeds(self):
        logging.info("Fetching RSS industry news feeds...")
        rss_urls = {
            "Healthcare Dive": "https://www.healthcaredive.com/feeds/news/",
            "HHS OIG News": "https://oig.hhs.gov/rss/newsroom.xml"
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

    # C. BLS Wage & Labor Data via Public API
    def fetch_bls_labor_data(self):
        logging.info("Fetching BLS labor series metrics...")
        url = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
        headers = {"Content-Type": "application/json"}
        # Series ID: Average Hourly Earnings for Nursing Facilities (CES6562311003)
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
                    for data in series["data"][:1]:  # Latest data point
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


def generate_executive_digest(signals):
    """
    Transforms ingested signals into a formatted Executive Digest.
    """
    if not signals:
        return "No new intelligence signals retrieved."

    # Group signals by category
    categorized = {}
    for sig in signals:
        cat = sig.get("category", "General Updates")
        categorized.setdefault(cat, []).append(sig)

    # Build Markdown string
    digest_md = "## 📢 Executive Intelligence Signal Digest\n"
    digest_md += f"*Generated on: {signals[0].get('ingested_at', 'N/A')[:10]}*\n\n---\n\n"

    for category, items in categorized.items():
        digest_md += f"### 📌 {category}\n"
        for item in items[:3]:  # Top 3 items per category
            digest_md += f"* **[{item['title']}]({item['url']})**\n"
            digest_md += f"  > *Source: {item['source']} | Date: {item['published_at'][:10]}*\n"
            if item.get("content"):
                digest_md += f"  > {item['content'][:150]}...\n"
            digest_md += "\n"

    return digest_md


def send_to_slack(digest_md, webhook_url):
    """Pushes digest directly to Slack if a webhook URL is present."""
    if not webhook_url:
        return
    payload = {"text": digest_md}
    response = requests.post(webhook_url, json=payload)
    if response.status_code == 200:
        logging.info("✅ Alert successfully sent to Slack!")
    else:
        logging.error(f"❌ Failed to send to Slack: {response.status_code}")


if __name__ == "__main__":
    # 1. Instantiate and run Ingestion Engine
    engine = RegulatoryIngestionEngine()
    signals = engine.run_all()

    # 2. Format into Executive Digest
    digest_output = generate_executive_digest(signals)

    # 3. Print directly to standard output (GitHub Actions log)
    print("\n" + "="*50)
    print(digest_output)
    print("="*50 + "\n")

    # 4. Save digest to Markdown file inside reports/ folder for GitHub Artifacts
    os.makedirs("reports", exist_ok=True)
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    report_filename = f"reports/Executive_Digest_{today_str}.md"

    with open(report_filename, "w", encoding="utf-8") as f:
        f.write(digest_output)

    logging.info(f"✅ Saved report to {report_filename}")

    # 5. Push to Slack if SLACK_WEBHOOK_URL environment variable is set
    slack_webhook = os.getenv("SLACK_WEBHOOK_URL")
    if slack_webhook:
        send_to_slack(digest_output, slack_webhook)
