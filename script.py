import requests
import json
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, Optional, List, Set
from datetime import datetime
import os
import unicodedata
import time
import signal
import sys
import socket

# Data directory for persistent storage
DATA_DIR = os.getenv('DATA_DIR', '/app/data')
RESULTS_FILE = os.path.join(DATA_DIR, 'results.json')
PREVIOUS_FILE = os.path.join(DATA_DIR, 'previous_results.json')

# Check interval in seconds (default: 5 minutes)
CHECK_INTERVAL = int(os.getenv('CHECK_INTERVAL', '300'))  # 300 seconds = 5 minutes

# Email timeout in seconds
EMAIL_TIMEOUT = int(os.getenv('EMAIL_TIMEOUT', '30'))

# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)

# Global flag for graceful shutdown
running = True


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global running
    print("\n\n⚠️  Received shutdown signal. Finishing current check...")
    running = False


# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def remove_accents(text: str) -> str:
    """
    Remove accents from Czech characters.
    """
    nfd = unicodedata.normalize('NFD', text)
    return ''.join(char for char in nfd if unicodedata.category(char) != 'Mn')


def search_sreality_clusters(zoom_level: int = 15) -> Optional[Dict[str, Any]]:
    """
    Search for apartments in Poruba using clusters endpoint with very high zoom.
    """

    url = "https://www.sreality.cz/api/v1/estates/search/clusters"

    params = {
        "category_type_cb": "1",
        "category_main_cb": "1",
        "category_sub_cb": "5,4,7,6,9,8,11,10",
        "locality_country_id": "112",
        "locality_search_name": "městská část Poruba, Ostrava",
        "locality_entity_type": "ward",
        "locality_entity_id": "14829",
        "locality_radius": "1",
        "price_to": "5000000",
        "ownership": "1",
        "usable_area_from": "60",
        "lang": "cs",
        "lat_max": "49.87",
        "lat_min": "49.80",
        "lon_max": "18.22",
        "lon_min": "18.12",
        "zoom": str(zoom_level)
    }

    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"❌ Error: {e}")
        return None


