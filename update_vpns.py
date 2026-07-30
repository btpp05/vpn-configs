#!/usr/bin/env python3
"""
Update VPN configs from publicvpnlist.com - filter for ISP/residential IPs
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

# Known datacenter/cloud providers to exclude
DC_KEYWORDS = [
    "hetzner", "datacamp", "digitalocean", "linode", "vultr", "aws", "amazon",
    "google cloud", "azure", "microsoft", "oracle cloud", "ovh", "scaleway",
    "contabo", "rackspace", "softlayer", "ibm cloud", "alibaba cloud",
    "tencent cloud", "huawei cloud", "upcloud", "profitbricks", "ionos",
    "netcup", "netcologne", "strato", "hostinger", "namecheap", "godaddy",
    "bluehost", "siteground", "dreamhost", "a2hosting", "inmotion",
    "colocrossing", "psychz", "quadranet", "sharktech", "dacentec",
    "choopa", "velocity", "atlantic.net", "leaseweb", "worldstream",
    "nfoservers", "gameservers", "riseup", "tor project",
]

# Known ISP/residential providers to prefer
ISP_KEYWORDS = [
    "comcast", "xfinity", "at&t", "verizon", "charter", "spectrum",
    "cox", "centurylink", "frontier", "windstream", "mediacom",
    "cableone", "suddenlink", "charter", "t-mobile", "sprint",
    "telia", "deutsche telekom", "telefonica", "orange", "bt group",
    "vodafone", "kpn", "swisscom", "telenor", "telia", "elisa",
    "cogeco", "rogers", "bell canada", "shaw", "videotron",
    "optimum", "altice", "wahoo", "wideopenwest",
    "consolidated", "fairpoint", "hughes", "viasat",
    "frankfort plant board", "fewpb",
]


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


def check_ip_type(ip):
    """Check if an IP is ISP/residential or datacenter"""
    try:
        url = f"https://ipinfo.io/{ip}/json"
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "Mozilla/5.0")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        
        org = (data.get("org", "") or "").lower()
        hostname = (data.get("hostname", "") or "").lower()
        text = f"{org} {hostname}"

        # Check if it's a known ISP
        for kw in ISP_KEYWORDS:
            if kw in text:
                return "isp", data.get("org", "?")

        # Check if it's a known datacenter
        for kw in DC_KEYWORDS:
            if kw in text:
                return "dc", data.get("org", "?")

        # If unknown, check by AS number
        asn = data.get("org", "").split()[0] if data.get("org") else ""
        if asn and asn.startswith("AS"):
            as_num = asn[2:]
            # Common residential ASNs
            residential_asns = {"7922", "7018", "701", "6167", "11427", "20115",
                               "33588", "10796", "11351", "12271", "22394",
                               "30036", "33363", "36492", "46887", "30475",
                               "19108", "11426", "6389", "577", "6128", "7015"}
            if as_num in residential_asns:
                return "isp", data.get("org", "?")

        return "unknown", data.get("org", "?")
    except:
        return "error", "timeout"


def get_server_ids():
    """Scrape the country page to get server IDs with speed data"""
    print(f"📡 Scraping {COUNTRY.upper()} servers...")
    html = http_get(f"{BASE_URL}/country/{COUNTRY}/")

    # Find all server entries
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

    # Dedup by server ID
    seen = set()
    unique = []
    for s in servers:
        if s["id"] not in seen:
            seen.add(s["id"])
            unique.append(s)

    print(f"   Found {len(unique)} unique servers, checking IP types...")

    # Check IP type for each server
    for s in unique:
        ip_type, org = check_ip_type(s["host"])
        s["ip_type"] = ip_type
        s["org"] = org
        time.sleep(0.3)  # Rate limit

    # Sort: ISP first, then unknown, then DC, then error
    type_order = {"isp": 0, "unknown": 1, "dc": 2, "error": 3}
    unique.sort(key=lambda s: (type_order.get(s["ip_type"], 9), -s["speed"], s["latency"]))

    # Print summary
    isp_count = sum(1 for s in unique if s["ip_type"] == "isp")
    dc_count = sum(1 for s in unique if s["ip_type"] == "dc")
    print(f"   ISP: {isp_count}, Datacenter: {dc_count}, Unknown: {len(unique) - isp_count - dc_count}")

    # Take top N, preferring ISP
    result = unique[:MAX_NODES]
    print(f"   Taking top {len(result)}:")
    for s in result:
        label = "🏠" if s["ip_type"] == "isp" else "🏢" if s["ip_type"] == "dc" else "❓"
        print(f"   {label} {s['host']} ({s['speed']} Mbps, {s['latency']}ms) - {s.get('org','?')}")

    return result


def download_config(server_id):
    """Get download token and download OVPN config"""
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

    dl_url = f"{BASE_URL}/download.php?token={token}"
    dl_headers = {"Accept": "application/x-openvpn-profile, application/octet-stream;q=0.9"}
    
    req = urllib.request.Request(dl_url)
    req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    for k, v in dl_headers.items():
        req.add_header(k, v)
    
    with urllib.request.urlopen(req, timeout=15) as resp:
        content = resp.read().decode("utf-8", errors="replace")

    if len(content) < 100:
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
        ip_type = srv.get("ip_type", "?")

        print(f"\n📄 {host} ({proto} {port}, {speed} Mbps, {ip_type})")
        config = download_config(sid)
        if not config:
            print(f"   ❌ Download failed")
            continue

        label = "isp" if ip_type == "isp" else "dc" if ip_type == "dc" else "mix"
        filename = f"{COUNTRY}-{host}-{proto}{port}-{speed:.1f}Mbps-{label}.ovpn"
        filepath = os.path.join("configs", filename)
        with open(filepath, "w") as f:
            f.write(config)
        print(f"   ✅ {filename} ({len(config)} bytes)")
        downloaded += 1
        time.sleep(1)

    print(f"\n{'='*50}")
    print(f"✅ Downloaded {downloaded}/{len(servers)} configs")
    print(f"📁 Output: configs/")

    if downloaded == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()