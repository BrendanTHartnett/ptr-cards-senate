# Senate PTR Card Generator

## What this project does
Generates 1080x1080 PNG "Federal Stock Report" card images from U.S. Senate Periodic Transaction Reports (PTRs). These are polished, branded images using the Graveur Variable font and a designer template. This is the Senate companion to the House version at `ptr-cards`.

## First-time setup

```bash
cd ~/ptr-cards-senate  # or wherever you cloned it
pip install -r requirements.txt
playwright install chromium
```

If you don't have the repo yet:
```bash
git clone https://github.com/BrendanTHartnett/ptr-cards-senate.git ~/ptr-cards-senate
cd ~/ptr-cards-senate
pip install -r requirements.txt
playwright install chromium
```

**Important:** Playwright + Chromium is required because the Senate eFD site has a JavaScript-based agreement gate that must be accepted before data is accessible.

## How to generate a PTR card from a URL

When the user gives you a Senate eFD URL (from efdsearch.senate.gov), run:

```bash
cd ~/ptr-cards-senate
python generate_from_url.py "<URL>"
```

This will:
1. Launch a headless browser to accept the Senate eFD agreement
2. Scrape the PTR transaction table
3. Look up the senator's canonical name, party, and state
4. Generate a polished 1080x1080 card image
5. Save it as `PTR_SEN_NAME.png` in the current directory

Example:
```bash
python generate_from_url.py "https://efdsearch.senate.gov/search/view/ptr/141ea86c-9411-4d3f-ae9b-ce6e5e8065d1/"
```

The output file path is printed at the end — read the image to show the user.

## Key files
- `generate_card.py` — core card image generator (Graveur font, 2550x2550 canvas, downscaled to 1080x1080)
- `generate_from_url.py` — full pipeline: Senate eFD URL -> Playwright scrape -> card generation
- `assets/members_of_congress.csv` — canonical member names and party affiliations
- `assets/senator_states.csv` — senator name -> state code mapping
- `assets/template_background.png` — designer's background template
- `assets/Graveur-Regular.otf`, `assets/Graveur-Italic.otf` — bundled fonts

## How the name, party, and state work
- The bold title (e.g. "SEN. JOHN BOOZMAN (AR)") pulls the senator's name from `assets/members_of_congress.csv` and state from `assets/senator_states.csv`.
- Party is looked up from the CSV. If not found, shows "Unknown".
- To add or fix a senator, edit both CSVs.

## Design specs
- Font: Graveur Variable (bundled in assets/)
- Background: designer's InDesign template
- Colors: Red `(200, 61, 52)`, Green `(79, 138, 79)`
- Canvas: 2550x2550, downscaled to 1080x1080
- Table: up to 6 rows, sorted by amount descending, overflow note with Senate eFD link
- Purchase = green, Sale = red

## Making changes
- **Card layout/fonts/colors**: edit `generate_card.py`
- **Scraping/parsing logic**: edit `fetch_senate_ptr()` in `generate_from_url.py`
- **Name/party data**: edit `assets/members_of_congress.csv`
- **State data**: edit `assets/senator_states.csv`
- After making changes, test by generating a card and reading the output image to verify it looks right.
- If you make improvements, commit and push so the changes are shared.
