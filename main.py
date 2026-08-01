import os
import json
import asyncio
import feedparser
import edge_tts
from google import genai
from google.genai import types

# MoviePy & PIL for Video Assembly
from moviepy.editor import TextClip, CompositeVideoClip, AudioFileClip, ColorClip

# Configure Google Gemini Client
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

    Output format MUST be valid JSON array of objects:
    [
      {{"category": "National", "headline": "...", "hindi_narration": "..."}}
    ]
    """

    response = client.models.generate_content(
        model="gemini-3.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
        ),
    )
    return response.text

def clean_json_text(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return text.strip()

async def generate_hindi_audio(script_data, output_file="final_news_audio.mp3"):
    full_narration = ""
    for item in script_data:
        full_narration += f"{item.get('hindi_narration', '')}\n\n"

    voice = "hi-IN-SwaraNeural"
    communicate = edge_tts.Communicate(full_narration, voice)
    await communicate.save(output_file)
    print(f"Audio file saved: {output_file}")

def build_news_video(audio_file="final_news_audio.mp3", output_file="final_news_video.mp4"):
    print("Building 1080p News Video with MoviePy...")
    audio_clip = AudioFileClip(audio_file)
    duration = audio_clip.duration

    # Create dark red news studio background (1920x1080)
    bg_clip = ColorClip(size=(1920, 1080), color=(20, 20, 30), duration=duration)

    # Title Banner (Top)
    title_clip = TextClip("DAILY HINDI NEWS BULLETIN", fontsize=50, color='white', bg_color='red', size=(1920, 100))
    title_clip = title_clip.set_position(('center', 'top')).set_duration(duration)

    # Lower Third News Banner (Bottom Ticker)
    ticker_clip = TextClip("Top Stories | Fact-Checked Updates", fontsize=40, color='yellow', bg_color='black', size=(1920, 80))
    ticker_clip = ticker_clip.set_position(('center', 900)).set_duration(duration)

    # Combine video and audio layers
    video = CompositeVideoClip([bg_clip, title_clip, ticker_clip])
    video = video.set_audio(audio_clip)

    # Render MP4 file
    video.write_videofile(output_file, fps=24, codec="libx264", audio_codec="aac")
    print(f"Video created successfully: {output_file}")

if __name__ == "__main__":
    print("1. Fetching 5:30 AM News...")
    news = fetch_all_headlines()

    print("2. Verifying and Generating Script...")
    final_script_raw = verify_and_generate_script(news)
    final_script_clean = clean_json_text(final_script_raw)

    try:
        parsed = json.loads(final_script_clean)
        print("3. Generating Hindi Voiceover...")
        asyncio.run(generate_hindi_audio(parsed))

        print("4. Compiling Final News Video...")
        build_news_video()

    except Exception as e:
        print(f"Error during execution: {e}")
