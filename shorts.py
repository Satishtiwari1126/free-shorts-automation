import os, re, json, textwrap, subprocess, sys, time
from pathlib import Path
from urllib.parse import quote
import requests, feedparser
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(".")
OUT = ROOT / "output.mp4"
WORK = ROOT / "work"
WORK.mkdir(exist_ok=True)
LOG = ROOT / "run.log"

def log(msg):
    print(msg, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(msg + "\n")

def required(name):
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing GitHub Actions secret: {name}")
    return value

def get_topic():
    feeds = [
        "https://trends.google.com/trending/rss?geo=US",
        "https://trends.google.com/trending/rss?geo=KR",
    ]
    seen = set()
    for url in feeds:
        feed = feedparser.parse(url)
        for entry in feed.entries:
            title = (entry.get("title") or "").strip()
            if title and title.lower() not in seen:
                seen.add(title.lower())
                news_url = "https://news.google.com/rss/search?q=" + quote(title) + "&hl=en-US&gl=US&ceid=US:en"
                news = feedparser.parse(news_url)
                if news.entries:
                    item = news.entries[0]
                    summary = re.sub("<[^>]+>", " ", item.get("summary", ""))
                    summary = re.sub(r"\s+", " ", summary).strip()[:1800]
                    return {
                        "trend": title,
                        "headline": item.get("title", title),
                        "summary": summary,
                        "url": item.get("link", ""),
                        "source": item.get("source", {}).get("title", "Google News")
                    }
    raise RuntimeError("No usable trending story was returned by the feeds.")

def make_script(story, api_key):
    prompt = f"""
Create one original 30-40 second vertical YouTube Short about this trending story.
Use ONLY the factual information in the supplied headline and summary. Do not invent
numbers, quotes, causes, outcomes, or background facts. If the summary is too thin,
make the Short a clearly framed explainer about what the headline says and what remains
unknown. No misinformation, medical advice, investment advice, or political persuasion.
Return ONLY valid JSON with this schema:
{{"title":"under 70 characters","description":"2 short sentences plus source URL and hashtags",
"scenes":[{{"voice":"one spoken sentence, 8-18 words",
"visual":"a concrete shot description showing the exact subject and action described in this sentence",
"search_queries":["specific Wikimedia image search phrase 1","specific phrase 2","specific phrase 3"],
"on_screen_label":"short 2-5 word scene label"}}]}}
Provide exactly 5 scenes. Every visual MUST literally depict the sentence it accompanies:
name the visible subject, action, setting, and important object. Never use vague terms
such as technology, world, news, future, or science by themselves. Do not reuse one
generic visual across scenes. If the sentence describes a process, choose an image of
that exact process; if it describes a person, place, object, or event, search for that
specific thing. Search queries must be concrete Wikimedia Commons subjects, not the
whole story title. Make the opening sentence a strong hook, keep language clear,
and end with a question. Do not mention that you are an AI.

TREND: {story['trend']}
HEADLINE: {story['headline']}
SUMMARY: {story['summary']}
SOURCE: {story['source']} {story['url']}
"""
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    r = requests.post(url, params={"key": api_key}, json={
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.55, "responseMimeType": "application/json"}
    }, timeout=90)
    r.raise_for_status()
    data = r.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    result = json.loads(text)
    if len(result.get("scenes", [])) != 5:
        raise RuntimeError("AI response did not contain exactly five scenes.")
    return result

def commons_image(scene, number):
    # Search for the exact visual requested for this narration beat.
    visual = (scene.get("visual") or "").strip()
    queries = scene.get("search_queries") or []
    queries = [q.strip() for q in queries if isinstance(q, str) and q.strip()]
    if visual:
        queries.insert(0, visual)
    queries = list(dict.fromkeys(queries))[:4]
    if not queries:
        queries = ["documentary photograph " + (scene.get("voice") or "")]
    api = "https://commons.wikimedia.org/w/api.php"
    headers = {"User-Agent": "FreeShortsBot/1.0 (educational video automation)"}
    candidates = []
    for query in queries:
        params = {
            "action": "query", "generator": "search",
            "gsrsearch": query + " filetype:bitmap",
            "gsrnamespace": 6, "gsrlimit": 12,
            "prop": "imageinfo", "iiprop": "url|extmetadata",
            "iiurlwidth": 1400, "format": "json"
        }
        r = requests.get(api, params=params, headers=headers, timeout=40)
        r.raise_for_status()
        pages = r.json().get("query", {}).get("pages", {})
        for page in pages.values():
            title = page.get("title", "")
            tokens = set(re.findall(r"[a-z0-9]{3,}", (query + " " + visual).lower()))
            title_tokens = set(re.findall(r"[a-z0-9]{3,}", title.lower()))
            score = len(tokens & title_tokens)
            candidates.append((score, page))
    candidates.sort(key=lambda item: item[0], reverse=True)
    seen = set()
    for score, page in candidates:
        if page.get("title") in seen:
            continue
        seen.add(page.get("title"))
        info = (page.get("imageinfo") or [{}])[0]
        url = info.get("thumburl") or info.get("url")
        if not url:
            continue
        try:
            image = requests.get(url, timeout=40, headers=headers).content
            path = WORK / f"source_{number}.jpg"
            path.write_bytes(image)
            with Image.open(path) as im:
                im.verify()
            meta = info.get("extmetadata", {})
            artist = re.sub("<[^>]+>", "", meta.get("Artist", {}).get("value", "Unknown"))
            license_name = meta.get("LicenseShortName", {}).get("value", "See source page")
            page_url = "https://commons.wikimedia.org/wiki/" + quote(page.get("title", "").replace(" ", "_"))
            return path, f"{page.get('title','Wikimedia Commons')} — {artist} — {license_name} — {page_url}"
        except Exception:
            continue
    return None, None