def extract_all_estates(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract all estates from clusters response."""
    results = data.get('results', [])
    all_estates = []

    for cluster in results:
        estates = cluster.get('estates', [])
        if estates:
            all_estates.extend(estates)

    return all_estates


def load_previous_results() -> Set[int]:
    """Load previously seen estate IDs from persistent storage."""
    if os.path.exists(PREVIOUS_FILE):
        try:
            with open(PREVIOUS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return set(data.get('estate_ids', []))
        except Exception as e:
            print(f"⚠️  Could not load previous results: {e}")
    return set()


def save_current_results(estate_ids: Set[int]):
    """Save current estate IDs to persistent storage for next comparison."""
    try:
        with open(PREVIOUS_FILE, 'w', encoding='utf-8') as f:
            json.dump({
                'estate_ids': list(estate_ids),
                'last_check': datetime.now().isoformat()
            }, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"❌ Failed to save tracking data: {e}")


def generate_estate_permalink(estate: Dict[str, Any]) -> str:
    """
    Generate permalink to individual estate detail page.
    """
    hash_id = estate.get('hash_id', '')

    category_sub = estate.get('category_sub_cb', {})
    apt_type = category_sub.get('name', '').lower()

    locality = estate.get('locality', {})
    city = locality.get('city', 'ostrava').lower()
    citypart = locality.get('citypart', 'poruba').lower()
    street = locality.get('street', '').lower()

    city = remove_accents(city)
    citypart = remove_accents(citypart)
    street = remove_accents(street)

    city = city.replace(' ', '-').replace('.', '')
    citypart = citypart.replace(' ', '-').replace('.', '')
    street = street.replace(' ', '-').replace('.', '')

    location_part = f"{city}-{citypart}"
    if street:
        location_part += f"-{street}"

    permalink = f"https://www.sreality.cz/detail/prodej/byt/{apt_type}/{location_part}/{hash_id}"

    return permalink


def send_email_notification(new_estates: List[Dict[str, Any]],
                            mail_host: str, mail_port: int,
                            mail_username: str, mail_password: str,
                            mail_from_address: str, mail_from_name: str,
                            recipient_email: str, use_ssl: bool = True):
    """Send email notification about new apartments with timeout."""

    if not new_estates:
        return

    # Create email content
    subject = f"🏠 {len(new_estates)} New Apartment(s) in Poruba, Ostrava!"

    # HTML email body
    html_body = f"""
    <html>
      <head></head>
      <body>
        <h2>🏠 New Apartments Found in Poruba, Ostrava!</h2>
        <p>Found <strong>{len(new_estates)}</strong> new apartment(s) matching your criteria:</p>
        <ul>
          <li>Location: Poruba, Ostrava</li>
          <li>Sizes: 2+1, 2+kk, 3+1, 3+kk, 4+1, 4+kk, 5+1, 5+kk</li>
          <li>Max Price: 5,000,000 CZK</li>
          <li>Min Area: 60 m²</li>
        </ul>
        <hr>
    """

    for i, estate in enumerate(new_estates, 1):
        name = estate.get('advert_name', 'N/A')
        price = estate.get('price_czk', 0)
        price_m2 = estate.get('price_czk_m2', 0)

        locality = estate.get('locality', {})
        city = locality.get('city', '')
        citypart = locality.get('citypart', '')
        street = locality.get('street', '')

        location_parts = [p for p in [street, citypart, city] if p]
        location_str = ', '.join(location_parts)

        permalink = generate_estate_permalink(estate)

        html_body += f"""
        <div style="margin: 20px 0; padding: 15px; border: 1px solid #ddd; border-radius: 5px;">
          <h3>{i}. {name}</h3>
          <p>
            <strong>💰 Price:</strong> {price:,.0f} CZK ({price_m2:,.0f} CZK/m²)<br>
            <strong>📍 Location:</strong> {location_str}<br>
            <strong>🔗 Link:</strong> <a href="{permalink}" style="color: #0066cc;">{permalink}</a>
          </p>
        </div>
        """

    html_body += f"""
        <hr>
        <p style="color: #666; font-size: 12px;">
          This is an automated notification from your Sreality apartment monitor.<br>
          Sent by {mail_from_name} at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        </p>
      </body>
    </html>
    """

    # Create message
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = f"{mail_from_name} <{mail_from_address}>"
    message["To"] = recipient_email

    html_part = MIMEText(html_body, "html")
    message.attach(html_part)

    # Send email with timeout
    try:
        print(f"📧 Sending email to {recipient_email}...")
        print(f"   SMTP: {mail_host}:{mail_port} (SSL: {use_ssl}, Timeout: {EMAIL_TIMEOUT}s)")

        # Set default socket timeout
        socket.setdefaulttimeout(EMAIL_TIMEOUT)

        if use_ssl:
            # Use SSL (port 465)
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(mail_host, mail_port, timeout=EMAIL_TIMEOUT, context=context) as server:
                server.login(mail_username, mail_password)
                server.sendmail(mail_from_address, recipient_email, message.as_string())
        else:
            # Use STARTTLS (port 587)
            with smtplib.SMTP(mail_host, mail_port, timeout=EMAIL_TIMEOUT) as server:
                server.starttls()
                server.login(mail_username, mail_password)
                server.sendmail(mail_from_address, recipient_email, message.as_string())

        print("✅ Email sent successfully!")
        return True

    except socket.timeout:
        print(f"❌ Email timeout after {EMAIL_TIMEOUT}s - SMTP server not responding")
        print(f"   Check if port {mail_port} is blocked by firewall")
        return False
    except smtplib.SMTPAuthenticationError as e:
        print(f"❌ SMTP Authentication failed: {e}")
        print(f"   Check username/password")
        return False
    except smtplib.SMTPException as e:
        print(f"❌ SMTP Error: {e}")
        return False
    except Exception as e:
        print(f"❌ Failed to send email: {e}")
        print(f"   Error type: {type(e).__name__}")
        return False
    finally:
        # Reset socket timeout
        socket.setdefaulttimeout(None)


def check_for_new_apartments(email_config: Dict[str, Any]) -> int:
    """
    Check for new apartments and send notifications.
    Returns the number of new apartments found.
    """

    # Load previous results
    previous_ids = load_previous_results()

    # Search with multiple zoom levels
    zoom_levels = [19, 18, 17, 16]
    best_estates = []

    for zoom in zoom_levels:
        results = search_sreality_clusters(zoom_level=zoom)
        if not results:
            continue

        estates = extract_all_estates(results)

        if len(estates) > len(best_estates):
            best_estates = estates

        if len(estates) >= 11:
            break

    # Get current estate IDs
    current_ids = set(estate.get('hash_id') for estate in best_estates)

    # Find new estates
    new_ids = current_ids - previous_ids
    new_estates = [e for e in best_estates if e.get('hash_id') in new_ids]

    # Find removed estates
    removed_ids = previous_ids - current_ids

    print(f"   Total: {len(best_estates)} | New: {len(new_estates)} 🆕 | Removed: {len(removed_ids)} 🗑️")

    # Display new estates
    if new_estates:
        print("\n🆕 NEW APARTMENTS FOUND:\n")
        for i, estate in enumerate(new_estates, 1):
            name = estate.get('advert_name', 'N/A')
            price = estate.get('price_czk', 0)
            price_m2 = estate.get('price_czk_m2', 0)

            locality = estate.get('locality', {})
            city = locality.get('city', '')
            citypart = locality.get('citypart', '')
            street = locality.get('street', '')

            location_parts = [p for p in [street, citypart, city] if p]
            location_str = ', '.join(location_parts)

            permalink = generate_estate_permalink(estate)

            print(f"{i}. {name}")
            print(f"   💰 {price:,.0f} CZK ({price_m2:,.0f} CZK/m²)")
            print(f"   📍 {location_str}")
            print(f"   🔗 {permalink}")
            print()

        # Send email notification if configured
        if email_config['enabled']:
            success = send_email_notification(
                new_estates,
                email_config['host'],
                email_config['port'],
                email_config['username'],
                email_config['password'],
                email_config['from_address'],
                email_config['from_name'],
                email_config['recipient'],
                email_config['use_ssl']
            )
            if not success:
                print("⚠️  Continuing without email notification...")
        print()

    # Save all results
    output_data = {
        "timestamp": datetime.now().isoformat(),
        "result_count": len(best_estates),
        "new_count": len(new_estates),
        "removed_count": len(removed_ids),
        "estates": best_estates
    }

    try:
        with open(RESULTS_FILE, "w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"❌ Failed to save results: {e}")

    # Save current IDs for next run
    save_current_results(current_ids)

    return len(new_estates)


def main():
    """Main execution with continuous monitoring loop."""

    print("\n" + "=" * 80)
    print("🏠 SREALITY.CZ - PORUBA APARTMENT MONITOR (CONTINUOUS MODE)")
    print("=" * 80)
    print(f"📂 Data directory: {DATA_DIR}")
    print(f"⏱️  Check interval: {CHECK_INTERVAL} seconds ({CHECK_INTERVAL // 60} minutes)")
    print(f"📧 Email timeout: {EMAIL_TIMEOUT} seconds")
    print("=" * 80 + "\n")

    # Email configuration
    MAIL_HOST = os.getenv('MAIL_HOST', 'smtp.m1.websupport.sk')
    MAIL_PORT = int(os.getenv('MAIL_PORT', '465'))
    MAIL_USERNAME = os.getenv('MAIL_USERNAME', '')
    MAIL_PASSWORD = os.getenv('MAIL_PASSWORD', '')
    MAIL_FROM_ADDRESS = os.getenv('MAIL_FROM_ADDRESS', '')
    MAIL_FROM_NAME = os.getenv('MAIL_FROM_NAME', 'Synapps App')
    MAIL_ENCRYPTION = os.getenv('MAIL_ENCRYPTION', 'ssl').lower()
    RECIPIENT_EMAIL = os.getenv('RECIPIENT_EMAIL', '')

    use_ssl = MAIL_PORT == 465 or MAIL_ENCRYPTION == 'ssl'
    email_enabled = all([MAIL_HOST, MAIL_USERNAME, MAIL_PASSWORD, MAIL_FROM_ADDRESS, RECIPIENT_EMAIL])

    email_config = {
        'enabled': email_enabled,
        'host': MAIL_HOST,
        'port': MAIL_PORT,
        'username': MAIL_USERNAME,
        'password': MAIL_PASSWORD,
        'from_address': MAIL_FROM_ADDRESS,
        'from_name': MAIL_FROM_NAME,
        'recipient': RECIPIENT_EMAIL,
        'use_ssl': use_ssl
    }

    if email_enabled:
        print(f"📧 Email notifications: ENABLED")
        print(f"   To: {RECIPIENT_EMAIL}\n")
    else:
        print(f"⚠️  Email notifications: DISABLED\n")

    check_count = 0

    print("🔄 Starting monitoring loop...")
    print("   Press Ctrl+C to stop gracefully\n")
    print("=" * 80 + "\n")

    # Main monitoring loop
    while running:
        check_count += 1
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        print(f"🔍 Check #{check_count} at {timestamp}")

        try:
            new_count = check_for_new_apartments(email_config)

            if new_count == 0:
                print("   ✅ No new apartments\n")

        except Exception as e:
            print(f"   ❌ Error during check: {e}\n")

        print("-" * 80)

        # Sleep until next check
        if running:
            next_check = datetime.now().timestamp() + CHECK_INTERVAL
            next_check_time = datetime.fromtimestamp(next_check).strftime('%H:%M:%S')
            print(f"💤 Sleeping until next check at {next_check_time}...\n")

            sleep_remaining = CHECK_INTERVAL
            while sleep_remaining > 0 and running:
                sleep_chunk = min(sleep_remaining, 10)
                time.sleep(sleep_chunk)
                sleep_remaining -= sleep_chunk

    print("\n" + "=" * 80)
    print("👋 Monitor stopped gracefully")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()