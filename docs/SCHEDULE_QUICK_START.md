# Quick Start: Enhanced Schedule Features

## 🎮 Create a Game Night Event (New Way!)

### Step 1: Open Schedule Tab
Click the **📅 Schedule** button in the top navigation

### Step 2: Fill in the Basics
- **Title**: "Friday Coop Night" (required)
- **Date**: Pick a date with the date picker
- **Time**: Pick a time (24-hour format)

### Step 3: Add Game (Fuzzy Search) ⭐ NEW
1. Click the **Game** field
2. Start typing the game name (e.g., "portal")
3. See matching games with images appear below
4. Click a game to select it
5. Game image + App ID are captured automatically

**Pro Tips:**
- Type partial names: "port" finds Portal games
- Type Steam App ID: "620" finds Portal 2
- More specific = better results

### Step 4: Add Attendees (Fuzzy Search) ⭐ NEW
1. Click the **Attendees** field  
2. Start typing a friend's name (e.g., "ali")
3. See matching friends appear below
4. Click to add them
5. Added attendees show as colored tags

**Pro Tips:**
- Type partial names: "ali" finds Alice, Alison, etc.
- Click the × on any tag to remove that person
- Can also type names directly (comma-separated)

### Step 5: Optional Settings
- **Notes**: Add any notes about the event
- **Create Discord Event**: ⭐ NEW - Check this to automatically create a Discord event with the game image!

### Step 6: Save
Click **💾 Save Event** button

✅ Event created! Schedule updated! Discord event sent (if enabled)!

---

## 📢 Create Discord Event from Existing Schedule (Alternative Method)

**Already have a schedule event?** Just want to add it to Discord now?

1. Find the event in your schedule list
2. If the event has a game, you'll see a **📢 Create Discord Event** button
3. Click it
4. Done! Discord event created with game image

---

## 🔍 How Fuzzy Search Works

### For Games
We're smart! Find games by:
- ✅ Full name: "Portal 2"
- ✅ Partial name: "Por", "Porta", "Portal"
- ✅ App ID: "620" (Steam)
- ✅ Typos: Will still find it

Minimum: **2 characters** to start searching

### For Attendees
Find friends easily:
- ✅ Full name: "Alice"
- ✅ Partial name: "Ali", "Alic"
- ✅ Case-insensitive: "alice", "ALICE", both work

Minimum: **1 character** to start searching

---

## 🎨 What You Get with Discord Integration

When you create a Discord event from GAPI:

✨ **Automatic Discord Event includes:**
- Game title in the event name
- Game image as event cover
- Start/end times from schedule
- Your attendees listed in description
- "Created by GAPI Game Night Scheduler" footer

**No more:** Creating events manually in Discord
**No more:** Uploading game images manually
**No more:** Typing attendee lists

---

## 📸 Game Images

When you select a game via fuzzy search:
- Game image automatically captured
- Displayed in your schedule event card
- Used as Discord event cover image
- Falls back to bot banner if no image

**Supports:** Steam, Epic Games, GOG

---

## ✏️ Editing Events

1. Click **✏️ Edit** on any event card
2. All fields populate (including game image!)
3. Make changes
4. Click **💾 Save Event**
5. Event updated
6. *(Discord event doesn't auto-update - by design)*

---

## 🗑️ Deleting Events

1. Click **🗑️ Delete** on any event card
2. Confirm deletion
3. Event removed from schedule
4. *(Discord event remains - delete manually if needed)*

---

## 💡 Pro Tips & Tricks

### Attendee Management
- **Add multiple**: Click each attendee one at a time
- **See tags**: Attendees show as colored pills below the field
- **Edit inline**: Click × to remove, type more to add

### Game Selection
- **Image preview**: Hover over game results to see larger image
- **Check App ID**: Use app ID to find exact game
- **No game yet?**: Leave blank and add "TBA" in notes

### Discord Integration  
- **Auto-create**: Check "Create Discord event" before saving
- **Manual create**: Or use **📢** button on event card anytime
- **Update schedule**: Changing schedule doesn't auto-update Discord (clean separation)

### Keyboard Shortcuts
- **ESC**: Close search dropdowns
- **Click outside**: Also closes dropdowns
- **Arrow up/down**: *(Coming soon)* Navigate search results

---

## ❓ FAQs

**Q: Can I search by game genre?**
A: Not yet, only by title and App ID. Type partial titles!

**Q: What happens if a game has no image?**
A: Discord uses the bot's banner as fallback. No blank events!

**Q: Can I delete the Discord event from GAPI?**
A: Not directly. Delete it manually in Discord. Schedule event stays (separate systems).

**Q: Do attendees get notified automatically?**
A: Discord event goes to server, but no direct DMs yet.

**Q: Can I use Discord IDs instead of names?**
A: Currently uses user names. Discord ID support coming!

**Q: How long does a Discord event last?**
A: Default 2 hours. Edit time in schedule to change end time.

**Q: Can I add the bot to multiple servers?**
A: Yes! Each server gets its own Discord events.

**Q: What if I misspell an attendee name?**
A: It still saves as-is. Use the × and re-add for corrections.

---

## 🚀 What's Next?

Upcoming enhancements being considered:
- Sync Discord event when you edit schedule
- Attendee availability checking
- Game voting before event
- Calendar export
- Discord reminder notifications

---

## 📞 Need Help?

If something doesn't work:
1. **Check browser console** (Press F12)
2. **Ensure minimum characters** (Games: 2+, Friends: 1+)
3. **Verify friends are added** to your GAPI multiuser setup
4. **Check Discord bot permissions** (needs MANAGE_EVENTS)

See **SCHEDULE_ENHANCEMENT.md** for detailed troubleshooting!

---

**Happy gaming! 🎮**

