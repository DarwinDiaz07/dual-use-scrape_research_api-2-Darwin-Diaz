import base64
import csv
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import pandas as pd
import requests
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By

# Global GitHub Token to bypass API rate limits
GITHUB_TOKEN = ""  # Optional: Add your token here to bypass API limits

# Extra standalone target profiles to process at the end
ADDITIONAL_GITHUB_PROFILES = [
    {
        "author_name": "Gilberto León",
        "github_username": "ripflame",
        "paper_title": "N/A (Direct Profile Scan)",
        "profile_url": "N/A",
        "paper_url": "N/A",
    }
]

# ==========================================
# 1. OPENREVIEW & HOMEPAGE SCRAPING
# ==========================================


def get_personal_homepage(profile_url: str, session: requests.Session) -> str:
    """Extracts the author's personal homepage from OpenReview API v2 profile structure."""
    if (
        not profile_url
        or not str(profile_url).startswith("http")
        or "id=~" not in str(profile_url)
    ):
        return "Not Listed"

    match = re.search(r"id=(~[^&]+)", str(profile_url))
    if not match:
        return "Not Listed"

    profile_id = match.group(1)
    api_url = f"https://api2.openreview.net/profiles?id={profile_id}"

    try:
        res = session.get(
            api_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5
        )
        if res.status_code == 200:
            data = res.json()
            profiles = data.get("profiles", [])
            if profiles:
                content = profiles[0].get("content", {})
                homepage_entry = content.get("homepage", {})
                homepage_val = ""

                if isinstance(homepage_entry, dict):
                    homepage_val = homepage_entry.get("value", "")
                elif isinstance(homepage_entry, str):
                    homepage_val = homepage_entry

                if homepage_val and homepage_val.strip():
                    url_str = homepage_val.strip()
                    if not url_str.startswith("http"):
                        url_str = f"https://{url_str}"
                    return url_str
    except Exception:
        pass

    return "Not Listed"


# ==========================================
# 2. GITHUB PROFILE DETAILS & README PARSER
# ==========================================


def parse_markdown_sections(readme_text: str) -> dict[str, str]:
    """Parses markdown headings from Profile READMEs into structured sections."""
    clean_text = re.sub(r"<[^>]+>", "", readme_text)
    sections = {}
    heading_pattern = (
        r"(?m)^(#{1,4}\s+|[\U00010000-\U0010ffff\u2600-\u27ff]\s*)(.+)$"
    )

    lines = clean_text.split("\n")
    current_section = "General Overview"
    current_content = []

    for line in lines:
        match = re.match(heading_pattern, line.strip())
        if match:
            if current_content:
                sections[current_section] = "\n".join(current_content).strip()
                current_content = []
            current_section = match.group(2).strip()
        else:
            if line.strip():
                current_content.append(line.strip())

    if current_content:
        sections[current_section] = "\n".join(current_content).strip()

    return sections


def fetch_github_details_by_username(
    username: str, github_token: str = ""
) -> dict[str, str]:
    """Retrieves full profile metadata and Profile README content directly by GitHub username."""
    headers = {"User-Agent": "ResearchTool/1.0"}
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    output = {
        "GitHub Profile": f"https://github.com/{username}",
        "Public Repositories": "N/A",
        "GitHub Username": username,
        "GitHub Full Name": "Not Listed",
        "GitHub Email": "Not Listed",
        "GitHub Website/Blog": "Not Listed",
        "GitHub Location": "Not Listed",
        "GitHub Bio/Headline": "Not Listed",
        "GitHub Twitter": "Not Listed",
        "GitHub Company": "Not Listed",
        "About Me Section": "Not Listed",
        "Tech Stack": "Not Listed",
        "Ongoing Experiments / Projects": "Not Listed",
    }

    try:
        # 1. Fetch user's top public repositories
        repos_url = f"https://api.github.com/users/{username}/repos?sort=updated&per_page=6"
        repo_res = requests.get(repos_url, headers=headers, timeout=5)
        if repo_res.status_code == 200:
            repo_data = repo_res.json()
            repos = [r["name"] for r in repo_data if not r.get("fork")]
            if not repos and repo_data:
                repos = [r["name"] for r in repo_data]
            output["Public Repositories"] = (
                ", ".join(repos[:5]) if repos else "No public repos"
            )

        # 2. Fetch User API Metadata
        user_api_url = f"https://api.github.com/users/{username}"
        user_res = requests.get(user_api_url, headers=headers, timeout=5)
        if user_res.status_code == 200:
            u_json = user_res.json()
            output["GitHub Full Name"] = u_json.get("name") or "Not Listed"
            output["GitHub Email"] = u_json.get("email") or "Not Listed"
            output["GitHub Website/Blog"] = u_json.get("blog") or "Not Listed"
            output["GitHub Location"] = u_json.get("location") or "Not Listed"
            output["GitHub Bio/Headline"] = u_json.get("bio") or "Not Listed"
            output["GitHub Twitter"] = (
                u_json.get("twitter_username") or "Not Listed"
            )
            output["GitHub Company"] = u_json.get("company") or "Not Listed"

        # 3. Fetch Profile README (username/username)
        readme_url = (
            f"https://api.github.com/repos/{username}/{username}/readme"
        )
        readme_res = requests.get(readme_url, headers=headers, timeout=5)
        if readme_res.status_code == 200:
            content_b64 = readme_res.json().get("content", "")
            readme_text = base64.b64decode(content_b64).decode(
                "utf-8", errors="ignore"
            )

            parsed_sections = parse_markdown_sections(readme_text)
            for title, content in parsed_sections.items():
                title_lower = title.lower()
                if "about" in title_lower or "hi," in title_lower:
                    output["About Me Section"] = content
                elif (
                    "tech" in title_lower
                    or "stack" in title_lower
                    or "skill" in title_lower
                ):
                    output["Tech Stack"] = content
                elif (
                    "experiment" in title_lower
                    or "project" in title_lower
                    or "building" in title_lower
                ):
                    output["Ongoing Experiments / Projects"] = content
    except Exception as e:
        print(f"⚠️ Error fetching details for {username}: {e}")

    return output


