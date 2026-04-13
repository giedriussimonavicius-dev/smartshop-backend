"""
SmartShop Backend API v3.2
"""
from flask import Flask, request, jsonify
from flask_cors import CORS
import os, json, time, hashlib, urllib.request
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DAILY_FREE_LIMIT  = int(os.getenv("DAILY_FREE_LIMIT", "10"))
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "1800"))

cache = {}
rate_store = {}

def get_cache(key):
    if key in cache:
        entry = cache[key]
        if time.time() - entry["ts"] < CACHE_TTL_SECONDS:
            return entry["data"]
        del cache[key]
    return None

def set_cache(key, data):
    cache[key] = {"data": data, "ts": time.time()}

def rate_limit(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        ip = request.remote_addr or "unknown"
        today = time.strftime("%Y-%m-%d")
        if ip not in rate_store or rate_store[ip]["date"] != today:
            rate_store[ip] = {"date": today, "count": 0}
        rate_store[ip]["count"] += 1
        if rate_store[ip]["count"] > DAILY_FREE_LIMIT:
            return jsonify({
                "error": "daily_limit",
                "message": f"Free limit of {DAILY_FREE_LIMIT} searches/day reached.",
                "remaining": 0
            }), 429
        return f(*args, **kwargs)
    return decorated

AFFILIATE = {
    # LT tiesioginiai pardavėjai
    "varle.lt":        "https://varle.lt/search/?q={query}",
    "pigu.lt":         "https://pigu.lt/lt/search?query={query}",
    "euronics.lt":     "https://euronics.lt/paieska?q={query}",
    "senukai.lt":      "https://senukai.lt/paieska?q={query}",
    "1a.lt":           "https://1a.lt/search?q={query}",
    "skytech.lt":      "https://skytech.lt/search?q={query}",
    "elesen.lt":       "https://www.elesen.lt/paieska?search={query}",
    "topocentras.lt":  "https://www.topocentras.lt/search?q={query}",
    "rde.lt":          "https://www.rde.lt/search?q={query}",
    "topo.lt":         "https://www.topo.lt/search/?q={query}",
    "kilobaitas.lt":   "https://www.kilobaitas.lt/Search.aspx?SearchText={query}",
    "bikko.com":       "https://www.bikko.com/lt/search?q={query}",
    "fotopartneris.lt":"https://www.fotopartneris.lt/paieska?q={query}",
    "apvaraibu.lt":    "https://www.apvaraibu.lt/search?q={query}",
    # Tarptautiniai
    "amazon.de":       "https://www.amazon.de/s?k={query}",
    "ebay.com":        "https://www.ebay.com/sch/i.html?_nkw={query}",
}

SHOPS = [
    # LT tiesioginiai pardavėjai (ne agregatoriai)
    {"id": "varle",        "name": "Varle.lt",       "flag": "🇱🇹", "url": "varle.lt"},
    {"id": "pigu",         "name": "Pigu.lt",        "flag": "🇱🇹", "url": "pigu.lt"},
    {"id": "euronics",     "name": "Euronics",       "flag": "🇱🇹", "url": "euronics.lt"},
    {"id": "senukai",      "name": "Senukai",        "flag": "🇱🇹", "url": "senukai.lt"},
    {"id": "1a",           "name": "1a.lt",          "flag": "🇱🇹", "url": "1a.lt"},
    {"id": "skytech",      "name": "Skytech",        "flag": "🇱🇹", "url": "skytech.lt"},
    {"id": "elesen",       "name": "Elesen.lt",      "flag": "🇱🇹", "url": "elesen.lt"},
    {"id": "topocentras",  "name": "Topocentras",    "flag": "🇱🇹", "url": "topocentras.lt"},
    {"id": "rde",          "name": "RDE.lt",         "flag": "🇱🇹", "url": "rde.lt"},
    {"id": "kilobaitas",   "name": "Kilobaitas",     "flag": "🇱🇹", "url": "kilobaitas.lt"},
    {"id": "fotopartneris","name": "Fotopartneris",  "flag": "🇱🇹", "url": "fotopartneris.lt"},
    # Tarptautiniai
    {"id": "amazon",       "name": "Amazon.de",      "flag": "🌍",  "url": "amazon.de"},
    {"id": "ebay",         "name": "eBay",           "flag": "🌍",  "url": "ebay.com"},
]

def build_affiliate_url(shop_url, query):
    q = query.replace(" ", "+")
    for key, pattern in AFFILIATE.items():
        if key in shop_url:
            return pattern.replace("{query}", q)
    return f"https://{shop_url}"

def build_prompt(query, shops):
    shop_str = ", ".join([f"{s['name']} ({s['url']})" for s in shops])
    return f"""You are SmartShop AI — a price intelligence engine with review analysis.

PRODUCT: "{query}"
SHOPS: {shop_str}

Use web_search to find:
1. PRICES: Search "{query} kaina pigu.lt", "{query} price amazon.de", "{query} varle.lt kaina"
2. REVIEWS: Search "{query} atsiliepimai", "{query} review 2024", "{query} pros cons"
3. RATING: Find average user rating from review sites, Amazon, etc.

RULES:
- Put DIRECT product page URL in "url" field when found
- Use exact prices from search results only
- If price not found for a shop, skip it entirely
- Summarize real user reviews into review_summary (2-3 sentences in Lithuanian)
- verdict_label in Lithuanian: "Pirkti dabar" / "Palaukti" / "Vengti" / "Normalu"
- All text fields in Lithuanian

Return ONLY valid JSON (no markdown, no extra text):
{{"product_name":"","product_emoji":"","ai_verdict":"BUY|WAIT|SKIP|OK","verdict_label":"","verdict_reason":"","ai_summary":"","buy_recommendation":"","deal_score":75,"price_min":0,"price_max":0,"price_avg":0,"overall_rating":0,"review_count":0,"review_summary":"","review_pros":"","review_cons":"","results":[{{"shop":"","flag":"","url":"","price":0,"currency":"EUR","in_stock":true,"delivery":"","deal_score":80,"rating":0,"review_count":0,"notes":"","is_best_value":false,"is_cheapest":false,"is_top_rated":false,"why_recommended":"","source":"web_search"}}]}}"""

def call_anthropic(prompt):
    messages = [{"role": "user", "content": prompt}]
    headers = {
        "Content-Type": "application/json",
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
    }

    def do_request(msgs, timeout):
        payload = json.dumps({
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 4000,
            "tools": [{"type": "web_search_20250305", "name": "web_search"}],
            "messages": msgs
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload, headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    data = do_request(messages, 60)

    if data.get("stop_reason") == "tool_use":
        tool_results = [
            {"type": "tool_result", "tool_use_id": b["id"], "content": "Search completed."}
            for b in data["content"] if b.get("type") == "tool_use"
        ]
        messages.append({"role": "assistant", "content": data["content"]})
        messages.append({"role": "user", "content": tool_results})
        data = do_request(messages, 90)

    return "".join(
        b.get("text", "") for b in data.get("content", [])
        if b.get("type") == "text"
    )

def call_anthropic_vision(image_b64):
    """Dedicated vision call for image analysis."""
    prompt_text = """Analyze this image carefully and identify:

1. PRODUCT: What product/item is shown? Give exact brand, model, name.
2. PRICE TAG: Is there any price label, price sticker, or price display visible?
   - If YES: What is the EXACT price shown? (numbers only, e.g. 299.99)
   - If NO: Return 0 for price_visible
3. BARCODE: Is there a barcode or QR code? If yes, what number is shown?

Be very precise. Do NOT guess prices. Only report prices you can clearly see.

Return ONLY this JSON:
{"product_name":"exact brand and model","price_visible":0,"barcode":"","brand":"","model":"","context":"what you see in the image"}

Rules:
- price_visible must be 0 if no price is clearly visible
- price_visible must be the exact number shown if a price label is visible
- Do not hallucinate prices"""

    payload = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 500,
        "messages": [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}},
            {"type": "text", "text": prompt_text}
        ]}]
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8"))

    return "".join(b.get("text","") for b in data.get("content",[]) if b.get("type")=="text")

