import os
import json
import requests
import edge_tts
import asyncio
from pydub import AudioSegment
from pydub.silence import split_on_silence
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from googleapiclient.http import MediaFileUpload
from moviepy import AudioFileClip, ImageClip, TextClip, CompositeVideoClip, ColorClip
import urllib.parse


# 1. Generate Voiceover for Shorts (Short & Punchy ~25s)
async def generate_shorts_audio(text, output_file="shorts_audio.mp3"):
    # Clear, engaging Hindi MALE voice (was hi-IN-SwaraNeural, female)
    voice = "hi-IN-MadhurNeural"

    # Slightly faster rate tightens the natural gaps edge-tts leaves at
    # every "।" / comma, without making the voice sound rushed.
    communicate = edge_tts.Communicate(text, voice, rate="+12%")
    raw_file = "shorts_audio_raw.mp3"
    await communicate.save(raw_file)

    # edge-tts still leaves noticeable silences at punctuation. Detect
    # those gaps and shrink any pause longer than 350ms down to 200ms,
    # instead of cutting them completely (which sounds unnatural).
    trim_long_silences(raw_file, output_file)
    print(f"Shorts audio saved to {output_file}")


def trim_long_silences(input_file, output_file, silence_thresh_db=-40,
                        min_silence_len=350, keep_silence=200):
    audio = AudioSegment.from_file(input_file)
    chunks = split_on_silence(
        audio,
        min_silence_len=min_silence_len,
        silence_thresh=silence_thresh_db,
        keep_silence=keep_silence,
    )

    if not chunks:
        # Nothing detected as silence (e.g. very short clip) - just reuse original
        audio.export(output_file, format="mp3")
        return

    tightened = AudioSegment.empty()
    gap = AudioSegment.silent(duration=keep_silence)
    for i, chunk in enumerate(chunks):
        tightened += chunk
        if i != len(chunks) - 1:
            tightened += gap

    tightened.export(output_file, format="mp3")

# 2. Fetch Visual Background for Shorts (Vertical 9:16)

