#!/usr/bin/env bash

# osint-flow.sh - Smart OSINT pivoting workflow
# Designed for the osint_me kali container with phoneinfoga, ignorant, holehe, maigret, and sherlock

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m'

# Directories
WORKSPACE="${WORKSPACE:-/workspace}"
if [ "$#" -gt 1 ] && ! { [ "$#" -eq 2 ] && [ "$1" = "--case" ]; }; then
    echo "Usage: osint [username] | osint --case intake.json" >&2
    exit 2
fi
if ! mkdir -p "$WORKSPACE" || ! CASE_DIR=$(mktemp -d "$WORKSPACE/osint-$(date +%Y%m%d_%H%M%S)-XXXXXX" 2>/dev/null); then
    echo "Cannot create a case in $WORKSPACE. Check that the workspace is writable." >&2
    echo "The dashboard container is read-only. Run from your host: docker compose run --rm kali osint [username]" >&2
    exit 1
fi
CASE_STORE="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/case_store.py"

# Tool paths
PHONEINFOGA=$(command -v phoneinfoga 2>/dev/null || echo "")
IGNORANT=$(command -v ignorant 2>/dev/null || echo "")
HOLEHE=$(command -v holehe 2>/dev/null || echo "")
MAIGRET=$(command -v maigret 2>/dev/null || echo "")
SHERLOCK=$(command -v sherlock 2>/dev/null || echo "")

declare -a DISCOVERED_USERNAMES=()
declare -a DISCOVERED_EMAILS=()
declare -a DISCOVERED_PHONES=()

record_identifier() {
    python3 "$CASE_STORE" identifier "$CASE_DIR" "$1" "$2"
}

run_scan() {
    local kind="$1" target="$2" tool="$3" status=0
    shift 3
    SCAN_FILE=$(mktemp "$CASE_DIR/${tool}_XXXXXX.txt")
    if (set -o pipefail; "$@" 2>&1 | tee "$SCAN_FILE"); then :; else status=$?; fi
    python3 "$CASE_STORE" scan "$CASE_DIR" "$kind" "$target" "$tool" "$(basename "$SCAN_FILE")" "$status"
    if [ "$status" -ne 0 ]; then
        echo -e "${RED}[!] $tool failed; see $(basename "$SCAN_FILE")${NC}"
    fi
}

banner() {
    clear
    echo -e "${CYAN}"
    echo "  ____  ____ ___ _   _ _____   _____ _     _____  _     _ "
    echo " / ___||  _ \_ _| \ | |_   _| |  ___| |   / _ \ \ / /   | |"
    echo "| |    | |_) | ||  \| | | |   | |_  | |  | | | \ V /____| |"
    echo "| |___ |  _ < | || |\  | | |   |  _| | |__| |_| || |_____| |"
    echo " \____||_| \_\___|_| \_| |_|   |_|   |_____\___/ |_|     |_|"
    echo -e "${NC}"
    echo -e "${YELLOW}Smart OSINT Pivoting Workflow${NC}"
    echo -e "${BLUE}Case: $CASE_DIR${NC}"
    echo "------------------------------------------------------------"
    echo ""
}

check_tools() {
    echo -e "${CYAN}[*] Checking for available tools...${NC}"
    [ -n "$PHONEINFOGA" ] && echo -e "  ${GREEN}[+]${NC} phoneinfoga" || echo -e "  ${RED}[-]${NC} phoneinfoga (not found)"
    [ -n "$IGNORANT" ] && echo -e "  ${GREEN}[+]${NC} ignorant" || echo -e "  ${RED}[-]${NC} ignorant (not found)"
    [ -n "$HOLEHE" ] && echo -e "  ${GREEN}[+]${NC} holehe" || echo -e "  ${RED}[-]${NC} holehe (not found)"
    [ -n "$MAIGRET" ] && echo -e "  ${GREEN}[+]${NC} maigret" || echo -e "  ${RED}[-]${NC} maigret (not found)"
    [ -n "$SHERLOCK" ] && echo -e "  ${GREEN}[+]${NC} sherlock" || echo -e "  ${RED}[-]${NC} sherlock (not found)"
    echo ""
    sleep 1
}