def parse_response(text, query):
    s = text.strip()
    for fence in ["```json", "```"]:
        s = s.replace(fence, "")
    s = s.strip()
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1:
        s = s[start:end+1]
    try:
        return json.loads(s)
    except:
        return {
            "product_name": query,
            "product_emoji": "📦",
            "ai_verdict": "OK",
            "verdict_label": "Normalu",
            "verdict_reason": "Duomenys gauti.",
            "ai_summary": text[:300],
            "deal_score": 50,
            "results": [],
            "price_min": 0,
            "price_max": 0,
            "price_avg": 0
        }

def post_process(data, query):
    results = [r for r in data.get("results", []) if r.get("price", 0) > 0]
    if not results:
        return data
    results.sort(key=lambda x: x.get("price", 0))
    prices = [r["price"] for r in results]
    data["price_min"] = min(prices)
    data["price_max"] = max(prices)
    data["price_avg"] = round(sum(prices) / len(prices))
    for i, r in enumerate(results):
        r["is_cheapest"] = (i == 0)
        r["is_worst"] = (i == len(results) - 1)
    best_idx = max(range(len(results)), key=lambda i: results[i].get("deal_score", 0))
    results[best_idx]["is_best_value"] = True
    rated = [r for r in results if r.get("rating", 0) > 0]
    if rated:
        max(rated, key=lambda r: r.get("rating", 0))["is_top_rated"] = True
    for r in results:
        url = r.get("url", r.get("shop", ""))
        r["affiliate_url"] = build_affiliate_url(url, query)
    data["results"] = results
    return data

