"""Download a spreadsheet from a link: Google Sheets share links, OneDrive/Dropbox direct links or any public
https URL to a .csv / .xlsx / .xls file.

Safety: https only, no credentials in the URL, every hop (including redirects) must resolve to a public IP
address, at most 4 redirects, a size cap equal to the upload limit and a total timeout.
"""
from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse, urlunparse

import httpx

MAX_REDIRECTS = 4
TIMEOUT_SECONDS = 25
GSHEET_RE = re.compile(r"^/spreadsheets/d/([A-Za-z0-9_-]{20,})")
TYPES = {"text/csv": "csv", "application/csv": "csv", "text/plain": "csv",
         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
         "application/vnd.ms-excel": "xls"}


class FetchError(Exception):
    def __init__(self, message: str, code: str = "fetch_failed"):
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass
class Fetched:
    data: bytes
    file_type: str
    filename: str
    source_url: str        # the link as the user gave it (normalised), used for refresh
    download_url: str


def normalize(url: str) -> tuple[str, str, str | None]:
    """Returns (source url, download url, filename hint). Google Sheets links become CSV exports of the tab."""
    url = url.strip()
    p = urlparse(url)
    if p.scheme != "https":
        raise FetchError("Use an https:// link.", "invalid_url")
    if p.username or p.password:
        raise FetchError("Links with a user name or password are not accepted.", "invalid_url")
    if not p.hostname:
        raise FetchError("This is not a valid link.", "invalid_url")
    host = p.hostname.lower()
    if host == "docs.google.com":
        m = GSHEET_RE.match(p.path)
        if not m:
            raise FetchError("This Google link is not a spreadsheet. Open the sheet and copy the link from the address bar.", "invalid_url")
        gid = (parse_qs(p.query).get("gid") or parse_qs(p.fragment).get("gid") or ["0"])[0]
        if not gid.isdigit():
            gid = "0"
        download = f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=csv&gid={gid}"
        return download, download, "google_sheet.csv"
    if host.endswith("dropbox.com"):
        q = parse_qs(p.query)
        q["dl"] = ["1"]
        query = "&".join(f"{k}={v[0]}" for k, v in q.items())
        download = urlunparse(p._replace(query=query))
        return url, download, None
    return url, url, None


def _check_host(host: str) -> None:
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise FetchError(f"Could not find the server '{host}'.", "unreachable")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or ip.is_multicast:
            raise FetchError("Links to private, local or internal addresses are not allowed.", "blocked_address")


def _filename_from(resp: httpx.Response, url: str, hint: str | None) -> str:
    cd = resp.headers.get("content-disposition", "")
    m = re.search(r"filename\*=UTF-8''([^;]+)|filename=\"?([^\";]+)\"?", cd)
    if m:
        from urllib.parse import unquote
        return unquote(m.group(1) or m.group(2)).strip()
    if hint:
        return hint
    name = urlparse(url).path.rsplit("/", 1)[-1]
    return name or "download"


def _file_type(name: str, content_type: str, data: bytes) -> str:
    ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    if ext in ("csv", "xlsx", "xls"):
        return ext
    ct = content_type.split(";")[0].strip().lower()
    if data[:4] == b"PK\x03\x04":
        return "xlsx"
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "xls"
    if ct in TYPES:
        return TYPES[ct]
    if ct == "text/html" or data.lstrip()[:15].lower().startswith((b"<!doctype", b"<html")):
        raise FetchError("The link opened a web page, not a file. Make the file public (anyone with the link can view) "
                         "or use a direct download link.", "not_a_file")
    raise FetchError("The link did not return a .csv, .xlsx or .xls file.", "unsupported_type")


async def fetch(url: str, max_bytes: int) -> Fetched:
    source, current, hint = normalize(url)
    async with httpx.AsyncClient(follow_redirects=False, timeout=httpx.Timeout(TIMEOUT_SECONDS),
                                 headers={"User-Agent": "DataAnalyst/1.0 (+spreadsheet import)"}) as client:
        for _ in range(MAX_REDIRECTS + 1):
            p = urlparse(current)
            if p.scheme != "https" or not p.hostname:
                raise FetchError("The link redirected to an address that is not https.", "invalid_url")
            await asyncio.to_thread(_check_host, p.hostname)
            try:
                async with client.stream("GET", current) as resp:
                    if resp.is_redirect:
                        current = str(resp.url.join(resp.headers.get("location", "")))
                        continue
                    if resp.status_code in (401, 403):
                        raise FetchError("The file is not public. Share it so that anyone with the link can view it.", "not_public")
                    if resp.status_code == 404:
                        raise FetchError("Nothing was found at this link.", "not_found")
                    if resp.status_code >= 400:
                        raise FetchError(f"The server answered with an error ({resp.status_code}).", "fetch_failed")
                    declared = int(resp.headers.get("content-length") or 0)
                    if declared > max_bytes:
                        raise FetchError(f"The file is larger than the {max_bytes // (1024 * 1024)} MB limit.", "too_large")
                    buf = bytearray()
                    async for chunk in resp.aiter_bytes():
                        buf.extend(chunk)
                        if len(buf) > max_bytes:
                            raise FetchError(f"The file is larger than the {max_bytes // (1024 * 1024)} MB limit.", "too_large")
                    data = bytes(buf)
                    name = _filename_from(resp, current, hint)
                    ftype = _file_type(name, resp.headers.get("content-type", ""), data)
                    if not name.lower().endswith(f".{ftype}"):
                        name = f"{name.rsplit('.', 1)[0] if '.' in name else name}.{ftype}"
                    return Fetched(data, ftype, name, source, current)
            except httpx.TimeoutException:
                raise FetchError("The server took too long to send the file.", "timeout")
            except httpx.HTTPError:
                raise FetchError("Could not download the file from this link.", "fetch_failed")
        raise FetchError("The link redirected too many times.", "fetch_failed")
