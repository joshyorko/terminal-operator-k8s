import os
import logging

import kopf
from dotenv import load_dotenv
from terminal_shop import Terminal

# Load environment variables from .env file (set externally to .env.dev or .env.prod)
load_dotenv()

if not os.environ.get("TERMINAL_BEARER_TOKEN"):
    raise RuntimeError("ANGRY! NO TERMINAL_BEARER_TOKEN FOUND! NEED TOKEN!")

logger = logging.getLogger(__name__)

# Initialize the Terminal API client with environment variables
terminal_client = Terminal(
    bearer_token=os.environ.get("TERMINAL_BEARER_TOKEN"),
    environment=os.environ.get("TERMINAL_ENVIRONMENT", "dev"),
)

@kopf.on.create("coffee.terminal.sh", "v1alpha1", "coffeeorders")
@kopf.on.update("coffee.terminal.sh", "v1alpha1", "coffeeorders")
def handle_coffee_order(spec, status, meta, patch, logger, **kwargs):
    resource_name = meta.get("name")
    generation = meta.get("generation")
    logger.info(f"HANDLE ORDER {resource_name} (gen: {generation})! HUNGRY FOR COFFEE!")

    # If the order has already been created, do nothing (idempotency)
    if status.get("orderId"):
        logger.info(f"ALREADY MADE ORDER WITH ID {status['orderId']}! NO ORDER TWICE!")
        return

    # Extract spec details
    product_variant_id = spec.get("productVariantId")
    quantity = spec.get("quantity", 1)
    address_spec = spec.get("address", {})
    card_token = spec.get("cardToken")
    email = spec.get("email")

    # Validate required fields
    if not product_variant_id:
        msg = "ANGRY! NO productVariantId IN SPEC!"
        logger.error(msg)
        patch.status["phase"] = "Failed"
        patch.status["message"] = msg
        raise kopf.PermanentError(msg)
    if not address_spec:
        msg = "CONFUSED! WHERE DELIVER COFFEE? NO address IN SPEC!"
        logger.error(msg)
        patch.status["phase"] = "Failed"
        patch.status["message"] = msg
        raise kopf.PermanentError(msg)
    if not card_token:
        msg = "NEED PAY FOR COFFEE! NO cardToken IN SPEC!"
        logger.error(msg)
        patch.status["phase"] = "Failed"
        patch.status["message"] = msg
        raise kopf.PermanentError(msg)
    if not email:
        msg = "NEED EMAIL FOR ORDER! NO email IN SPEC!"
        logger.error(msg)
        patch.status["phase"] = "Failed"
        patch.status["message"] = msg
        raise kopf.PermanentError(msg)

    # Update initial status
    patch.status["phase"] = "Processing"
    patch.status["message"] = "WORKING HARD TO GET COFFEE!"
    patch.status["observedGeneration"] = generation

    try:
        # 1. Update user profile with email and recipient name
        recipient_name = address_spec.get("name", "MIGHTY KUBE GORILLA")
        profile_params = {"name": recipient_name, "email": email}
        profile_response = terminal_client.profile.update(**profile_params)
        logger.info(f"PROFILE UPDATED! {recipient_name} is now famous!")

        # 2. Create shipping address - remove unsupported fields (e.g., 'state')
        address_payload = address_spec.copy()
        address_payload.pop("state", None)
        address_response = terminal_client.address.create(**address_payload)
        if isinstance(address_response.data, str):
            address_id = address_response.data
        else:
            address_id = address_response.data.id
        logger.info(f"ADDRESS CREATED! ID: {address_id}")

        # 3. Create card using the provided card token
        try:
            card_response = terminal_client.card.create(token=card_token)
            card_id = card_response.data.id
            logger.info(f"CARD CREATED! ID: {card_id}")
        except Exception as e:
            # If the card already exists, list existing cards and use the first one
            if "already_exists" in str(e):
                logger.info("CARD ALREADY EXISTS! Listing existing cards...")
                cards_response = terminal_client.card.list()
                card_list = list(cards_response.data) if hasattr(cards_response.data, '__iter__') else []
                if card_list:
                    card_id = card_list[0].id
                    logger.info(f"USING EXISTING CARD! ID: {card_id}")
                else:
                    raise Exception("No existing card found despite 'already_exists' error.")
            else:
                raise

        # 4. Create order directly (without using cart)
        order_response = terminal_client.order.create(
            address_id=address_id,
            card_id=card_id,
            variants={product_variant_id: quantity}
        )
        if isinstance(order_response.data, str):
            order_id = order_response.data
        else:
            order_id = order_response.data.id
        logger.info(f"ORDER CREATED! Order ID: {order_id}")

        patch.status["phase"] = "Ordered"
        patch.status["orderId"] = order_id
        patch.status["message"] = "ORDER SUCCESSFUL! COFFEE COMING SOON!"

    except Exception as e:
        logger.error(f"ORDER FAILED: {e}")
        patch.status["phase"] = "Failed"
        patch.status["message"] = f"ORDER ERROR: {e}"
        raise kopf.TemporaryError(f"TRY AGAIN LATER! ERROR: {e}", delay=30)
