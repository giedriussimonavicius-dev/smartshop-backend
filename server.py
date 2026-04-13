"""
SmartShop Backend API
---------------------
Run: python server.py
Requires: pip install flask flask-cors anthropic python-dotenv
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import anthropic
import os
import json
import time
import hashlib
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)  # Allow all origins (lock down in production)

# ── CONFIG ─────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DAILY_FREE_LIMIT  = int(os.getenv("DAILY_FREE_LIMIT", "10"))
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "1800"))  # 30 min cache

# ── SIMPLE IN-MEMORY CACHE ─────────────────────────
cache = {}

def get_cache(key):
    if key in cache:
        entry = cache[key]
        if time.time() - entry["ts"] < CACHE_TTL_SECONDS:
            return entry["data"]
        del cache[key]
    return None

def set_cache(key, data):
    cache[key] = {"data": data, "ts": time.time()}

# ── SIMPLE RATE LIMITER (IP-based) ─────────────────
rate_store = {}  # {ip: {date: str, count: int}}

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
                "message": f"Free limit of {DAILY_FREE_LIMIT} searches/day reached. Upgrade for unlimited access.",
                "remaining": 0
            }), 429
        return f(*args, **kwargs)
    return decorated

# ── AFFILIATE LINK BUILDER ─────────────────────────
AFFILIATE = {
    "varle.lt":      {"tag": "smartshop-varle",  "pattern": "https://varle.lt/search/?q={query}&ref=smartshop"},
    "pigu.lt":       {"tag": "smartshop-pigu",   "pattern": "https://pigu.lt/lt/search?query={query}&utm_source=smartshop"},
    "euronics.lt":   {"tag": "smartshop-euro",   "pattern": "https://euronics.lt/paieska?q={query}"},
    "senukai.lt":    {"tag": "smartshop-senu",   "pattern": "https://senukai.lt/search?q={query}"},
    "1a.lt":         {"tag": "smartshop-1a",     "pattern": "https://1a.lt/search?q={query}"},
    "amazon.de":     {"tag": "smartshop-amz",    "pattern": "https://www.amazon.de/s?k={query}&tag=smartshop-21"},
    "ebay.com":      {"tag": "smartshop-ebay",   "pattern": "https://www.ebay.com/sch/i.html?_nkw={query}&mkcid=1&mkrid=711-53200-19255-0&campid=smartshop"},
    "idealo.de":     {"tag": "smartshop-idea",   "pattern": "https://www.idealo.de/preisvergleich/MainSearchProductCategory.html?q={query}"},
    "pricerunner.com":{"tag": "smartshop-pr",    "pattern": "https://www.pricerunner.com/search?q={query}"},
}

def build_affiliate_url(shop_url: str, query: str) -> str:
    domain = shop_url.replace("https://", "").replace("http://", "").split("/")[0]
    for key, aff in AFFILIATE.items():
        if key in domain:
            return aff["pattern"].replace("{query}", query.replace(" ", "+"))
    return f"https://{shop_url}"

# ── SHOPS LIST ─────────────────────────────────────
SHOPS = [
    {"id": "varle",       "name": "Varle.lt",     "flag": "🇱🇹", "url": "varle.lt"},
    {"id": "pigu",        "name": "Pigu.lt",       "flag": "🇱🇹", "url": "pigu.lt"},
    {"id": "euronics",    "name": "Euronics",      "flag": "🇱🇹", "url": "euronics.lt"},
    {"id": "senukai",     "name": "Senukai",       "flag": "🇱🇹", "url": "senukai.lt"},
    {"id": "1a",          "name": "1a.lt",         "flag": "🇱🇹", "url": "1a.lt"},
    {"id": "skytech",     "name": "Skytech",       "flag": "🇱🇹", "url": "skytech.lt"},
    {"id": "amazon",      "name": "Amazon",        "flag": "🌍", "url": "amazon.de"},
    {"id": "ebay",        "name": "eBay",          "flag": "🌍", "url": "ebay.com"},
    {"id": "idealo",      "name": "Idealo",        "flag": "🇩🇪", "url": "idealo.de"},
    {"id": "pricerunner", "name": "PriceRunner",   "flag": "🇸🇪", "url": "pricerunner.com"},
    {"id": "notino",      "name": "Notino",        "flag": "🇨🇿", "url": "notino.com"},
]

# ── AI PROMPT BUILDER ──────────────────────────────
def build_prompt(query: str, shops: list) -> str:
    shop_str = ", ".join([f"{s['name']} ({s['url']})" for s in shops])
    return f"""You are SmartShop AI — a price intelligence engine for Lithuanian and European shoppers.

PRODUCT TO FIND: "{query}"
SHOPS TO CHECK: {shop_str}

Use web_search to find REAL current prices. Search for:
- "{query} kaina pigu.lt"
- "{query} price amazon.de"
- "{query} varle.lt kaina"
- "{query} best price europe"

SCORING RULES (calculate deal_score 0-100):
- Price vs 90-day average: lower = higher score
- Stock availability: in stock = +10
- Delivery speed: fast = +5
- Review score if found: good = +10

