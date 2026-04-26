import os
import sys
import json
import random
import requests
import logging
import re
from io import BytesIO
from datetime import datetime
from PIL import Image
from atproto import Client, models, client_utils
import anthropic

# --- LOGGING SETUP ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger()

# --- CONSTANTS ---
RANDOM_PROMO_CHANCE = 0.33
CURRENT_YEAR = 2026

PLATFORM_PRIORITY = [49, 79, 167, 109, 12, 27, 83, 106, 15, 105, 80, 24, 43]

FRANCHISE_MAP = {
    "ZELDA": "#LegendOfZelda", "MARIO": "#SuperMario", "METROID": "#Metroid",
    "SONIC": "#SonicTheHedgehog", "FINAL FANTASY": "#FinalFantasy",
    "RESIDENT EVIL": "#ResidentEvil", "METAL GEAR": "#MetalGear",
    "CASTLEVANIA": "#Castlevania", "MEGA MAN": "#MegaMan",
    "STREET FIGHTER": "#StreetFighter", "DONKEY KONG": "#DonkeyKong",
    "PHANTASY STAR": "#PhantasyStar", "MIDNIGHT CLUB": "#MidnightClub",
    "TEKKEN": "#Tekken", "MORTAL KOMBAT": "#MortalKombat", "PAC-MAN": "#PacMan",
    "EVERMORE": "#SecretOfEvermore", "CHRONO": "#ChronoTrigger", "GRAND THEFT AUTO": "#GrandTheftAuto"
}

RETRO_PLATFORMS = {
    167: "Sega Genesis", 79: "SNES", 24: "GBA", 27: "PS1", 15: "PS2",
    83: "N64", 106: "Dreamcast", 80: "Xbox", 49: "NES", 105: "GameCube",
    109: "TurboGrafx-16", 117: "Sega 32X", 119: "Sega CD", 12: "Neo Geo", 43: "GBC"
}
RETRO_IDS_STR = ",".join(map(str, RETRO_PLATFORMS.keys()))
GENRES = {"Platformer": 83, "Shooter": 2, "RPG": 5, "Fighting": 6, "Racing": 1}

SCHEDULE = {
    0: {9: 1,  15: 2,  21: 13},
    1: {9: 9,  15: 3,  21: 14},
    2: {9: 4,  15: 17, 21: 13},
    3: {9: 6,  15: 18, 21: 14},
    4: {9: 9,  15: 8,  21: 13},
    5: {9: 9,  15: 10, 21: 15},
    6: {9: 11, 15: 12, 21: 13}
}

# Words Claude keeps defaulting to — ban them explicitly
BANNED_WORDS = [
    "captivating", "mesmerizing", "stunning", "breathtaking", "timeless",
    "iconic", "legendary", "masterpiece", "unforgettable", "remarkable",
    "incredible", "amazing", "fascinating", "enthralling", "immersive",
    "revolutionary", "groundbreaking", "beloved", "cherished", "nostalgic journey"
]

# Varied prompt openers to force different writing styles each run
PROMPT_STYLES = [
    "Write like a passionate retro gamer texting a friend.",
    "Write like a game critic who is brutally honest but fair.",
    "Write like someone who just found this game in a garage sale.",
    "Write like a speedrunner who knows this game inside out.",
    "Write like a parent who played this with their kid in the 90s.",
    "Write like someone defending this game in an argument.",
    "Write like a game historian dropping a fun obscure fact.",
    "Write in a punchy, tweet-style voice with energy.",
    "Write like someone who just replayed this for the first time in 20 years.",
    "Write like a retro collector explaining why this cartridge matters.",
]

# --- HELPERS ---

def load_json(filename, default):
    try:
        if os.path.exists(filename):
            with open(filename, 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"⚠️  Could not load {filename}: {e}")
    return default

