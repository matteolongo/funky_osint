#!/usr/bin/env bash

# osint-flow.sh - Smart OSINT pivoting workflow
# Designed for the osint_me kali container with phoneinfoga, ignorant, holehe, maigret, sherlock, scylla

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
WORKSPACE="/workspace"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
CASE_DIR="$WORKSPACE/osint-$TIMESTAMP"
mkdir -p "$CASE_DIR"

# Tool paths
PHONEINFOGA=$(command -v phoneinfoga 2>/dev/null || echo "")
IGNORANT=$(command -v ignorant 2>/dev/null || echo "")
HOLEHE=$(command -v holehe 2>/dev/null || echo "")
MAIGRET=$(command -v maigret 2>/dev/null || echo "")
SHERLOCK=$(command -v sherlock 2>/dev/null || echo "")
SCYLLA=$(command -v scylla 2>/dev/null || echo "")

declare -a DISCOVERED_USERNAMES=()
declare -a DISCOVERED_EMAILS=()
declare -a DISCOVERED_PHONES=()

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
    [ -n "$SCYLLA" ] && echo -e "  ${GREEN}[+]${NC} scylla" || echo -e "  ${RED}[-]${NC} scylla (not found)"
    echo ""
    sleep 1
}

extract_usernames_from_file() {
    local file="$1"
    [ ! -f "$file" ] && return
    grep -oP '(?<=@)[a-zA-Z0-9_.-]+' "$file" 2>/dev/null >> "$CASE_DIR/.tmp_usernames" || true
    grep -oP '"username":\s*"\K[^"]+' "$file" 2>/dev/null >> "$CASE_DIR/.tmp_usernames" || true
    grep -oP 'username[:\s]+\K[a-zA-Z0-9_.-]+' "$file" 2>/dev/null >> "$CASE_DIR/.tmp_usernames" || true
}

extract_emails_from_file() {
    local file="$1"
    [ ! -f "$file" ] && return
    grep -oP '[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}' "$file" 2>/dev/null >> "$CASE_DIR/.tmp_emails" || true
}

deduplicate_pivots() {
    [ -f "$CASE_DIR/.tmp_usernames" ] && sort -u "$CASE_DIR/.tmp_usernames" | grep -v '^$' > "$CASE_DIR/pivot_usernames.txt" && mapfile -t DISCOVERED_USERNAMES < "$CASE_DIR/pivot_usernames.txt"
    [ -f "$CASE_DIR/.tmp_emails" ] && sort -u "$CASE_DIR/.tmp_emails" | grep -v '^$' > "$CASE_DIR/pivot_emails.txt" && mapfile -t DISCOVERED_EMAILS < "$CASE_DIR/pivot_emails.txt"
}

phone_flow() {
    echo -e "${CYAN}[*] Phone Number Investigation${NC}"
    echo ""
    read -p "Enter phone number (with country code, e.g. +1234567890): " PHONE_NUM
    DISCOVERED_PHONES+=("$PHONE_NUM")
    echo "$PHONE_NUM" > "$CASE_DIR/target_phone.txt"
    
    if [ -n "$PHONEINFOGA" ]; then
        echo -e "\n${YELLOW}[>] Running PhoneInfoga...${NC}"
        $PHONEINFOGA scan -n "$PHONE_NUM" 2>&1 | tee "$CASE_DIR/phoneinfoga_scan.txt" || true
        extract_emails_from_file "$CASE_DIR/phoneinfoga_scan.txt"
    fi
    
    if [ -n "$IGNORANT" ]; then
        echo -e "\n${YELLOW}[>] Running Ignorant (phone -> social accounts)...${NC}"
        $IGNORANT "$PHONE_NUM" 2>&1 | tee "$CASE_DIR/ignorant_scan.txt" || true
        extract_usernames_from_file "$CASE_DIR/ignorant_scan.txt"
        extract_emails_from_file "$CASE_DIR/ignorant_scan.txt"
    fi
    
    deduplicate_pivots
    pivot_menu
}

username_flow() {
    echo -e "${CYAN}[*] Username Investigation${NC}"
    echo ""
    read -p "Enter username: " USERNAME
    DISCOVERED_USERNAMES+=("$USERNAME")
    echo "$USERNAME" > "$CASE_DIR/target_username.txt"
    
    if [ -n "$MAIGRET" ]; then
        echo -e "\n${YELLOW}[>] Running Maigret (comprehensive)...${NC}"
        $MAIGRET "$USERNAME" --timeout 10 2>&1 | tee "$CASE_DIR/maigret_scan.txt" || $MAIGRET "$USERNAME" --timeout 10 -a 2>&1 | tee "$CASE_DIR/maigret_scan.txt" || true
        extract_usernames_from_file "$CASE_DIR/maigret_scan.txt"
        extract_emails_from_file "$CASE_DIR/maigret_scan.txt"
    fi
    
    if [ -n "$SHERLOCK" ]; then
        echo -e "\n${YELLOW}[>] Running Sherlock...${NC}"
        $SHERLOCK "$USERNAME" 2>&1 | tee "$CASE_DIR/sherlock_scan.txt" || true
        extract_usernames_from_file "$CASE_DIR/sherlock_scan.txt"
    fi
    
    deduplicate_pivots
    pivot_menu
}

