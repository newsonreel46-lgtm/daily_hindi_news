import os
import json
import feedparser
from google import genai
from google.genai import types

# Configure Google Gemini Client using your repository secret
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

# Official Morning RSS Feeds
SOURCES = [
    "https://www.thehindu.com/news/national/feeder/default.rss",
    "https://timesofindia.indiatimes.com/rssfeedstopstories.cms",
    "https://economictimes.indiatimes.com/rssfeedstopstories.cms"
]


def fetch_all_headlines():
    raw_articles = []
    for url in SOURCES:
        feed = feedparser.parse(url)
        for entry in feed.entries[:10]:
            raw_articles.append({
                "title": entry.title,
                "summary": entry.get("summary", "")
            })
    return raw_articles


def verify_and_generate_script(articles):
    prompt = f"""
    You are an automated Hindi news bulletin editor.
    Review these raw news articles: {json.dumps(articles)}

    DOUBLE-CHECK & VERIFICATION RULES:
    1. Cross-verify each headline against standard news facts.
    2. If a news item seems unverified or unclear, check if another source in the list reports the same topic.
    3. IF A SECOND SOURCE ALSO DOES NOT CONFIRM IT, OR IF IT IS AN UNVERIFIED RUMOR/CLICKBAIT, DROP THAT NEWS ITEM ENTIRELY AND MOVE TO THE NEXT ONE.
    4. Select the top 10 VERIFIED stories across National, International, Business, and Sports.
    5. Write a short 30-40 second news narration in natural spoken Hindi (Devanagari script) for each verified story.

    Output format MUST be valid JSON:
    [
      {{"category": "National", "headline": "...", "hindi_narration": "..."}}
    ]
    """

    response = client.models.generate_content(
        model="gemini-3.5-flash",  # gemini-1.5-flash and gemini-2.5-flash are both closed off now; this is the current generation
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",  # forces clean JSON, avoids ```json fences
        ),
    )
    return response.text


def clean_json_text(text):
    """Fallback in case the model still wraps output in markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return text.strip()


if __name__ == "__main__":
    print("Fetching 5:30 AM News...")
    news = fetch_all_headlines()
    print(f"Fetched {len(news)} raw items. Verifying with Gemini Fact-Checker...")

    final_script_raw = verify_and_generate_script(news)
    final_script_clean = clean_json_text(final_script_raw)

    try:
        parsed = json.loads(final_script_clean)
        print("\nVerified Hindi Script Ready:\n")
        print(json.dumps(parsed, ensure_ascii=False, indent=2))
    except json.JSONDecodeError as e:
        print(f"\nWarning: could not parse model output as JSON ({e}). Raw output below:\n")
        print(final_script_raw)