def extract_image_keywords(news_text):
    """
    Uses Gemini to turn the Hindi news script into 2-4 short English
    keywords describing the actual subject, so the image search is
    about the story instead of a generic "news india" query.
    Falls back to a generic query if Gemini isn't available/fails.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return "news india"

    try:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-1.5-flash:generateContent?key={api_key}"
        )
        prompt = (
            "Read this Hindi news script and reply with ONLY 3-4 English "
            "keywords (comma separated, no extra text) describing the main "
            "visual subject of the story - e.g. specific objects, place, "
            "event type, industry. This will be used as an image search "
            f"query.\n\nScript:\n{news_text}"
        )
        body = {"contents": [{"parts": [{"text": prompt}]}]}
        res = requests.post(url, json=body, timeout=15)
        if res.status_code == 200:
            data = res.json()
            keywords = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            keywords = keywords.replace("\n", " ").strip()
            if keywords:
                print(f"Gemini image keywords: '{keywords}'")
                return keywords
    except Exception as e:
        print(f"Gemini keyword extraction failed: {e}")

    return "news india"


def get_pexels_image(search_keyword, image_path):
    """Primary source: Pexels has real, topical stock photos (needs a free
    PEXELS_API_KEY secret). Much more reliable for topic-matching than
    Wikimedia Commons, which is a media archive, not a news photo bank."""
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        return None

    try:
        headers = {"Authorization": api_key}
        url = (
            "https://api.pexels.com/v1/search"
            f"?query={urllib.parse.quote(search_keyword)}&orientation=portrait&per_page=5"
        )
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            photos = res.json().get("photos", [])
            for photo in photos:
                img_url = photo.get("src", {}).get("portrait") or photo.get("src", {}).get("large")
                if img_url:
                    img_data = requests.get(img_url, timeout=10)
                    if img_data.status_code == 200:
                        with open(image_path, "wb") as f:
                            f.write(img_data.content)
                        print("Successfully downloaded topic image from Pexels!")
                        return image_path
    except Exception as e:
        print(f"Pexels search failed: {e}")

    return None


def get_vertical_news_background(search_keyword="news india", image_path="shorts_bg.jpg"):
    print(f"Fetching dynamic news background for keyword: '{search_keyword}'...")

    # 1. Try Pexels first - actual topical stock photos matching the keyword
    pexels_path = get_pexels_image(search_keyword, image_path)
    if pexels_path:
        return pexels_path

    # 2. Try fetching topic-relevant image from Wikimedia Commons API (100% Free, Public, Reliable)
    try:
        wiki_url = f"https://commons.wikimedia.org/w/api.php?action=query&generator=search&prop=imageinfo&iiprop=url&gqssort=just_created&format=json&gsrnamespace=6&gsrsearch={urllib.parse.quote(search_keyword)}&gsrlimit=5"
        headers = {'User-Agent': 'YouTubeShortsBot/1.0 (contact@example.com)'}
        res = requests.get(wiki_url, headers=headers, timeout=10)
        
        if res.status_code == 200:
            data = res.json()
            pages = data.get("query", {}).get("pages", {})
            for page in pages.values():
                image_info = page.get("imageinfo", [{}])[0]
                img_download_url = image_info.get("url")
                # Filter for direct standard image formats
                if img_download_url and any(img_download_url.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png']):
                    img_data = requests.get(img_download_url, headers=headers, timeout=10)
                    if img_data.status_code == 200:
                        with open(image_path, "wb") as f:
                            f.write(img_data.content)
                        print("Successfully downloaded topic image from Wikimedia!")
                        return image_path
    except Exception as e:
        print(f"Wikimedia search failed: {e}")

    # 2. Backup Fallback (Guaranteed static high-res news studio image)
    print("Using high-quality fallback news background...")
    fallback_url = "https://picsum.photos/1080/1920"  # Always returns a valid random 1080x1920 portrait photo
    
    try:
        res = requests.get(fallback_url, timeout=10)
        if res.status_code == 200:
            with open(image_path, "wb") as f:
                f.write(res.content)
            return image_path
    except Exception as e:
        print(f"Fallback download failed: {e}")

    return None
    
# 3. Build Vertical 9:16 Video
# 3. Build Vertical 9:16 Video (Updated for MoviePy v2.x)
# 3. Build Vertical 9:16 Video (Updated for MoviePy v2.x)
def build_youtube_shorts(script_text, audio_file="shorts_audio.mp3", output_file="shorts_video.mp4"):
    print("Building 9:16 YouTube Shorts Video...")
    audio_clip = AudioFileClip(audio_file)
    duration = min(audio_clip.duration, 30) # Hard cap at 30 seconds

    # Vertical Canvas (1080x1920)
    image_keyword = extract_image_keywords(script_text)
    bg_path = get_vertical_news_background(search_keyword=image_keyword)
    if bg_path and os.path.exists(bg_path):
        bg_clip = ImageClip(bg_path).with_duration(duration).resized((1080, 1920))
        # Continuous zoom-in animation for engagement
        bg_clip = bg_clip.resized(lambda t: 1 + 0.04 * t)
    else:
        bg_clip = ColorClip(size=(1080, 1920), color=(15, 23, 42), duration=duration)

    # Top Header Badge
    header_bg = ColorClip(size=(1080, 140), color=(220, 38, 38)).with_duration(duration)
    
    # TextClip in MoviePy v2 requires explicitly named parameters: text="...", font_size=...
    header_text = TextClip(
        text="BREAKING NEWS | FACT CHECK", 
        font_size=45, 
        color='white'
    ).with_duration(duration)
    
    header = CompositeVideoClip([header_bg, header_text.with_position(('center', 'center'))]).with_position(('center', 150))

    # Center Visual Frame Box
    center_box = ColorClip(size=(960, 1000), color=(0, 0, 0)).with_opacity(0.4).with_duration(duration).with_position(('center', 'center'))

    # Bottom Overlay Ticker
    ticker_bg = ColorClip(size=(1080, 180), color=(15, 23, 42)).with_duration(duration)
    
    ticker_text = TextClip(
        text="Subscribe for Daily Hindi Shorts!", 
        font_size=38, 
        color='#FACC15'
    ).with_duration(duration)
    
    ticker = CompositeVideoClip([ticker_bg, ticker_text.with_position(('center', 'center'))]).with_position(('center', 1600))

    final_shorts = CompositeVideoClip([
        bg_clip,
        center_box,
        header,
        ticker
    ]).with_audio(audio_clip)

    final_shorts.write_videofile(output_file, fps=30, codec="libx264", audio_codec="aac", preset="fast")
    print("Shorts Video Rendering Complete!")    
# 4. Upload to YouTube as Shorts
def upload_shorts(video_file="shorts_video.mp4"):
    print("Uploading to YouTube Shorts...")
    SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
    creds = Credentials(
        token=None,
        refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YOUTUBE_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
        scopes=SCOPES
    )
    youtube = build("youtube", "v3", credentials=creds)

    # Note: Adding #Shorts in title and description triggers YouTube's Shorts shelf
    body = {
        "snippet": {
            "title": "आज की बड़ी खबर | Daily Fact Check #Shorts #News",
            "description": "25-second fast news update. #Shorts #HindiNews #NewsUpdate #FactCheck",
            "tags": ["Shorts", "Hindi News", "Fact Check", "Breaking News"],
            "categoryId": "25"
        },
        "status": {
            "privacyStatus": "public"
        }
    }

    media = MediaFileUpload(video_file, chunksize=-1, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = request.execute()
    print(f"Shorts Upload Success! Video ID: https://youtu.be/{response.get('id')}")

if __name__ == "__main__":
    # Example Single Headline Script (Can be generated via Gemini API)
    script_text = "आज की सबसे बड़ी खबर! रेलवे सुरक्षा को लेकर सरकार ने उठाया बड़ा कदम। अब सभी प्रमुख ट्रेनों में नए सुरक्षा कवच सिस्टम को लागू किया जा रहा है।"
    
    asyncio.run(generate_shorts_audio(script_text))
    build_youtube_shorts(script_text)
    upload_shorts()
