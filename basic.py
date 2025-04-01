import os
import click  # Import the click library
from terminal_shop import Terminal, APIStatusError, _models as models  # Changed import per error suggestion
from dotenv import load_dotenv
from rich import print # Use rich for pretty printing
import time
from typing import Optional, List # For type hints

load_dotenv()

# --- Configuration ---
BEARER_TOKEN = os.environ.get("TERMINAL_BEARER_TOKEN")
ENVIRONMENT = "dev" # Keep using sandbox for exploration

# Sample data (used by place-order command)
ORDER_DATA = {
    "email": "joshua.yorko@gmail.com",
    "address": {
        "name": "CODE GORILLA",
        "street1": "42 Binary Jungle",
        "city": "Silicon Forest",
        "zip": "94107",
        "country": "US"
    },
    "card_token": "tok_visa",
    "product_variant_id": "var_01JNH7GTF9FBA62Y0RT0WMK3BT", # Flow coffee - CHECK IF STILL VALID IN SANDBOX
    "quantity": 1
}

# --- API Client ---
if not BEARER_TOKEN:
    # Use click.UsageError for CLI context
    raise click.UsageError("TERMINAL_BEARER_TOKEN not found in environment variables. Please set it in a .env file or the environment.")

# Initialize client globally for simplicity in this script
try:
    client = Terminal(
        bearer_token=BEARER_TOKEN,
        environment=ENVIRONMENT,
    )
except Exception as e:
     # Catch potential initialization errors
    raise click.UsageError(f"Failed to initialize Terminal client: {e}")

# --- Helper Functions (Mostly Unchanged) ---

def get_id_from_response(response_data):
    if isinstance(response_data, str):
        return response_data
    elif hasattr(response_data, 'id'):
        return response_data.id
    else:
        print(f"⚠️ Warning: Could not extract ID from response data: {response_data}")
        return None

def safe_get_list_data(response_data):
    if response_data is None:
        return []
    # Check if it's already a list or tuple before trying to list() it
    if isinstance(response_data, (list, tuple)):
        return response_data
    return list(response_data) if hasattr(response_data, '__iter__') else []

# --- Click Command Group ---
@click.group()
def cli():
    """
    A CLI tool to explore the Terminal Shop API using the Python SDK.
    Helps inspect data structures returned by various API calls.
    """
    print(f"🚀 Initialized Terminal Client for environment: [bold cyan]{ENVIRONMENT}[/]")
    pass

# --- API Interaction Functions as Commands ---

@cli.command(name="list-products")
def list_products_command():
    """Lists available products from the Terminal shop."""
    print("\n🛍️ Listing all products...")
    try:
        products_response = client.product.list()
        # Access the actual list of products, often in response.data
        # Adjust based on the actual SDK response structure if needed
        product_list: List[models.Product] = safe_get_list_data(getattr(products_response, 'data', None))

        if not product_list:
            print("ℹ️ No products found or response structure unexpected.")
            return

        print(f"✅ Found {len(product_list)} products.")
        # Print each product object using rich for inspection
        for i, product in enumerate(product_list):
             print(f"\n--- Product {i+1} ---")
             print(product)
             # You could print specific fields too:
             # print(f"  ID: {getattr(product, 'id', 'N/A')}")
             # print(f"  Name: {getattr(product, 'name', 'N/A')}")
             # print(f"  Variants: {getattr(product, 'variants', [])}") # Variants might be complex
        print("\n--------------------")

    except Exception as e:
        print(f"❌ Error listing products: {e}")

@cli.command(name="update-profile")
@click.option('--name', default=ORDER_DATA["address"]["name"], help='Name for the profile.')
@click.option('--email', default=ORDER_DATA["email"], help='Email for the profile.')
def update_profile_command(name: str, email: str):
    """Updates the user profile."""
    print(f"📝 Updating profile to Name: '{name}', Email: '{email}'...")
    try:
        profile_response = client.profile.update(name=name, email=email)
        print("✅ Profile update response:")
        print(getattr(profile_response, 'data', profile_response)) # Print data if available
    except Exception as e:
        print(f"❌ Error updating profile: {e}")

@cli.command(name="create-address")
# Add options for address details, defaulting to sample data
@click.option('--name', default=ORDER_DATA["address"]["name"])
@click.option('--street1', default=ORDER_DATA["address"]["street1"])
@click.option('--city', default=ORDER_DATA["address"]["city"])
@click.option('--zip', default=ORDER_DATA["address"]["zip"])
@click.option('--country', default=ORDER_DATA["address"]["country"])
def create_address_command(name, street1, city, zip, country):
    """Creates a shipping address."""
    address_payload = {
        "name": name,
        "street1": street1,
        "city": city,
        "zip": zip,
        "country": country
    }
    print("\n📦 Creating shipping address with payload:")
    print(address_payload)
    try:
        address_response = client.address.create(**address_payload)
        address_id = get_id_from_response(getattr(address_response, 'data', address_response))
        print(f"✅ Address create response (ID): {address_id}")
        print("Full response object:")
        print(getattr(address_response, 'data', address_response))
    except Exception as e:
        print(f"❌ Error creating address: {e}")


@cli.command(name="create-card")
@click.option('--token', default=ORDER_DATA["card_token"], help="Stripe card token (e.g., tok_visa).")
def create_card_command(token: str):
    """Creates/registers a card using a token."""
    print(f"\n💳 Creating card with token: {token}...")
    try:
        card_response = client.card.create(token=token)
        card_id = get_id_from_response(getattr(card_response, 'data', card_response))
        print(f"✅ Card create response (ID): {card_id}")
        print("Full response object:")
        print(getattr(card_response, 'data', card_response))
    except APIStatusError as e:
         # Simplified check for already exists
         if e.status_code == 400 and "already_exists" in str(e.body).lower():
             print(f"ℹ️ Card with token '{token}' likely already exists.")
         else:
            print(f"❌ API Error creating card: {e}")
            print(f"   Body: {e.body}")
    except Exception as e:
        print(f"❌ Error creating card: {e}")

