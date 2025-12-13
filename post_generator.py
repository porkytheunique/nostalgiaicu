import os
import sys
import json
import random
import requests
import textwrap
from datetime import datetime
from PIL import Image
from io import BytesIO
from atproto import Client, models

# --- CONFIGURATION & CONSTANTS ---
RAWG_API_KEY = os.environ.get("RAWG_API_KEY")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
BSKY_HANDLE = os.environ.get("BLUESKY_HANDLE")
BSKY_PASSWORD = os.environ.get("BLUESKY_PASSWORD")

# Website Features for Monday Rotation
WEBSITE_FEATURES = [
    "Retro Gaming Magazine Library (Read full scans of vintage mags)",
    "Retro Media Player (Vintage TV channels, cartoons, & game promos)",
    "24/7 Retro Video Game Music Radio",
    "Retro Terminal Advisor (Ask our AI historian anything about retro gaming)",
    "Daily Pixel Challenge (Guess the game from 3 screenshots)",
    "Nostalgia Quest (A playable mini-dungeon crawler)",
    "Retro History & Release Calendar (See what games released today or any date)",
    "The Retro Game Database (Search & discover detailed game info)"
]

# Generic Question Themes (Text-Only)
GENERIC_THEMES = [
    "Gaming Soundtracks (Jingles, Ambient, Music)",
    "Accessories & Peripherals (Controllers, Weird Gadgets)",
    "Arcade Culture (Cabinets, High Scores, Atmosphere)",
    "Hardware Aesthetics (Boot screens, Cartridges, Cables)",
    "Gaming Media & Myths (Magazines, Rumors, TV Shows)",
    "Game Shop Memories (Rental stores, Buying, Browsing)"
]

# Hashtag Logic
MANDATORY_TAGS = ["#Retro", "#RetroGaming"]

# --- HELPER FUNCTIONS ---

def load_json(filename, default):
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            return json.load(f)
    return default

def save_json(filename, data):
    with open(filename, 'w') as f:
        json.dump(data, f)

def get_claude_response(prompt):
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    data = {
        "model": "claude-3-haiku-20240307",
        "max_tokens": 300,
        "messages": [{"role": "user", "content": prompt}]
    }
    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 200:
        return response.json()['content'][0]['text'].strip()
    else:
        print(f"Claude API Error: {response.text}")
        sys.exit(0) # Fail gracefully (no post)

def download_image(url):
    response = requests.get(url)
    if response.status_code == 200:
        return Image.open(BytesIO(response.content))
    return None

def create_collage(images, mode='2x2'):
    """Creates a 2x2 or 2x1 collage from a list of PIL Images."""
    if not images:
        return None
    
    # Resize all to a standard size for collage
    target_size = (600, 600)
    resized_imgs = [img.resize(target_size) for img in images]

    if mode == '2x2':
        width, height = 1200, 1200
        collage = Image.new('RGB', (width, height))
        collage.paste(resized_imgs[0], (0, 0))
        if len(images) > 1: collage.paste(resized_imgs[1], (600, 0))
        if len(images) > 2: collage.paste(resized_imgs[2], (0, 600))
        if len(images) > 3: collage.paste(resized_imgs[3], (600, 600))
    elif mode == '2x1':
        width, height = 1200, 600
        collage = Image.new('RGB', (width, height))
        collage.paste(resized_imgs[0], (0, 0))
        if len(images) > 1: collage.paste(resized_imgs[1], (600, 0))
    
    return collage

def truncate_text(text, max_chars=280):
    """Safely truncates text to fit limits."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars-3] + "..."

# --- CONTENT GENERATORS ---

def generate_monday_ad():
    used_ads = load_json('used_ads.json', {'last_index': -1})
    idx = (used_ads['last_index'] + 1) % len(WEBSITE_FEATURES)
    feature = WEBSITE_FEATURES[idx]
    
    prompt = f"Write an enthusiastic, engaging social media post promoting the '{feature}' feature on nostalgia.icu. Keep it under 200 characters. No hashtags needed here. Include the link: https://nostalgia.icu"
    text = get_claude_response(prompt)
    
    save_json('used_ads.json', {'last_index': idx})
    
    # Hashtags
    tags = ["#Retro", "#Nostalgia", "#Tools"]
    return text, tags, ['images/promo_ad.jpg'] # Returns local path for image

def generate_generic_text_post():
    used_qs = load_json('used_questions.json', [])
    
    # Pick a theme not recently used
    available_themes = [t for t in GENERIC_THEMES if t not in used_qs[-4:]] 
    if not available_themes: available_themes = GENERIC_THEMES # Reset if all used
    theme = random.choice(available_themes)
    
    prompt = f"You are a retro gaming historian. Write one short, open-ended, engaging question about '{theme}' to spark a debate. Text-only, NO visual references (like 'look at this picture'). End with the 🤔 emoji. Strictly under 230 characters."
    text = get_claude_response(prompt)
    
    used_qs.append(theme)
    if len(used_qs) > 10: used_qs.pop(0) # Keep list short
    save_json('used_questions.json', used_qs)
    
    return text, MANDATORY_TAGS, [] # No images

def fetch_rawg_game(platform_id=None, count=1):
    """Fetches a random game(s) from RAWG that hasn't been used."""
    used_games = load_json('used_games.json', [])
    
    # Simple logic: Fetch a page of high-rated games
    # In production, you might want to randomize the 'page' parameter
    url = f"https://api.rawg.io/api/games?key={RAWG_API_KEY}&dates=1980-01-01,2005-12-31&ordering=-rating&page_size=40"
    if platform_id:
        url += f"&platforms={platform_id}"
        
    try:
        data = requests.get(url).json()
        candidates = [g for g in data['results'] if g['id'] not in used_games and g.get('background_image')]
        
        if len(candidates) < count:
            return None # Not enough fresh games found
            
        selected = random.sample(candidates, count)
        return selected
    except Exception as e:
        print(f"RAWG Error: {e}")
        return None