email_flow() {
    echo -e "${CYAN}[*] Email Investigation${NC}"
    echo ""
    read -p "Enter email address: " EMAIL
    DISCOVERED_EMAILS+=("$EMAIL")
    echo "$EMAIL" > "$CASE_DIR/target_email.txt"
    
    if [ -n "$HOLEHE" ]; then
        echo -e "\n${YELLOW}[>] Running Holehe (email -> registered sites)...${NC}"
        $HOLEHE "$EMAIL" 2>&1 | tee "$CASE_DIR/holehe_scan.txt" || true
        extract_usernames_from_file "$CASE_DIR/holehe_scan.txt"
    fi
    
    if [ -n "$SCYLLA" ]; then
        echo -e "\n${YELLOW}[>] Running Scylla for additional data...${NC}"
        $SCYLLA -e "$EMAIL" 2>&1 | tee "$CASE_DIR/scylla_scan.txt" || true
        extract_usernames_from_file "$CASE_DIR/scylla_scan.txt"
        extract_emails_from_file "$CASE_DIR/scylla_scan.txt"
    fi
    
    deduplicate_pivots
    pivot_menu
}

username_flow_from_pivot() {
    echo -e "\n${YELLOW}[>] Pivoting on username: $USERNAME${NC}"
    [ -n "$MAIGRET" ] && $MAIGRET "$USERNAME" --timeout 10 2>&1 | tee "$CASE_DIR/maigret_pivot_${USERNAME}.txt" || true
    [ -n "$SHERLOCK" ] && $SHERLOCK "$USERNAME" 2>&1 | tee "$CASE_DIR/sherlock_pivot_${USERNAME}.txt" || true
    extract_usernames_from_file "$CASE_DIR/maigret_pivot_${USERNAME}.txt" 2>/dev/null
    extract_emails_from_file "$CASE_DIR/maigret_pivot_${USERNAME}.txt" 2>/dev/null
    extract_usernames_from_file "$CASE_DIR/sherlock_pivot_${USERNAME}.txt" 2>/dev/null
    deduplicate_pivots
    pivot_menu
}

email_flow_from_pivot() {
    echo -e "\n${YELLOW}[>] Pivoting on email: $EMAIL${NC}"
    [ -n "$HOLEHE" ] && $HOLEHE "$EMAIL" 2>&1 | tee "$CASE_DIR/holehe_pivot_${EMAIL//[@.]/_}.txt" || true
    [ -n "$SCYLLA" ] && $SCYLLA -e "$EMAIL" 2>&1 | tee "$CASE_DIR/scylla_pivot_${EMAIL//[@.]/_}.txt" || true
    extract_usernames_from_file "$CASE_DIR/holehe_pivot_${EMAIL//[@.]/_}.txt" 2>/dev/null
    extract_usernames_from_file "$CASE_DIR/scylla_pivot_${EMAIL//[@.]/_}.txt" 2>/dev/null
    extract_emails_from_file "$CASE_DIR/scylla_pivot_${EMAIL//[@.]/_}.txt" 2>/dev/null
    deduplicate_pivots
    pivot_menu
}

