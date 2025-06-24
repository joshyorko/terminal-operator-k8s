import os
import logging
import asyncio
import datetime
from typing import Optional
import base64

import kopf
from dotenv import load_dotenv
from terminal_shop import AsyncTerminal, APIStatusError
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

terminal_client = AsyncTerminal(
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
async def resolve_resource_reference(ref: dict, namespace: str, api: client.CustomObjectsApi, group: str, version: str, plural: str) -> Optional[dict]:
    """Resolves a reference to another custom resource."""
    try:
        resource = await asyncio.to_thread(
            api.get_namespaced_custom_object,
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

# --- Profile Handler ---
@kopf.on.create('coffee.terminal.sh', 'v1alpha1', 'coffeeprofiles')
@kopf.on.update('coffee.terminal.sh', 'v1alpha1', 'coffeeprofiles')
async def handle_profile(spec, status, meta, patch, logger, **kwargs):
    """Sync user profile information with the Terminal API."""
    resource_name = meta['name']
    generation = meta.get('generation')

    if status.get('phase') == 'Synced' and status.get('observedGeneration') == generation:
        return

    patch.status['phase'] = 'Pending'
    patch.status['message'] = 'Syncing profile with Terminal API'
    patch.status['observedGeneration'] = generation

    try:
        await terminal_client.profile.update(name=spec['name'], email=spec['email'])
        patch.status['phase'] = 'Synced'
        patch.status['message'] = 'Profile synced successfully'
        patch.status['lastSyncTime'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    except APIStatusError as e:
        patch.status['phase'] = 'Failed'
        patch.status['message'] = f"API error updating profile: {e.status_code} - {e.body or e.reason}"
        if 400 <= e.status_code < 500:
            raise kopf.PermanentError(patch.status['message'])
        raise kopf.TemporaryError(patch.status['message'], delay=60)
    except Exception as e:
        patch.status['phase'] = 'Failed'
        patch.status['message'] = f"Unexpected error updating profile: {e}"
        raise kopf.TemporaryError(patch.status['message'], delay=60)

@kopf.timer('coffee.terminal.sh', 'v1alpha1', 'coffeeprofiles', interval=3600)
async def sync_profile_status(spec, status, meta, patch, logger, **kwargs):
    if status.get('phase') != 'Synced':
        return
    try:
        await terminal_client.profile.get()
        patch.status['lastSyncTime'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    except Exception as e:
        patch.status['message'] = f"Profile sync check failed: {e}"

# --- Address Handler ---
@kopf.on.create('coffee.terminal.sh', 'v1alpha1', 'coffeeaddresses')
@kopf.on.update('coffee.terminal.sh', 'v1alpha1', 'coffeeaddresses')
async def handle_address(spec, status, meta, patch, logger, **kwargs):
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
        address_response = await terminal_client.address.create(**address_payload)
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
async def handle_card(spec, status, meta, patch, logger, **kwargs):
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
            card_response = await terminal_client.card.create(token=spec['cardToken'])
            card_id = get_id_from_response(card_response.data)
        except APIStatusError as e:
            if e.status_code == 400 and e.body and e.body.get("code") == "already_exists":
                logger.info(f"Card token already exists. Finding existing card...")
                cards_response = await terminal_client.card.list()
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
async def delete_card(spec, status, meta, logger, **kwargs):
    """Handles CoffeeCard deletion."""
    card_id = status.get('cardId')
    if not card_id:
        logger.info(f"No card ID found for {meta['name']}, nothing to delete")
        return

    try:
        logger.info(f"Deleting card {card_id}...")
        await terminal_client.card.delete(card_id)
        logger.info(f"Card {card_id} deleted successfully")
    except Exception as e:
        logger.error(f"Failed to delete card {card_id}: {e}")
        # Don't raise an error here as the resource is being deleted anyway

# --- Subscription Handler ---
@kopf.on.create('coffee.terminal.sh', 'v1alpha1', 'coffeesubscriptions')
@kopf.on.update('coffee.terminal.sh', 'v1alpha1', 'coffeesubscriptions')
async def handle_subscription(spec, status, meta, patch, logger, **kwargs):
    """Handles CoffeeSubscription creation/updates."""
    resource_name = meta['name']
    generation = meta.get('generation')

    # Idempotency: Don't reprocess if already active and generation matches
    if status.get('subscriptionId') and \
       status.get('phase') == 'Active' and \
       status.get('observedGeneration') == generation:
        logger.info(f"Subscription {resource_name} already active with ID {status['subscriptionId']} for this generation.")
        return

    # Set initial phase
    if status.get('phase') != 'Active':
        patch.status['phase'] = 'Pending'
        patch.status['message'] = 'Validating subscription dependencies'
        patch.status['observedGeneration'] = generation

    try:
        # Get and validate profile
        profile = await get_referenced_resource('coffeeprofiles', spec['profileRef'], meta.get('namespace'))
        if not profile or profile['status'].get('phase') != 'Synced':
            patch.status['profileReadyStatus'] = False
            raise kopf.TemporaryError("Referenced profile not ready", delay=10)
        patch.status['profileReadyStatus'] = True

        # Get and validate address
        address = await get_referenced_resource('coffeeaddresses', spec['addressRef'], meta.get('namespace'))
        if not address or not address['status'].get('addressId') or address['status'].get('phase') != 'Verified':
            patch.status['addressReadyStatus'] = False
            raise kopf.TemporaryError("Referenced address not ready", delay=10)
        patch.status['addressReadyStatus'] = True
        address_id = address['status']['addressId']

        # Get and validate card
        card = await get_referenced_resource('coffeecards', spec['cardRef'], meta.get('namespace'))
        if not card or not card['status'].get('cardId') or card['status'].get('phase') != 'Registered':
            patch.status['cardReadyStatus'] = False
            raise kopf.TemporaryError("Referenced card not ready", delay=10)
        patch.status['cardReadyStatus'] = True
        card_id = card['status']['cardId']

        logger.info(f"Creating/updating subscription for {resource_name}...")
        
        # If we already have a subscription ID, check if it exists and is active
        if status.get('subscriptionId'):
            try:
                sub_response = await terminal_client.subscription.get_by_id(status['subscriptionId'])
                if sub_response.data:
                    logger.info(f"Subscription exists, updating if needed...")
                    # TODO: Implement subscription updates when API supports it
                    return
            except APIStatusError as e:
                if e.status_code == 404:
                    logger.info("Subscription no longer exists, creating new one")
                else:
                    raise

        # Create new subscription
        sub_data = {
            'productVariantId': spec['productVariantId'],
            'quantity': spec.get('quantity', 1),
            'addressId': address_id,
            'cardId': card_id,
            'schedule': {
                'type': spec['schedule']['type'],
                'interval': spec['schedule']['interval']
            }
        }

        sub_response = await terminal_client.subscription.create(**sub_data)
        sub_id = get_id_from_response(sub_response.data)
        
        if not sub_id:
            patch.status['phase'] = 'Failed'
            patch.status['message'] = 'Failed to get subscription ID from API response'
            logger.error(f"Subscription {resource_name} creation failed: No subscription ID in response")
            raise kopf.PermanentError("No subscription ID in successful API response")

        # Update status with subscription details
        patch.status['subscriptionId'] = sub_id
        patch.status['phase'] = 'Active'
        patch.status['message'] = 'Subscription activated successfully'
        if 'next' in sub_response.data:
            patch.status['nextDelivery'] = sub_response.data['next']
        patch.status['lastStatusCheck'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        logger.info(f"Subscription {resource_name} created with ID {sub_id}")

    except APIStatusError as e:
        patch.status['phase'] = 'Failed'
        patch.status['message'] = f"API error creating subscription: {e.status_code} - {e.body or e.reason}"
        logger.error(f"Subscription {resource_name} API creation failed: {e}")
        if 400 <= e.status_code < 500:
            raise kopf.PermanentError(f"Subscription API creation failed permanently: {e}")
        else:
            raise kopf.TemporaryError(f"Subscription API creation failed: {e}", delay=60)

    except Exception as e:
        patch.status['phase'] = 'Failed'
        patch.status['message'] = f"Unexpected error creating subscription: {str(e)}"
        logger.error(f"Subscription {resource_name} creation failed unexpectedly: {e}", exc_info=True)
        raise kopf.TemporaryError(f"Subscription creation failed unexpectedly: {e}", delay=60)

@kopf.on.delete('coffee.terminal.sh', 'v1alpha1', 'coffeesubscriptions')
async def delete_subscription(spec, status, meta, logger, **kwargs):
    """Handles CoffeeSubscription deletion by cancelling the subscription."""
    resource_name = meta['name']
    subscription_id = status.get('subscriptionId')

    if not subscription_id:
        logger.info(f"No subscription ID found for {resource_name}, nothing to cancel")
        return

    try:
        logger.info(f"Cancelling subscription {subscription_id} for {resource_name}...")
        await terminal_client.subscription.delete(subscription_id)
        logger.info(f"Subscription {subscription_id} cancelled successfully")
    except APIStatusError as e:
        if e.status_code == 404:
            logger.info(f"Subscription {subscription_id} already cancelled or not found")
        else:
            logger.error(f"Error cancelling subscription {subscription_id}: {e}")
            raise kopf.TemporaryError(f"Failed to cancel subscription: {e}", delay=10)
    except Exception as e:
        logger.error(f"Unexpected error cancelling subscription {subscription_id}: {e}")
        raise kopf.TemporaryError(f"Failed to cancel subscription: {e}", delay=10)

# --- Operator Handlers ---

@kopf.on.create("coffee.terminal.sh", "v1alpha1", "coffeeorders")
@kopf.on.update("coffee.terminal.sh", "v1alpha1", "coffeeorders")
async def handle_coffee_order_creation(spec, status, meta, patch, logger, **kwargs):
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
        profile = await resolve_resource_reference(
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
        await terminal_client.profile.update(
            name=profile['spec']['name'],
            email=profile['spec']['email']
        )

        # 2. Resolve Address reference
        logger.info(f"[Create/Update: {resource_name}] Resolving address reference...")
        address = await resolve_resource_reference(
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
        card = await resolve_resource_reference(
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
        order_response = await terminal_client.order.create(
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
    """Periodically checks the status of placed orders via the Terminal API.
    
    Important Notes:
    - The Terminal API does not provide a direct 'delivered' or 'status' field
    - Shipping status is inferred from the presence of tracking information
    - 'Shipped' is considered the final observable state from the API
    - Actual delivery confirmation would require external carrier tracking integration
    """
    resource_name = meta.get("name")
    order_id = status.get("orderId")
    current_phase = status.get("phase")

    # Include 'Shipped' as a final state since it's the last reliable state we can detect
    final_states = ["Failed", "Delivered", "Cancelled", "Shipped"]
    if not order_id or current_phase in final_states:
        logger.debug(f"[Timer: {resource_name}] Skipping check - OrderID exists: {bool(order_id)}, Current phase: {current_phase}")
        return

    logger.info(f"[Timer: {resource_name}] Checking status for Order ID: {order_id} (Current Phase: {current_phase})")

    try:
        order_details_response = await terminal_client.order.get(order_id)
        order_data = order_details_response.data

        # Log available fields for debugging
        logger.debug(f"[Timer: {resource_name}] Order data fields available: {dir(order_data)}")

        # --- Check Tracking Info ---
        tracking_info = getattr(order_data, 'tracking', None)
        if tracking_info:
            logger.debug(f"[Timer: {resource_name}] Tracking info fields: {dir(tracking_info)}")
        
        tracking_number = getattr(tracking_info, 'number', None) if tracking_info else None
        tracking_service = getattr(tracking_info, 'service', None) if tracking_info else None
        tracking_url = getattr(tracking_info, 'url', None) if tracking_info else None

        logger.debug(f"[Timer: {resource_name}] Tracking details: number={tracking_number}, service={tracking_service}")

        if tracking_number and current_phase != "Shipped":
            # When tracking info appears, we can reliably say the order has shipped
            logger.info(f"[Timer: {resource_name}] Tracking number found ({tracking_number} via {tracking_service}). Updating phase to Shipped.")
            patch.status['phase'] = "Shipped"
            patch.status['message'] = f"Order shipped via {tracking_service}. Tracking: {tracking_number}"
            # Update tracking fields in status
            patch.status['trackingNumber'] = tracking_number
            patch.status['trackingUrl'] = tracking_url
            patch.status['trackingService'] = tracking_service
            patch.status['lastStatusCheck'] = datetime.datetime.utcnow().isoformat() + "Z"

        elif not tracking_number and current_phase == "Ordered":
            # No tracking yet, order is still being processed
            logger.info(f"[Timer: {resource_name}] No tracking number found. Order remains in 'Ordered' state.")
            patch.status['message'] = f"Order placed, awaiting shipment. Last check: {datetime.datetime.utcnow().isoformat()}Z"
            patch.status['lastStatusCheck'] = datetime.datetime.utcnow().isoformat() + "Z"

        else:
            # Either already Shipped or in another state
            logger.info(f"[Timer: {resource_name}] No status change needed. Current phase: {current_phase}, Has tracking: {bool(tracking_number)}")
            patch.status['message'] = f"Order {current_phase}. Last check: {datetime.datetime.utcnow().isoformat()}Z"
            patch.status['lastStatusCheck'] = datetime.datetime.utcnow().isoformat() + "Z"

    except APIStatusError as e:
        if e.status_code == 404:
            logger.error(f"[Timer: {resource_name}] Order ID {order_id} not found in Terminal API. Marking as Failed.")
            patch.status['phase'] = "Failed"
            patch.status['message'] = f"Order ID {order_id} not found in API (404)."
        else:
            logger.error(f"[Timer: {resource_name}] API error checking status for {order_id}: {e}")
            patch.status['message'] = f"API error during status check: {e.status_code}" # Don't mark as failed for transient API errors
    except Exception as e:
        logger.error(f"[Timer: {resource_name}] Error checking status for {order_id}: {e}", exc_info=True)
        patch.status['message'] = f"Error during status check: {str(e)}"

# ---- Deletion Handler ----
@kopf.on.delete("coffee.terminal.sh", "v1alpha1", "coffeeorders")
async def handle_coffee_order_deletion(spec, status, meta, logger, **kwargs):
    """Handles the deletion of a CoffeeOrder CR."""
    resource_name = meta.get("name")
    order_id = status.get("orderId")

    logger.info(f"[Delete: {resource_name}] CoffeeOrder CR deleted.")

    if order_id:
        logger.warning(f"[Delete: {resource_name}] Deleting the CoffeeOrder CR does NOT cancel the real order (ID: {order_id}) in the Terminal API.")
        logger.warning(f"[Delete: {resource_name}] The Terminal API does not provide an endpoint to cancel existing orders.")
    else:
        logger.info(f"[Delete: {resource_name}] No associated Terminal order ID found in status. Nothing to do in API.")

@kopf.on.create('coffee.terminal.sh', 'v1alpha1', 'coffeecarts')
@kopf.on.update('coffee.terminal.sh', 'v1alpha1', 'coffeecarts')
async def handle_cart(spec, status, meta, patch, logger, **kwargs):
    """Handles CoffeeCart creation/updates."""
    resource_name = meta['name']
    generation = meta.get('generation')

    # Initialize cart if needed
    if status.get('phase') in [None, 'Empty']:
        logger.info(f"Initializing cart for {resource_name}...")
        try:
            # Clear any existing cart first
            await terminal_client.cart.delete()
            patch.status['phase'] = 'Empty'
            patch.status['message'] = 'Cart initialized'
            patch.status['observedGeneration'] = generation
        except Exception as e:
            logger.error(f"Failed to initialize cart: {e}")
            patch.status['phase'] = 'Failed'
            patch.status['message'] = f"Cart initialization failed: {str(e)}"
            raise kopf.TemporaryError(f"Cart initialization failed: {e}", delay=30)

    try:
        # Add/update items in cart
        if spec.get('items'):
            logger.info(f"Adding/updating items in cart for {resource_name}...")
            for item in spec['items']:
                await terminal_client.cart.add_item(
                    product_variant_id=item['productVariantId'],
                    quantity=item.get('quantity', 1)
                )
            patch.status['phase'] = 'ItemsAdded'
            patch.status['message'] = 'Items added to cart'
            
            # Get updated cart details
            cart_response = await terminal_client.cart.get()
            if cart_response.data:
                patch.status['subtotal'] = getattr(cart_response.data, 'subtotal', 0)
                if hasattr(cart_response.data, 'amount'):
                    amount = cart_response.data.amount
                    if isinstance(amount, dict):
                        patch.status['shipping'] = amount.get('shipping', 0)
                    else:
                        patch.status['shipping'] = getattr(amount, 'shipping', 0)
                else:
                    patch.status['shipping'] = 0
                patch.status['total'] = patch.status['subtotal'] + patch.status['shipping']

        # Set shipping address if provided
        if spec.get('addressRef'):
            address = await get_referenced_resource('coffeeaddresses', spec['addressRef'], meta.get('namespace'))
            if not address or not address['status'].get('addressId') or address['status'].get('phase') != 'Verified':
                patch.status['addressReadyStatus'] = False
                patch.status['message'] = 'Waiting for address to be ready'
                raise kopf.TemporaryError("Referenced address not ready", delay=10)
            
            patch.status['addressReadyStatus'] = True
            address_id = address['status']['addressId']
            await terminal_client.cart.set_address(address_id=address_id)
            if patch.status['phase'] == 'ItemsAdded':
                patch.status['phase'] = 'AddressSet'

        # Set payment card if provided
        if spec.get('cardRef'):
            card = await get_referenced_resource('coffeecards', spec['cardRef'], meta.get('namespace'))
            if not card or not card['status'].get('cardId') or card['status'].get('phase') != 'Registered':
                patch.status['cardReadyStatus'] = False
                patch.status['message'] = 'Waiting for card to be ready'
                raise kopf.TemporaryError("Referenced card not ready", delay=10)
            
            patch.status['cardReadyStatus'] = True
            card_id = card['status']['cardId']
            await terminal_client.cart.set_card(card_id=card_id)
            if patch.status['phase'] in ['ItemsAdded', 'AddressSet']:
                patch.status['phase'] = 'CardSet'

        # Check if cart is ready to be converted
        if spec.get('convertToOrder') and \
           patch.status.get('addressReadyStatus') and \
           patch.status.get('cardReadyStatus') and \
           patch.status['phase'] in ['ItemsAdded', 'AddressSet', 'CardSet']:
            
            patch.status['phase'] = 'Converting'
            patch.status['message'] = 'Converting cart to order...'
            
            # Convert cart to order
            order_response = await terminal_client.cart.convert()
            order_id = get_id_from_response(order_response.data)
            
            if not order_id:
                patch.status['phase'] = 'Failed'
                patch.status['message'] = 'Failed to get order ID after cart conversion'
                raise kopf.PermanentError("No order ID in cart conversion response")
            
            patch.status['orderId'] = order_id
            patch.status['phase'] = 'Converted'
            patch.status['message'] = f'Cart converted to order {order_id}'
            logger.info(f"Cart {resource_name} converted to order {order_id}")

    except APIStatusError as e:
        patch.status['message'] = f"API error managing cart: {e.status_code} - {e.body or e.reason}"
        logger.error(f"Cart {resource_name} API operation failed: {e}")
        if 400 <= e.status_code < 500:
            patch.status['phase'] = 'Failed'
            raise kopf.PermanentError(f"Cart operation failed permanently: {e}")
        else:
            raise kopf.TemporaryError(f"Cart operation failed: {e}", delay=60)

    except Exception as e:
        logger.error(f"Cart {resource_name} operation failed unexpectedly: {e}", exc_info=True)
        patch.status['message'] = f"Unexpected error managing cart: {str(e)}"
        if not isinstance(e, kopf.TemporaryError):
            patch.status['phase'] = 'Failed'
        raise

@kopf.on.delete('coffee.terminal.sh', 'v1alpha1', 'coffeecarts')
async def delete_cart(spec, status, meta, logger, **kwargs):
    """Handles CoffeeCart deletion by clearing the cart."""
    resource_name = meta['name']

    try:
        logger.info(f"Clearing cart for {resource_name}...")
        await terminal_client.cart.delete()
        logger.info(f"Cart cleared successfully")
    except Exception as e:
        logger.error(f"Failed to clear cart: {e}")
        # Don't raise since resource is being deleted anyway

@kopf.on.create('coffee.terminal.sh', 'v1alpha1', 'terminaltokens')
@kopf.on.update('coffee.terminal.sh', 'v1alpha1', 'terminaltokens')
async def handle_token(spec, status, meta, patch, logger, **kwargs):
    """Handles TerminalToken creation/updates."""
    resource_name = meta['name']
    generation = meta.get('generation')

    # Idempotency: Don't reprocess if already active and generation matches
    if status.get('tokenId') and \
       status.get('phase') == 'Active' and \
       status.get('observedGeneration') == generation:
        logger.info(f"Token {resource_name} already active with ID {status['tokenId']} for this generation.")
        return

    # Set initial phase
    if status.get('phase') != 'Active':
        patch.status['phase'] = 'Pending'
        patch.status['message'] = 'Creating Terminal API token'
        patch.status['observedGeneration'] = generation

    try:
        logger.info(f"Creating token for {resource_name}...")
        token_response = await terminal_client.token.create()
        token_id = get_id_from_response(token_response.data)

        if not token_id:
            patch.status['phase'] = 'Failed'
            patch.status['message'] = 'Failed to get token ID from API response'
            logger.error(f"Token {resource_name} creation failed: No token ID in response")
            raise kopf.PermanentError("No token ID in successful API response")

        # Update status with token details
        patch.status['tokenId'] = token_id
        patch.status['phase'] = 'Active'
        patch.status['message'] = 'Token created successfully'
        patch.status['created'] = getattr(token_response.data, 'created', datetime.datetime.now(datetime.timezone.utc).isoformat())
        patch.status['lastStatusCheck'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        logger.info(f"Token {resource_name} created with ID {token_id}")

    except APIStatusError as e:
        patch.status['phase'] = 'Failed'
        patch.status['message'] = f"API error creating token: {e.status_code} - {e.body or e.reason}"
        logger.error(f"Token {resource_name} API creation failed: {e}")
        if 400 <= e.status_code < 500:
            raise kopf.PermanentError(f"Token API creation failed permanently: {e}")
        else:
            raise kopf.TemporaryError(f"Token API creation failed: {e}", delay=60)

    except Exception as e:
        patch.status['phase'] = 'Failed'
        patch.status['message'] = f"Unexpected error creating token: {str(e)}"
        logger.error(f"Token {resource_name} creation failed unexpectedly: {e}", exc_info=True)
        raise kopf.TemporaryError(f"Token creation failed unexpectedly: {e}", delay=60)

@kopf.on.delete('coffee.terminal.sh', 'v1alpha1', 'terminaltokens')
async def delete_token(spec, status, meta, logger, **kwargs):
    """Handles TerminalToken deletion."""
    resource_name = meta['name']
    token_id = status.get('tokenId')

    if not token_id:
        logger.info(f"No token ID found for {resource_name}, nothing to delete")
        return

    try:
        logger.info(f"Deleting token {token_id} for {resource_name}...")
        await terminal_client.token.delete(token_id)
        logger.info(f"Token {token_id} deleted successfully")
    except APIStatusError as e:
        if e.status_code == 404:
            logger.info(f"Token {token_id} already deleted or not found")
        else:
            logger.error(f"Error deleting token {token_id}: {e}")
            raise kopf.TemporaryError(f"Failed to delete token: {e}", delay=10)
    except Exception as e:
        logger.error(f"Unexpected error deleting token {token_id}: {e}")
        raise kopf.TemporaryError(f"Failed to delete token: {e}", delay=10)

def create_or_update_app_secret(name: str, namespace: str, client_id: str, client_secret: str):
    """Creates or updates a Kubernetes secret for app credentials."""
    core_v1 = client.CoreV1Api()
    secret_name = f"{name}-credentials"
    
    secret_data = {
        "client_id": base64.b64encode(client_id.encode()).decode(),
        "client_secret": base64.b64encode(client_secret.encode()).decode()
    }
    
    secret = client.V1Secret(
        metadata=client.V1ObjectMeta(name=secret_name, namespace=namespace),
        type="Opaque",
        data=secret_data
    )
    
    try:
        core_v1.create_namespaced_secret(namespace=namespace, body=secret)
    except client.exceptions.ApiException as e:
        if e.status == 409:  # Conflict, secret already exists
            core_v1.replace_namespaced_secret(name=secret_name, namespace=namespace, body=secret)
        else:
            raise
    
    return {"name": secret_name, "namespace": namespace}

@kopf.on.create('coffee.terminal.sh', 'v1alpha1', 'coffeeapps')
@kopf.on.update('coffee.terminal.sh', 'v1alpha1', 'coffeeapps')
async def handle_app(spec, status, meta, patch, logger, **kwargs):
    """Handles CoffeeApp creation/updates."""
    resource_name = meta['name']
    generation = meta.get('generation')
    namespace = meta.get('namespace', 'default')

    # Idempotency: Don't reprocess if already active and generation matches
    if status.get('appId') and \
       status.get('phase') == 'Active' and \
       status.get('observedGeneration') == generation:
        logger.info(f"App {resource_name} already active with ID {status['appId']} for this generation.")
        return

    # Set initial phase
    if status.get('phase') != 'Active':
        patch.status['phase'] = 'Pending'
        patch.status['message'] = 'Creating Terminal API OAuth app'
        patch.status['observedGeneration'] = generation

    try:
        logger.info(f"Creating/updating OAuth app {resource_name}...")
        app_response = await terminal_client.app.create(
            name=spec['name'],
            redirect_uri=spec['redirectUri']
        )
        app_id = get_id_from_response(app_response.data)
        
        if not app_id:
            patch.status['phase'] = 'Failed'
            patch.status['message'] = 'Failed to get app ID from API response'
            logger.error(f"App {resource_name} creation failed: No app ID in response")
            raise kopf.PermanentError("No app ID in successful API response")

        # Store credentials in Kubernetes secret
        client_id = app_id
        client_secret = getattr(app_response.data, 'secret', None)
        if not client_secret:
            patch.status['phase'] = 'Failed'
            patch.status['message'] = 'Failed to get app secret from API response'
            logger.error(f"App {resource_name} creation failed: No client secret in response")
            raise kopf.PermanentError("No client secret in successful API response")

        # Create or update the secret
        secret_ref = create_or_update_app_secret(
            name=resource_name,
            namespace=namespace,
            client_id=client_id,
            client_secret=client_secret
        )

        # Update status with app details
        patch.status['appId'] = app_id
        patch.status['phase'] = 'Active'
        patch.status['message'] = 'OAuth app created successfully'
        patch.status['secretRef'] = secret_ref
        patch.status['lastStatusCheck'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        logger.info(f"OAuth app {resource_name} created with ID {app_id}")

    except APIStatusError as e:
        patch.status['phase'] = 'Failed'
        patch.status['message'] = f"API error creating OAuth app: {e.status_code} - {e.body or e.reason}"
        logger.error(f"App {resource_name} API creation failed: {e}")
        if 400 <= e.status_code < 500:
            raise kopf.PermanentError(f"OAuth app API creation failed permanently: {e}")
        else:
            raise kopf.TemporaryError(f"OAuth app API creation failed: {e}", delay=60)

    except Exception as e:
        patch.status['phase'] = 'Failed'
        patch.status['message'] = f"Unexpected error creating OAuth app: {str(e)}"
        logger.error(f"App {resource_name} creation failed unexpectedly: {e}", exc_info=True)
        raise kopf.TemporaryError(f"OAuth app creation failed unexpectedly: {e}", delay=60)

@kopf.on.delete('coffee.terminal.sh', 'v1alpha1', 'coffeeapps')
async def delete_app(spec, status, meta, logger, **kwargs):
    """Handles CoffeeApp deletion."""
    resource_name = meta['name']
    app_id = status.get('appId')
    namespace = meta.get('namespace', 'default')

    if not app_id:
        logger.info(f"No app ID found for {resource_name}, nothing to delete")
        return

    try:
        # Delete the app from Terminal API
        logger.info(f"Deleting OAuth app {app_id} for {resource_name}...")
        await terminal_client.app.delete(app_id)
        logger.info(f"OAuth app {app_id} deleted successfully")

        # Clean up the associated secret
        if status.get('secretRef'):
            try:
                core_v1 = client.CoreV1Api()
                secret_name = status['secretRef']['name']
                secret_namespace = status['secretRef'].get('namespace', namespace)
                core_v1.delete_namespaced_secret(name=secret_name, namespace=secret_namespace)
                logger.info(f"Deleted associated secret {secret_name} in namespace {secret_namespace}")
            except client.exceptions.ApiException as e:
                if e.status != 404:  # Ignore if secret is already gone
                    logger.error(f"Failed to delete secret: {e}")

    except APIStatusError as e:
        if e.status_code == 404:
            logger.info(f"OAuth app {app_id} already deleted or not found")
        else:
            logger.error(f"Error deleting OAuth app {app_id}: {e}")
            raise kopf.TemporaryError(f"Failed to delete OAuth app: {e}", delay=10)
    except Exception as e:
        logger.error(f"Unexpected error deleting OAuth app {app_id}: {e}")
        raise kopf.TemporaryError(f"Failed to delete OAuth app: {e}", delay=10)
