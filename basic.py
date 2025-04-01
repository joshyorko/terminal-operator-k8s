import os
from terminal_shop import Terminal, APIStatusError
from dotenv import load_dotenv
from rich import print
import time

load_dotenv()

# --- Configuration ---
BEARER_TOKEN = os.environ.get("TERMINAL_BEARER_TOKEN")
ENVIRONMENT = "dev"

# Sample order data
ORDER_DATA = {
    "email": "joshua.yorko@gmail.com",
    "address": {
        "name": "CODE GORILLA",
        "street1": "42 Binary Jungle",
        "city": "Silicon Forest",
        "zip": "94107",
        "country": "US"
        # state is intentionally omitted as it's not supported by create
    },
    "card_token": "tok_visa", # Standard Stripe test token
    "product_variant_id": "var_01JNH7GTF9FBA62Y0RT0WMK3BT", # Flow coffee
    "quantity": 1
}

# --- API Client ---
if not BEARER_TOKEN:
    raise ValueError("TERMINAL_BEARER_TOKEN not found in environment variables.")

client = Terminal(
    bearer_token=BEARER_TOKEN,
    environment=ENVIRONMENT,
)

# --- Helper Functions ---

def get_id_from_response(response_data):
    """Safely extracts ID from API response data."""
    if isinstance(response_data, str):
        return response_data
    elif hasattr(response_data, 'id'):
        return response_data.id
    else:
        raise ValueError(f"Could not extract ID from response data: {response_data}")

def safe_get_list_data(response_data):
    """Safely gets list data, handling None or non-iterable."""
    if response_data is None:
        return []
    return list(response_data) if hasattr(response_data, '__iter__') else []

# --- API Interaction Functions ---

def update_profile(name, email):
    """Updates the user profile."""
    print("📝 Updating profile...")
    try:
        profile_response = client.profile.update(name=name, email=email)
        print(f"✅ Profile updated: {profile_response.data}")
        return profile_response.data
    except Exception as e:
        print(f"❌ Error updating profile: {e}")
        raise

def create_or_get_address(address_payload):
    """Creates a shipping address or potentially finds an existing identical one."""
    print("\n📦 Creating/Verifying shipping address...")
    # Remove unsupported keys before sending
    payload = address_payload.copy()
    payload.pop("state", None)
    try:
        address_response = client.address.create(**payload)
        address_id = get_id_from_response(address_response.data)
        print(f"✅ Address created/verified: {address_id}")
        return address_id
    except Exception as e:
        print(f"❌ Error creating address: {e}")
        raise

def create_or_get_card(card_token):
    """Creates a card or gets the ID if it already exists."""
    print("\n💳 Creating/Verifying card...")
    try:
        card_response = client.card.create(token=card_token)
        card_id = get_id_from_response(card_response.data)
        print(f"✅ Card created: {card_id}")
        return card_id
    except APIStatusError as e:
        # If the card already exists (400 Bad Request with 'already_exists' code)
        if e.status_code == 400 and e.body and e.body.get("code") == "already_exists":
            print("💳 Card already exists. Listing existing cards...")
            cards_response = client.card.list()
            card_list = safe_get_list_data(cards_response.data)
            if card_list:
                # Assuming the first card is the one we want (could add more logic here)
                existing_card_id = card_list[0].id
                print(f"✅ Using existing card: {existing_card_id}")
                return existing_card_id
            else:
                raise Exception("No existing card found despite 'already_exists' error.") from e
        else:
            print(f"❌ Error creating card: {e}")
            raise
    except Exception as e:
        print(f"❌ Error creating card: {e}")
        raise

def create_order(address_id, card_id, product_variant_id, quantity):
    """Creates an order directly."""
    print("\n☕ Creating coffee order...")
    try:
        order_response = client.order.create(
            address_id=address_id,
            card_id=card_id,
            variants={product_variant_id: quantity}
        )
        order_id = get_id_from_response(order_response.data)
        print(f"✅ Order created: {order_id}")
        return order_id
    except Exception as e:
        print(f"❌ Error creating order: {e}")
        raise

def list_orders():
    """Lists all orders for the current user."""
    print("\n📜 Listing all orders...")
    try:
        orders_response = client.order.list()
        order_list = safe_get_list_data(orders_response.data)
        print(f"✅ Found {len(order_list)} orders.")
        for order in order_list:
            # Assuming the Order object has id and status attributes
            status = getattr(order, 'status', 'Unknown')
            print(f"  - ID: {order.id}, Status: {status}")
        return order_list
    except Exception as e:
        print(f"❌ Error listing orders: {e}")
        return []

def get_order_details(order_id):
    """Gets details for a specific order."""
    print(f"\n🔍 Getting details for order {order_id}...")
    try:
        order_details_response = client.order.get(order_id)
        print(f"✅ Order details retrieved:")
        print(order_details_response.data)
        return order_details_response.data
    except APIStatusError as e:
        if e.status_code == 404:
            print(f"⚠️ Order {order_id} not found.")
            return None
        else:
            print(f"❌ Error getting order details: {e}")
            raise
    except Exception as e:
        print(f"❌ Error getting order details: {e}")
        raise

# --- Main Execution ---
if __name__ == "__main__":
    created_order_id = None
    try:
        # Step 1: Update Profile
        update_profile(name=ORDER_DATA["address"]["name"], email=ORDER_DATA["email"])

        # Step 2: Create/Verify Address
        address_id = create_or_get_address(ORDER_DATA["address"])

        # Step 3: Create/Verify Card
        card_id = create_or_get_card(ORDER_DATA["card_token"])

        # Step 4: Create Order
        created_order_id = create_order(
            address_id=address_id,
            card_id=card_id,
            product_variant_id=ORDER_DATA["product_variant_id"],
            quantity=ORDER_DATA["quantity"]
        )

        # Step 5: Get details of the created order (if successful)
        if created_order_id:
            print("\n⏳ Waiting a moment before fetching details...")
            time.sleep(2) # Give API a moment
            get_order_details(created_order_id)

        # Step 6: List all orders
        list_orders()

    except Exception as e:
        print(f"\n💥 Main script execution failed: {e}")