@app.route("/api/search", methods=["POST"])
@rate_limit
def search():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400
    query = data.get("query", "").strip()
    shop_ids = data.get("shops", [s["id"] for s in SHOPS])
    if not query:
        return jsonify({"error": "Query required"}), 400

    cache_key = hashlib.md5(f"{query}:{sorted(shop_ids)}".encode()).hexdigest()
    cached = get_cache(cache_key)
    if cached:
        cached["_cached"] = True
        return jsonify(cached)

    shops = [s for s in SHOPS if s["id"] in shop_ids] or SHOPS
    if not ANTHROPIC_API_KEY:
        return jsonify({"error": "Server not configured"}), 500

    try:
        text = call_anthropic(build_prompt(query, shops))
        result = parse_response(text, query)
        result = post_process(result, query)
        set_cache(cache_key, result)

        ip = request.remote_addr or "unknown"
        today = time.strftime("%Y-%m-%d")
        used = rate_store.get(ip, {}).get("count", 1)
        result["_rate"] = {
            "used": used,
            "limit": DAILY_FREE_LIMIT,
            "remaining": max(0, DAILY_FREE_LIMIT - used)
        }
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": "server_error", "message": str(e)}), 500

@app.route("/api/scan-image", methods=["POST"])
@rate_limit
def scan_image():
    data = request.get_json()
    if not data or "image" not in data:
        return jsonify({"error": "No image"}), 400

    try:
        text = call_anthropic_vision(data["image"])
        result = parse_response(text, "")

        # Validate price - only return if clearly visible (> 1 and reasonable)
        price = result.get("price_visible", 0)
        if isinstance(price, (int, float)) and price <= 1:
            result["price_visible"] = 0

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "version": "3.3",
        "api_configured": bool(ANTHROPIC_API_KEY),
        "cache_entries": len(cache),
        "rate_store_size": len(rate_store)
    })

@app.route("/api/rate-limit", methods=["GET"])
def rate_limit_status():
    ip = request.remote_addr or "unknown"
    today = time.strftime("%Y-%m-%d")
    used = rate_store.get(ip, {}).get("count", 0) if rate_store.get(ip, {}).get("date") == today else 0
    return jsonify({"used": used, "limit": DAILY_FREE_LIMIT, "remaining": max(0, DAILY_FREE_LIMIT - used)})

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"SmartShop API v3.3 on http://localhost:{port}")
    print(f"API key: {'configured' if ANTHROPIC_API_KEY else 'MISSING'}")
    app.run(host="0.0.0.0", port=port, debug=True)