extract_usernames_from_file() {
    local file="$1"
    [ ! -f "$file" ] && return
    grep -oP '(?<![a-zA-Z0-9._%+-])@\K[a-zA-Z0-9_.-]+' "$file" 2>/dev/null >> "$CASE_DIR/.tmp_usernames" || true
    grep -oP '"username":\s*"\K[^"]+' "$file" 2>/dev/null >> "$CASE_DIR/.tmp_usernames" || true
    grep -oP 'username[:\s]+\K[a-zA-Z0-9_.-]+' "$file" 2>/dev/null >> "$CASE_DIR/.tmp_usernames" || true
}

extract_emails_from_file() {
    local file="$1"
    [ ! -f "$file" ] && return
    grep -oP '[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}' "$file" 2>/dev/null >> "$CASE_DIR/.tmp_emails" || true
}

deduplicate_pivots() {
    { printf '%s\n' "${DISCOVERED_USERNAMES[@]}"; cat "$CASE_DIR/.tmp_usernames" 2>/dev/null || true; } | sed '/^$/d' | sort -u > "$CASE_DIR/pivot_usernames.txt"
    { printf '%s\n' "${DISCOVERED_EMAILS[@]}"; cat "$CASE_DIR/.tmp_emails" 2>/dev/null || true; } | sed '/^$/d' | sort -u > "$CASE_DIR/pivot_emails.txt"
    mapfile -t DISCOVERED_USERNAMES < "$CASE_DIR/pivot_usernames.txt"
    mapfile -t DISCOVERED_EMAILS < "$CASE_DIR/pivot_emails.txt"
}

phone_flow() {
    echo -e "${CYAN}[*] Phone Number Investigation${NC}"
    echo ""
    if [ -n "${1:-}" ]; then PHONE_NUM=$1; else read -r -p "Enter phone number (with country code, e.g. +1234567890): " PHONE_NUM; fi
    DISCOVERED_PHONES+=("$PHONE_NUM")
    record_identifier phone "$PHONE_NUM"
    echo "$PHONE_NUM" > "$CASE_DIR/target_phone.txt"
    
    if [ -n "$PHONEINFOGA" ]; then
        echo -e "\n${YELLOW}[>] Running PhoneInfoga...${NC}"
        run_scan phone "$PHONE_NUM" phoneinfoga "$PHONEINFOGA" scan -n "$PHONE_NUM"
        extract_emails_from_file "$SCAN_FILE"
    fi
    
    if [ -n "$IGNORANT" ]; then
        echo -e "\n${YELLOW}[>] Running Ignorant (phone -> social accounts)...${NC}"
        read -r -p "Enter the country calling code (e.g. +1): " country_code
        if [[ "$country_code" =~ ^\+[0-9]{1,3}$ && "$PHONE_NUM" == "$country_code"* && "$PHONE_NUM" != "$country_code" ]]; then
            run_scan phone "$PHONE_NUM" ignorant "$IGNORANT" "$country_code" "${PHONE_NUM#"$country_code"}"
            extract_usernames_from_file "$SCAN_FILE"
            extract_emails_from_file "$SCAN_FILE"
        else
            echo -e "${RED}[!] Invalid country code for this number; skipping Ignorant${NC}"
        fi
    fi
    
    deduplicate_pivots
}

username_flow() {
    echo -e "${CYAN}[*] Username Investigation${NC}"
    echo ""
    if [ -n "${1:-}" ]; then USERNAME=$1; else read -r -p "Enter username: " USERNAME; fi
    DISCOVERED_USERNAMES+=("$USERNAME")
    record_identifier username "$USERNAME"
    echo "$USERNAME" > "$CASE_DIR/target_username.txt"
    
    if [ -n "$MAIGRET" ]; then
        echo -e "\n${YELLOW}[>] Running Maigret (comprehensive)...${NC}"
        run_scan username "$USERNAME" maigret "$MAIGRET" "$USERNAME" --timeout 10
        extract_usernames_from_file "$SCAN_FILE"
        extract_emails_from_file "$SCAN_FILE"
    fi
    
    if [ -n "$SHERLOCK" ]; then
        echo -e "\n${YELLOW}[>] Running Sherlock...${NC}"
        run_scan username "$USERNAME" sherlock "$SHERLOCK" "$USERNAME"
        extract_usernames_from_file "$SCAN_FILE"
    fi
    
    deduplicate_pivots
}