def save_json(filename, data):
    try:
        with open(filename, 'w') as f:
            json.dump(data, f)
        logger.info(f"💾 Saved {filename} successfully")
    except Exception as e:
        logger.warning(f"⚠️  Could not save {filename}: {e}")

def download_image(url):
    if not url:
        return None
    try:
        logger.debug(f"🖼️  Downloading image: {url[:60]}...")
        resp = requests.get(url, timeout=12)
        if resp.status_code == 200:
            return Image.open(BytesIO(resp.content))
        else:
            logger.warning(f"⚠️  Image download failed with status {resp.status_code}")
            return None
    except Exception as e:
        logger.warning(f"⚠️  Image download error: {e}")
        return None

def image_to_bytes(img):
    quality = 85
    for attempt in range(5):
        buf = BytesIO()
        temp_img = img.convert("RGB")
        temp_img.save(buf, format="JPEG", quality=quality)
        data = buf.getvalue()
        if len(data) < 950000:
            logger.debug(f"🗜️  Image compressed to {len(data)//1024}KB at quality {quality}")
            return data
        quality -= 15
    logger.warning(f"⚠️  Image still {len(data)//1024}KB after max compression")
    return data

def create_collage(images):
    if not images or len(images) < 2:
        return images[0] if images else None
    target_h = 600
    resized = [img.resize((int(target_h * (img.width / img.height)), target_h)) for img in images[:2]]
    total_w = sum(i.width for i in resized)
    collage = Image.new('RGB', (total_w, target_h))
    x = 0
    for i in resized:
        collage.paste(i, (x, 0))
        x += i.width
    logger.info(f"🖼️  Created collage ({total_w}x{target_h}px)")
    return collage

def clean_game_hashtag(game_name, current_tags):
    upper = game_name.upper()
    for k, v in FRANCHISE_MAP.items():
        if k in upper:
            return v
    clean_name = re.sub(r'[^a-zA-Z0-9\s]', '', game_name)
    words = clean_name.split()[:3]
    tag = "#" + "".join(word.capitalize() for word in words)
    if len(tag) > 25 or len(tag) < 3:
        return "#Nostalgia" if "#Nostalgia" not in current_tags else None
    return tag

def get_platform_tags(game_data):
    p_ids = [p['platform']['id'] for p in game_data.get('platforms', [])]
    for priority_id in PLATFORM_PRIORITY:
        if priority_id in p_ids:
            tag = f"#{RETRO_PLATFORMS[priority_id].replace(' ', '')}"
            logger.info(f"🕹️  Platform tag resolved: {tag}")
            return [tag]
    return ["#RetroGaming"]

def build_anti_repetition_instruction():
    banned = ", ".join(f'"{w}"' for w in BANNED_WORDS)
    style = random.choice(PROMPT_STYLES)
    return (
        f"{style} "
        f"NEVER use these overused words: {banned}. "
        f"Be specific, concrete, and surprising. Avoid generic praise. "
        f"Use a different structure than: hook → describe → question. "
        f"Try starting with a fact, a strong opinion, a memory, or a bold claim instead."
    )

def fetch_games_list(api_key, count=1, genre_id=None, dates=None):
    rand_page = random.randint(1, 10)
    url = f"https://api.rawg.io/api/games?key={api_key}&platforms={RETRO_IDS_STR}&page_size=40&page={rand_page}"
    if genre_id:
        url += f"&genres={genre_id}"
    if dates:
        url += f"&dates={dates}"
    logger.info(f"🔍 Fetching games list (page {rand_page}, genre={genre_id}, dates={dates})")
    try:
        resp = requests.get(url, timeout=10).json()
        results = resp.get('results', [])
        logger.info(f"📋 RAWG returned {len(results)} games")
        history = load_json('history_games.json', [])
        available = [g for g in results if g['id'] not in history]
        logger.info(f"📋 {len(available)} games not seen before (history size: {len(history)})")
        if not available:
            logger.warning("⚠️  All results already in history, allowing repeats")
            available = results
        selected = random.sample(available, min(len(available), count))
        for g in selected:
            logger.info(f"🎯 Selected game: '{g['name']}' (ID: {g['id']})")
        return selected
    except Exception as e:
        logger.error(f"❌ Failed to fetch games list: {e}")
        return []

