import asyncio
import random
import os
import yaml
from playwright.async_api import async_playwright, TimeoutError as PWTimeout
from utils.logger import already_applied, log_applied
from utils.browser import get_browser_options

with open("config.yaml") as f:
    cfg = yaml.safe_load(f)

PLATFORM = "Naukri"
APPLICANT = cfg["applicant"]
LIMITS = cfg["limits"]
RESUME = os.path.abspath(cfg["resume_path"])


async def delay(base=None):
    base = base or LIMITS["delay_between_jobs"]
    await asyncio.sleep(random.uniform(base * 0.8, base * 1.4))


async def login(page, email, password):
    print("🔐 Logging into Naukri...")
    
    # 1. Use "networkidle" instead of "domcontentloaded" to let anti-bot trackers settle
    await page.goto("https://www.naukri.com/nlogin/login", wait_until="networkidle")
    await page.wait_for_timeout(3000)

    try:
        # 2. Explicitly wait for the username selector to appear on screen before typing
        await page.wait_for_selector("#usernameField", timeout=15000)
        
        # 3. Simulate human-like staggered delays instead of instant machine filling
        await page.fill("#usernameField", email)
        await page.wait_for_timeout(random.randint(500, 1500))
        await page.fill("#passwordField", password)
        await page.wait_for_timeout(random.randint(500, 1500))
        
        await page.click("button[type='submit']")
        
        # 4. Wait to ensure we transitioned past the login wall onto the dashboard
        await page.wait_for_url("**/mnjhome**", timeout=15000)
        print("✅ Naukri logged in successfully")
        
    except PWTimeout:
        print("❌ Login timed out. Naukri triggered a CAPTCHA or location verification check.")
        # Take a screenshot to inspect later in your GitHub Action artifacts
        await page.screenshot(path="login_error_fallback.png")
        raise Exception("Naukri Login Failed due to bot protection wall.")


async def apply_to_job(page, url, title, company, location):
    if already_applied(url):
        print(f"    ⏭️  Skip (already applied): {title}")
        return False

    try:
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)

        # Click Apply button
        apply_btn = await page.query_selector("button#apply-button, a#apply-button, button.apply-button")
        if not apply_btn:
            # Try text-based match
            apply_btn = await page.query_selector("text=Apply")
        if not apply_btn:
            print(f"    ❌ No apply button: {title}")
            return False

        await apply_btn.click()
        await page.wait_for_timeout(3000)

        # Handle any modal / popup that appears
        inputs = await page.query_selector_all("input[type='text'], input[type='number'], textarea")
        for inp in inputs:
            try:
                placeholder = (await inp.get_attribute("placeholder") or "").lower()
                val = await inp.input_value()
                if val:
                    continue
                if "phone" in placeholder or "mobile" in placeholder:
                    await inp.fill(APPLICANT["phone"])
                elif "salary" in placeholder or "ctc" in placeholder:
                    await inp.fill(APPLICANT["expected_ctc"])
                elif "notice" in placeholder:
                    await inp.fill(APPLICANT["notice_period"])
                elif "experience" in placeholder or "year" in placeholder:
                    await inp.fill(APPLICANT["experience_years"])
                elif "name" in placeholder:
                    await inp.fill(APPLICANT["name"])
            except:
                pass

        # Submit / confirm
        submit = (
            await page.query_selector("button:has-text('Submit')") or
            await page.query_selector("button:has-text('Apply')") or
            await page.query_selector("button:has-text('Confirm')")
        )
        if submit:
            await submit.click()
            await page.wait_for_timeout(2000)

        log_applied(url, title, company, location, PLATFORM)
        print(f"    ✅ Applied: {title} @ {company}")
        await delay()
        return True

    except PWTimeout:
        print(f"    ⏱️ Timeout: {title}")
        return False
    except Exception as e:
        print(f"    ⚠️ Error: {title} — {e}")
        return False


async def run(email, password):
    count = 0
    async with async_playwright() as p:
        # Pull standard config arguments
        browser_args = get_browser_options()
        
        # 5. Inject a realistic, human User-Agent string so GitHub doesn't scream 'Automated Bot'
        context_args = {
            "viewport": {"width": 1280, "height": 800},
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        }
        
        browser = await p.chromium.launch(**browser_args)
        context = await browser.new_context(**context_args)
        page = await context.new_page()

        try:
            await login(page, email, password)
        except Exception as login_err:
            print(f"💥 Execution halted: {login_err}")
            await browser.close()
            return 0

        for keyword in cfg["keywords"]:
            if count >= LIMITS["max_per_platform"]:
                break

            for location in cfg["filters"]["locations"]:
                if count >= LIMITS["max_per_platform"]:
                    break

                kw = keyword.replace(" ", "-").lower()
                loc = location.lower()
                if loc == "remote":
                    search_url = f"https://www.naukri.com/{kw}-jobs?jobAge=7&experience=0"
                else:
                    search_url = f"https://www.naukri.com/{kw}-jobs-in-{loc}?jobAge=7&experience=0"

                print(f"\n🔍 Naukri: '{keyword}' in {location}")
                try:
                    await page.goto(search_url, wait_until="domcontentloaded")
                    await page.wait_for_timeout(3000)

                    for _ in range(2):
                        await page.keyboard.press("End")
                        await page.wait_for_timeout(1000)

                    job_cards = await page.query_selector_all("article.jobTuple, div.srp-jobtuple-wrapper")
                    print(f"    Found {len(job_cards)} listings")

                    for card in job_cards:
                        if count >= LIMITS["max_per_platform"]:
                            break
                        try:
                            title_el = await card.query_selector("a.title, a.jobTitle")
                            if not title_el:
                                continue
                            job_title = (await title_el.inner_text()).strip()
                            job_url = await title_el.get_attribute("href")

                            company_el = await card.query_selector("a.subTitle, a.companyInfo")
                            company = (await company_el.inner_text()).strip() if company_el else ""

                            loc_el = await card.query_selector("span.locWdth, li.location")
                            job_loc = (await loc_el.inner_text()).strip() if loc_el else location

                            result = await apply_to_job(page, job_url, job_title, company, job_loc)
                            if result:
                                count += 1

                        except Exception as e:
                            continue

                    await asyncio.sleep(LIMITS["delay_between_searches"])

                except Exception as e:
                    print(f"    ⚠️ Search error: {e}")
                    continue

        await browser.close()
    print(f"\n✅ Naukri done — {count} applications")
    return count
