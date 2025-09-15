import os
import yfinance as yf
import requests
import time
import logging
import json
import threading
from flask import Flask, redirect, url_for, render_template_string, request, session, jsonify
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("stock_alert_bot")

# --- Environment Variables (Secrets) ---
# NOTE: We no longer need DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, DISCORD_REDIRECT_URI, or DISCORD_BOT_TOKEN
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

if not DISCORD_WEBHOOK_URL:
    logger.error("❌ กรุณาตั้งค่า DISCORD_WEBHOOK_URL ใน Environment Variables ให้ครบถ้วน")
    # The application will still run to serve the website, but without notifications.

# --- Flask App Setup ---
app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)

login_manager = LoginManager()
login_manager.init_app(app)

# --- Database & User Management ---
# Using a simple JSON file for persistence, suitable for small projects
class User(UserMixin):
    def __init__(self, user_id, username):
        self.id = user_id
        self.username = username
        self.targets = {}

    def get_id(self):
        return self.id

class Database:
    def __init__(self, file_path='discord_users.json'):
        self.file_path = file_path
        self.data = self.load_data()

    def load_data(self):
        try:
            with open(self.file_path, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def save_data(self):
        with open(self.file_path, 'w') as f:
            json.dump(self.data, f, indent=4)

    def get_user(self, user_id):
        user_data = self.data.get(str(user_id))
        if user_data:
            user = User(user_data['id'], user_data['username'])
            user.targets = user_data['targets']
            return user
        return None

    def add_user(self, user):
        self.data[str(user.id)] = {'id': user.id, 'username': user.username, 'targets': {}}
        self.save_data()

    def update_user_targets(self, user_id, targets):
        if str(user_id) in self.data:
            self.data[str(user_id)]['targets'] = targets
            self.save_data()

db = Database()

@login_manager.user_loader
def load_user(user_id):
    return db.get_user(user_id)

# --- Web Application Routes ---
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template_string("""
        <!doctype html>
        <html lang="th">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no">
            <title>ล็อกอินด้วย Discord</title>
            <style>
                body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; text-align: center; padding-top: 50px; background-color: #f0f2f5; color: #333; }
                .container { max-width: 450px; margin: auto; padding: 40px; border-radius: 12px; background-color: white; box-shadow: 0 10px 20px rgba(0,0,0,0.05); }
                h1 { color: #5865F2; margin-bottom: 20px; }
                .btn { padding: 12px 20px; border: none; border-radius: 8px; cursor: pointer; font-size: 16px; transition: background-color 0.3s; }
                .btn-discord { background-color: #5865F2; color: white; text-decoration: none; }
                .btn-discord:hover { background-color: #4B55C4; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>เข้าสู่ระบบด้วย Discord</h1>
                <p>โปรดตรวจสอบโค้ดและตั้งค่าใน Render ให้ถูกต้อง</p>
            </div>
        </body>
        </html>
    """)

# The following endpoints are placeholders and will not work without a full OAuth2 implementation
# For a full implementation, you would need DISCORD_CLIENT_ID etc.
# These routes are here for illustration and to avoid errors.
@app.route('/login')
def login_discord():
    return "This login route is not implemented in this version. Please set up Discord OAuth2 separately."

@app.route('/callback')
def callback():
    return "This callback route is not implemented in this version."

@app.route('/dashboard')
def dashboard():
    return "Dashboard not available in this simplified version. Please implement the OAuth2 flow to access this."

@app.route('/logout')
def logout():
    return "Logout not implemented in this simplified version."

@app.route('/api/set_target', methods=['POST'])
def api_set_target():
    return jsonify(success=False, message="API not implemented in this version.")

@app.route('/api/delete_target', methods=['POST'])
def api_delete_target():
    return jsonify(success=False, message="API not implemented in this version.")

# --- Stock Check and Discord Notify Logic ---
def fetch_price_blocking(symbol: str):
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.history(period="1d", interval="1m")
        if data.empty:
            return None
        return float(data["Close"].iloc[-1])
    except Exception as e:
        logger.warning(f"ไม่สามารถดึงราคาหุ้น {symbol}: {e}")
        return None

def send_discord_webhook(message: str):
    """Sends a message to a Discord channel via webhook."""
    if not DISCORD_WEBHOOK_URL:
        logger.warning("DISCORD_WEBHOOK_URL is not set. Cannot send notification.")
        return

    payload = {
        "content": message
    }
    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=payload)
        response.raise_for_status() # Raises an exception for bad status codes
        logger.info(f"Notification sent successfully to Discord via webhook.")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error sending Discord webhook: {e}")

def run_stock_checker():
    while True:
        logger.info("เริ่มตรวจสอบราคาหุ้น...")
        all_users_data = db.load_data()
        
        # In this simplified version, we're assuming the webhook is for a single user/purpose.
        # You'll need to manually add the stocks to discord_users.json for testing.
        for user_id_str, user_data in all_users_data.items():
            targets_to_check = list(user_data.get('targets', {}).items())
            
            for symbol, data in targets_to_check:
                target = data.get('target')
                trigger_type = data.get('trigger_type', 'below')
                
                current_price = fetch_price_blocking(symbol)
                if current_price is None:
                    continue
                
                should_notify = False
                if (trigger_type == 'below' and current_price <= target) or \
                   (trigger_type == 'above' and current_price >= target):
                    should_notify = True
                
                if should_notify:
                    message = f"📢 แจ้งเตือนหุ้นถึงเป้าหมาย!\n" \
                              f"หุ้น: {symbol}\n" \
                              f"ราคาปัจจุบัน: {current_price} บาท\n" \
                              f"ราคาเป้าหมาย: {target} บาท"
                    
                    send_discord_webhook(message)
                    
        time.sleep(60)

# --- Main Entry Point ---
if __name__ == "__main__":
    # Start the stock checker in a separate thread
    threading.Thread(target=run_stock_checker, daemon=True).start()
    
    # Run the web server
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
