import os
import logging
import asyncio
from typing import Optional

import kopf
from dotenv import load_dotenv
from terminal_shop import Terminal, APIStatusError
from kubernetes import client, config

# Load environment variables from .env file (set externally to .env.dev or .env.prod)
load_dotenv()

# --- Configuration & Client Setup ---
BEARER_TOKEN = os.environ.get("TERMINAL_BEARER_TOKEN")
ENVIRONMENT = os.environ.get("TERMINAL_ENVIRONMENT", "dev")

if not BEARER_TOKEN:
    raise RuntimeError("ANGRY! NO TERMINAL_BEARER_TOKEN FOUND! NEED TOKEN!")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

# --- Resource Reference Resolution ---
def resolve_resource_reference(ref: dict, namespace: str, api: client.CustomObjectsApi, group: str, version: str, plural: str) -> Optional[dict]:
    """Resolves a reference to another custom resource."""
    try:
        resource = api.get_namespaced_custom_object(
            group=group,
            version=version,
            namespace=ref.get('namespace', namespace),
            plural=plural,
            name=ref['name']
        )
        return resource
    except client.exceptions.ApiException as e:
        if e.status == 404:
            return None
        raise

# --- Address Handler ---
@kopf.on.create('coffee.terminal.sh', 'v1alpha1', 'coffeeaddresses')
@kopf.on.update('coffee.terminal.sh', 'v1alpha1', 'coffeeaddresses')
def handle_address(spec, status, meta, patch, logger, **kwargs):
    """Handles CoffeeAddress creation/updates."""
    resource_name = meta['name']
    generation = meta.get('generation')

    # Idempotency: Don't reprocess if already verified and generation matches
    if status.get('addressId') and \
       status.get('phase') == 'Verified' and \
       status.get('observedGeneration') == generation:
        logger.info(f"Address {resource_name} already verified with ID {status['addressId']} for this generation.")
        return

    # Set initial/processing phase immediately
    if status.get('phase') != 'Verified':
        patch.status['phase'] = 'Processing'
        patch.status['message'] = 'Attempting address verification with API'
        patch.status['observedGeneration'] = generation

    # Extract address details
    address_payload = {
        'name': spec['name'],
        'street1': spec['street1'],
        'street2': spec.get('street2'),
        'city': spec['city'],
        'zip': spec['zip'],
        'country': spec['country']
    }
    
    # Filter out None values from payload
    address_payload = {k: v for k, v in address_payload.items() if v is not None}

    try:
        logger.info(f"Creating/verifying address for {resource_name}...")
        address_response = terminal_client.address.create(**address_payload)
        address_id = get_id_from_response(address_response.data)

        if not address_id:
            patch.status['phase'] = 'Failed'
            patch.status['message'] = 'Failed to get address ID from API response despite success'
            logger.error(f"Address {resource_name} verification failed: No address ID in response")
            raise kopf.PermanentError("No address ID in successful API response")

        patch.status['addressId'] = address_id
        patch.status['phase'] = 'Verified'
        patch.status['message'] = 'Address verified successfully'
        patch.status['observedGeneration'] = generation

        logger.info(f"Address {resource_name} verified with ID {address_id}")

    except APIStatusError as e:
        patch.status['phase'] = 'Failed'
        patch.status['message'] = f"API error verifying address: {e.status_code} - {e.body or e.reason}"
        logger.error(f"Address {resource_name} API verification failed: {e}")
        if 400 <= e.status_code < 500:
            raise kopf.PermanentError(f"Address API verification failed permanently: {e}")
        else:
            raise kopf.TemporaryError(f"Address API verification failed: {e}", delay=60)

    except Exception as e:
        patch.status['phase'] = 'Failed'
        patch.status['message'] = f"Unexpected error verifying address: {str(e)}"
        logger.error(f"Address {resource_name} verification failed unexpectedly: {e}", exc_info=True)
        raise kopf.TemporaryError(f"Address verification failed unexpectedly: {e}", delay=60)

