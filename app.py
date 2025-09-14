import os
import yfinance as yf
import requests
import shelve
from threading import Thread
import time
import logging
from flask import Flask, redirect, url_for, render_template_string, request, jsonify
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("stock_alert_bot")

# --- Environment Variables (Secrets) ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    logger.error("❌ กรุณาตั้งค่า TELEGRAM_BOT_TOKEN และ TELEGRAM_CHAT_ID ใน Environment Variables")

# --- Flask App Setup ---
app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)

login_manager = LoginManager()
login_manager.init_app(app)

# --- Database Setup (using shelve for persistence) ---
class User(UserMixin):
    def __init__(self, username):
        self.username = username
        self.password_hash = None
        self.targets = {}

    def get_id(self):
        return self.username

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        # แก้ไข Pyright Error: 'self.password_hash' is Optional[str] but 'pwhash' is str.
        if self.password_hash is None:
            return False
        return check_password_hash(self.password_hash, password)

def get_db():
    return shelve.open('user_database')

@login_manager.user_loader
def load_user(user_id):
    with get_db() as db:
        # แก้ไข Pyright Error: 'user_id' can be Optional[str].
        if user_id in db:
            user = User(user_id)
            user_data = db[user_id]
            user.password_hash = user_data.password_hash
            user.targets = user_data.targets
            return user
    return None

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
            <title>ระบบแจ้งเตือนหุ้น</title>
            <link href="https://fonts.googleapis.com/css2?family=Kanit:wght@300;400;600&display=swap" rel="stylesheet">
            <style>
                :root {
                    --primary-color: #1a73e8;
                    --primary-hover: #1669c7;
                    --success-color: #28a745;
                    --success-hover: #218838;
                    --danger-color: #dc3545;
                    --danger-hover: #c82333;
                    --bg-color: #f0f2f5;
                    --card-bg: white;
                    --text-color: #333;
                    --light-text-color: #666;
                    --border-color: #e0e0e0;
                }
                body {
                    font-family: 'Kanit', sans-serif;
                    background-color: var(--bg-color);
                    color: var(--text-color);
                    margin: 0;
                    padding: 0;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    min-height: 100vh;
                }
                .container {
                    width: 90%;
                    max-width: 450px;
                    padding: 30px;
                    border-radius: 15px;
                    background-color: var(--card-bg);
                    box-shadow: 0 10px 30px rgba(0,0,0,0.1);
                }
                .logo {
                    font-size: 2.5em;
                    font-weight: 600;
                    color: var(--primary-color);
                    text-align: center;
                    margin-bottom: 20px;
                }
                .auth-form h2 {
                    text-align: center;
                    color: var(--primary-color);
                    margin-bottom: 25px;
                }
                .form-group {
                    margin-bottom: 15px;
                }
                .form-group input {
                    width: 100%;
                    padding: 12px 15px;
                    border: 1px solid var(--border-color);
                    border-radius: 8px;
                    box-sizing: border-box;
                    font-size: 16px;
                }
                .btn {
                    width: 100%;
                    padding: 12px;
                    border: none;
                    border-radius: 8px;
                    font-size: 18px;
                    font-weight: 600;
                    cursor: pointer;
                    transition: background-color 0.3s, transform 0.2s;
                    color: white;
                }
                .btn-primary {
                    background-color: var(--primary-color);
                }
                .btn-primary:hover {
                    background-color: var(--primary-hover);
                    transform: translateY(-2px);
                }
                .toggle-link {
                    display: block;
                    text-align: center;
                    margin-top: 20px;
                    color: var(--primary-color);
                    text-decoration: none;
                    font-size: 14px;
                    transition: color 0.3s;
                }
                .toggle-link:hover {
                    color: var(--primary-hover);
                }
                .flash {
                    padding: 12px;
                    margin-bottom: 20px;
                    border-radius: 8px;
                    text-align: center;
                    font-weight: bold;
                    color: white;
                }
                .flash.error { background-color: var(--danger-color); }
                .flash.success { background-color: var(--success-color); }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="logo">📈</div>
                <div id="flash-message"></div>
                <form id="login-form" class="auth-form" action="{{ url_for('login') }}" method="post">
                    <h2>เข้าสู่ระบบ</h2>
                    <div class="form-group">
                        <input type="text" id="username_login" name="username" placeholder="ชื่อผู้ใช้" required>
                    </div>
                    <div class="form-group">
                        <input type="password" id="password_login" name="password" placeholder="รหัสผ่าน" required>
                    </div>
                    <button type="submit" class="btn btn-primary">เข้าสู่ระบบ</button>
                    <a href="#" onclick="showRegisterForm()" class="toggle-link">ไม่มีบัญชี? สมัครที่นี่</a>
                </form>

                <form id="register-form" class="auth-form" action="{{ url_for('register') }}" method="post" style="display:none;">
                    <h2>สมัครสมาชิก</h2>
                    <div class="form-group">
                        <input type="text" id="username_register" name="username" placeholder="ชื่อผู้ใช้" required>
                    </div>
                    <div class="form-group">
                        <input type="password" id="password_register" name="password" placeholder="รหัสผ่าน" required>
                    </div>
                    <button type="submit" class="btn btn-primary">สมัครสมาชิก</button>
                    <a href="#" onclick="showLoginForm()" class="toggle-link">มีบัญชีแล้ว? เข้าสู่ระบบ</a>
                </form>
            </div>
            <script>
                function showMessage(type, message) {
                    const flash = document.getElementById('flash-message');
                    flash.innerHTML = `<div class="flash ${type}">${message}</div>`;
                }

                function showRegisterForm() {
                    document.getElementById('login-form').style.display = 'none';
                    document.getElementById('register-form').style.display = 'block';
                    document.getElementById('flash-message').innerHTML = '';
                    document.querySelector('.container h2').innerText = 'สมัครสมาชิก';
                }
                function showLoginForm() {
                    document.getElementById('register-form').style.display = 'none';
                    document.getElementById('login-form').style.display = 'block';
                    document.getElementById('flash-message').innerHTML = '';
                    document.querySelector('.container h2').innerText = 'เข้าสู่ระบบ';
                }
                document.getElementById('login-form').onsubmit = async (e) => {
                    e.preventDefault();
                    const formData = new FormData(e.target);
                    const response = await fetch('/login', { method: 'POST', body: formData });
                    const result = await response.json();
                    if (result.success) {
                        window.location.href = '/dashboard';
                    } else {
                        showMessage('error', result.message);
                    }
                };
                document.getElementById('register-form').onsubmit = async (e) => {
                    e.preventDefault();
                    const formData = new FormData(e.target);
                    const response = await fetch('/register', { method: 'POST', body: formData });
                    const result = await response.json();
                    showMessage(result.success ? 'success' : 'error', result.message);
                    if (result.success) {
                        e.target.reset();
                        showLoginForm();
                    }
                };
            </script>
        </body>
        </html>
    """)

@app.route('/login', methods=['POST'])
def login():
    username = request.form.get('username')
    password = request.form.get('password')
    # แก้ไข Pyright Error: username อาจเป็น None
    if not username:
        return jsonify(success=False, message="ชื่อผู้ใช้ไม่ถูกต้อง"), 400

    with get_db() as db:
        if username in db:
            user_data = db[username]
            user = User(username)
            user.password_hash = user_data.password_hash
            if user.check_password(password):
                login_user(user)
                return jsonify(success=True, message="เข้าสู่ระบบสำเร็จ!")
    return jsonify(success=False, message="ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")

@app.route('/register', methods=['POST'])
def register():
    username = request.form.get('username')
    password = request.form.get('password')
    # แก้ไข Pyright Error: username อาจเป็น None
    if not username:
        return jsonify(success=False, message="ชื่อผู้ใช้ไม่ถูกต้อง"), 400

    with get_db() as db:
        if username in db:
            return jsonify(success=False, message="ชื่อผู้ใช้นี้ถูกใช้งานแล้ว")
        user = User(username)
        user.set_password(password)
        db[username] = user
    return jsonify(success=True, message="สมัครสมาชิกสำเร็จ! กรุณาเข้าสู่ระบบ")

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    user_id = current_user.get_id()
    # แก้ไข Pyright Error: user_id อาจเป็น None
    if user_id is None:
        return redirect(url_for('index'))

    with get_db() as db:
        user_data = db[user_id]
        targets = user_data.targets

    return render_template_string("""
        <!doctype html>
        <html lang="th">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no">
            <title>Dashboard</title>
            <link href="https://fonts.googleapis.com/css2?family=Kanit:wght@300;400;600&display=swap" rel="stylesheet">
            <style>
                :root {
                    --primary-color: #1a73e8;
                    --primary-hover: #1669c7;
                    --success-color: #28a745;
                    --success-hover: #218838;
                    --danger-color: #dc3545;
                    --danger-hover: #c82333;
                    --bg-color: #f0f2f5;
                    --card-bg: white;
                    --text-color: #333;
                    --light-text-color: #666;
                    --border-color: #e0e0e0;
                }
                body {
                    font-family: 'Kanit', sans-serif;
                    background-color: var(--bg-color);
                    color: var(--text-color);
                    margin: 0;
                    padding: 20px;
                }
                .container {
                    width: 95%;
                    max-width: 900px;
                    margin: auto;
                    padding: 30px;
                    border-radius: 15px;
                    background-color: var(--card-bg);
                    box-shadow: 0 10px 30px rgba(0,0,0,0.1);
                }
                .header {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    margin-bottom: 30px;
                    flex-wrap: wrap;
                    gap: 15px;
                }
                .header h2 {
                    color: var(--primary-color);
                    margin: 0;
                }
                .header .logout-btn {
                    background-color: var(--danger-color);
                    color: white;
                    padding: 10px 20px;
                    border-radius: 8px;
                    text-decoration: none;
                    transition: background-color 0.3s;
                }
                .header .logout-btn:hover {
                    background-color: var(--danger-hover);
                }
                .form-section {
                    background-color: #fafafa;
                    padding: 25px;
                    border-radius: 12px;
                    margin-bottom: 30px;
                    border: 1px solid var(--border-color);
                }
                .form-section h3 {
                    margin-top: 0;
                    color: var(--text-color);
                    border-bottom: 2px solid var(--primary-color);
                    padding-bottom: 10px;
                    margin-bottom: 20px;
                }
                .form-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                    gap: 15px;
                    align-items: end;
                }
                .form-group label {
                    display: block;
                    margin-bottom: 8px;
                    font-weight: 600;
                    color: var(--light-text-color);
                }
                .form-group input, .form-group select {
                    width: 100%;
                    padding: 12px;
                    border: 1px solid var(--border-color);
                    border-radius: 8px;
                    box-sizing: border-box;
                    font-size: 16px;
                }
                .btn {
                    padding: 12px 20px;
                    border: none;
                    border-radius: 8px;
                    cursor: pointer;
                    font-size: 16px;
                    font-weight: 600;
                    transition: background-color 0.3s;
                    color: white;
                }
                .btn-success { background-color: var(--success-color); }
                .btn-success:hover { background-color: var(--success-hover); }
                .btn-danger { background-color: var(--danger-color); }
                .btn-danger:hover { background-color: var(--danger-hover); }

                .list-section h3 {
                    margin-top: 0;
                    color: var(--text-color);
                    border-bottom: 2px solid var(--primary-color);
                    padding-bottom: 10px;
                    margin-bottom: 20px;
                }
                .target-item {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    padding: 15px;
                    margin-bottom: 15px;
                    border-radius: 12px;
                    background-color: #fcfcfc;
                    box-shadow: 0 4px 10px rgba(0,0,0,0.05);
                }
                .target-details strong {
                    font-size: 1.1em;
                    color: var(--primary-color);
                }
                .target-details span {
                    color: var(--light-text-color);
                }
                .no-targets {
                    text-align: center;
                    color: var(--light-text-color);
                    padding: 20px;
                    border: 1px dashed var(--border-color);
                    border-radius: 10px;
                }
                @media (max-width: 600px) {
                    .header { flex-direction: column; text-align: center; }
                    .header .logout-btn { width: 100%; }
                    .form-grid { grid-template-columns: 1fr; }
                    .btn { margin-top: 15px; }
                }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>สวัสดี, {{ current_user.get_id() }}</h2>
                    <a href="{{ url_for('logout') }}" class="logout-btn">ออกจากระบบ</a>
                </div>

                <div class="form-section">
                    <h3>🔔 ตั้งค่าแจ้งเตือนหุ้นใหม่</h3>
                    <form id="set-target-form">
                        <div class="form-grid">
                            <div class="form-group">
                                <label for="symbol">ชื่อหุ้น:</label>
                                <input type="text" id="symbol" name="symbol" placeholder="เช่น AAPL หรือ PTT.BK" required>
                            </div>
                            <div class="form-group">
                                <label for="target_price">ราคาเป้าหมาย (บาท):</label>
                                <input type="number" step="0.01" id="target_price" name="target_price" placeholder="ระบุราคาเป็นตัวเลข" required>
                            </div>
                            <div class="form-group">
                                <label for="trigger_type">เงื่อนไข:</label>
                                <select id="trigger_type" name="trigger_type">
                                    <option value="below">ราคาต่ำกว่า/เท่ากับ</option>
                                    <option value="above">ราคาสูงกว่า/เท่ากับ</option>
                                </select>
                            </div>
                            <div class="form-group" style="align-self: flex-end;">
                                <button type="submit" class="btn btn-success" style="width:100%;">ตั้งค่า</button>
                            </div>
                        </div>
                    </form>
                </div>

                <div class="list-section">
                    <h3>📋 รายการแจ้งเตือนของคุณ</h3>
                    <div id="target-list-container">
                        {% if targets %}
                            {% for symbol, data in targets.items() %}
                                <div class="target-item">
                                    <div class="target-details">
                                        <strong>{{ symbol }}</strong>:
                                        <span>เป้าหมาย {{ data.target }} บาท</span><br>
                                        <span>เงื่อนไข: {{ 'ราคาต่ำกว่า/เท่ากับ' if data.trigger_type == 'below' else 'ราคาสูงกว่า/เท่ากับ' }}</span>
                                    </div>
                                    <button class="btn btn-danger" onclick="deleteTarget('{{ symbol }}')">ลบ</button>
                                </div>
                            {% endfor %}
                        {% else %}
                            <p class="no-targets">ยังไม่มีการตั้งค่าเป้าหมาย กรุณาเพิ่มรายการใหม่ด้านบน</p>
                        {% endif %}
                    </div>
                </div>
            </div>

            <script>
                document.getElementById('set-target-form').onsubmit = async (e) => {
                    e.preventDefault();
                    const form = e.target;
                    const formData = new FormData(form);
                    const data = Object.fromEntries(formData.entries());

                    const submitBtn = form.querySelector('button');
                    submitBtn.disabled = true;
                    submitBtn.innerText = 'กำลังบันทึก...';

                    try {
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
                    } catch (error) {
                        alert('เกิดข้อผิดพลาดในการเชื่อมต่อ');
                    } finally {
                        submitBtn.disabled = false;
                        submitBtn.innerText = 'ตั้งค่า';
                    }
                };

                async function deleteTarget(symbol) {
                    if (!confirm(`คุณต้องการลบเป้าหมายของหุ้น ${symbol} หรือไม่?`)) return;

                    try {
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
                    } catch (error) {
                        alert('เกิดข้อผิดพลาดในการลบเป้าหมาย');
                    }
                }
            </script>
        </body>
        </html>
    """, targets=targets)

# --- API Endpoints ---
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

    with get_db() as db:
        # แก้ไข Pyright Error: current_user.get_id() อาจเป็น None
        user_id = current_user.get_id()
        if user_id is None:
            return jsonify(success=False, message="ไม่พบข้อมูลผู้ใช้"), 401

        user_data = db[user_id]
        if not hasattr(user_data, 'targets'):
            user_data.targets = {}
        user_data.targets[symbol] = {
            'target': target_price,
            'trigger_type': trigger_type,
            'notified': False
        }
        db[user_id] = user_data

    return jsonify(success=True, message=f"✅ ตั้งเป้าหมายสำหรับ **{symbol}** ที่ **{target_price}** บาทเรียบร้อยแล้ว")

@app.route('/api/delete_target', methods=['POST'])
@login_required
def api_delete_target():
    data = request.json
    symbol = data.get('symbol', '').upper()

    # แก้ไข Pyright Error: current_user.get_id() อาจเป็น None
    user_id = current_user.get_id()
    if user_id is None:
        return jsonify(success=False, message="ไม่พบข้อมูลผู้ใช้"), 401

    with get_db() as db:
        user_data = db[user_id]
        if hasattr(user_data, 'targets') and symbol in user_data.targets:
            del user_data.targets[symbol]
            db[user_id] = user_data
            return jsonify(success=True, message=f"🗑️ ลบเป้าหมายสำหรับ **{symbol}** เรียบร้อยแล้ว")
        else:
            return jsonify(success=False, message="❌ ไม่พบเป้าหมายที่คุณตั้งไว้"), 404

# --- Stock Check and Telegram Bot Logic ---
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

def send_telegram_notification(message: str):
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    data = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'Markdown'
    }
    try:
        response = requests.post(url, data=data)
        if response.status_code != 200:
            logger.error(f"Failed to send Telegram notification: {response.text}")
    except Exception as e:
        logger.error(f"Error sending Telegram notification: {e}")

def run_stock_checker():
    while True:
        logger.info("เริ่มตรวจสอบราคาหุ้น...")
        with get_db() as db:
            users_to_check = list(db.keys())
            for user_id in users_to_check:
                # แก้ไข Pyright Error: user_id อาจเป็น None
                if user_id is None:
                    continue
                try:
                    # แก้ไข Pyright Error: 'user_data' อาจเป็น None
                    user_data = db.get(user_id)
                    if user_data is None:
                        continue

                    if not hasattr(user_data, 'targets'):
                        continue

                    targets_to_check = list(user_data.targets.items())
                    for symbol, data in targets_to_check:
                        target = data.get('target')
                        trigger_type = data.get('trigger_type', 'below')
                        notified = data.get('notified', False)

                        if notified:
                            continue

                        current_price = fetch_price_blocking(symbol)
                        if current_price is None:
                            continue

                        should_notify = False
                        if trigger_type == 'below' and current_price <= target:
                            should_notify = True
                        elif trigger_type == 'above' and current_price >= target:
                            should_notify = True

                        if should_notify:
                            message = f"📢 *แจ้งเตือนหุ้นถึงเป้าหมาย!*\n\n" \
                                      f"ผู้ใช้: `{user_id}`\n" \
                                      f"หุ้น: `{symbol}`\n" \
                                      f"ราคาปัจจุบัน: `{current_price} บาท`\n" \
                                      f"ราคาเป้าหมาย: `{target} บาท`"
                            send_telegram_notification(message)

                            user_data.targets[symbol]["notified"] = True
                            db[user_id] = user_data

                except KeyError:
                    logger.warning(f"User {user_id} removed while checking stocks.")
                except Exception as e:
                    logger.error(f"An error occurred during stock check for {user_id}: {e}")

        # แก้ไขโค้ดส่วนนี้ให้รอ 60 วินาที
        time.sleep(60)

# --- Main Entry Point ---
if __name__ == "__main__":
    Thread(target=run_stock_checker, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
