# Kindle Deals Monitor

Monitor Kindle samples for price deals and receive email notifications.

## Setup

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
python setup.py
```

## Usage

```bash
# Sync your Kindle library
python src/sync_library.py

# Check for deals
python src/check_deals.py

# Test email notification
python src/send_notification.py --test
```

## Configuration

Copy `config.yaml.example` to `config.yaml` and update with your settings, including:
- MySQL database credentials
- Email SMTP settings and password
- Amazon Product Advertising API credentials