@cli.command(name="place-order")
@click.option('--variant-id', default=ORDER_DATA["product_variant_id"], help="Product Variant ID to order.")
@click.option('--quantity', default=ORDER_DATA["quantity"], type=int, help="Quantity to order.")
@click.option('--address-id', default=None, help="Existing Address ID (shp_...). If omitted, attempts to create/get default.")
@click.option('--card-id', default=None, help="Existing Card ID (crd_...). If omitted, attempts to create/get default.")
def place_order_command(variant_id: str, quantity: int, address_id: Optional[str], card_id: Optional[str]):
    """Runs the full sequence: update profile, create/get address & card, create order."""
    print("[bold yellow]--- Running Full Order Sequence ---[/]")
    try:
        # 1. Update Profile (using defaults from ORDER_DATA)
        print("➡️ Step 1: Updating profile...")
        profile_data = ORDER_DATA["address"]["name"]
        email_data = ORDER_DATA["email"]
        profile_response = client.profile.update(name=profile_data, email=email_data)
        print(f"✅ Profile updated.") # Don't print full object here unless needed

        # 2. Get/Create Address
        print("\n➡️ Step 2: Handling Address...")
        if not address_id:
            print("  (No Address ID provided, attempting create/verify default)")
            addr_payload = ORDER_DATA["address"].copy()
            addr_payload.pop("state", None) # Remove unsupported field
            address_create_response = client.address.create(**addr_payload)
            address_id = get_id_from_response(getattr(address_create_response, 'data', address_create_response))
            if not address_id:
                 raise ValueError("Failed to get Address ID after creation.")
            print(f"✅ Default Address created/verified: {address_id}")
        else:
            print(f"✅ Using provided Address ID: {address_id}")


        # 3. Get/Create Card
        print("\n➡️ Step 3: Handling Card...")
        if not card_id:
            print("  (No Card ID provided, attempting create/verify default)")
            try:
                card_create_response = client.card.create(token=ORDER_DATA["card_token"])
                card_id = get_id_from_response(getattr(card_create_response, 'data', card_create_response))
                print(f"✅ Default Card created: {card_id}")
            except APIStatusError as e:
                 if e.status_code == 400 and e.body and e.body.get("code") == "already_exists":
                    print("  Card already exists. Listing...")
                    cards_response = client.card.list()
                    card_list: List[models.Card] = safe_get_list_data(getattr(cards_response, 'data', None))
                    if card_list:
                         # Assume first card matches the token for simplicity
                         card_id = card_list[0].id
                         print(f"✅ Using existing default Card ID: {card_id}")
                    else:
                         raise Exception("No existing card found despite 'already_exists' error.") from e
                 else:
                    raise # Re-raise other API errors
            if not card_id:
                raise ValueError("Failed to get Card ID after creation/lookup.")
        else:
            print(f"✅ Using provided Card ID: {card_id}")

        # 4. Create Order
        print("\n➡️ Step 4: Creating Order...")
        order_create_response = client.order.create(
            address_id=address_id,
            card_id=card_id,
            variants={variant_id: quantity}
        )
        created_order_id = get_id_from_response(getattr(order_create_response, 'data', order_create_response))
        if not created_order_id:
             raise ValueError("Failed to get Order ID after creation.")
        print(f"✅ Order created: {created_order_id}")

        # 5. Get details of the created order
        print("\n➡️ Step 5: Fetching details of created order...")
        print("  (Waiting 2 seconds for API...)")
        time.sleep(2)
        order_get_response = client.order.get(created_order_id)
        print("✅ Created order details:")
        print(getattr(order_get_response, 'data', order_get_response))

        print("\n[bold green]--- Full Order Sequence Complete ---[/]")

    except Exception as e:
        print(f"\n💥 Order sequence failed: {e}")


@cli.command(name="list-orders")
def list_orders_command():
    """Lists all orders for the current user."""
    print("\n📜 Listing all orders...")
    try:
        orders_response = client.order.list()
        order_list: List[models.Order] = safe_get_list_data(getattr(orders_response, 'data', None))

        if not order_list:
            print("ℹ️ No orders found.")
            return

        print(f"✅ Found {len(order_list)} orders.")
        for i, order in enumerate(order_list):
            print(f"\n--- Order {i+1} ---")
            # Print the full order object for structure inspection
            print(order)
            # Specifically check tracking details
            tracking_info = getattr(order, 'tracking', None)
            tracking_number = getattr(tracking_info, 'number', 'N/A') if tracking_info else 'N/A'
            print(f"  Tracking Number: {tracking_number}")
        print("\n--------------------")

    except Exception as e:
        print(f"❌ Error listing orders: {e}")

@cli.command(name="get-order")
@click.argument('order_id')
def get_order_details_command(order_id: str):
    """Gets details for a specific order ID."""
    print(f"\n🔍 Getting details for order {order_id}...")
    try:
        order_details_response = client.order.get(order_id)
        print(f"✅ Order details response object:")
        # Print the full data object
        print(getattr(order_details_response, 'data', order_details_response))
    except APIStatusError as e:
        if e.status_code == 404:
            print(f"⚠️ Order {order_id} not found.")
        else:
            print(f"❌ API Error getting order details: {e}")
            print(f"   Body: {e.body}")
    except Exception as e:
        print(f"❌ Error getting order details: {e}")


# --- Main Execution Hook ---
if __name__ == "__main__":
    cli()