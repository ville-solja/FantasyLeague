"""
Run: python debug_jwt.py

Paste a fresh JWT (from DevTools → Network → Authorization header, strip "Bearer ")
and the TWITCH_EXTENSION_SECRET from the .env on the server.
"""
import base64
import sys

try:
    import jwt as pyjwt
except ImportError:
    print("pip install PyJWT>=2.9")
    sys.exit(1)

# ── Paste values here ──────────────────────────────────────────────────────────
SECRET = "PASTE_EXTENSION_SECRET_HERE"   # Extension Secrets tab → Key column
TOKEN  = "PASTE_JWT_HERE"                # strip "Bearer " prefix
# ──────────────────────────────────────────────────────────────────────────────

def try_decode(label, secret_bytes):
    try:
        payload = pyjwt.decode(TOKEN, secret_bytes, algorithms=["HS256"])
        print(f"  ✓ {label}: VALID  exp={payload.get('exp')}  role={payload.get('role')}")
        return True
    except pyjwt.ExpiredSignatureError:
        print(f"  ✗ {label}: EXPIRED (token exp is in the past — get a fresher JWT)")
    except pyjwt.InvalidSignatureError:
        print(f"  ✗ {label}: WRONG SIGNATURE (secret doesn't match)")
    except pyjwt.InvalidTokenError as e:
        print(f"  ✗ {label}: {e}")
    except Exception as e:
        print(f"  ✗ {label}: unexpected error — {e}")
    return False

print(f"\nSecret length   : {len(SECRET)} chars")
padded = SECRET + "=" * (-len(SECRET) % 4)

try:
    b1 = base64.b64decode(padded)
    print(f"b64decode       : {len(b1)} bytes  first={b1[:4].hex()}")
except Exception as e:
    print(f"b64decode       : FAILED — {e}")
    b1 = None

try:
    b2 = base64.urlsafe_b64decode(padded)
    print(f"urlsafe_b64     : {len(b2)} bytes  first={b2[:4].hex()}")
except Exception as e:
    print(f"urlsafe_b64     : FAILED — {e}")
    b2 = None

if b1 == b2:
    print("(both decode methods produce identical bytes — no URL-safe chars in secret)")
else:
    print("*** b64decode and urlsafe_b64decode differ — secret contains - or _ chars ***")

print("\nJWT verification:")
if b1: try_decode("b64decode   (old server code)", b1)
if b2: try_decode("urlsafe_b64 (new server code)", b2)
