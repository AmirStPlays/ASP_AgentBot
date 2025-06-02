from flask import Flask
import threading

app = Flask(__name__)

@app.route('/')
def home():
    return "OK - bot is alive ✅"

def keep_alive():
    def run():
        app.run(host="0.0.0.0", port=8080)  # Render پورت 8080 رو می‌خواد
    thread = threading.Thread(target=run)
    thread.start()