email_flow() {
    echo -e "${CYAN}[*] Email Investigation${NC}"
    echo ""
    read -p "Enter email address: " EMAIL
    DISCOVERED_EMAILS+=("$EMAIL")
    record_identifier email "$EMAIL"
    echo "$EMAIL" > "$CASE_DIR/target_email.txt"
    
    if [ -n "$HOLEHE" ]; then
        echo -e "\n${YELLOW}[>] Running Holehe (email -> registered sites)...${NC}"
        run_scan email "$EMAIL" holehe "$HOLEHE" "$EMAIL"
        extract_usernames_from_file "$SCAN_FILE"
    fi
    
    deduplicate_pivots
}

username_flow_from_pivot() {
    echo -e "\n${YELLOW}[>] Pivoting on username: $USERNAME${NC}"
    record_identifier username "$USERNAME"
    if [ -n "$MAIGRET" ]; then
        run_scan username "$USERNAME" maigret "$MAIGRET" "$USERNAME" --timeout 10
        extract_usernames_from_file "$SCAN_FILE"; extract_emails_from_file "$SCAN_FILE"
    fi
    if [ -n "$SHERLOCK" ]; then
        run_scan username "$USERNAME" sherlock "$SHERLOCK" "$USERNAME"
        extract_usernames_from_file "$SCAN_FILE"
    fi
    deduplicate_pivots
}

email_flow_from_pivot() {
    echo -e "\n${YELLOW}[>] Pivoting on email: $EMAIL${NC}"
    record_identifier email "$EMAIL"
    if [ -n "$HOLEHE" ]; then
        run_scan email "$EMAIL" holehe "$HOLEHE" "$EMAIL"
        extract_usernames_from_file "$SCAN_FILE"
    fi
    deduplicate_pivots
}

aggressive_pivot() {
    echo -e "\n${RED}[!] Running everything on all discovered pivots${NC}"
    echo -e "${YELLOW}This may take a while...${NC}"
    sleep 2
    deduplicate_pivots
    for uname in "${DISCOVERED_USERNAMES[@]}"; do
        [ -z "$uname" ] && continue
        echo -e "\n${CYAN}[*] Aggressive scan: $uname${NC}"
        USERNAME="$uname"
        username_flow_from_pivot
    done
    for em in "${DISCOVERED_EMAILS[@]}"; do
        [ -z "$em" ] && continue
        echo -e "\n${CYAN}[*] Aggressive scan: $em${NC}"
        EMAIL="$em"
        email_flow_from_pivot
    done
    deduplicate_pivots
    echo -e "\n${GREEN}[+] Aggressive pivot complete${NC}"
}

