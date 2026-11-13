"""Private storage on Google Drive: conversation logs and uploads. Never stored in the public repo.

Auth (pick one):
  * Service account: GDRIVE_SA_JSON (JSON key contents). The folder must be in a *Shared Drive*
    (service accounts have no My-Drive storage quota) and shared with the SA email.
  * OAuth (personal My Drive): GDRIVE_CLIENT_ID, GDRIVE_CLIENT_SECRET, GDRIVE_REFRESH_TOKEN.
GDRIVE_FOLDER_ID = id of the root folder for tinybrains data.

Layout under the root folder:
  conversations/<YYYY-MM-DD>/<timestamp>-<kind>.json   one file per event (no read-modify-write races)
  uploads/<topic-id>/<filename>                        raw uploaded files
"""
from __future__ import annotations

import io
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from .settings import env

log = logging.getLogger("tb.drive")
FOLDER = "application/vnd.google-apps.folder"
SCOPES = ["https://www.googleapis.com/auth/drive"]


class Drive:
    def __init__(self):
        self.root = env("GDRIVE_FOLDER_ID")
        self.svc = None
        self._cache: dict[tuple[str, str], str] = {}
        if not self.root:
            log.info("Google Drive not configured (GDRIVE_FOLDER_ID unset) - private data will not be persisted")
            return
        creds = None
        if env("GDRIVE_SA_JSON"):
            from google.oauth2 import service_account
            creds = service_account.Credentials.from_service_account_info(json.loads(env("GDRIVE_SA_JSON")), scopes=SCOPES)
        elif env("GDRIVE_REFRESH_TOKEN"):
            from google.oauth2.credentials import Credentials
            creds = Credentials(None, refresh_token=env("GDRIVE_REFRESH_TOKEN"), client_id=env("GDRIVE_CLIENT_ID"),
                                client_secret=env("GDRIVE_CLIENT_SECRET"), token_uri="https://oauth2.googleapis.com/token",
                                scopes=SCOPES)
        if creds is None:
            log.warning("GDRIVE_FOLDER_ID set but no credentials - Drive disabled")
            return
        from googleapiclient.discovery import build
        self.svc = build("drive", "v3", credentials=creds, cache_discovery=False)

    @property
    def enabled(self) -> bool:
        return self.svc is not None

    # ---- helpers
    def _q(self, q: str) -> list[dict[str, Any]]:
        out, token = [], None
        while True:
            r = self.svc.files().list(q=q, fields="nextPageToken, files(id,name,mimeType,createdTime)", pageToken=token,
                                      supportsAllDrives=True, includeItemsFromAllDrives=True, pageSize=200).execute()
            out += r.get("files", [])
            token = r.get("nextPageToken")
            if not token:
                return out

    def _child(self, parent: str, name: str, create: bool) -> str | None:
        key = (parent, name)
        if key in self._cache:
            return self._cache[key]
        safe = name.replace("'", "\\'")
        hits = self._q(f"'{parent}' in parents and name = '{safe}' and mimeType = '{FOLDER}' and trashed = false")
        if hits:
            fid = hits[0]["id"]
        elif create:
            fid = self.svc.files().create(body={"name": name, "mimeType": FOLDER, "parents": [parent]}, fields="id",
                                          supportsAllDrives=True).execute()["id"]
        else:
            return None
        self._cache[key] = fid
        return fid

    def folder(self, path: str, create: bool = True) -> str | None:
        cur = self.root
        for part in [p for p in path.split("/") if p]:
            cur = self._child(cur, part, create)
            if cur is None:
                return None
        return cur

    # ---- public API
    def upload(self, path: str, name: str, data: bytes, mime: str = "application/octet-stream") -> str | None:
        if not self.enabled:
            return None
        from googleapiclient.http import MediaIoBaseUpload
        parent = self.folder(path)
        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime, resumable=False)
        return self.svc.files().create(body={"name": name, "parents": [parent]}, media_body=media, fields="id",
                                       supportsAllDrives=True).execute()["id"]

    def log_event(self, kind: str, payload: dict[str, Any]) -> None:
        """Append a conversation event (inbound message, bot reply, agent note)."""
        if not self.enabled:
            return
        now = datetime.now(timezone.utc)
        body = json.dumps({"at": now.isoformat(), "kind": kind, **payload}, ensure_ascii=False).encode()
        try:
            self.upload(f"conversations/{now:%Y-%m-%d}", f"{now:%H%M%S%f}-{kind}.json", body, "application/json")
        except Exception as e:  # noqa: BLE001 - logging must never break a run
            log.warning("drive log failed: %s", type(e).__name__)

    def list(self, path: str) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        fid = self.folder(path, create=False)
        return self._q(f"'{fid}' in parents and trashed = false") if fid else []

    def download(self, file_id: str) -> bytes:
        from googleapiclient.http import MediaIoBaseDownload
        buf = io.BytesIO()
        dl = MediaIoBaseDownload(buf, self.svc.files().get_media(fileId=file_id, supportsAllDrives=True))
        done = False
        while not done:
            _, done = dl.next_chunk()
        return buf.getvalue()

    def delete_path(self, path: str) -> bool:
        """Permanently delete a folder (e.g. uploads/T003) once its post is generated/published."""
        if not self.enabled:
            return False
        fid = self.folder(path, create=False)
        if not fid:
            return False
        self.svc.files().delete(fileId=fid, supportsAllDrives=True).execute()
        self._cache = {k: v for k, v in self._cache.items() if v != fid}
        return True

    def purge_conversations(self, older_than_days: int) -> int:
        if not self.enabled:
            return 0
        conv = self.folder("conversations", create=False)
        if not conv:
            return 0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).strftime("%Y-%m-%d")
        n = 0
        for f in self._q(f"'{conv}' in parents and mimeType = '{FOLDER}' and trashed = false"):
            if f["name"] < cutoff:
                self.svc.files().delete(fileId=f["id"], supportsAllDrives=True).execute()
                n += 1
        return n