aggressive_pivot() {
    echo -e "\n${RED}[!] Running everything on all discovered pivots${NC}"
    echo -e "${YELLOW}This may take a while...${NC}"
    sleep 2
    deduplicate_pivots
    for uname in "${DISCOVERED_USERNAMES[@]}"; do
        [ -z "$uname" ] && continue
        echo -e "\n${CYAN}[*] Aggressive scan: $uname${NC}"
        [ -n "$MAIGRET" ] && $MAIGRET "$uname" --timeout 8 2>&1 | tee "$CASE_DIR/aggressive_maigret_$uname.txt" >/dev/null || true
        [ -n "$SHERLOCK" ] && $SHERLOCK "$uname" 2>&1 | tee "$CASE_DIR/aggressive_sherlock_$uname.txt" >/dev/null || true
        extract_usernames_from_file "$CASE_DIR/aggressive_maigret_$uname.txt" 2>/dev/null
        extract_emails_from_file "$CASE_DIR/aggressive_maigret_$uname.txt" 2>/dev/null
        extract_usernames_from_file "$CASE_DIR/aggressive_sherlock_$uname.txt" 2>/dev/null
    done
    for em in "${DISCOVERED_EMAILS[@]}"; do
        [ -z "$em" ] && continue
        echo -e "\n${CYAN}[*] Aggressive scan: $em${NC}"
        [ -n "$HOLEHE" ] && $HOLEHE "$em" 2>&1 | tee "$CASE_DIR/aggressive_holehe_${em//[@.]/_}.txt" >/dev/null || true
        [ -n "$SCYLLA" ] && $SCYLLA -e "$em" 2>&1 | tee "$CASE_DIR/aggressive_scylla_${em//[@.]/_}.txt" >/dev/null || true
    done
    deduplicate_pivots
    echo -e "\n${GREEN}[+] Aggressive pivot complete${NC}"
    pivot_menu
}

pivot_menu() {
    deduplicate_pivots
    echo ""
    echo -e "${GREEN}============================================================${NC}"
    echo -e "${GREEN}[*] PIVOTS DISCOVERED${NC}"
    echo -e "${GREEN}============================================================${NC}"
    [ ${#DISCOVERED_USERNAMES[@]} -gt 0 ] && echo -e "${CYAN}Usernames:${NC} ${DISCOVERED_USERNAMES[*]}"
    [ ${#DISCOVERED_EMAILS[@]} -gt 0 ] && echo -e "${CYAN}Emails:${NC} ${DISCOVERED_EMAILS[*]}"
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
    echo ""
    read -p "Choice [1-9]: " choice
    case $choice in
        1) if [ ${#DISCOVERED_USERNAMES[@]} -eq 0 ]; then echo -e "${RED}[!] No usernames discovered yet${NC}"; sleep 2; pivot_menu; return; fi; echo "Select username:"; select uname in "${DISCOVERED_USERNAMES[@]}" "Cancel"; do [ "$uname" = "Cancel" ] && break; [ -n "$uname" ] && { USERNAME="$uname"; username_flow_from_pivot; break; }; done ;;
        2) if [ ${#DISCOVERED_EMAILS[@]} -eq 0 ]; then echo -e "${RED}[!] No emails discovered yet${NC}"; sleep 2; pivot_menu; return; fi; echo "Select email:"; select em in "${DISCOVERED_EMAILS[@]}" "Cancel"; do [ "$em" = "Cancel" ] && break; [ -n "$em" ] && { EMAIL="$em"; email_flow_from_pivot; break; }; done ;;
        3) read -p "Enter username: " USERNAME; DISCOVERED_USERNAMES+=("$USERNAME"); username_flow_from_pivot ;;
        4) read -p "Enter email: " EMAIL; DISCOVERED_EMAILS+=("$EMAIL"); email_flow_from_pivot ;;
        5) phone_flow ;;
        6) aggressive_pivot ;;
        7) echo -e "\n${CYAN}[*] Results in: $CASE_DIR${NC}"; ls -lh "$CASE_DIR" | tail -n +2; echo ""; read -p "Press enter to continue..."; pivot_menu ;;
        8) main_menu ;;
        9) echo -e "${GREEN}Good hunting. Results saved to: $CASE_DIR${NC}"; exit 0 ;;
        *) echo -e "${RED}[!] Invalid choice${NC}"; sleep 2; pivot_menu ;;
    esac
}

main_menu() {
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
        1) phone_flow ;;
        2) username_flow ;;
        3) email_flow ;;
        4) echo ""; read -p "Path to file with usernames/emails/phones: " pivot_file; [ -f "$pivot_file" ] && while IFS= read -r line; do [[ -z "$line" || "$line" =~ ^# ]] && continue; if [[ "$line" =~ @ ]]; then DISCOVERED_EMAILS+=("$line"); elif [[ "$line" =~ ^\+?[0-9]{7,15}$ ]]; then DISCOVERED_PHONES+=("$line"); else DISCOVERED_USERNAMES+=("$line"); fi; done < "$pivot_file" && deduplicate_pivots && pivot_menu || { echo -e "${RED}[!] File not found${NC}"; sleep 2; main_menu; } ;;
        5) echo -e "${GREEN}Good hunting. Results saved to: $CASE_DIR${NC}"; exit 0 ;;
        *) echo -e "${RED}[!] Invalid choice${NC}"; sleep 2; main_menu ;;
    esac
}

trap 'rm -f "$CASE_DIR/.tmp_usernames" "$CASE_DIR/.tmp_emails" 2>/dev/null' EXIT
main_menu