def deep_fetch_game(api_key, game_id):
    url = f"https://api.rawg.io/api/games/{game_id}?key={api_key}"
    logger.info(f"🔎 Deep fetching game ID: {game_id}")
    try:
        data = requests.get(url, timeout=10).json()
        logger.info(f"✅ Deep fetch OK: '{data.get('name', 'Unknown')}' | Released: {data.get('released', 'N/A')} | Rating: {data.get('rating', 'N/A')}")
        return data
    except Exception as e:
        logger.error(f"❌ Deep fetch failed for game {game_id}: {e}")
        return None

def get_deep_images(api_key, full_game_obj, limit=3):
    final_imgs, seen_urls = [], set()
    game_name = full_game_obj.get('name', 'Unknown')

    def add_url(url):
        if url and url not in seen_urls and len(final_imgs) < limit:
            img = download_image(url)
            if img:
                final_imgs.append(img)
                seen_urls.add(url)

    add_url(full_game_obj.get('background_image_additional'))
    add_url(full_game_obj.get('background_image'))
    try:
        ss_url = f"https://api.rawg.io/api/games/{full_game_obj['id']}/screenshots?key={api_key}"
        res = requests.get(ss_url, timeout=10).json().get('results', [])
        logger.info(f"📸 Found {len(res)} screenshots for '{game_name}'")
        for s in res:
            add_url(s.get('image'))
    except Exception as e:
        logger.warning(f"⚠️  Screenshot fetch failed: {e}")
    if len(final_imgs) < limit:
        for s in full_game_obj.get('short_screenshots', []):
            add_url(s.get('image'))

    logger.info(f"🖼️  Total images collected for '{game_name}': {len(final_imgs)}")
    return final_imgs

def call_claude(anthropic_key, prompt, slot_tag):
    logger.info(f"🤖 Calling Claude API for slot {slot_tag}...")
    logger.debug(f"📝 Prompt preview: {prompt[:120]}...")
    try:
        msg = anthropic.Anthropic(api_key=anthropic_key).messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )
        text = msg.content[0].text.strip().replace('"', '')
        logger.info(f"✅ Claude responded ({len(text)} chars)")
        logger.info(f"📣 Generated text: {text[:180]}{'...' if len(text) > 180 else ''}")
        return text
    except Exception as e:
        logger.error(f"❌ Claude API call failed: {e}")
        raise

def post_to_bluesky(bsky, tb, blobs, game_name, slot_tag):
    embed = models.AppBskyEmbedImages.Main(images=blobs) if blobs else None
    logger.info(f"📤 Posting to Bluesky | Game: '{game_name}' | Slot: {slot_tag} | Images: {len(blobs)}")
    try:
        result = bsky.send_post(tb, embed=embed)
        logger.info(f"✅ POST SUCCESSFUL | URI: {getattr(result, 'uri', 'N/A')}")
        return result
    except Exception as e:
        logger.error(f"❌ Bluesky post failed: {e}")
        raise

# --- CORE HANDLERS ---

