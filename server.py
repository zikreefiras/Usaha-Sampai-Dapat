import contextlib
import hashlib
import http.cookies
import json
import os
import re
import secrets
import sqlite3
import time
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
PORT = 8000
COOKIE_NAME = "sinca_session"
SESSION_SECONDS = 14 * 24 * 60 * 60
PASSWORD_ITERATIONS = 310_000
APP_DATA = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "SINCA"
DB_PATH = Path(os.environ.get("SINCA_DB_PATH", APP_DATA / "game-saves.sqlite3"))
ALLOWED_ORIGINS = {"http://localhost:8000", "http://127.0.0.1:8000"}
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/game-save-extension.js": ("game-save-extension.js", "text/javascript; charset=utf-8"),
    "/gameThumbnail/SINCA.png": ("gameThumbnail/SINCA.png", "image/png"),
}


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


@contextlib.contextmanager
def database():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database():
    with database() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                salt BLOB NOT NULL,
                password_hash BLOB NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS progress (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                money TEXT NOT NULL DEFAULT '0',
                level INTEGER NOT NULL DEFAULT 0,
                device TEXT NOT NULL DEFAULT '2',
                updated_at TEXT NOT NULL
            );
            """
        )


def password_digest(password, salt):
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )


def token_digest(token):
    return hashlib.sha256(token.encode("ascii")).hexdigest()


class LauncherHandler(BaseHTTPRequestHandler):
    server_version = "SINCA/1.0"

    def _send_json(self, status, payload, headers=None):
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if headers:
            for name, value in headers:
                self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, error):
        self._send_json(error.status, {"error": error.message})

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ApiError(400, "Invalid request size.")
        if length < 1 or length > 16_384:
            raise ApiError(400, "Invalid request size.")
        try:
            value = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ApiError(400, "Invalid JSON.")
        if not isinstance(value, dict):
            raise ApiError(400, "Expected a JSON object.")
        return value

    def _require_same_origin(self):
        if self.headers.get("Origin") not in ALLOWED_ORIGINS:
            raise ApiError(403, "Request origin was not accepted.")

    def _session_user(self):
        cookie_header = self.headers.get("Cookie", "")
        cookies = http.cookies.SimpleCookie()
        try:
            cookies.load(cookie_header)
        except http.cookies.CookieError:
            return None
        morsel = cookies.get(COOKIE_NAME)
        if not morsel:
            return None

        with database() as connection:
            row = connection.execute(
                """
                SELECT users.id, users.username
                FROM sessions
                JOIN users ON users.id = sessions.user_id
                WHERE sessions.token_hash = ? AND sessions.expires_at > ?
                """,
                (token_digest(morsel.value), int(time.time())),
            ).fetchone()
            connection.execute(
                "DELETE FROM sessions WHERE expires_at <= ?", (int(time.time()),)
            )
        return row

    def _require_user(self):
        user = self._session_user()
        if user is None:
            raise ApiError(401, "Please sign in to continue.")
        return user

    def _issue_session(self, user_id):
        token = secrets.token_urlsafe(32)
        expires_at = int(time.time()) + SESSION_SECONDS
        with database() as connection:
            connection.execute(
                "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                (token_digest(token), user_id, expires_at),
            )
        cookie = (
            f"{COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Strict; "
            f"Max-Age={SESSION_SECONDS}"
        )
        return [("Set-Cookie", cookie)]

    def do_GET(self):
        path = urlparse(self.path).path
        try:
            if path == "/api/me":
                user = self._session_user()
                if user is None:
                    self._send_json(401, {"error": "Please sign in."})
                else:
                    self._send_json(200, {"username": user["username"]})
                return

            if path == "/api/progress":
                user = self._require_user()
                with database() as connection:
                    row = connection.execute(
                        "SELECT money, level, device, updated_at FROM progress WHERE user_id = ?",
                        (user["id"],),
                    ).fetchone()
                if row is None:
                    raise ApiError(404, "Save data was not found.")
                self._send_json(
                    200,
                    {
                        "money": row["money"],
                        "level": row["level"],
                        "device": row["device"],
                        "updatedAt": row["updated_at"],
                    },
                )
                return

            static_file = STATIC_FILES.get(path)
            if static_file is None:
                raise ApiError(404, "Not found.")
            relative_path, content_type = static_file
            file_path = ROOT / relative_path
            if not file_path.is_file():
                raise ApiError(404, "File not found.")
            body = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except ApiError as error:
            self._send_error_json(error)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            self._require_same_origin()
            body = self._read_json()

            if path == "/api/register":
                username = body.get("username")
                password = body.get("password")
                if not isinstance(username, str) or not re.fullmatch(
                    r"[A-Za-z0-9_.-]{3,32}", username
                ):
                    raise ApiError(
                        400, "Username must be 3-32 letters, numbers, dots, dashes, or underscores."
                    )
                if not isinstance(password, str) or not 8 <= len(password) <= 256:
                    raise ApiError(400, "Password must be 8–256 characters.")

                salt = secrets.token_bytes(16)
                digest = password_digest(password, salt)
                try:
                    with database() as connection:
                        cursor = connection.execute(
                            "INSERT INTO users (username, salt, password_hash, created_at) VALUES (?, ?, ?, ?)",
                            (username, salt, digest, int(time.time())),
                        )
                        user_id = cursor.lastrowid
                        connection.execute(
                            "INSERT INTO progress (user_id, updated_at) VALUES (?, ?)",
                            (user_id, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
                        )
                except sqlite3.IntegrityError:
                    raise ApiError(409, "That username is already in use.")
                self._send_json(
                    201,
                    {"username": username},
                    self._issue_session(user_id),
                )
                return

            if path == "/api/login":
                username = body.get("username")
                password = body.get("password")
                if not isinstance(username, str) or not isinstance(password, str):
                    raise ApiError(400, "Enter a username and password.")
                with database() as connection:
                    user = connection.execute(
                        "SELECT id, username, salt, password_hash FROM users WHERE username = ?",
                        (username,),
                    ).fetchone()
                if user is None or not secrets.compare_digest(
                    password_digest(password, user["salt"]), user["password_hash"]
                ):
                    raise ApiError(401, "Username or password is incorrect.")
                self._send_json(
                    200,
                    {"username": user["username"]},
                    self._issue_session(user["id"]),
                )
                return

            if path == "/api/logout":
                user = self._require_user()
                cookie_header = self.headers.get("Cookie", "")
                cookies = http.cookies.SimpleCookie()
                cookies.load(cookie_header)
                token = cookies.get(COOKIE_NAME)
                if token:
                    with database() as connection:
                        connection.execute(
                            "DELETE FROM sessions WHERE token_hash = ?",
                            (token_digest(token.value),),
                        )
                clear_cookie = (
                    f"{COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"
                )
                self._send_json(200, {"ok": True}, [("Set-Cookie", clear_cookie)])
                return

            raise ApiError(404, "Not found.")
        except ApiError as error:
            self._send_error_json(error)

    def do_PUT(self):
        try:
            self._require_same_origin()
            if urlparse(self.path).path != "/api/progress":
                raise ApiError(404, "Not found.")
            user = self._require_user()
            body = self._read_json()

            try:
                money = Decimal(str(body["money"]))
                level = int(body["level"])
            except (KeyError, ValueError, TypeError, InvalidOperation):
                raise ApiError(400, "Money and level must be valid numbers.")
            device = str(body.get("device", ""))
            if not money.is_finite() or money < 0 or money > Decimal("1e18"):
                raise ApiError(400, "Money is outside the supported range.")
            if isinstance(body.get("level"), bool) or level < 0 or level > 1_000_000:
                raise ApiError(400, "Level is outside the supported range.")
            if device not in {"1", "2"}:
                raise ApiError(400, "Device must be 1 or 2.")

            money_value = format(money.normalize(), "f")
            if "." in money_value:
                money_value = money_value.rstrip("0").rstrip(".")
            if not money_value:
                money_value = "0"
            updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            with database() as connection:
                connection.execute(
                    """
                    UPDATE progress
                    SET money = ?, level = ?, device = ?, updated_at = ?
                    WHERE user_id = ?
                    """,
                    (money_value, level, device, updated_at, user["id"]),
                )
            self._send_json(
                200,
                {
                    "money": money_value,
                    "level": level,
                    "device": device,
                    "updatedAt": updated_at,
                },
            )
        except ApiError as error:
            self._send_error_json(error)

    def log_message(self, format_string, *args):
        print("%s - %s" % (self.address_string(), format_string % args))


def main():
    initialize_database()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), LauncherHandler)
    print(f"SINCA launcher listening at http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping SINCA launcher.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
