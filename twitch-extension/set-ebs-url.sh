#!/usr/bin/env bash
# Configure the EBS (backend) URL in the Twitch Extension Configuration Service.
#
# Run this once after the first deploy, and again any time the backend URL changes.
# No extension rebuild or re-upload is required — the change takes effect immediately.
#
# Usage:
#   bash twitch-extension/set-ebs-url.sh [ebs-url]
#   bash twitch-extension/set-ebs-url.sh --debug   # print JWT payload and raw API responses
#
# ── Prerequisite ──────────────────────────────────────────────────────────────
#
#  The Twitch Extension Configuration Service MUST be saved as the active option
#  before running this script. If it is not, the API returns 401.
#
#  To enable it:
#    1. https://dev.twitch.tv/console/extensions → click extension → Extension Settings
#    2. Under "Select how you will configure your extension", choose
#       "Extension Configuration Service" and click Save Changes.
#    3. The extension version must be in "Local Test" status or higher.
#
# ── Where to find the values ──────────────────────────────────────────────────
#
#  Both values are on the Extension Settings page:
#    https://dev.twitch.tv/console/extensions → click extension → Extension Settings
#
#  TWITCH_CLIENT_ID    "Client ID" shown in the top-right corner of the page
#  TWITCH_EXT_SECRET   Extension Secrets table at the bottom → Key column (base64)
#                      This is NOT the "Twitch API Client Secret" shown mid-page.

set -e

DEBUG=false
if [[ "${1:-}" == "--debug" ]]; then
    DEBUG=true
    shift
fi

EBS_URL="${1:-}"

# ── Pre-set values (optional — fill in to skip interactive prompts) ────────────

TWITCH_CLIENT_ID=""      # Client ID  (Extension Settings → top-right)
TWITCH_EXT_SECRET=""     # Extension Secret  (Extension Settings → Extension Secrets table → Key column)
TWITCH_OWNER_USER_ID=""  # Numeric Twitch user ID of the extension owner  (https://www.streamweasels.com/tools/convert-twitch-username-to-user-id/)

# ─────────────────────────────────────────────────────────────────────────────

# ── Validation ────────────────────────────────────────────────────────────────