def run_rivalry(bsky, api_key, anthropic_key):
    logger.info("⚔️  Starting RIVALRY post")
    g_name, g_id = random.choice(list(GENRES.items()))
    logger.info(f"🎮 Genre selected: {g_name} (ID: {g_id})")

    games_basic = fetch_games_list(api_key, count=2, genre_id=g_id)
    if len(games_basic) < 2:
        logger.error("❌ Could not fetch 2 games for rivalry — aborting")
        return

    g1 = deep_fetch_game(api_key, games_basic[0]['id'])
    g2 = deep_fetch_game(api_key, games_basic[1]['id'])

    anti_rep = build_anti_repetition_instruction()
    prompt = (
        f"{anti_rep} "
        f"Compare '{g1['name']}' vs '{g2['name']}' in a retro gaming rivalry post. "
        f"Be punchy and opinionated. End with a 'Pick one' question. "
        f"Max 200 chars. No hashtags in body."
    )
    text = call_claude(anthropic_key, prompt, "#Rivalry")

    tags = ["#Retro", "#RetroGaming", "#Rivalry"]
    for g in [g1, g2]:
        t = clean_game_hashtag(g['name'], tags)
        if t:
            tags.append(t)
    unique_tags = list(dict.fromkeys(tags))
    logger.info(f"🏷️  Tags: {' '.join(unique_tags)}")

    tb = client_utils.TextBuilder()
    tb.text(f"{text[:220]}\n\n")
    for i, t in enumerate(unique_tags):
        tb.tag(t, t.replace("#", ""))
        if i < len(unique_tags) - 1:
            tb.text(" ")

    final_imgs = []
    c1 = download_image(g1.get('background_image_additional') or g1.get('background_image'))
    c2 = download_image(g2.get('background_image_additional') or g2.get('background_image'))
    if c1 and c2:
        final_imgs.append(create_collage([c1, c2]))
    for g in [g1, g2]:
        sc = get_deep_images(api_key, g, limit=5)
        if len(sc) > 1:
            final_imgs.append(sc[1])

    if random.random() < RANDOM_PROMO_CHANCE and os.path.exists("images/promo_ad.jpg"):
        logger.info("📢 Adding promo image")
        with Image.open("images/promo_ad.jpg") as ad:
            final_imgs.append(ad.copy())

    blobs = []
    for i in final_imgs[:4]:
        if i:
            blob = bsky.upload_blob(image_to_bytes(i)).blob
            blobs.append(models.AppBskyEmbedImages.Image(alt="Rivalry", image=blob))

    post_to_bluesky(bsky, tb, blobs, f"{g1['name']} vs {g2['name']}", "#Rivalry")


