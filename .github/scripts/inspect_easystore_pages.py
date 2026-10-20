import re
import urllib.request

SOURCES = [
    "https://admin.easystore.co/assets/index-BLIo0Nmo.js",
    "https://admin.easystore.co/assets/new-Bzg9ED2L.js",
    "https://admin.easystore.co/assets/index-B7_9miUl.js",
]
PATTERNS = ["updatePage", "is_published", "published_at", "update_navigation_name", "content.updatePage", "publishPage"]
for url in SOURCES:
    print("SOURCE", url, flush=True)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as response:
            content = response.read(15_000_000).decode("utf-8")
        print("SIZE", len(content))
        for pattern in PATTERNS:
            matches = list(re.finditer(re.escape(pattern), content))
            print("PATTERN", pattern, "COUNT", len(matches), flush=True)
            for match in matches[:8]:
                print("  EXCERPT", content[max(0, match.start()-320):match.end()+320].replace("\n"," "),flush=True)
    except Exception as exc:
        print("FETCH ERROR", type(exc).__name__, str(exc)[:250], flush=True)
