import os
import sys
import json
import random
import requests
import logging
from io import BytesIO
from datetime import datetime
from PIL import Image
from atproto import Client, models, client_utils
import anthropic

# --- LOGGING SETUP (Must be at the top!) ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger()

# --- CONFIGURATION ---
RAWG_API_KEY = os.environ.get("RAWG_API_KEY")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
BSKY_HANDLE = os.environ.get("BLUESKY_HANDLE")
BSKY_PASSWORD = os.environ.get("BLUESKY_PASSWORD")

# --- CONSTANTS & SCHEDULE ---
SCHEDULE = {
    0: {10: 1, 15: 2},   # Mon
    1: {10: 3},          # Tue
    2: {10: 4, 15: 5},   # Wed
    3: {10: 6},          # Thu
    4: {10: 7, 15: 8},   # Fri
    5: {10: 9, 15: 10},  # Sat
    6: {10: 11, 15: 12}  # Sun
}

MONDAY_FEATURES = [
    {"name": "Retro Radio", "url": "https://nostalgia.icu/radio", "img": "images/ad_radio.jpg", "tag": "#Radio"},
    {"name": "Nostalgia Quest", "url": "https://nostalgia.icu/login", "img": "images/ad_quest.jpg", "tag": "#RPG"},
    {"name": "Game Database", "url": "https://nostalgia.icu", "img": "images/ad_general.jpg", "tag": "#Library"},
    {"name": "Pixel Challenge", "url": "https://nostalgia.icu/challenge", "img": "images/ad_general.jpg", "tag": "#Challenge"} 
]

GENERIC_TOPICS = [
    "Memory Cards", "Cheat Codes", "Couch Co-op", "Game Over Screens", "Demo Discs", 
    "Instruction Manuals", "Boss Fights", "Soundtracks", "Loading Screens", "Controller Cables",
    "Video Rental Stores", "Strategy Guides", "Save Points", "Easter Eggs", "Start Menus"
]

PLATFORM_TAGS = {
    "PlayStation": "#PS1", "PlayStation 2": "#PS2", "PlayStation 3": "#PS3",
    "Xbox": "#Xbox", "Xbox 360": "#Xbox360",
    "SNES": "#SNES", "NES": "#NES", "Nintendo 64": "#N64", "GameCube": "#GameCube",
    "Game Boy": "#GameBoy", "Game Boy Advance": "#GBA", "Sega Genesis": "#SegaGenesis",
    "Dreamcast": "#Dreamcast", "PC": "#PCGaming"
}

RIVAL_PAIRS = [
    {"p1": "27", "p2": "83", "t1": "#PS1", "t2": "#N64"},      # PS1 vs N64
    {"p1": "15", "p2": "80", "t1": "#PS2", "t2": "#Xbox"},     # PS2 vs Xbox
    {"p1": "79", "p2": "167", "t1": "#SNES", "t2": "#Sega"},   # SNES vs Genesis
    {"p1": "106", "p2": "15", "t1": "#Dreamcast", "t2": "#PS2"} # Dreamcast vs PS2
]

# --- HELPERS ---

def load_json(filename, default):
    if os.path.exists(filename):
        try:
            with open(filename, 'r') as f: return json.load(f)
        except: return default
    return default

def save_json(filename, data):
    with open(filename, 'w') as f: json.dump(data, f)

def get_claude_text(prompt):
    if not ANTHROPIC_API_KEY: return None
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model="claude-3-haiku-20240307", max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )
        return msg.content[0].text.strip()
    except Exception as e:
        logger.error(f"Claude Error: {e}")
        return None

def download_image(url):
    try:
        resp = requests.get(url, timeout=10)
        return Image.open(BytesIO(resp.content)) if resp.status_code == 200 else None
    except: return None

def image_to_bytes(img):
    buf = BytesIO()
    img = img.convert("RGB")
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()