def run_single_game(bsky, api_key, anthropic_key, theme_desc, slot_tag, force_on_this_day=False):
    logger.info(f"🎮 Starting SINGLE GAME post | Theme: {theme_desc} | Slot: {slot_tag} | OnThisDay: {force_on_this_day}")

    game, header, now = None, "", datetime.now()
    matched_exactly = False

    if force_on_this_day:
        yr = random.randint(1985, 2005)
        d_str = f"{yr}-{now.strftime('%m-%d')}"
        logger.info(f"📅 Trying exact On This Day: {d_str}")
        res = fetch_games_list(api_key, count=1, dates=f"{d_str},{d_str}")
        if res:
            game, header, matched_exactly = res[0], f"📅 On This Day in {yr}\n\n", True
            logger.info(f"✅ Exact date match found: '{game['name']}'")
        else:
            m_name, yr_fb = now.strftime('%B'), random.randint(1985, 2005)
            logger.info(f"⚠️  No exact match — falling back to month {m_name} {yr_fb}")
            res = fetch_games_list(api_key, count=1, dates=f"{yr_fb}-{now.strftime('%m')}-01,{yr_fb}-{now.strftime('%m')}-28")
            if res:
                game, header = res[0], f"🗓️ In {m_name}, {yr_fb}\n\n"
                logger.info(f"✅ Month fallback match: '{game['name']}'")
            else:
                logger.warning("⚠️  Month fallback also failed — using random game")

    if not game:
        logger.info("🎲 Fetching random game (no date filter)")
        game = (fetch_games_list(api_key, count=1) or [None])[0]

    if not game:
        logger.error("❌ No game found at all — aborting post")
        return

    full = deep_fetch_game(api_key, game['id'])
    if not full:
        logger.error(f"❌ Deep fetch failed for game '{game.get('name')}' — aborting")
        return

    # --- Tone / grounding logic ---
    rel_str = full.get('released', 'Unknown')
    tone_hint = "Speak about this game's legacy generally."
    if rel_str != 'Unknown':
        try:
            r_y, r_m, r_d = map(int, rel_str.split('-'))
            age = CURRENT_YEAR - r_y
            if matched_exactly and now.month == r_m and now.day == r_d:
                tone_hint = f"Celebrate its EXACT {age}th anniversary today! Be excited."
            elif now.month == r_m:
                tone_hint = f"It's the anniversary month! Mention it turns {age} this year."
            else:
                tone_hint = f"It came out in {r_y}, that's {age} years ago now."
        except Exception as e:
            logger.warning(f"⚠️  Could not parse release date '{rel_str}': {e}")

    logger.info(f"📝 Tone: {tone_hint}")

    # --- YouTube CTA on some slots ---
    yt_cta = ""
    if slot_tag in ["#Nostalgia", "#RetroGaming", "#OnThisDay"] and random.random() < 0.4:
        yt_cta = " (I live stream retro games on YouTube — link in bio if you want to watch)"
        logger.info("📺 Adding YouTube CTA to this post")

    anti_rep = build_anti_repetition_instruction()
    prompt = (
        f"{anti_rep} "
        f"Write a {theme_desc} post about '{full['name']}'. "
        f"Context: {tone_hint} Current Year: {CURRENT_YEAR}. "
        f"Rules: Be specific about THIS game — mechanics, a scene, a feeling. "
        f"End with a genuine question that invites replies. "
        f"Max 220 chars. No hashtags in body. Do NOT lie about dates."
        f"{yt_cta}"
    )

    text = call_claude(anthropic_key, prompt, slot_tag)

    tags = ["#Retro", "#RetroGaming", slot_tag] + get_platform_tags(full)
    gtag = clean_game_hashtag(full['name'], tags)
    if gtag:
        tags.append(gtag)
    unique_tags = list(dict.fromkeys(tags))
    logger.info(f"🏷️  Tags: {' '.join(unique_tags)}")

    final_body = f"{header}{text}"
    if len(final_body) > 250:
        final_body = final_body[:245].rsplit('.', 1)[0] + "."
        logger.info(f"✂️  Text trimmed to {len(final_body)} chars")

    tb = client_utils.TextBuilder()
    tb.text(f"{final_body}\n\n")
    for i, t in enumerate(unique_tags):
        tb.tag(t, t.replace("#", ""))
        if i < len(unique_tags) - 1:
            tb.text(" ")

    final_imgs = get_deep_images(api_key, full, limit=3)

    if random.random() < RANDOM_PROMO_CHANCE and os.path.exists("images/promo_ad.jpg"):
        logger.info("📢 Adding promo image")
        with Image.open("images/promo_ad.jpg") as ad:
            final_imgs.append(ad.copy())

    blobs = []
    for i in final_imgs[:4]:
        if i:
            blob = bsky.upload_blob(image_to_bytes(i)).blob
            blobs.append(models.AppBskyEmbedImages.Image(alt=full['name'], image=blob))

    post_to_bluesky(bsky, tb, blobs, full['name'], slot_tag)

    history = load_json('history_games.json', [])
    updated = (history + [full['id']])[-2000:]
    save_json('history_games.json', updated)
    logger.info(f"📚 History updated: {len(updated)} games tracked")


# --- MAIN ---

