import os

def is_ci() -> bool:
    return os.getenv("CI") == "true" or os.getenv("GITHUB_ACTIONS") == "true"
def get_browser_options():
    return {
        "headless": True, # Or False if running locally
        "args": [
            "--disable-blink-features=AutomationControlled", # Hides the 'navigator.webdriver' flag
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--window-size=1280,800"
        ]
    }
