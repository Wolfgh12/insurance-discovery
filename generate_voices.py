import asyncio
import os
import subprocess
import edge_tts

# West African Neural Female Voice
VOICE = "en-NG-EzinneNeural"

PROMPTS = {
    "static/audio/install_prompt.mp3": (
        "To install InheritanceBox on your phone, tap Install Now to add your encrypted i-box directly to your home screen."
    ),
    "static/audio/no_policy_found.mp3": (
        "This name was not identified in the registry. Please try again."
    ),
}

async def generate_and_preview():
    os.makedirs("static/audio", exist_ok=True)
    vlc_paths = [
        r"C:\Program Files\VideoLAN\VLC\vlc.exe",
        r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
    ]
    vlc_bin = next((p for p in vlc_paths if os.path.exists(p)), None)

    for file_path, text in PROMPTS.items():
        print(f"Generating West African Voice ({VOICE}) -> {file_path}...")
        comm = edge_tts.Communicate(text, VOICE, rate="-2%")
        await comm.save(file_path)
        print(f"✓ Saved: {file_path} ({os.path.getsize(file_path)} bytes)")

    # Launch in VLC (or default player) for instant listening preview
    test_file = os.path.abspath("static/audio/install_prompt.mp3")
    print(f"\n▶ Launching {test_file} for audio preview...")
    if vlc_bin:
        subprocess.Popen([vlc_bin, test_file])
    else:
        os.startfile(test_file)

if __name__ == "__main__":
    asyncio.run(generate_and_preview())
