# --- File: app.py ---

import os
import asyncio
import logging
import datetime
import discord
from discord.ext import commands, tasks
import yfinance as yf
import statistics
import concurrent.futures
import requests
import json
from threading import Thread

# --- Flask Web Application Imports ---
from flask import Flask, redirect, url_for, session, render_template_string, request, jsonify, g
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from requests_oauthlib import OAuth2Session
from discord import app_commands, ui, Interaction, embeds

# --- Setup Logging ---
logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("stockbot_full")

# --- Environment Variables (Secrets) ---
# IMPORTANT: Replace these with your actual values or use a .env file
# DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
# CLIENT_ID = os.environ.get("CLIENT_ID")
# CLIENT_SECRET = os.environ.get("CLIENT_SECRET")
# FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY")

# Placeholder for example, use environment variables in production
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "YOUR_DISCORD_BOT_TOKEN_HERE")
CLIENT_ID = os.environ.get("CLIENT_ID", "YOUR_DISCORD_CLIENT_ID_HERE")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET", "YOUR_DISCORD_CLIENT_SECRET_HERE")
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "YOUR_FINNHUB_API_KEY_HERE")

if not all([DISCORD_TOKEN, CLIENT_ID, CLIENT_SECRET, FINNHUB_API_KEY]):
    logger.error("❌ กรุณาตั้งค่า DISCORD_TOKEN, CLIENT_ID, CLIENT_SECRET, และ FINNHUB_API_KEY ใน Secrets/Environment Variables หรือไฟล์ .env")
    # In a real application, you might want to exit here. For this example, we'll continue with placeholders.

# --- Global Data Storage (using a simple dictionary for demonstration) ---
user_targets = {}
user_messages = {}
# Data structure: { "user_id": { "symbol": { "target": float, "trigger_type": str, ... } } }

# --- Discord Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- Flask App Setup ---
app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
app.config['SESSION_TYPE'] = 'filesystem'
app.config['OAUTHLIB_INSECURE_TRANSPORT'] = '1' # Set to '0' in production

login_manager = LoginManager()
login_manager.init_app(app)

class User(UserMixin):
    def __init__(self, user_id):
        self.id = user_id
    def __repr__(self):
        return f"User(id='{self.id}')"

@login_manager.user_loader
def load_user(user_id):
    return User(user_id)

# --- Discord OAuth2 Config ---
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
DISCORD_API_BASE_URL = 'https://discord.com/api/v10'
AUTHORIZATION_BASE_URL = DISCORD_API_BASE_URL + '/oauth2/authorize'
TOKEN_URL = DISCORD_API_BASE_URL + '/oauth2/token'

def get_discord_oauth():
    return OAuth2Session(CLIENT_ID, redirect_uri=url_for('callback', _external=True), scope=['identify'])

# --- Web Application Routes ---

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template_string("""
        <!doctype html>
        <html lang="en">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no">
            <title>เข้าสู่ระบบ</title>
            <style>
                body { font-family: sans-serif; text-align: center; padding-top: 50px; background-color: #f2f3f5; }
                .container { max-width: 500px; margin: auto; padding: 30px; border-radius: 10px; background-color: white; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
                h1 { color: #333; }
                p { color: #666; }
                .btn-discord { background-color: #7289da; color: white; padding: 15px 30px; text-decoration: none; border-radius: 8px; font-size: 18px; font-weight: bold; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>ยินดีต้อนรับสู่ Stock Alert Bot!</h1>
                <p>กรุณาเข้าสู่ระบบด้วยบัญชี Discord ของคุณ</p>
                <a href="{{ url_for('login') }}" class="btn-discord">เข้าสู่ระบบด้วย Discord</a>
            </div>
        </body>
        </html>
    """)

@app.route('/login')
def login():
    discord_oauth = get_discord_oauth()
    authorization_url, state = discord_oauth.authorization_url(AUTHORIZATION_BASE_URL)
    session['oauth_state'] = state
    return redirect(authorization_url)

@app.route('/callback')
def callback():
    if 'oauth_state' not in session or session['oauth_state'] != request.args.get('state'):
        return "Invalid state parameter", 400
        
    discord_oauth = get_discord_oauth()
    try:
        token = discord_oauth.fetch_token(TOKEN_URL, client_secret=CLIENT_SECRET, authorization_response=request.url)
    except Exception as e:
        logger.error(f"Failed to fetch token: {e}")
        return "Failed to authenticate with Discord.", 500
        
    session['oauth_token'] = token
    
    user_data = discord_oauth.get(f'{DISCORD_API_BASE_URL}/users/@me').json()
    user = User(user_data['id'])
    login_user(user)
    
    return redirect(url_for('dashboard'))

