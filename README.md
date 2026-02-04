# Kindle Deals Monitor

Monitor your Kindle samples for price drops and get email notifications when deals appear.

## Prerequisites

- **Python 3.7+**
- **MySQL** running locally
- **Amazon account** with Kindle samples in your "My Books" library
- **Email account** with SMTP access (iCloud with an app-specific password works well)

## Setup

```bash
# Clone and set up
git clone https://github.com/your-username/kindle-deals.git
cd kindle-deals
./setup.sh
source venv/bin/activate
```

Edit `config.yaml` with your settings. The fields you must change:

```yaml
database:
  password: ""              # your MySQL root password

email:
  from_address: "you@icloud.com"
  to_address: "you@gmail.com"
  password: "xxxx-xxxx-xxxx-xxxx"  # iCloud app-specific password
```

Log in to Amazon (one-time, saves browser session):

```bash
python src/sync_library.py --login
```

Verify email is working:

```bash
python src/send_notification.py --test
```

## Usage

Run the full workflow (sync library + check deals):

```bash
./check_all_deals.sh
```

Options:

```bash
./check_all_deals.sh --dry-run      # no emails, no database changes
./check_all_deals.sh --skip-sync    # skip library sync
./check_all_deals.sh --verbose      # detailed output
./check_all_deals.sh --force        # re-check books already checked today
```

### Automate with cron

```bash
# Run daily at 5 AM
0 5 * * * cd /path/to/kindle-deals && ./check_all_deals.sh
```
