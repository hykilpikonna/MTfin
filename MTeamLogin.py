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
    if not CONFIG_FILE.exists():
        print(f"Error: Configuration file '{CONFIG_FILE}' not found.")
        sys.exit(1)

    # with CONFIG_FILE.open("rb") as f:
    #     config = tomllib.load(f)
    config = tomllib.loads(CONFIG_FILE.read_text())
    
    if "m-team" not in config:
        print("Error: '[m-team]' section not found in config.toml")
        sys.exit(1)
        
    return config["m-team"]

def run():
    config = load_config()
    username = config.get("username")
    password = config.get("password")
    otp_key = config.get("otp_key")

    if not all([username, password, otp_key]):
        print("Error: Missing username, password, or otp_key in config.toml")
        sys.exit(1)

    print(f"Launching browser with persistent profile at: {USER_DATA_DIR}")
    
    with sync_playwright() as p:
        # Launch a persistent context to save cookies
        browser = p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=False,  # Set to True if you don't want to see the browser
            channel="chrome", # Optional: Use 'msedge' or remove to use bundled chromium
        )
        
        page = browser.new_page()
        
        print(f"Navigating to {LOGIN_URL}...")
        page.goto(LOGIN_URL)
        page.wait_for_load_state("networkidle")

        # Check if we are already logged in (Login form not present)
        if not page.is_visible("input#username"):
            print("Login form not found. You might already be logged in.")
            print("Checking page title...")
            print(f"Current Title: {page.title()}")
        else:
            print("Login form detected. Attempting to log in...")

            # 1. Fill Username
            page.fill("input#username", username)
            
            # 2. Fill Password
            page.fill("input#password", password)
            
            # 3. Click Submit
            submit_selector = 'button[type="submit"]'
            page.click(submit_selector)
            
            print("Credentials submitted. Waiting for OTP field...")

            # 4. Handle OTP
            try:
                # Wait up to 10 seconds for the OTP input to appear
                page.wait_for_selector("input#otpCode", timeout=10000)
                
                print("Generating OTP code from provided key...")
                # Generate TOTP code using the secret key
                totp = pyotp.TOTP(otp_key.replace(" ", "")) # Sanitize spaces just in case
                current_otp = totp.now()
                print(f"Generated Code: {current_otp}")
                
                # Fill the OTP
                page.fill("input#otpCode", current_otp)
                
                # Press Enter to submit
                page.press("input#otpCode", "Enter")
                
                print("OTP Submitted.")
                
            except Exception as e:
                print(f"OTP field did not appear or an error occurred: {e}")
                print("Maybe login failed or OTP wasn't required?")

        # Wait a moment to ensure login processes
        page.wait_for_timeout(5000)
        
        print(f"Final URL: {page.url}")
        print("Script finished. Cookies are saved in the profile folder.")
        
        # Close the browser
        browser.close()

if __name__ == "__main__":
    run()