def get_github_data_and_details(
    author_name: str, github_token: str = ""
) -> dict[str, str]:
    """Searches for a GitHub user by full name and fetches details."""
    headers = {"User-Agent": "ResearchTool/1.0"}
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    search_url = f"https://api.github.com/search/users?q={author_name}+in:fullname&per_page=1"

    try:
        res = requests.get(search_url, headers=headers, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if data.get("total_count", 0) > 0:
                username = data["items"][0]["login"]
                return fetch_github_details_by_username(username, github_token)
    except Exception:
        pass

    return fetch_github_details_by_username("", github_token)


# ==========================================
# 3. GITLEAKS SECURITY SCANNING
# ==========================================


def get_user_public_repos(username: str, github_token: str = "") -> list[str]:
    """Retrieves all clone URLs for public repositories."""
    if not username or username in ["N/A", "Not Listed", ""]:
        return []

    api_url = f"https://api.github.com/users/{username}/repos?per_page=100"
    headers = {"User-Agent": "SecurityScanner/1.0"}
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    try:
        res = requests.get(api_url, headers=headers, timeout=10)
        if res.status_code == 200:
            repos = res.json()
            return [repo["clone_url"] for repo in repos if not repo.get("fork")]
    except Exception:
        pass
    return []


def run_gitleaks_on_repo(clone_url: str) -> list[dict]:
    """Clones repo temporarily and runs Gitleaks to detect exposed secrets."""
    findings = []
    temp_dir = tempfile.mkdtemp()

    try:
        subprocess.run(
            ["git", "clone", "--depth", "50", clone_url, temp_dir],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
            check=True,
        )

        report_file = os.path.join(temp_dir, "gitleaks_results.json")
        cmd = [
            "gitleaks",
            "detect",
            f"--source={temp_dir}",
            f"--report-path={report_file}",
            "--format=json",
            "--no-git=false",
        ]

        subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )

        if os.path.exists(report_file):
            with open(report_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    raw_leaks = json.loads(content)
                    for leak in raw_leaks:
                        findings.append(
                            {
                                "RuleID": leak.get("RuleID", ""),
                                "Secret": leak.get("Secret", ""),
                                "File": leak.get("File", ""),
                                "StartLine": leak.get("StartLine", ""),
                                "Commit": leak.get("Commit", ""),
                            }
                        )
    except Exception:
        pass
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    return findings


# ==========================================
# 4. MAIN PIPELINE
# ==========================================


def run_master_pipeline(
    output_csv: str = "master_safegenai_researchers_full.csv",
    output_excel: str = "master_safegenai_researchers_multisheet.xlsx",
):
    options = uc.ChromeOptions()
    options.add_argument("--start-maximized")

    print("🚀 STEP 1: Launching Chrome v146 to scrape OpenReview...")
    driver = uc.Chrome(options=options, version_main=146)

    url = "https://openreview.net/group?id=NeurIPS.cc/2024/Workshop/SafeGenAi"
    driver.get(url)
    time.sleep(8)

    notes = driver.find_elements(By.CSS_SELECTOR, ".note")
    print(f"✅ Found {len(notes)} paper cards on OpenReview.")

    scraped_data = []
    for note in notes:
        try:
            title_el = note.find_element(By.CSS_SELECTOR, "h4 a")
            title = title_el.text.strip()
            paper_url = title_el.get_attribute("href")

            author_els = note.find_elements(By.CSS_SELECTOR, ".note-authors a")
            for author_el in author_els:
                author_name = author_el.text.strip()
                profile_url = author_el.get_attribute("href")

                if author_name:
                    scraped_data.append(
                        {
                            "author_name": author_name,
                            "paper_title": title,
                            "profile_url": profile_url,
                            "paper_url": paper_url,
                            "github_username": None,
                        }
                    )
        except Exception:
            continue

    driver.quit()

    session = requests.Session()
    final_records = []
    direct_profile_records = []

    print(
        "\n🔍 STEP 2 & 3: Extracting Details, Profiles, & Running Gitleaks..."
    )

    # Combine OpenReview Scraped Targets + Manual Profiles
    all_targets = scraped_data + ADDITIONAL_GITHUB_PROFILES

    for idx, item in enumerate(all_targets):
        author_name = item["author_name"]
        print(f"[{idx + 1}/{len(all_targets)}] Processing: {author_name}...")

        # Get Personal Homepage
        if item.get("profile_url") != "N/A":
            personal_homepage = get_personal_homepage(
                item["profile_url"], session
            )
        else:
            personal_homepage = "ripfla.me"

        # Fetch GitHub details & README content
        if item.get("github_username"):
            gh_details = fetch_github_details_by_username(
                item["github_username"], GITHUB_TOKEN
            )
        else:
            gh_details = get_github_data_and_details(author_name, GITHUB_TOKEN)

        # Gitleaks Scan
        leak_status = "No Leaks Detected"
        leak_details_list = []

        if gh_details["GitHub Username"] not in ["N/A", ""]:
            print(
                f"   ⚡ Running Gitleaks scan on: {gh_details['GitHub Username']}..."
            )
            repo_urls = get_user_public_repos(
                gh_details["GitHub Username"], GITHUB_TOKEN
            )

            for repo_url in repo_urls:
                findings = run_gitleaks_on_repo(repo_url)
                if findings:
                    for f in findings:
                        leak_details_list.append(
                            f"{f['RuleID']} in {f['File']}:{f['StartLine']}"
                        )

            if leak_details_list:
                leak_status = (
                    f"🚨 EXPOSED KEYS FOUND: {'; '.join(leak_details_list)}"
                )

        record = {
            "Researcher Name": author_name,
            "Paper Title": item["paper_title"],
            "Personal Homepage": personal_homepage,
            "GitHub Profile": gh_details["GitHub Profile"],
            "Public Repositories": gh_details["Public Repositories"],
            "Gitleaks Audit Status": leak_status,
            "GitHub Email": gh_details["GitHub Email"],
            "GitHub Website/Blog": gh_details["GitHub Website/Blog"],
            "GitHub Location": gh_details["GitHub Location"],
            "GitHub Bio/Headline": gh_details["GitHub Bio/Headline"],
            "GitHub Twitter": gh_details["GitHub Twitter"],
            "GitHub Company": gh_details["GitHub Company"],
            "About Me Section": gh_details["About Me Section"],
            "Tech Stack": gh_details["Tech Stack"],
            "Ongoing Experiments / Projects": (
                gh_details["Ongoing Experiments / Projects"]
            ),
            "OpenReview Profile": item["profile_url"],
            "Paper URL": item["paper_url"],
        }

        final_records.append(record)

        if item.get("paper_title") == "N/A (Direct Profile Scan)":
            direct_profile_records.append(record)

        time.sleep(0.5)

    # 1. Output Single Combined Master CSV
    fieldnames = list(final_records[0].keys()) if final_records else []
    with open(output_csv, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(final_records)

    # 2. Output Multi-Sheet Excel File
    df_all = pd.DataFrame(final_records)
    df_researchers = df_all[
        df_all["Paper Title"] != "N/A (Direct Profile Scan)"
    ]
    df_direct = pd.DataFrame(direct_profile_records)

    with pd.ExcelWriter(output_excel, engine="openpyxl") as writer:
        df_researchers.to_excel(
            writer, sheet_name="SafeGenAI Researchers", index=False
        )
        df_direct.to_excel(writer, sheet_name="Direct GitHub Scans", index=False)
        df_all.to_excel(writer, sheet_name="Master All Records", index=False)

    print(f"\n🎉 PIPELINE COMPLETE!")
    print(
        f" 📄 Combined Master CSV: '{output_csv}' (Row {len(final_records)} is {final_records[-1]['Researcher Name']})"
    )
    print(f" 📊 Multi-Sheet Excel: '{output_excel}'")


if __name__ == "__main__":
    run_master_pipeline()