validate_client_id() {
    local val="$1"
    [[ ${#val} -ge 10 && ${#val} -le 50 ]] || { echo "   ERROR: expected 10–50 characters, got ${#val}."; return 1; }
    [[ "$val" =~ ^[a-z0-9]+$ ]] || { echo "   ERROR: must be lowercase letters and digits only."; return 1; }
}

validate_user_id() {
    local val="$1"
    [[ "$val" =~ ^[0-9]+$ ]] || { echo "   ERROR: must be a numeric Twitch user ID (digits only)."; return 1; }
}

validate_ext_secret() {
    local val="$1"
    [[ ${#val} -ge 20 ]] || { echo "   ERROR: too short — paste the full key from the Extension Secrets table."; return 1; }
    [[ "$val" =~ ^[A-Za-z0-9+/=]+$ ]] || { echo "   ERROR: expected a base64 string (letters, digits, +, /, =)."; return 1; }
}

validate_url() {
    local val="$1"
    [[ "$val" =~ ^https?:// ]] || { echo "   ERROR: must start with https://"; return 1; }
    [[ "${val: -1}" != "/" ]] || { echo "   ERROR: remove the trailing slash."; return 1; }
    [[ ${#val} -le 256 ]] || { echo "   ERROR: URL too long (max 256 characters)."; return 1; }
}

# ── Prompt helper ─────────────────────────────────────────────────────────────

prompt() {
    local var_name="$1" label="$2" hint="$3" validate_fn="${4:-}"
    local current; eval current=\$$var_name
    [ -n "$current" ] && return

    while true; do
        echo ""
        echo "── $label"
        printf "   %s\n" "$hint"
        echo ""
        read -rp "   Enter value: " input
        [ -z "$input" ] && { echo "   ERROR: value is required."; continue; }
        [ -n "$validate_fn" ] && ! "$validate_fn" "$input" && continue
        eval "$var_name=\"\$input\""
        break
    done
}

# ── JWT generation ─────────────────────────────────────────────────────────────

make_jwt() {
    local secret="$1"
    local user_id="$2"
    python3 - "$secret" "$user_id" <<'PYEOF'
import sys, json, base64, hmac, hashlib, time

def b64url(data):
    if isinstance(data, str):
        data = data.encode()
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

raw, user_id = sys.argv[1], sys.argv[2]
pad = (4 - len(raw) % 4) % 4
secret = base64.b64decode(raw + "=" * pad)

header  = b64url('{"alg":"HS256","typ":"JWT"}')
payload_data = {"exp": int(time.time()) + 120, "role": "external", "user_id": user_id}
payload = b64url(json.dumps(payload_data, separators=(",", ":")))

sig = hmac.new(secret, f"{header}.{payload}".encode(), hashlib.sha256).digest()
sys.stderr.write(f"[debug] JWT payload: {json.dumps(payload_data)}\n")
sys.stderr.write(f"[debug] key (hex):   {secret.hex()}\n")
print(f"{header}.{payload}.{b64url(sig)}")
PYEOF
}

# ── Step 1: collect credentials ───────────────────────────────────────────────

echo ""
echo "Both values are on the Extension Settings page:"
echo "  https://dev.twitch.tv/console/extensions → click extension → Extension Settings"
echo ""

prompt TWITCH_CLIENT_ID \
    "Client ID" \
    "Shown in the top-right corner of the Extension Settings page.
   Lowercase alphanumeric, ~30 characters." \
    validate_client_id

prompt TWITCH_EXT_SECRET \
    "Extension Secret" \
    "Scroll to the bottom of Extension Settings → 'Extension Secrets' table → Key column.
   Long base64 string (letters, digits, +, /, =).
   NOT the 'Twitch API Client Secret' shown mid-page — that one is not used here." \
    validate_ext_secret

prompt TWITCH_OWNER_USER_ID \
    "Your Twitch User ID (numeric)" \
    "The numeric ID of the Twitch account that owns the extension — NOT a username.
   Look it up at: https://www.streamweasels.com/tools/convert-twitch-username-to-user-id/
   Or via Twitch API: GET https://api.twitch.tv/helix/users?login=<your_username>" \
    validate_user_id

# ── Step 2: generate JWT ──────────────────────────────────────────────────────

echo ""
echo "Generating JWT..."

if $DEBUG; then
    JWT=$(make_jwt "$TWITCH_EXT_SECRET" "$TWITCH_OWNER_USER_ID")
else
    JWT=$(make_jwt "$TWITCH_EXT_SECRET" "$TWITCH_OWNER_USER_ID" 2>/dev/null)
fi

$DEBUG && echo "[debug] JWT: $JWT"

# ── Step 3: query current EBS URL ─────────────────────────────────────────────

echo "Querying current configuration..."

GET_URL="https://api.twitch.tv/helix/extensions/configurations?extension_id=${TWITCH_CLIENT_ID}&segment=global"
$DEBUG && echo "[debug] GET: $GET_URL"

CURRENT_RESPONSE=$(curl -s \
    -H "Authorization: Bearer ${JWT}" \
    -H "Client-Id: ${TWITCH_CLIENT_ID}" \
    "$GET_URL")

$DEBUG && echo "[debug] GET response: $CURRENT_RESPONSE"

if echo "$CURRENT_RESPONSE" | grep -q '"error"'; then
    ERROR_MSG=$(echo "$CURRENT_RESPONSE" | grep -o '"message":"[^"]*"' | cut -d'"' -f4)
    echo ""
    echo "ERROR: Twitch API rejected the request — ${ERROR_MSG:-authentication failed}"
    echo ""
    echo "Most likely causes:"
    echo "  1. Extension Configuration Service is not saved as active."
    echo "     Go to Extension Settings → select 'Extension Configuration Service' → Save Changes."
    echo ""
    echo "  2. The Extension Secret is wrong or was recently regenerated."
    echo "     Use the CURRENT key from the Extension Secrets table at the bottom of Extension Settings."
    echo "     If you recently clicked 'Generate New Secret', use the new key."
    echo ""
    echo "  3. The extension version is not in 'Local Test' status or higher."
    echo ""
    echo "Run with --debug to see the full JWT and response:"
    echo "  bash twitch-extension/set-ebs-url.sh --debug"
    exit 1
fi

CURRENT_EBS=$(echo "$CURRENT_RESPONSE" | sed 's/\\"/"/g' | grep -o '"ebs_url":"[^"]*"' | cut -d'"' -f4)
echo ""
if [ -n "$CURRENT_EBS" ]; then
    echo "   Current EBS URL: $CURRENT_EBS"
else
    echo "   Current EBS URL: (not set)"
fi

# ── Step 4: prompt for new EBS URL ────────────────────────────────────────────

if [ -n "$EBS_URL" ]; then
    validate_url "$EBS_URL" || exit 1
else
    prompt EBS_URL \
        "New EBS URL" \
        "The public HTTPS URL of the Fantasy League backend (no trailing slash).
   Example: https://fantasyleague.makkis.life" \
        validate_url
fi

# Regenerate JWT in case TTL elapsed during prompts.
JWT=$(make_jwt "$TWITCH_EXT_SECRET" "$TWITCH_OWNER_USER_ID" 2>/dev/null)

# ── Step 5: set the new EBS URL ───────────────────────────────────────────────

echo ""
echo "Setting EBS URL to: $EBS_URL"

CONTENT=$(printf '{"ebs_url":"%s"}' "$EBS_URL")
BODY=$(printf '{"extension_id":"%s","segment":"global","content":"%s"}' \
        "$TWITCH_CLIENT_ID" \
        "$(echo "$CONTENT" | sed 's/"/\\"/g')")

$DEBUG && echo "[debug] PUT body: $BODY"

RESPONSE=$(curl -s -w "\n%{http_code}" -X PUT "https://api.twitch.tv/helix/extensions/configurations" \
    -H "Authorization: Bearer ${JWT}" \
    -H "Client-Id: ${TWITCH_CLIENT_ID}" \
    -H "Content-Type: application/json" \
    -d "$BODY")

HTTP_BODY=$(echo "$RESPONSE" | head -n -1)
HTTP_CODE=$(echo "$RESPONSE" | tail -n 1)

$DEBUG && echo "[debug] PUT response (${HTTP_CODE}): $HTTP_BODY"

if [ "$HTTP_CODE" = "204" ]; then
    echo ""
    echo "Done. EBS URL set to: $EBS_URL"
    echo "The extension will pick up the new URL on next load — no rebuild needed."
else
    echo "ERROR: Twitch API returned HTTP $HTTP_CODE"
    [ -n "$HTTP_BODY" ] && echo "$HTTP_BODY"
    exit 1
fi
