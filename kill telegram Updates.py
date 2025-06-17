import requests

asp_agentbot = "8048656293:AAHlZUYeR0Iv4rtZ0cAPvWq6vwBgZmq8XUE"
asp_imgtoolbot = "7439461370:AAGyyRmuakhU0QZO9vvsabeE39uAPVuSaDg"
asp_testbot = "7795014034:AAEhWsQJWqOaGtMZwcwi0JEbZAptbiWSeh0"
TG_TOKEN_PROVIDED =  asp_agentbot

def clear_updates():
    url = f"https://api.telegram.org/bot{TG_TOKEN_PROVIDED}/getUpdates"
    
    # ابتدا لیست آپدیت‌ها رو می‌گیریم
    response = requests.get(url)
    data = response.json()

    if not data["ok"]:
        print("❌Error when getting updates.  ", data)
        return

    updates = data["result"]
    print(f"✅Number of Updates: {len(updates)}")

    if updates:
        last_update_id = updates[-1]["update_id"]
        # یک درخواست دیگه با offset بزرگ‌تر برای پاک‌سازی
        clear_url = f"{url}?offset={last_update_id + 1}"
        requests.get(clear_url)
        print("✅Updates deleted successfully")
    else:
        print("📭There is no update for deleting")

if __name__ == "__main__":
    clear_updates()