#!/usr/bin/env python3
"""
Generate a PTR card image from a Senate eFD URL.

Usage:
    python generate_from_url.py <SENATE_EFD_URL> [output_path]

Examples:
    python generate_from_url.py https://efdsearch.senate.gov/search/view/ptr/141ea86c-9411-4d3f-ae9b-ce6e5e8065d1/
"""

import os
import re
import sys
import csv
import logging
from datetime import datetime
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from generate_card import generate_ptr_card, AMOUNT_RANGES

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("senate-ptr")

# ---------------------------------------------------------------------------
# Members CSV lookup
# ---------------------------------------------------------------------------
_ASSETS_DIR = os.path.dirname(os.path.abspath(__file__))
MEMBERS_CSV_PATH = os.path.join(_ASSETS_DIR, "assets", "members_of_congress.csv")

# Map state names to 2-letter codes
STATE_CODES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID",
    "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI",
    "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX",
    "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
    "District of Columbia": "DC",
}

# Reverse: code -> state name (for lookup from senator data)
CODE_TO_STATE = {v: k for k, v in STATE_CODES.items()}

SENATOR_STATES_PATH = os.path.join(_ASSETS_DIR, "assets", "senator_states.csv")


def _load_senator_states() -> dict:
    """Load senator_states.csv into a name -> state_code dict."""
    lookup = {}
    try:
        with open(SENATOR_STATES_PATH, newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get("Name", "").strip()
                state = row.get("State", "").strip()
                if name and state:
                    lookup[name.lower()] = state
    except Exception:
        pass
    return lookup


SENATOR_STATES = _load_senator_states()


def _lookup_senator_state(name: str) -> str:
    """Look up a senator's state code by name."""
    clean = re.sub(r"(?i)\b(?:Hon\.?|The Honorable|Sen\.?)\s*", "", name).strip()
    # Try exact match
    if clean.lower() in SENATOR_STATES:
        return SENATOR_STATES[clean.lower()]
    # Try last name match
    parts = clean.split()
    if parts:
        last = parts[-1].lower()
        matches = [(k, v) for k, v in SENATOR_STATES.items() if k.split()[-1] == last]
        if len(matches) == 1:
            return matches[0][1]
        elif len(matches) > 1 and len(parts) > 1:
            first = parts[0].lower()
            for k, v in matches:
                if k.split()[0] == first:
                    return v
            return matches[0][1]
    return ""


def _load_members_csv() -> list[dict]:
    """Load members_of_congress.csv into a list of dicts."""
    members = []
    try:
        with open(MEMBERS_CSV_PATH, newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                full = row.get("Name", "").strip()
                party = row.get("Party", "").strip()
                chamber = ""
                name = full
                if full.startswith("Rep. "):
                    chamber = "House"
                    name = full[5:]
                elif full.startswith("Sen. "):
                    chamber = "Senate"
                    name = full[5:]
                parts = name.split()
                last = parts[-1] if parts else ""
                first = parts[0] if parts else ""
                members.append({
                    "csv_name": full,
                    "full_name": name,
                    "first": first,
                    "last": last,
                    "party": party,
                    "chamber": chamber,
                })
    except Exception:
        pass
    return members


MEMBERS_CSV = _load_members_csv()


def _find_member_csv(name: str) -> dict | None:
    """Find a member in the CSV by matching last name (+ first name if ambiguous).
    Prefers Senate members for this tool."""
    clean = re.sub(r"(?i)\b(?:Hon\.?|The Honorable)\s*", "", name).strip()
    parts = clean.split()
    if not parts:
        return None
    last = parts[-1]
    first = parts[0] if len(parts) > 1 else ""
    # Prefer Senate matches
    all_matches = [m for m in MEMBERS_CSV if m["last"].lower() == last.lower()]
    senate_matches = [m for m in all_matches if m["chamber"] == "Senate"]
    matches = senate_matches if senate_matches else all_matches
    if len(matches) == 1:
        return matches[0]
    elif len(matches) > 1 and first:
        for m in matches:
            if m["first"].lower() == first.lower():
                return m
        for m in matches:
            if m["first"].lower().startswith(first.lower()[:3]):
                return m
        return matches[0]
    return None


def canonical_name(raw_name: str) -> str:
    """Get the canonical name from the CSV, uppercase, including Sen. prefix."""
    member = _find_member_csv(raw_name)
    if member:
        return member["csv_name"].upper()
    clean = re.sub(r"(?i)\b(?:Hon\.?|The Honorable)\s*", "", raw_name).strip()
    return f"SEN. {clean}".upper()


def party_lookup(name: str) -> str:
    """Look up party from CSV."""
    member = _find_member_csv(name)
    if member and member["party"]:
        return member["party"]
    return ""


# ---------------------------------------------------------------------------
# Senate eFD scraper (Playwright required for JS agreement gate)
# ---------------------------------------------------------------------------
def fetch_senate_ptr(url: str) -> dict:
    """Fetch and parse a Senate PTR page. Returns parsed data dict."""
    result = {
        "member_name": "", "filing_date": "", "state": "",
        "transactions": [], "parse_success": False,
    }

    log.info("Fetching Senate PTR: %s", url)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            # Accept the agreement
            page.goto("https://efdsearch.senate.gov/")
            page.wait_for_load_state("networkidle")
            page.click("#agree_statement")
            page.wait_for_load_state("networkidle")

            # Navigate to the PTR
            page.goto(url)
            page.wait_for_load_state("networkidle")
            content = page.content()
            browser.close()

        soup = BeautifulSoup(content, "html.parser")

        # Extract name from h2 (e.g. "The Honorable John Boozman (Boozman, John)")
        h2 = soup.find("h2")
        if h2:
            h2_text = h2.get_text(strip=True)
            # Remove the parenthetical (LastName, First) part
            name_clean = re.sub(r'\(.*?\)', '', h2_text).strip()
            name_clean = re.sub(r'(?i)\bThe Honorable\b', '', name_clean).strip()
            result["member_name"] = name_clean

        # Extract filing date from h1 (e.g. "Periodic Transaction Report for 03/06/2026")
        h1 = soup.find("h1")
        if h1:
            h1_text = h1.get_text(strip=True)
            date_match = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', h1_text)
            if date_match:
                result["filing_date"] = date_match.group(1)

        # Parse transaction table
        table = soup.find("table")
        if not table:
            log.warning("No transaction table found on page.")
            return result

        rows = table.find_all("tr")
        for row in rows[1:]:  # skip header
            cells = [c.get_text(strip=True) for c in row.find_all("td")]
            if len(cells) < 8:
                continue

            # Columns: #, Transaction Date, Owner, Ticker, Asset Name, Asset Type, Type, Amount, Comment
            tx_date_raw = cells[1]
            owner = cells[2]
            ticker = cells[3]
            asset_name = cells[4]
            asset_type = cells[5]
            tx_type_raw = cells[6]  # "Purchase", "Sale", "Exchange", etc.
            amount_raw = cells[7]

            # Format asset: include ticker if present
            if ticker and ticker != "--":
                asset_display = f"{asset_name} ({ticker})"
            else:
                asset_display = asset_name

            # Map type to single letter
            tx_type = tx_type_raw[0].upper() if tx_type_raw else ""
            is_partial = "partial" in tx_type_raw.lower()

            # Parse amount range
            amount_match = re.search(r'\$([\d,]+)\s*-\s*\$([\d,]+)', amount_raw)
            if amount_match:
                low = int(amount_match.group(1).replace(",", ""))
                high = int(amount_match.group(2).replace(",", ""))
                amount_display = f"${low:,} - ${high:,}"
            else:
                low, high = 0, 0
                amount_display = amount_raw

            # Format tx_date from MM/DD/YYYY to MM/DD/YYYY (already correct)
            result["transactions"].append({
                "owner": owner if owner != "--" else "",
                "asset": asset_display,
                "type": tx_type,
                "partial": is_partial,
                "tx_date": tx_date_raw,
                "notif_date": result["filing_date"],  # Senate uses filing date as notification
                "amount_low": low,
                "amount_high": high,
                "amount_display": amount_display,
            })

        result["parse_success"] = len(result["transactions"]) > 0
        log.info("Parsed %d transactions from Senate PTR.", len(result["transactions"]))

    except Exception as e:
        log.error("Failed to fetch/parse Senate PTR: %s", e)

    return result


# ---------------------------------------------------------------------------
# Convert parsed data to card format
# ---------------------------------------------------------------------------
def senate_to_card_data(url: str, parsed: dict) -> dict:
    """Convert parsed Senate PTR data into generate_ptr_card format."""
    raw_name = parsed.get("member_name", "")
    name = canonical_name(raw_name)

    party = party_lookup(raw_name)
    if not party:
        party = "Unknown"

    # Extract UUID from URL as filing ID
    uuid_match = re.search(r'/ptr/([a-f0-9-]+)', url)
    filing_id = uuid_match.group(1)[:8] if uuid_match else ""

    # Look up state code
    state = _lookup_senator_state(raw_name)

    return {
        "filing_id": filing_id,
        "name": name,
        "status": "Senator",
        "district": state,
        "source_url": url,
        "party": party,
        "pinned": [],
        "transactions": [
            {
                "asset": t["asset"],
                "owner": t["owner"],
                "type": t["type"],
                "partial": t.get("partial", False),
                "tx_date": t["tx_date"],
                "notif_date": t["notif_date"],
                "amount": t["amount_display"],
                "detail": "",
            }
            for t in parsed.get("transactions", [])
        ],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def generate_from_url(efd_url: str, output_path: str = None) -> str:
    """Full pipeline: Senate eFD URL -> scrape -> generate card. Returns output path."""
    parsed = fetch_senate_ptr(efd_url)
    if not parsed["parse_success"]:
        log.error("Failed to parse Senate PTR. Cannot generate card.")
        return None

    card_data = senate_to_card_data(efd_url, parsed)

    if not output_path:
        safe_name = card_data["name"].replace(" ", "_").replace(".", "")
        output_path = f"PTR_{safe_name}.png"

    generate_ptr_card(card_data, output_path)
    return output_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python generate_from_url.py <SENATE_EFD_URL> [output_path]")
        print("\nExample:")
        print("  python generate_from_url.py https://efdsearch.senate.gov/search/view/ptr/141ea86c-9411-4d3f-ae9b-ce6e5e8065d1/")
        sys.exit(1)

    url = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else None
    result = generate_from_url(url, out)
    if result:
        print(f"\nCard saved to: {result}")