@app.route('/logout')
@login_required
def logout():
    session.pop('oauth_token', None)
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    user_id = str(current_user.id)
    targets = user_targets.get(user_id, {})
    
    return render_template_string("""
        <!doctype html>
        <html lang="en">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no">
            <title>Dashboard</title>
            <style>
                body { font-family: sans-serif; padding: 20px; background-color: #f2f3f5; }
                .container { max-width: 800px; margin: auto; padding: 30px; border-radius: 10px; background-color: white; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
                .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
                .target-form { margin-top: 20px; padding: 20px; border: 1px solid #ddd; border-radius: 5px; background-color: #fafafa; }
                .target-list { margin-top: 20px; }
                .target-item { border: 1px solid #eee; padding: 15px; margin-bottom: 10px; border-radius: 5px; display: flex; justify-content: space-between; align-items: center; }
                .btn { padding: 8px 12px; border: none; border-radius: 4px; cursor: pointer; margin-left: 5px; }
                .btn-primary { background-color: #007bff; color: white; }
                .btn-danger { background-color: #dc3545; color: white; }
                .btn-success { background-color: #28a745; color: white; }
                input, select { padding: 10px; margin: 5px 0; width: 100%; box-sizing: border-box; border-radius: 4px; border: 1px solid #ccc; }
                .logout-btn { background-color: #f44336; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>สวัสดี, ผู้ใช้ {{ current_user.id }}</h2>
                    <a href="{{ url_for('logout') }}" class="logout-btn">ออกจากระบบ</a>
                </div>
                
                <div class="target-list">
                    <h3>รายการเป้าหมายหุ้นของคุณ</h3>
                    {% if targets %}
                        {% for symbol, data in targets.items() %}
                            <div class="target-item">
                                <div>
                                    <strong>{{ symbol }}</strong>: เป้าหมายที่ **{{ data.target }}** บาท<br>
                                    เงื่อนไข: {{ 'ราคาต่ำกว่า/เท่ากับ' if data.trigger_type == 'below' else 'ราคาสูงกว่า/เท่ากับ' }}
                                </div>
                                <button class="btn btn-danger btn-sm" onclick="deleteTarget('{{ symbol }}')">ลบ</button>
                            </div>
                        {% endfor %}
                    {% else %}
                        <p>คุณยังไม่ได้ตั้งเป้าหมายหุ้นใดๆ</p>
                    {% endif %}
                </div>
                
                <div class="target-form">
                    <h3>ตั้งเป้าหมายหุ้นใหม่</h3>
                    <form id="set-target-form">
                        <label for="symbol">ชื่อหุ้น:</label>
                        <input type="text" id="symbol" name="symbol" placeholder="เช่น AAPL หรือ PTT.BK" required>
                        
                        <label for="target_price">ราคาเป้าหมาย:</label>
                        <input type="number" step="0.01" id="target_price" name="target_price" placeholder="ราคาเป้าหมายเป็นตัวเลข" required>
                        
                        <label for="trigger_type">เงื่อนไขการแจ้งเตือน:</label>
                        <select id="trigger_type" name="trigger_type">
                            <option value="below">ราคาต่ำกว่า/เท่ากับ</option>
                            <option value="above">ราคาสูงกว่า/เท่ากับ</option>
                        </select>
                        
                        <button type="submit" class="btn btn-success">ตั้งค่า</button>
                    </form>
                </div>
            </div>
            
            <script>
                async function setTarget(event) {
                    event.preventDefault();
                    const form = document.getElementById('set-target-form');
                    const formData = new FormData(form);
                    const data = Object.fromEntries(formData.entries());
                    
                    const response = await fetch('/api/set_target', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(data)
                    });
                    const result = await response.json();
                    alert(result.message);
                    if (result.success) {
                        window.location.reload();
                    }
                }
                
                async function deleteTarget(symbol) {
                    if (!confirm(`คุณต้องการลบเป้าหมายของหุ้น ${symbol} หรือไม่?`)) {
                        return;
                    }
                    
                    const response = await fetch('/api/delete_target', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ symbol: symbol })
                    });
                    const result = await response.json();
                    alert(result.message);
                    if (result.success) {
                        window.location.reload();
                    }
                }
                
                document.getElementById('set-target-form').addEventListener('submit', setTarget);
            </script>
        </body>
        </html>
    """, targets=targets)

# --- API Endpoints for Web Application ---

