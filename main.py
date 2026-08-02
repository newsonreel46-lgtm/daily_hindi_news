import os
import json
import asyncio
import urllib.parse
import feedparser
import edge_tts
from google import genai
from google.genai import types
import requests
from pydub import AudioSegment
from pydub.silence import split_on_silence
# MoviePy (v2.x) for Video Assembly
from moviepy import (
    AudioFileClip, ImageClip, TextClip, CompositeVideoClip,
    ColorClip, concatenate_videoclips
)
# YouTube Upload Libraries
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Configure Google Gemini Client
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

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

def trim_long_silences(input_file, output_file, silence_thresh_db=-40,
                        min_silence_len=350, keep_silence=200):
    """edge-tts leaves noticeable dead air at every Hindi danda (।) and
    comma. Detect gaps longer than min_silence_len and shrink them down
    to keep_silence, instead of removing them entirely (which sounds
    unnatural)."""
    audio = AudioSegment.from_file(input_file)
    chunks = split_on_silence(
        audio,
        min_silence_len=min_silence_len,
        silence_thresh=silence_thresh_db,
        keep_silence=keep_silence,
    )

    if not chunks:
        audio.export(output_file, format="mp3")
        return

    tightened = AudioSegment.empty()
    gap = AudioSegment.silent(duration=keep_silence)
    for i, chunk in enumerate(chunks):
        tightened += chunk
        if i != len(chunks) - 1:
            tightened += gap

    tightened.export(output_file, format="mp3")


async def generate_story_audio(text, output_file):
    """Generates audio for a single story's narration (male voice,
    tightened pauses), rather than one giant concatenated file."""
    voice = "hi-IN-MadhurNeural"
    raw_file = output_file.replace(".mp3", "_raw.mp3")
    communicate = edge_tts.Communicate(text, voice, rate="+12%")
    await communicate.save(raw_file)
    trim_long_silences(raw_file, output_file)


async def generate_all_story_audio(script_data):
    """Generates one audio file per story. Returns a list of
    (story_item, audio_path) tuples for stories that had narration -
    keeps stories and their audio correctly paired even if some are
    skipped for empty narration."""
    folder = "segment_audio"
    os.makedirs(folder, exist_ok=True)
    paired = []
    for i, item in enumerate(script_data):
        narration = item.get("hindi_narration", "").strip()
        if not narration:
            print(f"Skipping story {i} (no narration): {item.get('headline', '')}")
            continue
        out_path = os.path.join(folder, f"story_{i}.mp3")
        await generate_story_audio(narration, out_path)
        paired.append((item, out_path))
        print(f"Audio generated for story {i}: {out_path}")
    return paired



def get_pexels_image(search_keyword, image_path):
    """Primary source: Pexels has real, topical stock photos (needs a
    free PEXELS_API_KEY secret). Much more reliable for topic-matching
    than a single hardcoded Unsplash URL."""
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        return None
    try:
        headers = {"Authorization": api_key}
        url = (
            "https://api.pexels.com/v1/search"
            f"?query={urllib.parse.quote(search_keyword)}&orientation=landscape&per_page=5"
        )
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            photos = res.json().get("photos", [])
            for photo in photos:
                img_url = photo.get("src", {}).get("large") or photo.get("src", {}).get("landscape")
                if img_url:
                    img_data = requests.get(img_url, timeout=10)
                    if img_data.status_code == 200:
                        with open(image_path, "wb") as f:
                            f.write(img_data.content)
                        print(f"Pexels image found for '{search_keyword}'")
                        return image_path
    except Exception as e:
        print(f"Pexels search failed: {e}")
    return None