def main():
    logger.info("=" * 60)
    logger.info("--- 🚀 RETRO BOT START ---")
    logger.info(f"⏰ UTC Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"📅 Local Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    # --- Env check ---
    rk  = os.environ.get("RAWG_API_KEY")
    ak  = os.environ.get("ANTHROPIC_API_KEY")
    h   = os.environ.get("BLUESKY_HANDLE")
    p   = os.environ.get("BLUESKY_PASSWORD")
    f   = os.environ.get("FORCED_SLOT", "")
    m   = os.environ.get("IS_MANUAL") == "true"

    logger.info(f"🔑 Env check — RAWG: {'✅' if rk else '❌ MISSING'} | Anthropic: {'✅' if ak else '❌ MISSING'} | Bluesky handle: {'✅' if h else '❌ MISSING'} | Bluesky pw: {'✅' if p else '❌ MISSING'}")
    logger.info(f"⚙️  Manual trigger: {m} | Forced slot input: '{f}'")

    if not h or not p:
        logger.error("❌ Bluesky credentials missing — aborting")
        return

    # --- Login ---
    try:
        bsky = Client()
        bsky.login(h, p)
        logger.info("✅ Bluesky login successful")
    except Exception as e:
        logger.error(f"❌ Bluesky login failed: {e}")
        return

    # --- Slot resolution ---
    n = datetime.utcnow()
    slot_id = None

    if m and "Slot" in f:
        match = re.search(r'Slot\s*(\d+)', f)
        if match:
            slot_id = int(match.group(1))
            logger.info(f"🎛️  Manual override — using Slot {slot_id}")

    if slot_id is None:
        day_schedule = SCHEDULE.get(n.weekday(), {})
        slot_id = day_schedule.get(n.hour)
        logger.info(f"📅 Schedule lookup — weekday: {n.weekday()} ({n.strftime('%A')}) | hour: {n.hour} UTC")
        logger.info(f"📋 Available slots for today: {day_schedule}")
        if slot_id:
            logger.info(f"✅ Scheduled slot resolved: Slot {slot_id}")
        else:
            logger.warning(f"⚠️  No slot scheduled for weekday={n.weekday()} hour={n.hour} UTC — nothing to post")

    if not slot_id:
        logger.info("🏁 Bot exiting cleanly — no slot to run at this time")
        logger.info("=" * 60)
        return

    # --- Handler map ---
    handlers = {
        1:  lambda b: run_single_game(b, rk, ak, "nostalgic and cozy memory", "#Nostalgia"),
        9:  lambda b: run_single_game(b, rk, ak, "surprising historical fact", "#RetroGaming"),
        4:  lambda b: run_single_game(b, rk, ak, "spicy unpopular opinion", "#UnpopularOpinion"),
        6:  lambda b: run_single_game(b, rk, ak, "mysterious hidden gem", "#HiddenGem"),
        11: lambda b: run_single_game(b, rk, ak, "relaxing weekend morning", "#RetroGaming"),
        2:  lambda b: run_single_game(b, rk, ak, "fast quick spotlight", "#ClassicGaming"),
        3:  lambda b: run_rivalry(b, rk, ak),
        18: lambda b: run_rivalry(b, rk, ak),
        17: lambda b: run_single_game(b, rk, ak, "nerdy gameplay mechanics dive", "#RetroGaming"),
        8:  lambda b: run_single_game(b, rk, ak, "tribute to the developers", "#RetroDev"),
        10: lambda b: run_single_game(b, rk, ak, "visual art direction focus", "#BoxArt"),
        12: lambda b: run_single_game(b, rk, ak, "Sunday playthrough", "#RetroGaming"),
        13: lambda b: run_single_game(b, rk, ak, "anniversary", "#OnThisDay", True),
        14: lambda b: run_single_game(b, rk, ak, "legacy impact", "#OnThisDay", True),
        15: lambda b: run_single_game(b, rk, ak, "historical release context", "#OnThisDay", True)
    }

    logger.info(f"▶️  Running Slot {slot_id}...")
    if slot_id in handlers:
        try:
            handlers[slot_id](bsky)
            logger.info(f"✅ Slot {slot_id} completed successfully")
        except Exception as e:
            logger.error(f"❌ Slot {slot_id} failed with error: {e}")
            raise
    else:
        logger.warning(f"⚠️  Slot {slot_id} has no handler defined")

    logger.info("=" * 60)
    logger.info("--- 🏁 RETRO BOT END ---")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