# --- Card Handler ---
@kopf.on.create('coffee.terminal.sh', 'v1alpha1', 'coffeecards')
@kopf.on.update('coffee.terminal.sh', 'v1alpha1', 'coffeecards')
def handle_card(spec, status, meta, patch, logger, **kwargs):
    """Handles CoffeeCard creation/updates."""
    resource_name = meta['name']
    generation = meta.get('generation')

    # Idempotency: Don't reprocess if already registered and generation matches
    if status.get('cardId') and \
       status.get('phase') == 'Registered' and \
       status.get('observedGeneration') == generation:
        logger.info(f"Card {resource_name} already registered with ID {status['cardId']} for this generation.")
        return

    # Set initial/processing phase immediately
    if status.get('phase') != 'Registered':
        patch.status['phase'] = 'Processing'
        patch.status['message'] = 'Attempting card registration with API'
        patch.status['observedGeneration'] = generation
    
    try:
        logger.info(f"Registering card for {resource_name}...")
        try:
            card_response = terminal_client.card.create(token=spec['cardToken'])
            card_id = get_id_from_response(card_response.data)
        except APIStatusError as e:
            if e.status_code == 400 and e.body and e.body.get("code") == "already_exists":
                logger.info(f"Card token already exists. Finding existing card...")
                cards_response = terminal_client.card.list()
                card_list = safe_get_list_data(cards_response.data)
                if card_list:
                    card_id = card_list[0].id
                    logger.info(f"Found existing card with ID: {card_id}")
                else:
                    raise Exception("No existing card found despite 'already_exists' error.")
            else:
                raise

        if not card_id:
            patch.status['phase'] = 'Failed'
            patch.status['message'] = 'Failed to get card ID from API response despite success'
            logger.error(f"Card {resource_name} registration failed: No card ID in response")
            raise kopf.PermanentError("No card ID in successful API response")

        patch.status['cardId'] = card_id
        patch.status['phase'] = 'Registered'
        patch.status['message'] = 'Card registered successfully'
        patch.status['observedGeneration'] = generation
        
        logger.info(f"Card {resource_name} registered with ID {card_id}")

    except APIStatusError as e:
        patch.status['phase'] = 'Failed'
        patch.status['message'] = f"API error registering card: {e.status_code} - {e.body or e.reason}"
        logger.error(f"Card {resource_name} API registration failed: {e}")
        if e.status_code != 400 or not e.body or e.body.get("code") != "already_exists":
            if 400 <= e.status_code < 500:
                raise kopf.PermanentError(f"Card API registration failed permanently: {e}")
            else:
                raise kopf.TemporaryError(f"Card API registration failed: {e}", delay=60)

    except Exception as e:
        patch.status['phase'] = 'Failed'
        patch.status['message'] = f"Unexpected error registering card: {str(e)}"
        logger.error(f"Card {resource_name} registration failed unexpectedly: {e}", exc_info=True)
        raise kopf.TemporaryError(f"Card registration failed unexpectedly: {e}", delay=60)

@kopf.on.delete('coffee.terminal.sh', 'v1alpha1', 'coffeecards')
def delete_card(spec, status, meta, logger, **kwargs):
    """Handles CoffeeCard deletion."""
    card_id = status.get('cardId')
    if not card_id:
        logger.info(f"No card ID found for {meta['name']}, nothing to delete")
        return

    try:
        logger.info(f"Deleting card {card_id}...")
        terminal_client.card.delete(card_id)
        logger.info(f"Card {card_id} deleted successfully")
    except Exception as e:
        logger.error(f"Failed to delete card {card_id}: {e}")
        # Don't raise an error here as the resource is being deleted anyway

# --- Operator Handlers ---