def get_wikimedia_image(search_keyword, image_path):
    try:
        wiki_url = (
            "https://commons.wikimedia.org/w/api.php?action=query&generator=search"
            "&prop=imageinfo&iiprop=url&format=json&gsrnamespace=6"
            f"&gsrsearch={urllib.parse.quote(search_keyword)}&gsrlimit=5"
        )
        headers = {'User-Agent': 'DailyHindiNewsBot/1.0 (contact@example.com)'}
        res = requests.get(wiki_url, headers=headers, timeout=10)
        if res.status_code == 200:
            pages = res.json().get("query", {}).get("pages", {})
            for page in pages.values():
                img_url = page.get("imageinfo", [{}])[0].get("url")
                if img_url and any(img_url.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png']):
                    img_data = requests.get(img_url, headers=headers, timeout=10)
                    if img_data.status_code == 200:
                        with open(image_path, "wb") as f:
                            f.write(img_data.content)
                        print(f"Wikimedia image found for '{search_keyword}'")
                        return image_path
    except Exception as e:
        print(f"Wikimedia search failed: {e}")
    return None


def download_story_background(headline, category, image_path):
    """Fetches a background image matching THIS story specifically,
    using its own English headline/category as the search query -
    replaces the old single hardcoded Unsplash image used for every
    story."""
    query = f"{category} {headline}".strip()
    print(f"Fetching background for: '{query}'")

    for fetch in (get_pexels_image, get_wikimedia_image):
        path = fetch(query, image_path)
        if path:
            return path

    # Last-resort static fallback so the pipeline never breaks
    fallback_url = "https://images.unsplash.com/photo-1585829365295-ab7cd400c167?w=1920&q=80"
    try:
        response = requests.get(fallback_url, timeout=10)
        if response.status_code == 200:
            with open(image_path, "wb") as f:
                f.write(response.content)
            print(f"Using static fallback image for '{query}'")
            return image_path
    except Exception as e:
        print(f"Fallback download failed: {e}")
    return None

def build_story_segment(item, audio_file, index):
    """Builds one video segment for one story: its own background
    image (matched to its headline) + its own narration audio, so the
    visual on screen is synced to whatever is being read at that
    moment."""
    audio_clip = AudioFileClip(audio_file)
    duration = audio_clip.duration

    bg_path = f"story_bg_{index}.jpg"
    bg_path = download_story_background(
        item.get("headline", ""), item.get("category", ""), bg_path
    )

    if bg_path and os.path.exists(bg_path):
        base_clip = ImageClip(bg_path).with_duration(duration).resized((1920, 1080))
        base_clip = base_clip.resized(lambda t: 1 + 0.03 * t)
    else:
        base_clip = ColorClip(size=(1920, 1080), color=(15, 23, 42), duration=duration)

    header_bg = ColorClip(size=(1920, 120), color=(220, 38, 38)).with_duration(duration)
    header_text = TextClip(
        text=item.get("category", "NEWS").upper(),
        font_size=55,
        color='white'
    ).with_duration(duration)
    header_composite = CompositeVideoClip([
        header_bg,
        header_text.with_position(('center', 'center'))
    ]).with_position(('center', 'top'))

    ticker_bg = ColorClip(size=(1920, 140), color=(15, 23, 42)).with_duration(duration)
    ticker_accent = ColorClip(size=(1920, 8), color=(234, 179, 8)).with_duration(duration)
    ticker_text = TextClip(
        text=item.get("headline", "")[:90],
        font_size=38,
        color='#FACC15'
    ).with_duration(duration)
    ticker_composite = CompositeVideoClip([
        ticker_bg,
        ticker_accent.with_position(('center', 'top')),
        ticker_text.with_position(('center', 'center'))
    ]).with_position(('center', 820))

    segment = CompositeVideoClip([
        base_clip,
        header_composite,
        ticker_composite
    ]).with_audio(audio_clip)

    return segment


def build_news_video(script_data, audio_files, output_file="final_news_video.mp4"):
    print("Building Dynamic TV-Style News Video (synced per story)...")

    segments = []
    for i, (item, audio_file) in enumerate(zip(script_data, audio_files)):
        print(f"Building segment {i}: {item.get('headline', '')[:60]}")
        segments.append(build_story_segment(item, audio_file, i))

    final_video = concatenate_videoclips(segments, method="compose")
    final_video.write_videofile(
        output_file,
        fps=24,
        codec="libx264",
        audio_codec="aac",
        preset="fast"
    )
    print(f"Professional news video generated successfully: {output_file}")
    
def upload_to_youtube(video_file="final_news_video.mp4"):
    print("Uploading news video to YouTube...")
    
    SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
    
    creds = Credentials(
        token=None,
        refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YOUTUBE_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
        scopes=SCOPES  # Added explicit scopes here
    )

    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": "Daily Hindi News Bulletin | Fact-Checked News Update",
            "description": "Daily automated morning Hindi news bulletin.",
            "tags": ["Hindi News", "Daily News", "News Update"],
            "categoryId": "25"  # News & Politics
        },
        "status": {
            "privacyStatus": "public"
        }
    }

    media = MediaFileUpload(video_file, chunksize=-1, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    
    response = request.execute()
    print(f"Video uploaded successfully! Video ID: https://youtu.be/{response.get('id')}")
if __name__ == "__main__":
    print("1. Fetching News...")
    news = fetch_all_headlines()

    print("2. Verifying & Scripting...")
    final_script_raw = verify_and_generate_script(news)
    final_script_clean = clean_json_text(final_script_raw)

    try:
        parsed = json.loads(final_script_clean)

        print("3. Generating Audio (per story)...")
        paired = asyncio.run(generate_all_story_audio(parsed))
        parsed = [p[0] for p in paired]
        audio_files = [p[1] for p in paired]

        print("4. Rendering Video (synced to each story)...")
        build_news_video(parsed, audio_files)

        print("5. Uploading to YouTube...")
        upload_to_youtube()

    except Exception as e:
        print(f"Error during execution: {e}")