VERDICT RULES:
- BUY: price is at/near historical low, good availability
- WAIT: price likely to drop (seasonal pattern, recently increased)
- SKIP: significantly overpriced vs alternatives
- OK: average market price, no strong signal

Return ONLY this JSON (no markdown, no preamble):
{{
  "product_name": "exact product name",
  "product_emoji": "single emoji",
  "category": "category",
  "ai_verdict": "BUY|WAIT|SKIP|OK",
  "verdict_label": "Pirkti dabar|Palaukti|Vengti|Normalu",
  "verdict_reason": "1-2 sentence explanation in Lithuanian",
  "ai_summary": "3-4 sentence detailed analysis in Lithuanian",
  "buy_recommendation": "specific recommendation in Lithuanian",
  "deal_score": 75,
  "price_min": 0,
  "price_max": 0,
  "price_avg": 0,
  "price_history_note": "historical context",
  "results": [
    {{
      "shop": "Shop name",
      "shop_id": "id",
      "flag": "🇱🇹",
      "url": "shop.lt/product-url",
      "price": 0,
      "currency": "EUR",
      "in_stock": true,
      "delivery": "1-2 d.d.",
      "deal_score": 85,
      "rating": 4.5,
      "review_count": 0,
      "notes": "short note about this offer",
      "is_best_value": false,
      "is_cheapest": false,
      "is_top_rated": false,
      "why_recommended": "brief reason",
      "source": "web_search"
    }}
  ]
}}

Mark is_cheapest=true for lowest price, is_best_value=true for best price/quality ratio, is_top_rated=true for highest rating.
Use source="estimated" if price not found. JSON ONLY."""


def run_search(query: str, shop_ids: list) -> dict:
    """Bendra paieškos funkcija — naudojama tiek /search, tiek /scan-image."""
    cache_key = hashlib.md5(f"{query}:{sorted(shop_ids)}".encode()).hexdigest()
    cached = get_cache(cache_key)
    if cached:
        cached["_cached"] = True
        return cached

    shops = [s for s in SHOPS if s["id"] in shop_ids] or SHOPS
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = build_prompt(query, shops)

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": prompt}]
    )
    if response.stop_reason == "tool_use":
        tool_results = [
            {"type": "tool_result", "tool_use_id": b.id, "content": "Search completed."}
            for b in response.content if b.type == "tool_use"
        ]
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": response.content},
                {"role": "user", "content": tool_results}
            ]
        )
    text = "".join(b.text for b in response.content if hasattr(b, "text"))
    result = parse_ai_response(text, query)
    result = post_process(result, query)
    set_cache(cache_key, result)
    return result


# ── MAIN SEARCH ENDPOINT ───────────────────────────
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
    if len(query) > 200:
        return jsonify({"error": "Query too long"}), 400

    # Check cache
    cache_key = hashlib.md5(f"{query}:{sorted(shop_ids)}".encode()).hexdigest()
    cached = get_cache(cache_key)
    if cached:
        cached["_cached"] = True
        return jsonify(cached)

    # Get shops to search
    shops = [s for s in SHOPS if s["id"] in shop_ids]
    if not shops:
        shops = SHOPS

    if not ANTHROPIC_API_KEY:
        return jsonify({"error": "Server not configured", "message": "API key missing on server"}), 500

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = build_prompt(query, shops)

    try:
        # First call with web search tool
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": prompt}]
        )

        # If tool use, continue conversation
        if response.stop_reason == "tool_use":
            tool_results = [
                {"type": "tool_result", "tool_use_id": b.id, "content": "Search completed."}
                for b in response.content if b.type == "tool_use"
            ]
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4000,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=[
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": response.content},
                    {"role": "user", "content": tool_results}
                ]
            )

        # Extract text
        text = "".join(b.text for b in response.content if hasattr(b, "text"))

        # Parse JSON
        result = parse_ai_response(text, query)

        # Post-process: add affiliate links, sort, mark labels
        result = post_process(result, query)

        # Cache result
        set_cache(cache_key, result)

        # Add rate limit info
        ip = request.remote_addr or "unknown"
        today = time.strftime("%Y-%m-%d")
        used = rate_store.get(ip, {}).get("count", 1)
        result["_rate"] = {"used": used, "limit": DAILY_FREE_LIMIT, "remaining": max(0, DAILY_FREE_LIMIT - used)}

        return jsonify(result)

    except anthropic.APIError as e:
        return jsonify({"error": "api_error", "message": str(e)}), 500
    except Exception as e:
        return jsonify({"error": "server_error", "message": str(e)}), 500


def parse_ai_response(text: str, query: str) -> dict:
    """Extract and parse JSON from AI response."""
    s = text.strip()
    # Remove markdown fences
    for fence in ["```json", "```"]:
        s = s.replace(fence, "")
    s = s.strip()
    # Find JSON boundaries
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1:
        s = s[start:end+1]
    try:
        return json.loads(s)
    except json.JSONDecodeError:
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


def post_process(data: dict, query: str) -> dict:
    """Sort results, add affiliate links, calculate scores."""
    results = [r for r in data.get("results", []) if r.get("price", 0) > 0]

    if not results:
        return data

    # Sort by price
    results.sort(key=lambda x: x.get("price", 0))

    prices = [r["price"] for r in results]
    data["price_min"] = min(prices)
    data["price_max"] = max(prices)
    data["price_avg"] = round(sum(prices) / len(prices))

    # Mark labels
    for i, r in enumerate(results):
        r["is_cheapest"] = (i == 0)
        r["is_worst"] = (i == len(results) - 1)

    # Best value = best deal_score (or cheapest if no scores)
    best_score_idx = max(range(len(results)), key=lambda i: results[i].get("deal_score", 0))
    results[best_score_idx]["is_best_value"] = True

    # Top rated = highest rating
    rated = [r for r in results if r.get("rating", 0) > 0]
    if rated:
        top = max(rated, key=lambda r: r.get("rating", 0))
        top["is_top_rated"] = True

    # Add affiliate links
    for r in results:
        url = r.get("url", r.get("shop", ""))
        r["affiliate_url"] = build_affiliate_url(url, query)

    data["results"] = results
    return data


# ── IMAGE RECOGNITION ENDPOINT ────────────────────
@app.route("/api/scan-image", methods=["POST"])
@rate_limit
def scan_image():
    data = request.get_json()
    if not data or "image" not in data:
        return jsonify({"error": "No image"}), 400

    b64 = data["image"]
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    try:
        # 1. Atpažinti produktą iš nuotraukos
        vision_prompt = """Analyze this image carefully.
