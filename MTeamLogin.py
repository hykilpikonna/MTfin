import sys
import argparse
import pyotp
from playwright.sync_api import sync_playwright
import tomllib
from pathlib import Path

# --- CONFIGURATION ---
LOGIN_URL = "https://kp.m-team.cc/login"
BASE_DIR = Path(__file__).parent
USER_DATA_DIR = BASE_DIR / "data/browser_profile"
CONFIG_FILE = BASE_DIR / "config.toml"

def load_config():
    return tomllib.loads(CONFIG_FILE.read_text())["m-team"]

def get_browser_context(p, headless=False):
    return p.chromium.launch_persistent_context(user_data_dir=USER_DATA_DIR, headless=headless, channel="chrome")

def ensure_logged_in(page):
    # 1. url is /login, 2. login form is visible
    if page.url.startswith(LOGIN_URL) or page.is_visible("input#username"):
        login(page, load_config())
    return True

def login(page, config):
    username = config.get("username")
    password = config.get("password")
    otp_key = config.get("otp_key")

    if not all([username, password, otp_key]):
        print("Error: Missing username, password, or otp_key in config.toml")
        sys.exit(1)

    print(f"Navigating to {LOGIN_URL}...")
    page.goto(LOGIN_URL)
    page.wait_for_load_state("networkidle")

    # Check if we are already logged in (Login form not present)
    if not page.is_visible("input#username"):
        print("Login form not found. You might already be logged in.")
        print("Checking page title...")
        print(f"Current Title: {page.title()}")
        return
        
    print("Login form detected. Attempting to log in...")
    page.fill("input#username", username)
    page.fill("input#password", password)
    submit_selector = 'button[type="submit"]'
    page.click(submit_selector)
    print("Credentials submitted. Waiting for OTP field...")
    try:
        page.wait_for_selector("input#otp-code", timeout=10000)
        print("Generating OTP code from provided key...")
        
        totp = pyotp.TOTP(otp_key.replace(" ", ""))
        current_otp = totp.now()
        print(f"Generated Code: {current_otp}")
        
        page.fill("input#otp-code", current_otp)
        page.press("input#otp-code", "Enter")
        print("OTP Submitted.")
    except Exception as e:
        print(f"OTP field did not appear or an error occurred: {e}")
        print("Maybe login failed or OTP wasn't required?")

    # Wait a moment to ensure login processes
    page.wait_for_timeout(5000)
    
    print(f"Final URL: {page.url}")
    print("Login process finished.")

def get_torrents(page, imdb: str):
    ensure_logged_in(page)

    if not imdb.startswith("https://www.imdb.com/title/"):
        imdb = f"https://www.imdb.com/title/{imdb}"
    
    url = f"https://kp.m-team.cc/mdb/title?source=imdb&imdb={urllib.parse.quote(imdb)}"
    print(f"Navigating to {url}...")
    page.goto(url)
    page.wait_for_load_state("networkidle")

    
    

def download(page, tid):
    url = f"https://kp.m-team.cc/detail/{tid}"
    print(f"Navigating to {url}...")
    page.goto(url)
    page.wait_for_load_state("networkidle")

    # Check if we are logged in (if we see the login form, we are not)
    if page.is_visible("input#username"):
        print("Error: Not logged in. Please run 'login' command first.")
        return

    try:
        print("Looking for download button...")
        # Button selector based on user request: <button ...><span>下載</span></button>
        # We use a role selector combined with name for robustness
        download_button = page.get_by_role("button", name="下載")
        
        if not download_button.is_visible():
             # Fallback to specific class if role text fails, though "下載" should work.
             # The user provided class: ant-btn css-fjnik7 ant-btn-primary ant-btn-color-primary ant-btn-variant-solid
             # But classes like css-fjnik7 might be dynamic.
             print("Download button not found by role/name. Trying generic selector...")
             # Try a looser selector
             download_button = page.locator("button:has-text('下載')")

        if not download_button.is_visible():
            print("Error: Download button not found on page.")
            return

        print("Clicking download button...")
        with page.expect_download() as download_info:
            download_button.click()
        
        download = download_info.value
        print(f"Download started: {download.suggested_filename}")
        
        # Save to current directory
        save_path = Path.cwd() / download.suggested_filename
        download.save_as(save_path)
        print(f"Successfully saved to: {save_path}")

    except Exception as e:
        print(f"An error occurred during download: {e}")

def main():
    parser = argparse.ArgumentParser(description="M-Team Automation Tool")
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Login command
    login_parser = subparsers.add_parser("login", help="Perform login")
    
    # Download command
    dl_parser = subparsers.add_parser("download", help="Download a torrent by TID")
    dl_parser.add_argument("tid", help="Torrent ID")

    args = parser.parse_args()
    
    # Default to login if no command provided (backward compatibility behavior)
    if not args.command:
        print("No command specified, defaulting to 'login'.")
        command = "login"
    else:
        command = args.command

    config = load_config()
    
    print(f"Launching browser with persistent profile at: {USER_DATA_DIR}")
    
    with sync_playwright() as p:
        context = get_browser_context(p, headless=False)
        
        # Persistent context might have an existing page or we create one
        if len(context.pages) > 0:
            page = context.pages[0]
        else:
            page = context.new_page()
            
        if command == "login":
            login(page, config)
        elif command == "download":
            download(page, args.tid)
            
        context.close()

if __name__ == "__main__":
    main()