@kopf.on.create("coffee.terminal.sh", "v1alpha1", "coffeeorders")
@kopf.on.update("coffee.terminal.sh", "v1alpha1", "coffeeorders")
def handle_coffee_order_creation(spec, status, meta, patch, logger, **kwargs):
    """Handles the creation or update of a CoffeeOrder."""
    resource_name = meta.get("name")
    generation = meta.get("generation")
    namespace = meta.get("namespace", "default")
    logger.info(f"[Create/Update: {resource_name}] Gen: {generation}. Checking if order needs placement.")

    # Prevent re-processing if order already exists
    if status.get("orderId") and status.get("phase") not in ["Failed", "Pending"]:
        logger.info(f"[Create/Update: {resource_name}] Order ID {status['orderId']} already exists.")
        if meta.get('generation') != status.get('observedGeneration'):
            patch.status['observedGeneration'] = meta.get('generation')
            patch.status['message'] = "Spec updated, but order cannot be modified after creation."
        return

    # --- Field Validation ---
    required_refs = {
        'productVariantId': spec.get('productVariantId'),
        'profileRef.name': spec.get('profileRef', {}).get('name'),
        'addressRef.name': spec.get('addressRef', {}).get('name'),
        'cardRef.name': spec.get('cardRef', {}).get('name')
    }
    
    missing_fields = [field for field, value in required_refs.items() if not value]
    if missing_fields:
        msg = f"Missing required fields in spec: {', '.join(missing_fields)}"
        logger.error(f"[Create/Update: {resource_name}] {msg}")
        patch.status["phase"] = "Failed"
        patch.status["message"] = msg
        raise kopf.PermanentError(msg)

    # Update status before making API calls
    patch.status["phase"] = "Processing"
    patch.status["message"] = "Resolving references and preparing order..."
    patch.status["observedGeneration"] = generation

    try:
        # Initialize Kubernetes API client
        api = client.CustomObjectsApi()

        # 1. Resolve Profile reference
        logger.info(f"[Create/Update: {resource_name}] Resolving profile reference...")
        profile = resolve_resource_reference(
            spec['profileRef'], namespace, api,
            'coffee.terminal.sh', 'v1alpha1', 'coffeeprofiles'
        )
        if not profile:
            msg = f"Profile '{spec['profileRef']['name']}' not found"
            logger.error(f"[Create/Update: {resource_name}] {msg}")
            patch.status["phase"] = "Failed"
            patch.status["message"] = msg
            patch.status["profileReadyStatus"] = False
            raise kopf.TemporaryError(msg, delay=60)

        patch.status["profileReadyStatus"] = True

        # Update user profile with Terminal API
        logger.info(f"[Create/Update: {resource_name}] Updating profile...")
        terminal_client.profile.update(
            name=profile['spec']['name'],
            email=profile['spec']['email']
        )

        # 2. Resolve Address reference
        logger.info(f"[Create/Update: {resource_name}] Resolving address reference...")
        address = resolve_resource_reference(
            spec['addressRef'], namespace, api,
            'coffee.terminal.sh', 'v1alpha1', 'coffeeaddresses'
        )
        if not address:
            msg = f"Address '{spec['addressRef']['name']}' not found"
            logger.error(f"[Create/Update: {resource_name}] {msg}")
            patch.status["phase"] = "Failed"
            patch.status["message"] = msg
            patch.status["addressReadyStatus"] = False
            raise kopf.TemporaryError(msg, delay=60)
        
        # Safely get status and check required fields/phase
        address_status = address.get('status', {})  # Get status dict or empty dict if 'status' key missing
        address_id = address_status.get('addressId')
        address_phase = address_status.get('phase')

        if not address_id or address_phase != 'Verified':
            # Provide a more specific message based on why it's not ready
            if not address.get('status'):
                msg = f"Address '{spec['addressRef']['name']}' exists but its status is not yet available."
            elif address_phase != 'Verified':
                msg = f"Address '{spec['addressRef']['name']}' status is '{address_phase}', waiting for 'Verified'."
            else:  # Should not happen if phase is Verified but ID missing, but handle defensively
                msg = f"Address '{spec['addressRef']['name']}' is verified but addressId is missing in status."

            logger.warning(f"[Create/Update: {resource_name}] Dependency not ready: {msg}")
            patch.status["phase"] = "Pending"  # Keep order pending while waiting
            patch.status["message"] = msg
            patch.status["addressReadyStatus"] = False
            raise kopf.TemporaryError(msg, delay=15)  # Retry sooner for dependencies
        
        patch.status["addressReadyStatus"] = True
        logger.info(f"[Create/Update: {resource_name}] Address dependency satisfied (ID: {address_id}).")

        # 3. Resolve Card reference
        logger.info(f"[Create/Update: {resource_name}] Resolving card reference...")
        card = resolve_resource_reference(
            spec['cardRef'], namespace, api,
            'coffee.terminal.sh', 'v1alpha1', 'coffeecards'
        )
        if not card:
            msg = f"Card '{spec['cardRef']['name']}' not found"
            logger.error(f"[Create/Update: {resource_name}] {msg}")
            patch.status["phase"] = "Failed"
            patch.status["message"] = msg
            patch.status["cardReadyStatus"] = False
            raise kopf.TemporaryError(msg, delay=60)
        
        # Safely get status and check required fields/phase
        card_status = card.get('status', {})  # Get status dict or empty dict if 'status' key missing
        card_id = card_status.get('cardId')
        card_phase = card_status.get('phase')

        if not card_id or card_phase != 'Registered':
            if not card.get('status'):
                msg = f"Card '{spec['cardRef']['name']}' exists but its status is not yet available."
            elif card_phase != 'Registered':
                msg = f"Card '{spec['cardRef']['name']}' status is '{card_phase}', waiting for 'Registered'."
            else:  # Defensive
                msg = f"Card '{spec['cardRef']['name']}' is registered but cardId is missing in status."

            logger.warning(f"[Create/Update: {resource_name}] Dependency not ready: {msg}")
            patch.status["phase"] = "Pending"  # Keep order pending
            patch.status["message"] = msg
            patch.status["cardReadyStatus"] = False
            raise kopf.TemporaryError(msg, delay=15)  # Retry sooner for dependencies

        patch.status["cardReadyStatus"] = True
        logger.info(f"[Create/Update: {resource_name}] Card dependency satisfied (ID: {card_id}).")

        # If we reached here, dependencies are met. Set status before final API call.
        patch.status["phase"] = "Processing"
        patch.status["message"] = "Dependencies resolved. Placing order with Terminal API..."


        # 4. Create Order
        logger.info(f"[Create/Update: {resource_name}] All references resolved. Placing order...")
        order_response = terminal_client.order.create(
            address_id=address_id,
            card_id=card_id,
            variants={spec['productVariantId']: spec.get('quantity', 1)}
        )
        order_id = get_id_from_response(order_response.data)
        if not order_id:
            msg = "Failed to get Order ID from response"
            logger.error(f"[Create/Update: {resource_name}] {msg}")
            patch.status["phase"] = "Failed"
            patch.status["message"] = msg
            raise ValueError(msg)
        
        logger.info(f"[Create/Update: {resource_name}] Order placed successfully! Order ID: {order_id}")

        # Update status
        patch.status["phase"] = "Ordered"
        patch.status["orderId"] = order_id
        patch.status["message"] = "Order placed successfully via API."

    except kopf.TemporaryError:
        raise
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

        # Add detailed debug logging
        logger.info("=== Full Order Data Structure ===")
        logger.info(f"Type: {type(order_data)}")
        logger.info(f"Available attributes: {dir(order_data)}")
        logger.info(f"Full data representation: {order_data}")
        logger.info("=== End Order Data Structure ===")

        # Try to find status in different possible locations
        api_status = None
        possible_status_fields = ['status', 'state', 'order_status', 'tracking_status']
        
        for field in possible_status_fields:
            value = getattr(order_data, field, None)
            if value:
                logger.info(f"Found status in field '{field}': {value}")
                api_status = value
                break

        if not api_status:
            logger.warning(f"[Timer: {resource_name}] API response for order {order_id} missing status field. Available fields: {dir(order_data)}")
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
