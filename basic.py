import os
from terminal_shop import Terminal
from dotenv import load_dotenv
from rich import print

load_dotenv()

client = Terminal(
    bearer_token=os.environ.get("TERMINAL_BEARER_TOKEN"),
    environment="dev",
)

# Sample order data (same as in our CoffeeOrder CR)
order_data = {
    "email": "joshua.yorko@gmail.com",
    "address": {
        "name": "CODE GORILLA",
        "street1": "42 Binary Jungle",
        "city": "Silicon Forest",
        # "state": "CA",  # Removed: not accepted by the Terminal API for address creation
        "zip": "94107",
        "country": "US"
    },
    "card_token": "tok_visa",
    "product_variant_id": "var_01JNH7GTF9FBA62Y0RT0WMK3BT",
    "quantity": 1
}

try:
    # 1. Update user profile
    print("📝 Updating profile...")
    profile_response = client.profile.update(
        name=order_data["address"]["name"],
        email=order_data["email"]
    )
    print(f"✅ Profile updated: {profile_response.data}")

    # 2. Create shipping address
    print("\n📦 Creating shipping address...")
    # Remove any unexpected keys (e.g., 'state')
    address_payload = order_data["address"].copy()
    address_payload.pop("state", None)
    address_response = client.address.create(**address_payload)
    
    # Determine the address_id based on response type
    if isinstance(address_response.data, str):
        address_id = address_response.data
    else:
        address_id = address_response.data.id
    print(f"✅ Address created: {address_id}")

    # 3. Create card using the test token
    print("\n💳 Creating card...")
    try:
        card_response = client.card.create(token=order_data["card_token"])
        card_id = card_response.data.id
        print(f"✅ Card created: {card_id}")
    except Exception as e:
        # If the card already exists, list existing cards and use the first one
        if "already_exists" in str(e):
            print("💳 Card already exists. Listing existing cards...")
            cards_response = client.card.list()
            card_list = list(cards_response.data) if hasattr(cards_response.data, '__iter__') else []
            if card_list:
                card_id = card_list[0].id
                print(f"✅ Using existing card: {card_id}")
            else:
                raise Exception("No existing card found despite 'already_exists' error.")
        else:
            raise

    # 4. Create order directly (without using cart)
    print("\n☕ Creating coffee order...")
    order_response = client.order.create(
        address_id=address_id,
        card_id=card_id,
        variants={order_data["product_variant_id"]: order_data["quantity"]}
    )
    # Determine the order_id based on response type
    if isinstance(order_response.data, str):
        order_id = order_response.data
    else:
        order_id = order_response.data.id
    print(f"✅ Order created: {order_id}")

except Exception as e:
    print(f"❌ Error: {e}")
