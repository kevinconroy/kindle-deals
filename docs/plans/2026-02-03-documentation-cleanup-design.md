# Documentation Cleanup Design

## Goal

Make it easy for someone with Claude Code to clone this repo and get it running on their own machine. Remove stale API references throughout.

## Changes

### 1. README.md — Full rewrite

Three sections only:

**Prerequisites**
- Python 3.7+
- MySQL running locally (empty root password as default)
- Amazon account with Kindle samples
- Email account with SMTP access (iCloud app-specific password as default example)

**Setup**
- Copy-paste commands: clone, run `./setup.sh`, activate venv
- Edit config.yaml — list the 3-4 fields they must change (database password, email addresses, email password)
- First-time login: `python src/sync_library.py --login`
- Test email: `python src/send_notification.py --test`

**Usage**
- Primary command: `./check_all_deals.sh`
- Flags: `--dry-run`, `--skip-sync`, `--verbose`, `--force`
- Cron example: `0 5 * * * cd /path/to/kindle-deals && ./check_all_deals.sh`

Remove: Features section, Configuration deep-dive, duplicate command references.

### 2. config.yaml.example — Remove API fields

Remove:
- `amazon.check_frequency`
- `amazon.daily_check_time`
- All Creator API / Product Advertising API fields

Keep:
- `amazon.domain`
- All `database`, `storage`, `email`, `deals`, `scraping` sections
- iCloud SMTP as default example
- Placeholder values for passwords/emails

### 3. CLAUDE.md — Remove API references

- Remove `api_access_key`, `api_secret_key`, `api_associate_tag`, `api_region` from amazon config documentation
- Rewrite "Price Checking Method" section to describe web scraping approach (no API)
- Remove mention of `paapi5-python-sdk`
- Ensure all descriptions of check_deals.py are consistent (web scraping, not API)
