#!/usr/bin/env python3
"""
Update VPN configs from publicvpnlist.com
"""
import os
import re
import sys
import json
import time
import urllib.request
import urllib.parse
import urllib.error


COUNTRY = "usa"
MAX_NODES = 10
BASE_URL = "https://publicvpnlist.com"


def http_get(url, headers=None):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="replace")


def http_post(url, data, headers=None):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode())
    req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read()


def get_server_ids():
    """Scrape the country page to get server IDs with speed data"""
    print(f"📡 Scraping {COUNTRY.upper()} servers...")
    html = http_get(f"{BASE_URL}/country/{COUNTRY}/")

    # Find all server entries from the download links
    # Format: <a href="/download/12345/" data-action="dl" data-id="12345"
    #   data-download-speed="0.5" data-download-latency="281" data-download-proto="TCP"
    #   data-download-port="1717" data-download-host="host" ...>
    pattern = r'/download/(\d+)/"[^>]*data-download-host="([^"]*)"[^>]*data-download-speed="([^"]*)"[^>]*data-download-latency="([^"]*)"[^>]*data-download-proto="([^"]*)"[^>]*data-download-port="([^"]*)"'
    servers = []
    for match in re.finditer(pattern, html):
        server_id = int(match.group(1))
        host = match.group(2)
        speed = float(match.group(3)) if match.group(3) else 0
        latency = int(match.group(4)) if match.group(4) else 9999
        proto = match.group(5).lower()
        port = match.group(6)
        servers.append({
            "id": server_id,
            "host": host,
            "speed": speed,
            "latency": latency,
            "proto": proto,
            "port": port,
        })

    # Dedup by server ID, keep first occurrence (highest in HTML = best)
    seen = set()
    unique = []
    for s in servers:
        if s["id"] not in seen:
            seen.add(s["id"])
            unique.append(s)

    # Sort by speed (descending), then by latency (ascending)
    unique.sort(key=lambda s: (-s["speed"], s["latency"]))
    print(f"   Found {len(unique)} unique servers, taking top {MAX_NODES}")
    return unique[:MAX_NODES]


def download_config(server_id):
    """Get download token and download OVPN config"""
    # Step 1: Get token
    headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "Referer": f"{BASE_URL}/download/{server_id}/",
    }
    resp = http_post(f"{BASE_URL}/get_token.php", {"id": server_id}, headers)
    data = json.loads(resp.decode())
    token = data.get("token")
    if not token:
        print(f"  ❌ No token for {server_id}: {data}")
        return None

    # Step 2: Download config
    dl_url = f"{BASE_URL}/download.php?token={token}"
    dl_headers = {"Accept": "application/x-openvpn-profile, application/octet-stream;q=0.9"}
    
    req = urllib.request.Request(dl_url)
    req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    for k, v in dl_headers.items():
        req.add_header(k, v)
    
    with urllib.request.urlopen(req, timeout=15) as resp:
        content = resp.read().decode("utf-8", errors="replace")

    if len(content) < 100:
        print(f"  ❌ Download too small for {server_id}: {len(content)} bytes")
        return None

    return content


def main():
    servers = get_server_ids()

    os.makedirs("configs", exist_ok=True)
    downloaded = 0

    for srv in servers:
        sid = srv["id"]
        host = srv["host"]
        proto = srv["proto"]
        port = srv["port"]
        speed = srv["speed"]
        latency = srv["latency"]

        print(f"\n📄 Server {sid}: {host} ({proto} {port}, {speed} Mbps, {latency}ms)")
        config = download_config(sid)
        if not config:
            continue

        # Name the file: country-ip-proto-port.ovpn
        filename = f"{COUNTRY}-{host}-{proto}{port}-{speed:.1f}Mbps.ovpn"
        filepath = os.path.join("configs", filename)
        with open(filepath, "w") as f:
            f.write(config)
        print(f"   ✅ Saved: {filename} ({len(config)} bytes)")
        downloaded += 1

        # Be nice to the server
        time.sleep(1)

    print(f"\n{'='*50}")
    print(f"✅ Downloaded {downloaded}/{len(servers)} configs")
    print(f"📁 Output: configs/")

    if downloaded == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()