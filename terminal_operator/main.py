import os
import logging
import asyncio

import kopf
from dotenv import load_dotenv
from terminal_shop import Terminal, APIStatusError

# Load environment variables from .env file (set externally to .env.dev or .env.prod)
load_dotenv()

# --- Configuration & Client Setup ---
BEARER_TOKEN = os.environ.get("TERMINAL_BEARER_TOKEN")
ENVIRONMENT = os.environ.get("TERMINAL_ENVIRONMENT", "dev")

if not BEARER_TOKEN:
    raise RuntimeError("ANGRY! NO TERMINAL_BEARER_TOKEN FOUND! NEED TOKEN!")

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

terminal_client = Terminal(
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
        logger.warning(f"Could not extract ID from response data: {response_data}")
        return None

def safe_get_list_data(response_data):
    """Safely gets list data, handling None or non-iterable."""
    if response_data is None:
        return []
    return list(response_data) if hasattr(response_data, '__iter__') else []

# --- Operator Handlers ---

@kopf.on.create("coffee.terminal.sh", "v1alpha1", "coffeeorders")
@kopf.on.update("coffee.terminal.sh", "v1alpha1", "coffeeorders")
def handle_coffee_order_creation(spec, status, meta, patch, logger, **kwargs):
    """Handles the creation or update of a CoffeeOrder, focusing on placing the order if not already done."""
    resource_name = meta.get("name")
    generation = meta.get("generation")
    logger.info(f"[Create/Update: {resource_name}] Gen: {generation}. Checking if order needs placement.")

    # Prevent re-processing if order already exists in status
    if status.get("orderId") and status.get("phase") not in ["Failed", "Pending"]:
        logger.info(f"[Create/Update: {resource_name}] Order ID {status['orderId']} already exists. Skipping creation.")
        # If we want to handle spec *changes* (e.g., quantity update), logic would go here
        # But API doesn't support order update, so we mostly just reconcile creation
        # Ensure observedGeneration is updated if spec changed but order exists
        if meta.get('generation') != status.get('observedGeneration'):
            patch.status['observedGeneration'] = meta.get('generation')
            patch.status['message'] = "Spec updated, but order cannot be modified via API after creation."
        return

    # Extract spec details
    product_variant_id = spec.get("productVariantId")
    quantity = spec.get("quantity", 1)
    address_spec = spec.get("address", {})
    card_token = spec.get("cardToken")
    profile_email = spec.get("email") # Renamed to avoid conflict

    # --- Field Validation ---
    if not product_variant_id:
        msg = "ANGRY! NO productVariantId IN SPEC!"
        logger.error(f"[Create/Update: {resource_name}] {msg}")
        patch.status["phase"] = "Failed"
        patch.status["message"] = msg
        raise kopf.PermanentError(msg)
    if not address_spec:
        msg = "CONFUSED! WHERE DELIVER COFFEE? NO address IN SPEC!"
        logger.error(f"[Create/Update: {resource_name}] {msg}")
        patch.status["phase"] = "Failed"
        patch.status["message"] = msg
        raise kopf.PermanentError(msg)
    if not card_token:
        msg = "NEED PAY FOR COFFEE! NO cardToken IN SPEC!"
        logger.error(f"[Create/Update: {resource_name}] {msg}")
        patch.status["phase"] = "Failed"
        patch.status["message"] = msg
        raise kopf.PermanentError(msg)
    if not profile_email:
        msg = "NEED EMAIL FOR ORDER! NO email IN SPEC!"
        logger.error(f"[Create/Update: {resource_name}] {msg}")
        patch.status["phase"] = "Failed"
        patch.status["message"] = msg
        raise kopf.PermanentError(msg)

    # Update status before making API calls
    patch.status["phase"] = "Processing"
    patch.status["message"] = "WORKING HARD TO GET COFFEE!"
    patch.status["observedGeneration"] = generation

    try:
        # 1. Update user profile
        recipient_name = address_spec.get("name", "Kube Coffee Drinker")
        logger.info(f"[Create/Update: {resource_name}] Updating profile for {recipient_name} ({profile_email})...")
        terminal_client.profile.update(name=recipient_name, email=profile_email)
        logger.info(f"[Create/Update: {resource_name}] Profile updated.")

        # 2. Create/Verify Address
        address_payload = address_spec.copy()
        address_payload.pop("state", None)
        logger.info(f"[Create/Update: {resource_name}] Creating/verifying address...")
        address_response = terminal_client.address.create(**address_payload)
        address_id = get_id_from_response(address_response.data)
        if not address_id:
            raise ValueError("Failed to get Address ID from response.")
        logger.info(f"[Create/Update: {resource_name}] Address ID: {address_id}")

        # 3. Create/Verify Card
        card_id = None
        logger.info(f"[Create/Update: {resource_name}] Creating/verifying card...")
        try:
            card_response = terminal_client.card.create(token=card_token)
            card_id = get_id_from_response(card_response.data)
            if not card_id:
                raise ValueError("Failed to get Card ID from create response.")
            logger.info(f"[Create/Update: {resource_name}] Card created: {card_id}")
        except APIStatusError as e:
            if e.status_code == 400 and e.body and e.body.get("code") == "already_exists":
                logger.info(f"[Create/Update: {resource_name}] Card token already exists. Finding existing card...")
                cards_response = terminal_client.card.list()
                card_list = safe_get_list_data(cards_response.data)
                if card_list:
                    card_id = card_list[0].id
                    logger.info(f"[Create/Update: {resource_name}] Using existing card: {card_id}")
                else:
                    raise Exception("No existing card found despite 'already_exists' error.") from e
            else:
                raise
        if not card_id:
            raise ValueError("Card ID could not be determined.")

        # 4. Create Order
        logger.info(f"[Create/Update: {resource_name}] Placing order...")
        order_response = terminal_client.order.create(
            address_id=address_id,
            card_id=card_id,
            variants={product_variant_id: quantity}
        )
        order_id = get_id_from_response(order_response.data)
        if not order_id:
            raise ValueError("Failed to get Order ID from response.")
        logger.info(f"[Create/Update: {resource_name}] Order placed successfully! Order ID: {order_id}")

        # Patch final success status
        patch.status["phase"] = "Ordered"
        patch.status["orderId"] = order_id
        patch.status["message"] = "Order placed successfully via API."

    except Exception as e:
        logger.error(f"[Create/Update: {resource_name}] Order placement failed: {e}", exc_info=True)
        patch.status["phase"] = "Failed"
        patch.status["message"] = f"Order placement error: {e}"
        raise kopf.TemporaryError(f"Order placement failed: {e}", delay=60)

# ---- Periodic Status Check using Timer ----
@kopf.timer("coffee.terminal.sh", "v1alpha1", "coffeeorders", interval=300.0, initial_delay=60)
async def check_order_status(spec, status, meta, patch, logger, **kwargs):
    """Periodically checks the status of placed orders via the Terminal API."""
    resource_name = meta.get("name")
    order_id = status.get("orderId")
    current_phase = status.get("phase")

    # Only check if we have an order ID and the order isn't already in a final state
    final_states = ["Failed", "Delivered", "Cancelled"]
    if not order_id or current_phase in final_states:
        return

    logger.info(f"[Timer: {resource_name}] Checking status for Order ID: {order_id} (Current Phase: {current_phase})")

    try:
        order_details_response = await asyncio.to_thread(terminal_client.order.get, order_id)
        order_data = order_details_response.data

        api_status = getattr(order_data, 'status', None)
        if not api_status:
            logger.warning(f"[Timer: {resource_name}] API response for order {order_id} missing 'status' field: {order_data}")
            return

        logger.info(f"[Timer: {resource_name}] Fetched API status for {order_id}: '{api_status}'")

        # Map API status to our CRD phase
        new_phase = current_phase # Default to no change
        if api_status.lower() == "shipped":
            new_phase = "Shipped"
        elif api_status.lower() == "delivered":
            new_phase = "Delivered"
        elif api_status.lower() == "cancelled":
            new_phase = "Cancelled"

        if new_phase != current_phase:
            logger.info(f"[Timer: {resource_name}] Updating phase from '{current_phase}' to '{new_phase}' based on API.")
            patch.status['phase'] = new_phase
            patch.status['message'] = f"Status updated via API: {api_status}"
        else:
            logger.info(f"[Timer: {resource_name}] API status '{api_status}' does not require phase change from '{current_phase}'.")
            patch.status['message'] = f"Last checked status: {api_status}"

    except APIStatusError as e:
        if e.status_code == 404:
            logger.error(f"[Timer: {resource_name}] Order ID {order_id} not found in Terminal API. Marking as Failed.")
            patch.status['phase'] = "Failed"
            patch.status['message'] = f"Order ID {order_id} not found in API (404)."
        else:
            logger.error(f"[Timer: {resource_name}] API error checking status for {order_id}: {e}")
    except Exception as e:
        logger.error(f"[Timer: {resource_name}] Error checking status for {order_id}: {e}", exc_info=True)

# ---- Deletion Handler ----
@kopf.on.delete("coffee.terminal.sh", "v1alpha1", "coffeeorders")
def handle_coffee_order_deletion(spec, status, meta, logger, **kwargs):
    """Handles the deletion of a CoffeeOrder CR."""
    resource_name = meta.get("name")
    order_id = status.get("orderId")

    logger.info(f"[Delete: {resource_name}] CoffeeOrder CR deleted.")

    if order_id:
        logger.warning(f"[Delete: {resource_name}] Deleting the CoffeeOrder CR does NOT cancel the real order (ID: {order_id}) in the Terminal API.")
        logger.warning(f"[Delete: {resource_name}] The Terminal API does not provide an endpoint to cancel existing orders.")
    else:
        logger.info(f"[Delete: {resource_name}] No associated Terminal order ID found in status. Nothing to do in API.")
