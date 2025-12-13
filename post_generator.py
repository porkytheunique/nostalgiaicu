# ... keep all imports and functions above valid ...

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
    
    # Check for Manual Overrides from YAML inputs
    forced_slot_input = os.environ.get("FORCED_SLOT", "").strip()
    is_manual = os.environ.get("IS_MANUAL") == "true"
    
    slot_id = None

    if forced_slot_input:
        # CASE A: User specifically typed a slot ID (e.g. "3")
        try:
            slot_id = int(forced_slot_input)
            logger.info(f"🛠️ Manual Override: Forcing Slot {slot_id}")
        except ValueError:
            logger.error("❌ Invalid Slot ID provided.")
            return
            
    elif is_manual:
        # CASE B: Manual run, but no ID typed -> Run "Today's First Slot"
        # Get all slots for today
        todays_slots = list(SCHEDULE.get(day, {}).values())
        if todays_slots:
            slot_id = todays_slots[0] # Pick the 10:00 AM slot usually
            logger.info(f"⚡ Manual Run (Auto): Forcing today's Slot {slot_id}")
        else:
            logger.warning("⚠️ No slots found for today? (Check Schedule)")
            
    else:
        # CASE C: Automatic Cron Run (Strict Time Check)
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
        logger.error(f"❌ Unknown Slot ID: {slot_id}")

    logger.info("--- BOT RUN FINISHED ---")

if __name__ == "__main__":
    main()