1. PRODUCT: Exact brand + model number (e.g. "Samsung QE75QN80FAUXXH")
2. PRICE TAG: Exact price shown (number only, 0 if not visible)
3. BARCODE: Number if visible

Return ONLY valid JSON, no markdown:
{"product_name":"exact brand and model","price_visible":0,"barcode":"","brand":"","model":"","context":"brief description"}"""

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=400,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                    {"type": "text", "text": vision_prompt}
                ]
            }]
        )
        text = "".join(b.text for b in response.content if hasattr(b, "text"))
        vision_result = parse_ai_response(text, "")

        product_name = vision_result.get("product_name", "").strip()
        price_visible = vision_result.get("price_visible", 0)
        if isinstance(price_visible, (int, float)) and price_visible <= 1:
            price_visible = 0

        if not product_name or product_name.lower() in ["", "unknown", "nežinoma"]:
            return jsonify({"error": "product_not_recognized", "message": "Nepavyko atpažinti produkto"}), 400

        # 2. Ieškoti kainų pagal atpažintą produktą
        shop_ids = data.get("shops", [s["id"] for s in SHOPS])

        # Patikrinti cache
        cache_key = hashlib.md5(f"scan:{product_name}:{sorted(shop_ids)}".encode()).hexdigest()
        cached = get_cache(cache_key)
        if cached:
            cached["_cached"] = True
            cached["scanned_product"] = product_name
            cached["store_price"] = price_visible
            return jsonify(cached)

        result = run_search(product_name, shop_ids)

        result["scanned_product"] = product_name
        result["store_price"] = price_visible

        # Pridėti parduotuvės kainą iš nuotraukos
        if price_visible > 1:
            store_entry = {
                "shop": "📷 Nuskaitytas",
                "flag": "📷",
                "price": price_visible,
                "currency": "EUR",
                "in_stock": True,
                "delivery": "Fizinė parduotuvė",
                "deal_score": 50,
                "is_cheapest": False,
                "is_best_value": False,
                "is_top_rated": False,
                "notes": "Kaina iš jūsų nuotraukos",
                "source": "scan"
            }
            result.setdefault("results", []).insert(0, store_entry)
            result = post_process(result, product_name)

        set_cache(cache_key, result)

        ip = request.remote_addr or "unknown"
        used = rate_store.get(ip, {}).get("count", 1)
        result["_rate"] = {"used": used, "limit": DAILY_FREE_LIMIT, "remaining": max(0, DAILY_FREE_LIMIT - used)}
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── HEALTH CHECK ──────────────────────────────────
@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "version": "3.0",
        "api_configured": bool(ANTHROPIC_API_KEY),
        "cache_entries": len(cache),
        "rate_store_size": len(rate_store)
    })


# ── RATE LIMIT STATUS ─────────────────────────────
@app.route("/api/rate-limit", methods=["GET"])
def rate_limit_status():
    ip = request.remote_addr or "unknown"
    today = time.strftime("%Y-%m-%d")
    used = rate_store.get(ip, {}).get("count", 0) if rate_store.get(ip, {}).get("date") == today else 0
    return jsonify({
        "used": used,
        "limit": DAILY_FREE_LIMIT,
        "remaining": max(0, DAILY_FREE_LIMIT - used)
    })


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("DEBUG", "true").lower() == "true"
    print(f"🚀 SmartShop API running on http://localhost:{port}")
    print(f"   API key: {'✓ configured' if ANTHROPIC_API_KEY else '✗ MISSING — set ANTHROPIC_API_KEY in .env'}")
    print(f"   Free limit: {DAILY_FREE_LIMIT} searches/day/IP")
    app.run(host="0.0.0.0", port=port, debug=debug)