load_pivots() {
    local pivot_file line
    read -r -p "Path to file with usernames/emails/phones: " pivot_file
    if [ ! -f "$pivot_file" ]; then
        echo -e "${RED}[!] File not found${NC}"
        return 1
    fi
    while IFS= read -r line || [ -n "$line" ]; do
        [[ -z "$line" || "$line" =~ ^# ]] && continue
        if [[ "$line" =~ @ ]]; then
            DISCOVERED_EMAILS+=("$line")
            record_identifier email "$line"
        elif [[ "$line" =~ ^\+?[0-9]{7,15}$ ]]; then
            DISCOVERED_PHONES+=("$line")
            record_identifier phone "$line"
        else
            DISCOVERED_USERNAMES+=("$line")
            record_identifier username "$line"
        fi
    done < "$pivot_file"
    deduplicate_pivots
}

pivot_menu() {
    while true; do
    deduplicate_pivots
    echo ""
    echo -e "${GREEN}============================================================${NC}"
    echo -e "${GREEN}[*] PIVOTS DISCOVERED${NC}"
    echo -e "${GREEN}============================================================${NC}"
    [ ${#DISCOVERED_USERNAMES[@]} -gt 0 ] && echo -e "${CYAN}Usernames:${NC} ${DISCOVERED_USERNAMES[*]}"
    [ ${#DISCOVERED_EMAILS[@]} -gt 0 ] && echo -e "${CYAN}Emails:${NC} ${DISCOVERED_EMAILS[*]}"
    [ ${#DISCOVERED_PHONES[@]} -gt 0 ] && echo -e "${CYAN}Phones:${NC} ${DISCOVERED_PHONES[*]}"
    echo ""
    echo "What would you like to pivot to?"
    echo "1) Investigate a discovered username"
    echo "2) Investigate a discovered email"
    echo "3) Investigate a new username (manual)"
    echo "4) Investigate a new email (manual)"
    echo "5) Investigate a phone number (manual)"
    echo "6) Run everything on ALL discovered pivots (aggressive)"
    echo "7) View all results so far"
    echo "8) Back to main menu"
    echo "9) Exit"
    echo "10) Investigate a discovered phone number"
    echo ""
    read -r -p "Choice [1-10]: " choice
    case $choice in
        1) if [ ${#DISCOVERED_USERNAMES[@]} -eq 0 ]; then echo -e "${RED}[!] No usernames discovered yet${NC}"; continue; fi; echo "Select username:"; select uname in "${DISCOVERED_USERNAMES[@]}" "Cancel"; do [ "$uname" = "Cancel" ] && break; [ -n "$uname" ] && { USERNAME="$uname"; username_flow_from_pivot; break; }; done ;;
        2) if [ ${#DISCOVERED_EMAILS[@]} -eq 0 ]; then echo -e "${RED}[!] No emails discovered yet${NC}"; continue; fi; echo "Select email:"; select em in "${DISCOVERED_EMAILS[@]}" "Cancel"; do [ "$em" = "Cancel" ] && break; [ -n "$em" ] && { EMAIL="$em"; email_flow_from_pivot; break; }; done ;;
        3) read -p "Enter username: " USERNAME; DISCOVERED_USERNAMES+=("$USERNAME"); username_flow_from_pivot ;;
        4) read -p "Enter email: " EMAIL; DISCOVERED_EMAILS+=("$EMAIL"); email_flow_from_pivot ;;
        5) phone_flow ;;
        6) aggressive_pivot ;;
        7) echo -e "\n${CYAN}[*] Results in: $CASE_DIR${NC}"; ls -lh "$CASE_DIR" | tail -n +2; echo ""; read -r -p "Press enter to continue..." ;;
        8) return ;;
        9) echo -e "${GREEN}Good hunting. Results saved to: $CASE_DIR${NC}"; exit 0 ;;
        10) if [ ${#DISCOVERED_PHONES[@]} -eq 0 ]; then echo -e "${RED}[!] No phone numbers discovered yet${NC}"; continue; fi; echo "Select phone number:"; select phone in "${DISCOVERED_PHONES[@]}" "Cancel"; do [ "$phone" = "Cancel" ] && break; [ -n "$phone" ] && { phone_flow "$phone"; break; }; done ;;
        *) echo -e "${RED}[!] Invalid choice${NC}" ;;
    esac
    done
}

main_menu() {
    while true; do
    banner
    check_tools
    echo -e "${CYAN}What do you have to start with?${NC}"
    echo "1) Phone number"
    echo "2) Username"
    echo "3) Email"
    echo "4) Load pivots from file (one per line)"
    echo "5) Exit"
    echo ""
    read -p "Choice [1-5]: " choice
    case $choice in
        1) phone_flow; pivot_menu ;;
        2) username_flow; pivot_menu ;;
        3) email_flow; pivot_menu ;;
        4) if load_pivots; then pivot_menu; fi ;;
        5) echo -e "${GREEN}Good hunting. Results saved to: $CASE_DIR${NC}"; exit 0 ;;
        *) echo -e "${RED}[!] Invalid choice${NC}" ;;
    esac
    done
}

trap 'rm -f "$CASE_DIR/.tmp_usernames" "$CASE_DIR/.tmp_emails" 2>/dev/null' EXIT
if [ "$#" -eq 2 ]; then
    python3 "$(dirname "$CASE_STORE")/case_runner.py" "$CASE_DIR" "$2"
    mapfile -t DISCOVERED_USERNAMES < <(python3 -c 'import json,sys; d=json.load(open(sys.argv[1], encoding="utf-8")); print("\n".join(i["value"] for i in d["identifiers"] if i["type"] == "username"))' "$CASE_DIR/case.json")
    mapfile -t DISCOVERED_EMAILS < <(python3 -c 'import json,sys; d=json.load(open(sys.argv[1], encoding="utf-8")); print("\n".join(i["value"] for i in d["identifiers"] if i["type"] == "email"))' "$CASE_DIR/case.json")
    mapfile -t DISCOVERED_PHONES < <(python3 -c 'import json,sys; d=json.load(open(sys.argv[1], encoding="utf-8")); print("\n".join(i["value"] for i in d["identifiers"] if i["type"] == "phone"))' "$CASE_DIR/case.json")
    pivot_menu
fi
if [ "$#" -eq 1 ]; then
    username_flow "$1"
    pivot_menu
fi
main_menu