def make_card(source, text, index):
    W, H = 1080, 1920
    if source:
        im = Image.open(source).convert("RGB")
        scale = max(W / im.width, H / im.height)
        im = im.resize((int(im.width * scale), int(im.height * scale)))
        x = (im.width - W) // 2
        y = (im.height - H) // 2
        im = im.crop((x, y, x + W, y + H))
    else:
        im = Image.new("RGB", (W, H), (24 + index*7, 32 + index*5, 58 + index*4))
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    d.rectangle((0, 1180, W, H), fill=(0, 0, 0, 190))
    im = Image.alpha_composite(im.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(im)
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    font = ImageFont.truetype(font_path, 62)
    lines = textwrap.wrap(text, width=24)
    y = 1280
    for line in lines[:5]:
        draw.text((70, y), line, font=font, fill="white", stroke_width=2, stroke_fill="black")
        y += 88
    small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 30)
    draw.text((70, 1810), "SOMEWHERE ELSE  •  DAILY STORY", font=small, fill=(230,230,230))
    path = WORK / f"card_{index}.jpg"
    im.convert("RGB").save(path, quality=90)
    return path

def run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def create_video(script):
    clips, credits = [], []
    for i, scene in enumerate(script["scenes"]):
        voice = scene["voice"].strip()
        audio = WORK / f"voice_{i}.wav"
        run(["espeak-ng", "-v", "en-us", "-s", "158", "-w", str(audio), voice])
        image, credit = commons_image(scene, i)
        if not image:
            # Never silently substitute a generic background for a scene that
            # could not find a subject-specific visual.
            raise RuntimeError(
                f"No matching visual found for scene {i + 1}: "
                f"{scene.get('visual', voice)}. Refusing to render/publish a mismatched Short."
            )
        log(f"Scene {i + 1} visual: {scene.get('visual', 'specific subject image')}")
        if credit:
            credits.append(credit)
        card = make_card(image, voice, i)
        clip = WORK / f"clip_{i}.mp4"

        # Turn each sourced image into a moving scene instead of a static slideshow.
        # A slow push-in, subtle horizontal drift, richer contrast, and short fades
        # create motion without any paid video-generation service.
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(audio)],
            check=True, capture_output=True, text=True
        )
        scene_seconds = max(0.5, float(probe.stdout.strip()))
        fade_start = max(0, scene_seconds - 0.35)
        zoom = (
            "scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,"
            "zoompan=z='min(zoom+0.0007,1.08)':"
            "x='iw/2-(iw/zoom/2)+sin(on/90)*8':"
            "y='ih/2-(ih/zoom/2)+cos(on/110)*8':"
            "d=1:s=1080x1920:fps=30,"
            "eq=saturation=1.12:contrast=1.05,"
            f"fade=t=in:st=0:d=0.35,fade=t=out:st={fade_start:.3f}:d=0.35"
        )
        audio_fades = (
            "afade=t=in:st=0:d=0.12,"
            f"afade=t=out:st={fade_start:.3f}:d=0.20"
        )
        run(["ffmpeg", "-y", "-loop", "1", "-i", str(card), "-i", str(audio),
             "-vf", zoom, "-af", audio_fades, "-c:v", "libx264",
             "-preset", "veryfast", "-crf", "21", "-c:a", "aac",
             "-b:a", "128k", "-shortest", "-pix_fmt", "yuv420p",
             "-movflags", "+faststart", str(clip)])
        clips.append(clip)

    concat = WORK / "concat.txt"
    concat.write_text("".join(f"file '{p.resolve()}'\\n" for p in clips), encoding="utf-8")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
         "-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "22", "-c:a", "aac", "-b:a", "128k",
         "-movflags", "+faststart", str(OUT)])
    return credits

def upload_youtube(title, description):
    cid, secret, refresh = required("YOUTUBE_CLIENT_ID"), required("YOUTUBE_CLIENT_SECRET"), required("YOUTUBE_REFRESH_TOKEN")
    token = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": cid, "client_secret": secret, "refresh_token": refresh,
        "grant_type": "refresh_token"
    }, timeout=40)
    token.raise_for_status()
    access = token.json()["access_token"]
    metadata = {
        "snippet": {"title": title[:100], "description": description[:4900],
                    "categoryId": "24", "tags": ["shorts", "trending", "daily stories"]},
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False}
    }
    with OUT.open("rb") as video:
        response = requests.post(
            "https://www.googleapis.com/upload/youtube/v3/videos",
            params={"uploadType": "multipart", "part": "snippet,status"},
            headers={"Authorization": f"Bearer {access}"},
            files={"metadata": (None, json.dumps(metadata), "application/json; charset=UTF-8"),
                   "video": ("short.mp4", video, "video/mp4")},
            timeout=600
        )
    response.raise_for_status()
    return response.json().get("id")

def main():
    LOG.write_text("", encoding="utf-8")
    api_key = required("GEMINI_API_KEY")
    log("Finding a current topic...")
    story = get_topic()
    log("Selected: " + story["headline"])
    script = make_script(story, api_key)
    credits = create_video(script)
    description = script.get("description", "") + "\n\nNews source: " + story["url"]
    if credits:
        description += "\n\nImage credits (Wikimedia Commons):\n" + "\n".join(credits[:5])
    log("Video rendered: " + str(OUT))
    video_id = upload_youtube(script["title"], description)
    log("Published successfully: https://youtube.com/shorts/" + str(video_id))

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log("FAILED: " + repr(exc))
        raise
