"""Shared settings, catalog (universities/courses), validators and password hashing."""
import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime

APP_NAME = "University Club"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAX_UPLOAD = 25 * 1024 * 1024  # 25 MB per file
ALLOWED_EXT = {".pdf", ".pptx", ".docx", ".doc"}
CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
}

# ---- Catalog: add more universities / courses here -------------------------
UNIVERSITIES = [
    {"id": "MGAHV", "name": "Mahatma Gandhi Antarrashtriya Hindi Vishwavidyalaya",
     "city": "Wardha, Maharashtra"},
    {"id": "DHSGU", "name": "Dr. Harisingh Gour Vishwavidyalaya",
     "city": "Sagar, Madhya Pradesh"},
    {"id": "University of South Bihar",
     "name": "Central University of South Bihar (CUSB)", "city": "Gaya, Bihar"},
]
COURSES = ["MCA", "MSW", "Masters of Psychology"]
SEMESTERS = ["1st Semester", "2nd Semester", "3rd Semester", "4th Semester"]
CATEGORIES = ["PYQs", "Study Notes", "PPTX"]

EMAIL_RE = re.compile(
    r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.(com|ac\.in|edu\.in)$")
MOBILE_RE = re.compile(r"^[6-9]\d{9}$")
FILENAME_RE = re.compile(r"^[A-Za-z0-9._\-]{1,150}$")


def load_env(path=None):
    """Tiny .env loader (no extra package). Real environment variables win."""
    path = path or os.path.join(BASE_DIR, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def valid_identifier(s):
    return bool(EMAIL_RE.match(s) or MOBILE_RE.match(s))


def safe_filename(name):
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.basename(name or "")).lstrip(".")
    return name[-80:] or "file"


# ---- Password hashing (standard library only) ------------------------------
def hash_password(pw, iterations=200_000):
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), iterations).hex()
    return "pbkdf2_sha256$%d$%s$%s" % (iterations, salt, h)


def verify_password(pw, stored):
    try:
        algo, it, salt, h = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        calc = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), int(it)).hex()
        return hmac.compare_digest(calc, h)
    except (ValueError, AttributeError):
        return False
