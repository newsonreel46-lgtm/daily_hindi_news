import os
import requests
import edge_tts
import asyncio
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from googleapiclient.http import MediaFileUpload
from moviepy import AudioFileClip, ImageClip, TextClip, CompositeVideoClip, ColorClip

# 1. Generate Voiceover for Shorts (Short & Punchy ~25s)
async def generate_shorts_audio(text, output_file="shorts_audio.mp3"):
    # Clear, engaging Hindi female voice
    voice = "hi-IN-SwaraNeural"
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_file)
    print(f"Shorts audio saved to {output_file}")

# 2. Fetch Visual Background for Shorts (Vertical 9:16)
def get_vertical_news_background(image_path="shorts_bg.jpg"):
    # Downloads high-res dynamic news background
    url = "https://images.unsplash.com/photo-1585829365295-ab7cd400c167?w=1080&h=1920&fit=crop"
    res = requests.get(url)
    if res.status_code == 200:
        with open(image_path, "wb") as f:
            f.write(res.content)
        return image_path
    return None

# 3. Build Vertical 9:16 Video
# 3. Build Vertical 9:16 Video (Updated for MoviePy v2.x)
# 3. Build Vertical 9:16 Video (Updated for MoviePy v2.x)
def build_youtube_shorts(audio_file="shorts_audio.mp3", output_file="shorts_video.mp4"):
    print("Building 9:16 YouTube Shorts Video...")
    audio_clip = AudioFileClip(audio_file)
    duration = min(audio_clip.duration, 30) # Hard cap at 30 seconds

    # Vertical Canvas (1080x1920)
    bg_path = get_vertical_news_background()
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
    build_youtube_shorts()
    upload_shorts()
