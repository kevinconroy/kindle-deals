#!/bin/bash
#
# Check All Deals - One-command workflow
#
# This script runs the complete deal checking workflow:
# 1. Sync Kindle library (with recommendations)
# 2. Check deals (sample books + daily deals)
#

set -e  # Exit on any error

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo ""
echo -e "${BLUE}=====================================${NC}"
echo -e "${BLUE}  Kindle Deals Monitor - Full Check ${NC}"
echo -e "${BLUE}=====================================${NC}"
echo ""

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}Warning: Virtual environment not found${NC}"
    echo "Run ./setup.sh first to set up the environment"
    exit 1
fi

# Activate virtual environment
source venv/bin/activate

# Parse arguments
DRY_RUN=""
VERBOSE=""
SKIP_SYNC=""
FORCE=""
SKIP_SAMPLES=""
SKIP_DAILY=""
SKIP_COLLECTIONS=""
LOGIN=""
SKIP_RECOMMENDATIONS=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN="--dry-run"
            shift
            ;;
        --verbose|-v)
            VERBOSE="--verbose"
            shift
            ;;
        --force|-f)
            FORCE="--force"
            shift
            ;;
        --skip-sync)
            SKIP_SYNC="true"
            shift
            ;;
        --skip-samples)
            SKIP_SAMPLES="--skip-samples"
            shift
            ;;
        --skip-daily)
            SKIP_DAILY="--skip-daily"
            shift
            ;;
        --skip-collections)
            SKIP_COLLECTIONS="--skip-collections"
            shift
            ;;
        --login)
            LOGIN="--login"
            shift
            ;;
        --skip-recommendations)
            SKIP_RECOMMENDATIONS="--skip-recommendations"
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [options]"
            echo ""
            echo "Options:"
            echo "  --dry-run        Don't send emails or update database"
            echo "  --verbose, -v    Show detailed output"
            echo "  --force, -f      Force full sync and check all books"
            echo "  --skip-sync      Skip library sync, only check deals"
            echo "  --skip-samples   Skip sample book price checks"
            echo "  --skip-daily     Skip daily deals check"
            echo "  --skip-collections  Skip auto-adding samples to collection"
            echo "  --login          Log in to Amazon (interactive, saves session)"
            echo "  --skip-recommendations  Skip checking recommended book prices"
            echo "  --help, -h       Show this help message"
            echo ""
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Step 1: Sync library (unless skipped)
if [ -z "$SKIP_SYNC" ]; then
    echo -e "${GREEN}Step 1: Syncing Kindle library...${NC}"
    echo "This may take a few minutes..."
    echo ""

    if python src/sync_library.py $VERBOSE $LOGIN $FORCE $SKIP_COLLECTIONS; then
        echo ""
        echo -e "${GREEN}✓ Library sync complete${NC}"
        echo ""
    else
        echo ""
        echo -e "${YELLOW}Warning: Library sync failed${NC}"
        echo "Continuing to deal checks anyway..."
        echo ""
    fi
else
    echo -e "${YELLOW}Skipping library sync (--skip-sync)${NC}"
    echo ""
fi

# Step 2: Check deals (sample books + daily deals)
echo -e "${GREEN}Step 2: Checking deals...${NC}"
echo ""

if python src/check_deals.py $DRY_RUN $VERBOSE $FORCE $SKIP_SAMPLES $SKIP_DAILY $SKIP_RECOMMENDATIONS; then
    echo ""
    echo -e "${GREEN}✓ Deal check complete${NC}"
    echo ""
else
    echo ""
    echo -e "${YELLOW}Deal check failed${NC}"
    exit 1
fi

# Summary
echo -e "${BLUE}=====================================${NC}"
echo -e "${BLUE}  Complete!${NC}"
echo -e "${BLUE}=====================================${NC}"
echo ""

if [ -n "$DRY_RUN" ]; then
    echo -e "${YELLOW}DRY RUN MODE: No emails sent, no database updates${NC}"
    echo ""
fi

exit 0
