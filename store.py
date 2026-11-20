"""Data storage. Two interchangeable back-ends with the same methods:

* LocalStore    - JSON files + a local folder (used when Supabase is not configured;
                  perfect for running on your own computer, fully offline).
* SupabaseStore - free Postgres tables + file Storage (used in the cloud, so data
                  survives restarts/deploys and is shared by every student).

Only the Python standard library is used (urllib), so nothing extra to install.
"""
import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid

from core import (BASE_DIR, CONTENT_TYPES, UNIVERSITIES, hash_password, now,
                  valid_identifier)

SEED_ITEMS = [
    ("MCA", "1st Semester", "Programming in C", "PYQs", "Programming in C - PYQ 2024"),
    ("MCA", "1st Semester", "Discrete Mathematics", "Study Notes", "Discrete Mathematics - Unit 1 Notes"),
    ("MCA", "1st Semester", "Computer Organization", "PPTX", "Computer Organization - Lecture 1 (sample)"),
    ("MSW", "1st Semester", "Social Work Profession", "Study Notes", "Introduction to Social Work Notes"),
    ("Masters of Psychology", "1st Semester", "Cognitive Psychology", "Study Notes", "Cognitive Psychology - Basics"),
]


def make_pdf(title, lines):
    """Return bytes of a tiny valid one-page PDF (used for sample data)."""
    def esc(s):
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content = "BT /F1 20 Tf 60 780 Td (%s) Tj ET\n" % esc(title)
    y = 740
    for line in lines:
        content += "BT /F1 12 Tf 60 %d Td (%s) Tj ET\n" % (y, esc(line))
        y -= 22
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        "<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content),
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += ("%d 0 obj\n%s\nendobj\n" % (i, o)).encode("latin-1")
    xref = len(out)
    out += ("xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)).encode()
    for off in offsets:
        out += ("%010d 00000 n \n" % off).encode()
    out += ("trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF"
            % (len(objs) + 1, xref)).encode()
    return out


def content_type_for(name):
    return CONTENT_TYPES.get(os.path.splitext(name)[1].lower(), "application/octet-stream")


# =============================================================================
class LocalStore:
    kind = "local (JSON files)"

    def __init__(self, data_dir=None):
        self.dir = data_dir or os.environ.get("UC_DATA_DIR") or os.path.join(BASE_DIR, "data")
        self.upload_dir = os.path.join(self.dir, "uploads")
        self.users_file = os.path.join(self.dir, "users.json")
        self.materials_file = os.path.join(self.dir, "materials.json")
        self._lock = threading.Lock()

    # -- helpers
    def _read(self, path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _write(self, path, data):
        with self._lock:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, path)

    # -- setup
    def init(self):
        os.makedirs(self.upload_dir, exist_ok=True)
        if not os.path.exists(self.users_file):
            self._write(self.users_file, [
                {"identifier": "Admin@gmail.com", "password": hash_password("Admin@123"),
                 "role": "admin", "created_at": now()},
                {"identifier": "Student@gmail.com", "password": hash_password("Student@123"),
                 "role": "student", "created_at": now()},
            ])
        if not os.path.exists(self.materials_file):
            items = []
            for uni in UNIVERSITIES:
                for course, sem, subject, cat, title in SEED_ITEMS:
                    mid = uuid.uuid4().hex[:10]
                    fname = "sample_%s_%s.pdf" % ("".join(c for c in uni["id"] if c.isalnum()), mid)
                    pdf = make_pdf(title, ["University: " + uni["id"], "Course: %s / %s" % (course, sem),
                                           "Subject: " + subject, "Section: " + cat, "",
                                           "This is a sample file. Admin can upload real",
                                           "material from the Admin panel."])
                    with open(os.path.join(self.upload_dir, fname), "wb") as f:
                        f.write(pdf)
                    items.append({"id": mid, "university": uni["id"], "course": course,
                                  "semester": sem, "subject": subject, "category": cat,
                                  "title": title, "file_path": fname, "uploaded_at": now()})
            self._write(self.materials_file, items)

    # -- users
    def get_user(self, ident):
        for u in self._read(self.users_file):
            if u["identifier"] == ident:  # case-sensitive
                return u
        return None

    def add_user(self, user):
        users = self._read(self.users_file)
        if any(u["identifier"] == user["identifier"] for u in users):
            return False
        users.append(user)
        self._write(self.users_file, users)
        return True

    def count_users(self):
        return len(self._read(self.users_file))

    # -- materials
    def list_materials(self):
        return sorted(self._read(self.materials_file), key=lambda m: m["uploaded_at"], reverse=True)

    def add_material(self, meta, filename, data):
        os.makedirs(self.upload_dir, exist_ok=True)
        with open(os.path.join(self.upload_dir, filename), "wb") as f:
            f.write(data)
        meta = dict(meta, file_path=filename)
        items = self._read(self.materials_file)
        items.append(meta)
        self._write(self.materials_file, items)

    def delete_material(self, mid):
        items = self._read(self.materials_file)
        keep = []
        for m in items:
            if m["id"] == mid:
                p = os.path.join(self.upload_dir, m["file_path"])
                if os.path.exists(p):
                    os.remove(p)
            else:
                keep.append(m)
        self._write(self.materials_file, keep)

    def read_file(self, name):
        p = os.path.join(self.upload_dir, name)
        if not os.path.isfile(p):
            return None
        with open(p, "rb") as f:
            return f.read(), content_type_for(name)


# =============================================================================
class StoreError(Exception):
    pass


class SupabaseStore:
    """Talks to Supabase over plain HTTPS (PostgREST + Storage). Needs the two
    tables and the public bucket from supabase/schema.sql."""
    kind = "Supabase (cloud database + file storage)"

    def __init__(self, url, key, bucket="materials"):
        self.url = url.rstrip("/")
        self.key = key
        self.bucket = bucket

    def _req(self, method, path, params=None, body=None, headers=None):
        url = self.url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        h = {"apikey": self.key, "Authorization": "Bearer " + self.key}
        h.update(headers or {})
        data = body
        if isinstance(body, (dict, list)):
            data = json.dumps(body).encode()
            h.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(url, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers)
        except urllib.error.URLError as e:
            raise StoreError("Cannot reach Supabase: %s" % e.reason)

    def _json(self, status, body, ok=(200, 201, 204)):
        if status not in ok:
            raise StoreError("Supabase error %s: %s" % (status, body[:300].decode("utf-8", "replace")))
        return json.loads(body) if body else None

    def _obj(self, name):
        return "/storage/v1/object/%s/%s" % (self.bucket, urllib.parse.quote(name))

    def init(self):
        """Create the first admin from ADMIN_IDENTIFIER / ADMIN_PASSWORD if there are no users."""
        if self.count_users() > 0:
            return
        ident = os.environ.get("ADMIN_IDENTIFIER", "").strip()
        pw = os.environ.get("ADMIN_PASSWORD", "")
        if valid_identifier(ident) and len(pw) >= 6:
            self.add_user({"identifier": ident, "password": hash_password(pw),
                           "role": "admin", "created_at": now()})
            print("Created first admin:", ident)
        else:
            print("WARNING: no users yet and ADMIN_IDENTIFIER / ADMIN_PASSWORD are not set "
                  "(or invalid). Set them and restart to create the first admin.")

    def count_users(self):
        s, b, _ = self._req("GET", "/rest/v1/users", {"select": "identifier", "limit": "1"})
        return len(self._json(s, b))

    def get_user(self, ident):
        s, b, _ = self._req("GET", "/rest/v1/users",
                            {"select": "*", "identifier": "eq." + ident, "limit": "1"})
        rows = self._json(s, b)
        return rows[0] if rows and rows[0]["identifier"] == ident else None

    def add_user(self, user):
        s, b, _ = self._req("POST", "/rest/v1/users", body=user,
                            headers={"Prefer": "return=minimal"})
        if s == 409:
            return False
        self._json(s, b)
        return True

    def list_materials(self):
        s, b, _ = self._req("GET", "/rest/v1/materials",
                            {"select": "*", "order": "uploaded_at.desc"})
        return self._json(s, b)

    def add_material(self, meta, filename, data):
        s, b, _ = self._req("POST", self._obj(filename), body=data,
                            headers={"Content-Type": content_type_for(filename)})
        self._json(s, b)
        meta = dict(meta, file_path=filename)
        s, b, _ = self._req("POST", "/rest/v1/materials", body=meta,
                            headers={"Prefer": "return=minimal"})
        if s not in (200, 201, 204):  # roll back the uploaded file
            self._req("DELETE", self._obj(filename))
            self._json(s, b)

    def delete_material(self, mid):
        s, b, _ = self._req("GET", "/rest/v1/materials", {"select": "file_path", "id": "eq." + mid})
        rows = self._json(s, b)
        s, b, _ = self._req("DELETE", "/rest/v1/materials", {"id": "eq." + mid})
        self._json(s, b)
        for r in rows or []:
            self._req("DELETE", self._obj(r["file_path"]))

    def read_file(self, name):
        s, b, h = self._req("GET", "/storage/v1/object/public/%s/%s"
                            % (self.bucket, urllib.parse.quote(name)))
        if s != 200:
            return None
        return b, content_type_for(name)


def get_store():
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
    if url and key:
        return SupabaseStore(url, key, os.environ.get("SUPABASE_BUCKET", "materials"))
    return LocalStore()