def create_collage(images, grid=(2,1)):
    if not images: return None
    target_h = 600
    resized_imgs = []
    for img in images:
        aspect = img.width / img.height
        new_w = int(target_h * aspect)
        resized_imgs.append(img.resize((new_w, target_h)))

    if grid == (2,1):
        total_w = sum(i.width for i in resized_imgs)
        collage = Image.new('RGB', (total_w, target_h))
        x_off = 0
        for img in resized_imgs:
            collage.paste(img, (x_off, 0))
            x_off += img.width
        return collage
    
    elif grid == (2,2):
        target_size = 600
        collage = Image.new('RGB', (target_size*2, target_size*2))
        for idx, img in enumerate(resized_imgs[:4]):
            min_dim = min(img.width, img.height)
            left = (img.width - min_dim)/2
            top = (img.height - min_dim)/2
            img = img.crop((left, top, left+min_dim, top+min_dim)).resize((target_size, target_size))
            x = (idx % 2) * target_size
            y = (idx // 2) * target_size
            collage.paste(img, (x, y))
        return collage
    return images[0]

def get_platform_tag(game_data):
    for p in game_data.get('platforms', []):
        name = p['platform']['name']
        if name in PLATFORM_TAGS: return PLATFORM_TAGS[name]
    return "#RetroGaming"

def fetch_games_from_rawg(count=1, platform_ids=None):
    used_games = load_json('history_games.json', [])
    found_games = []
    
    for _ in range(10): # Max attempts
        if len(found_games) >= count: break
        page = random.randint(1, 200)
        platforms = platform_ids if platform_ids else "27,15,83,79,24,167,80,106"
        url = f"https://api.rawg.io/api/games?key={RAWG_API_KEY}&platforms={platforms}&ordering=-rating&page_size={count*2}&page={page}"
        try:
            data = requests.get(url).json()
            for cand in data.get('results', []):
                if cand['id'] not in used_games and cand['id'] not in [g['id'] for g in found_games]:
                    if cand.get('background_image'):
                        found_games.append(cand)
                        if len(found_games) == count: break
        except Exception as e:
            logger.error(f"RAWG Error: {e}")

    if found_games:
        new_ids = [g['id'] for g in found_games]
        used_games.extend(new_ids)
        if len(used_games) > 2000: used_games = used_games[-2000:]
        save_json('history_games.json', used_games)
        
    return found_games

# --- SLOT HANDLERS (Same as before) ---
def run_slot_1_ad(bsky):
    history = load_json('history_ads.json', {'last_index': -1})
    idx = (history['last_index'] + 1) % len(MONDAY_FEATURES)
    feature = MONDAY_FEATURES[idx]
    
    prompt = f"Write a high-energy 1-sentence hook promoting '{feature['name']}' (a retro gaming tool). No hashtags."
    text = get_claude_text(prompt) or f"Discover {feature['name']} now!"
    
    tb = client_utils.TextBuilder()
    tb.text(text + "\n\n🔗 ")
    tb.link(feature['url'], feature['url'])
    tb.text("\n\n")
    tb.tag("#Retro", "Retro"); tb.text(" ")
    tb.tag("#Nostalgia", "Nostalgia"); tb.text(" ")
    tb.tag(feature['tag'], feature['tag'].replace("#", ""))
    
    img_bytes = None
    if os.path.exists(feature['img']):
        with open(feature['img'], 'rb') as f: img_bytes = f.read()
    
    if img_bytes:
        upload = bsky.upload_blob(img_bytes)
        embed = models.AppBskyEmbedImages.Main(images=[models.AppBskyEmbedImages.Image(alt=feature['name'], image=upload.blob)])
        bsky.send_post(tb, embed=embed)
        save_json('history_ads.json', {'last_index': idx})
        logger.info(f"✅ Slot 1 Posted: {feature['name']}")

def run_generic_q(bsky):
    used_q = load_json('history_questions.json', [])
    topic = random.choice([t for t in GENERIC_TOPICS if t not in used_q[-5:]])
    prompt = f"Write a short, engaging question for retro gamers about '{topic}'. Under 200 chars. No hashtags."
    text = get_claude_text(prompt) or f"What's your take on {topic} in retro games?"
    tb = client_utils.TextBuilder()
    tb.text(text + "\n\n")
    tb.tag("#Retro", "Retro"); tb.text(" ")
    tb.tag("#RetroGaming", "RetroGaming")
    bsky.send_post(tb)
    used_q.append(topic)
    save_json('history_questions.json', used_q[-50:])
    logger.info(f"✅ Generic Q Posted: {topic}")

def run_rivalry(bsky):
    pair = random.choice(RIVAL_PAIRS)
    games_p1 = fetch_games_from_rawg(1, pair['p1'])
    games_p2 = fetch_games_from_rawg(1, pair['p2'])
    if not games_p1 or not games_p2: return
    g1, g2 = games_p1[0], games_p2[0]
    prompt = f"Write a 'vs' question comparing {g1['name']} ({pair['t1']}) and {g2['name']} ({pair['t2']}). Who won this generation? Under 240 chars."
    text = get_claude_text(prompt) or f"{g1['name']} vs {g2['name']}. Which one did you play?"
    imgs_to_upload = []
    i1 = download_image(g1['background_image'])
    i2 = download_image(g2['background_image'])
    if i1 and i2:
        collage = create_collage([i1, i2], grid=(2,1))
        blob = bsky.upload_blob(image_to_bytes(collage)).blob
        imgs_to_upload.append(models.AppBskyEmbedImages.Image(alt="Rivalry Collage", image=blob))
    for g in [g1, g2]:
        if g.get('short_screenshots'):
            s_url = g['short_screenshots'][0]['image']
            s_img = download_image(s_url)
            if s_img:
                blob = bsky.upload_blob(image_to_bytes(s_img)).blob
                imgs_to_upload.append(models.AppBskyEmbedImages.Image(alt=g['name'], image=blob))
    if os.path.exists("images/promo_ad.jpg"):
        with open("images/promo_ad.jpg", "rb") as f:
            blob = bsky.upload_blob(f.read()).blob
            imgs_to_upload.append(models.AppBskyEmbedImages.Image(alt="Nostalgia.icu", image=blob))
    tb = client_utils.TextBuilder()
    tb.text(text + "\n\n")
    tb.tag("#Retro", "Retro"); tb.text(" ")
    tb.tag("#RetroGaming", "RetroGaming"); tb.text(" ")
    tb.tag(pair['t1'], pair['t1'].replace("#", "")); tb.text(" ")
    tb.tag(pair['t2'], pair['t2'].replace("#", ""))
    bsky.send_post(tb, embed=models.AppBskyEmbedImages.Main(images=imgs_to_upload[:4]))
    logger.info("✅ Rivalry Posted")

def run_single_game_post(bsky, slot_type):
    game_list = fetch_games_from_rawg(1)
    if not game_list: return
    game = game_list[0]
    configs = {
        "Unpopular": {"prompt": "unpopular opinion about difficulty or design", "tag": "#UnpopularOpinion"},
        "Obscure": {"prompt": "why this is a hidden gem", "tag": "#HiddenGem"},
        "Aesthetic": {"prompt": "praise the art style/graphics", "tag": "#PixelArt"},
        "Memory": {"prompt": "ask for a specific childhood memory", "tag": None}
    }
    cfg = configs[slot_type]
    prompt = f"Write a Bluesky post about '{game['name']}'. Theme: {cfg['prompt']}. Under 240 chars. No hashtags."
    text = get_claude_text(prompt) or f"Remember {game['name']}?"
    imgs_to_upload = []
    main_img = download_image(game['background_image'])
    if main_img:
        blob = bsky.upload_blob(image_to_bytes(main_img)).blob
        imgs_to_upload.append(models.AppBskyEmbedImages.Image(alt=game['name'], image=blob))
    for shot in game.get('short_screenshots', [])[:2]:
        s_img = download_image(shot['image'])
        if s_img:
            blob = bsky.upload_blob(image_to_bytes(s_img)).blob
            imgs_to_upload.append(models.AppBskyEmbedImages.Image(alt="Gameplay", image=blob))
    if os.path.exists("images/promo_ad.jpg"):
        with open("images/promo_ad.jpg", "rb") as f:
            blob = bsky.upload_blob(f.read()).blob
            imgs_to_upload.append(models.AppBskyEmbedImages.Image(alt="Nostalgia.icu", image=blob))
    plat_tag = get_platform_tag(game)
    tb = client_utils.TextBuilder()
    tb.text(text + "\n\n")
    tb.tag("#Retro", "Retro"); tb.text(" ")
    tb.tag("#RetroGaming", "RetroGaming"); tb.text(" ")
    tb.tag(plat_tag, plat_tag.replace("#", ""))
    if cfg['tag']:
        tb.text(" ")
        tb.tag(cfg['tag'], cfg['tag'].replace("#", ""))
    bsky.send_post(tb, embed=models.AppBskyEmbedImages.Main(images=imgs_to_upload[:4]))
    logger.info(f"✅ {slot_type} Posted: {game['name']}")

def run_fact(bsky):
    game_list = fetch_games_from_rawg(1)
    if not game_list: return
    game = game_list[0]
    prompt = f"Tell a surprising, short trivia fact about the video game '{game['name']}'. Under 200 chars. No hashtags."
    text = get_claude_text(prompt) or f"Did you know {game['name']} is considered a classic?"
    plat_tag = get_platform_tag(game)
    tb = client_utils.TextBuilder()
    tb.text(f"Did you know? 🧠\n\n{text}\n\n")
    tb.tag("#Retro", "Retro"); tb.text(" ")
    tb.tag("#RetroGaming", "RetroGaming"); tb.text(" ")
    tb.tag(plat_tag, plat_tag.replace("#", "")); tb.text(" ")
    tb.tag("#Trivia", "Trivia")
    bsky.send_post(tb)
    used_f = load_json('history_facts.json', [])
    used_f.append(game['id'])
    save_json('history_facts.json', used_f)
    logger.info(f"✅ Fact Posted: {game['name']}")

def run_starter_pack(bsky):
    games = fetch_games_from_rawg(4)
    if len(games) < 4: return
    prompt = "Ask: 'You have to delete one of these classics forever. Which one goes?' Under 200 chars."
    text = get_claude_text(prompt) or "One has to go. Which one do you choose?"
    imgs_to_upload = []
    pil_imgs = [download_image(g['background_image']) for g in games]
    pil_imgs = [p for p in pil_imgs if p]
    if len(pil_imgs) >= 4:
        collage = create_collage(pil_imgs[:4], grid=(2,2))
        blob = bsky.upload_blob(image_to_bytes(collage)).blob
        imgs_to_upload.append(models.AppBskyEmbedImages.Image(alt="Starter Pack", image=blob))
    for g in games[:2]:
        if g.get('short_screenshots'):
            s_img = download_image(g['short_screenshots'][0]['image'])
            if s_img:
                blob = bsky.upload_blob(image_to_bytes(s_img)).blob
                imgs_to_upload.append(models.AppBskyEmbedImages.Image(alt="Gameplay", image=blob))
    if os.path.exists("images/promo_ad.jpg"):
        with open("images/promo_ad.jpg", "rb") as f:
            blob = bsky.upload_blob(f.read()).blob
            imgs_to_upload.append(models.AppBskyEmbedImages.Image(alt="Nostalgia.icu", image=blob))
    tb = client_utils.TextBuilder()
    tb.text(text + "\n\n")
    tb.tag("#Retro", "Retro"); tb.text(" ")
    tb.tag("#RetroGaming", "RetroGaming"); tb.text(" ")
    tb.tag("#GamingSetup", "GamingSetup")
    bsky.send_post(tb, embed=models.AppBskyEmbedImages.Main(images=imgs_to_upload[:4]))
    logger.info("✅ Starter Pack Posted")

# --- MAIN DISPATCHER ---
def main():
    logger.info("--- BOT RUN STARTED ---")
    
    # 1. Login
    try:
        bsky = Client()
        bsky.login(BSKY_HANDLE, BSKY_PASSWORD)
        logger.info("✅ Connected to Bluesky.")
    except Exception as e:
        logger.error(f"❌ Login Failed: {e}")
        return

    # 2. Determine Slot
    now = datetime.utcnow()
    day = now.weekday()
    hour = now.hour
    
    # INPUT HANDLING (Dropdown text parsing)
    # The dropdown gives us string like "Slot 3: Tue 10:00..."
    # We need to extract the number "3" or determine if it's "Auto-Detect"
    
    forced_input = os.environ.get("FORCED_SLOT", "")
    is_manual = os.environ.get("IS_MANUAL") == "true"
    
    slot_id = None

    if is_manual and "Slot" in forced_input:
        # Extract the integer from "Slot 3: ..."
        try:
            parts = forced_input.split(":") 
            # "Slot 3" -> split " " -> ["Slot", "3"]
            slot_id = int(parts[0].replace("Slot", "").strip())
            logger.info(f"🛠️ Manual Override: User selected Slot {slot_id}")
        except Exception as e:
            logger.error(f"❌ Could not parse slot ID from '{forced_input}': {e}")
            return

    elif is_manual and "Auto-Detect" in forced_input:
        # Manual run but user chose "Auto"
        # Since it's likely testing at a weird time, just force the first slot of the current day
        todays_slots = list(SCHEDULE.get(day, {}).values())
        if todays_slots:
            slot_id = todays_slots[0]
            logger.info(f"⚡ Manual Auto-Run: Forcing today's Slot {slot_id}")
        else:
            logger.warning("⚠️ No slots found for today.")

    elif not is_manual:
        # Standard CRON Run
        slot_id = SCHEDULE.get(day, {}).get(hour)
        if not slot_id:
            logger.info(f"⏳ No slot scheduled for UTC Day {day} Hour {hour}. Exiting.")
            return

    # 3. Execute
    logger.info(f"🚀 Executing Slot {slot_id}...")

    if slot_id == 1: run_slot_1_ad(bsky)
    elif slot_id == 2: run_generic_q(bsky)
    elif slot_id == 3: run_rivalry(bsky)
    elif slot_id == 4: run_single_game_post(bsky, "Unpopular")
    elif slot_id == 5: run_fact(bsky)
    elif slot_id == 6: run_single_game_post(bsky, "Obscure")
    elif slot_id == 7: run_starter_pack(bsky)
    elif slot_id == 8: run_generic_q(bsky)
    elif slot_id == 9: run_single_game_post(bsky, "Aesthetic")
    elif slot_id == 10: run_fact(bsky)
    elif slot_id == 11: run_single_game_post(bsky, "Memory")
    elif slot_id == 12: run_fact(bsky)
    else:
        logger.error(f"❌ Unknown or Unscheduled Slot ID: {slot_id}")

    logger.info("--- BOT RUN FINISHED ---")

if __name__ == "__main__":
    main()