def generate_image_post(day_type):
    # Map Day to Platform/Logic
    # This is a simplified logic map. You can expand specific platform IDs per day.
    # IDs: 4=PC, 18=PS4... Need Retro IDs: NES=18, SNES=19, PS1=27, N64=83 (Check RAWG IDs)
    # For now, we will use a generic high-rated fetch for demo purposes.
    
    games = fetch_rawg_game(count=4 if day_type == 'Friday' else 2 if day_type == 'Tuesday' else 1)
    
    if not games:
        print("No fresh games found.")
        sys.exit(0)

    primary_game = games[0]
    game_title = primary_game['name']
    
    # Images Processing
    images_to_upload = []
    
    if day_type == 'Friday': # Starter Pack (Collage + Screenshots)
        # Download box arts (using background_image as proxy for box/screen)
        pil_imgs = [download_image(g['background_image']) for g in games]
        collage = create_collage(pil_imgs, '2x2')
        # Save collage to buffer
        collage_path = "temp_collage.jpg"
        collage.save(collage_path)
        images_to_upload.append(collage_path)
        
        # Add 2 screenshots of primary game (re-using background for demo, ideally fetch screenshots endpoint)
        # In full version: query /games/{id}/screenshots
        images_to_upload.append("images/promo_ad.jpg") # Add ad at end
        
        prompt = f"Create a 'Starter Pack' question asking which of these 4 games ({', '.join([g['name'] for g in games])}) people would pick to play first. End with 🤔. Under 230 chars."

    elif day_type == 'Tuesday': # Rivalry
        game_a, game_b = games[0], games[1]
        pil_imgs = [download_image(game_a['background_image']), download_image(game_b['background_image'])]
        collage = create_collage(pil_imgs, '2x1')
        collage_path = "temp_rivalry.jpg"
        collage.save(collage_path)
        images_to_upload.append(collage_path)
        images_to_upload.append("images/promo_ad.jpg")
        
        prompt = f"Write a rivalry debate question between {game_a['name']} and {game_b['name']}. Which one wins? End with 🤔. Under 230 chars."

    else: # Standard (Wednesday, Thursday, Saturday, Sunday)
        # 1 Screenshot + Ad
        # Ideally download the image to local temp file
        img_data = requests.get(primary_game['background_image']).content
        with open("temp_game.jpg", "wb") as f:
            f.write(img_data)
        images_to_upload.append("temp_game.jpg")
        images_to_upload.append("images/promo_ad.jpg")
        
        prompt = f"Write a nostalgic post about {game_title}. Ask a question about memory/opinion. End with 🤔. Under 230 chars."

    # Generate Text
    text = get_claude_response(prompt)
    
    # Save Used IDs
    used_games = load_json('used_games.json', [])
    for g in games:
        if g['id'] not in used_games: used_games.append(g['id'])
    save_json('used_games.json', used_games)
    
    return text, MANDATORY_TAGS + [f"#{game_title.replace(' ','')}"], images_to_upload


# --- MAIN EXECUTION ---
def main():
    now = datetime.utcnow()
    day_name = now.strftime("%A")
    hour = now.hour

    # DECISION LOGIC
    # 10:00 UTC Slots
    if hour == 10:
        if day_name == 'Monday':
            text, tags, images = generate_monday_ad()
        elif day_name == 'Tuesday':
            text, tags, images = generate_image_post('Tuesday')
        elif day_name == 'Friday':
            text, tags, images = generate_image_post('Friday')
        else: # Wed, Thu, Sat, Sun
            text, tags, images = generate_image_post('Standard')
            
    # 15:00 UTC Slots (Generic)
    elif hour == 15:
        if day_name in ['Monday', 'Friday', 'Saturday', 'Sunday']: # Added Sat/Sun
            text, tags, images = generate_generic_text_post()
        else:
            print("No post scheduled for this slot.")
            return
    else:
        print("Not a posting hour.")
        return

    # POST TO BLUESKY
    client = Client()
    client.login(BSKY_HANDLE, BSKY_PASSWORD)

    # Calculate final text length safety
    final_tags = " ".join(tags)
    max_text_len = 300 - len(final_tags) - 5
    safe_text = truncate_text(text, max_text_len)
    final_post_text = f"{safe_text}\n\n{final_tags}"

    # Upload Images & Create Post
    if images:
        img_blobs = []
        for img_path in images:
            with open(img_path, 'rb') as f:
                img_data = f.read()
                upload = client.upload_blob(img_data)
                img_blobs.append(models.AppBskyEmbedImages.Image(alt='Retro Game Image', image=upload.blob))
        
        client.send_post(text=final_post_text, embed=models.AppBskyEmbedImages.Main(images=img_blobs))
    else:
        # Text Only
        client.send_post(text=final_post_text)

    print(f"Posted successfully: {day_name} {hour}:00")

if __name__ == "__main__":
    main()