@app.route('/api/set_target', methods=['POST'])
@login_required
def api_set_target():
    data = request.json
    symbol = data.get('symbol', '').upper()
    target_price = data.get('target_price')
    trigger_type = data.get('trigger_type', 'below')

    try:
        target_price = float(target_price)
    except (ValueError, TypeError):
        return jsonify(success=False, message="❌ กรุณากรอกราคาเป็นตัวเลขที่ถูกต้อง"), 400

    user_id = str(current_user.id)
    if user_id not in user_targets:
        user_targets[user_id] = {}

    user_targets[user_id][symbol] = {
        'target': target_price,
        'trigger_type': trigger_type,
        'approaching_alert_sent': False
    }

    return jsonify(success=True, message=f"✅ ตั้งเป้าหมายสำหรับ **{symbol}** ที่ **{target_price}** บาทเรียบร้อยแล้ว")

@app.route('/api/delete_target', methods=['POST'])
@login_required
def api_delete_target():
    data = request.json
    symbol = data.get('symbol', '').upper()
    user_id = str(current_user.id)

    if user_id in user_targets and symbol in user_targets[user_id]:
        del user_targets[user_id][symbol]
        return jsonify(success=True, message=f"🗑️ ลบเป้าหมายสำหรับ **{symbol}** เรียบร้อยแล้ว")
    else:
        return jsonify(success=False, message="❌ ไม่พบเป้าหมายที่คุณตั้งไว้"), 404

# --- Stock Bot Logic and Tasks ---

def fetch_price_blocking(symbol: str):
    """Blocking function to fetch a stock's current price."""
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.history(period="1d", interval="1m")
        if data.empty:
            return None
        return float(data["Close"].iloc[-1])
    except Exception as e:
        logger.warning(f"ไม่สามารถดึงราคาหุ้น {symbol}: {e}")
        return None

async def async_fetch_price(symbol: str):
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, fetch_price_blocking, symbol)
    except Exception as e:
        logger.error(f"Error fetching price for {symbol}: {e}")
        return None

# --- Discord Bot Events and Tasks ---

@bot.event
async def on_ready():
    logger.info(f"บอท {bot.user.name} ออนไลน์แล้ว")
    logger.info("เริ่มรันเว็บเซิร์ฟเวอร์...")
    
    # Start the background stock check task
    if not auto_check.is_running():
        auto_check.start()

@tasks.loop(minutes=5)
async def auto_check():
    logger.info("เริ่มตรวจสอบราคาหุ้น...")
    for uid, targets in list(user_targets.items()):
        for stock, data in list(targets.items()):
            target = data.get('target')
            trigger_type = data.get('trigger_type', 'below')
            
            price = await async_fetch_price(stock)
            if price is None:
                continue

            should_notify = False
            if trigger_type == 'below' and price <= target:
                should_notify = True
            elif trigger_type == 'above' and price >= target:
                should_notify = True
            
            if should_notify:
                try:
                    user = await bot.fetch_user(uid)
                    if user is None: continue
                    
                    embed = discord.Embed(
                        title="📢 แจ้งเตือน: ราคาหุ้นถึงเป้าหมายแล้ว!",
                        color=0xe67e22,
                        timestamp=datetime.datetime.now(datetime.timezone.utc)
                    )
                    embed.add_field(name="หุ้น", value=f"**{stock}**", inline=True)
                    embed.add_field(name="ราคาปัจจุบัน", value=f"**{price}** บาท", inline=True)
                    embed.add_field(name="ราคาเป้าหมาย", value=f"**{target}** บาท", inline=True)
                    
                    await user.send(embed=embed)
                    
                    # Remove the target once it's been reached
                    if uid in user_targets and stock in user_targets[uid]:
                        del user_targets[uid][stock]

                except Exception as e:
                    logger.error(f"เกิดข้อผิดพลาดในการส่งแจ้งเตือนสำหรับ {stock} ถึง {uid}: {e}")

# --- Run the Bot and Flask App ---

if __name__ == "__main__":
    if DISCORD_TOKEN:
        # We need to run the Flask app and the bot.
        # This approach runs the bot first, and the bot will start the Flask server in a separate thread.
        # This is a common pattern for bots that require a web server.
        
        # Start the Flask app in a separate thread
        Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000))), daemon=True).start()
        
        # Then start the bot
        try:
            bot.run(DISCORD_TOKEN)
        except discord.errors.LoginFailure as e:
            logger.error(f"❌ โทเค็นบอทไม่ถูกต้อง: {e}")
    else:
        logger.error("❌ กรุณาตั้งค่า DISCORD_TOKEN")
