import os
import logging

import kopf
from dotenv import load_dotenv
from terminal_shop import Terminal

# Load environment variables from .env file (set externally to .env.dev or .env.prod)
load_dotenv()

# Check for required environment variable
if not os.environ.get("TERMINAL_BEARER_TOKEN"):
    raise RuntimeError("APE ANGRY! NO TERMINAL_BEARER_TOKEN FOUND! APE NEED TOKEN!")

logger = logging.getLogger(__name__)

# Initialize the Terminal API client with environment variables
terminal_client = Terminal(
    bearer_token=os.environ.get("TERMINAL_BEARER_TOKEN"),
    environment=os.environ.get("TERMINAL_ENVIRONMENT", "dev"),
)

@kopf.on.create("coffee.terminal.sh", "v1alpha1", "coffeeorders")
@kopf.on.update("coffee.terminal.sh", "v1alpha1", "coffeeorders")
def handle_coffee_order(spec, status, meta, patch, logger, **kwargs):
    name = meta.get("name")
    generation = meta.get("generation")
    logger.info(f"APE HANDLE ORDER {name} (gen: {generation})! APE HUNGRY FOR COFFEE!")

    # If the order has already been created, do nothing (idempotency)
    if status.get("orderId"):
        logger.info(f"APE ALREADY MAKE ORDER WITH ID {status['orderId']}! APE NO ORDER TWICE!")
        return

    # Extract spec details with defaults
    product_variant_id = spec.get("productVariantId")
    quantity = spec.get("quantity", 1)
    address_spec = spec.get("address", {})
    card_token = spec.get("cardToken")

    # Validate required fields
    if not product_variant_id:
        msg = "APE ANGRY! NO productVariantId IN SPEC!"
        logger.error(msg)
        patch.status["phase"] = "Failed"
        patch.status["message"] = msg
        raise kopf.PermanentError(msg)
    if not address_spec:
        msg = "APE CONFUSED! WHERE DELIVER COFFEE? NO address IN SPEC!"
        logger.error(msg)
        patch.status["phase"] = "Failed"
        patch.status["message"] = msg
        raise kopf.PermanentError(msg)
    if not card_token:
        msg = "APE NEED PAY FOR COFFEE! NO cardToken IN SPEC!"
        logger.error(msg)
        patch.status["phase"] = "Failed"
        patch.status["message"] = msg
        raise kopf.PermanentError(msg)

    # Update initial status
    patch.status["phase"] = "Processing"
    patch.status["message"] = "APE WORKING HARD TO GET COFFEE!"
    patch.status["observedGeneration"] = generation

    try:
        # Update user profile (for demonstration; adjust parameters as needed)
        terminal_client.profile.update(name="MIGHTY KUBE GORILLA")
        logger.info("APE UPDATE PROFILE! APE FAMOUS NOW!")

        # Create shipping address using provided spec
        address_response = terminal_client.address.create(**address_spec)
        address_id = address_response.data.id
        logger.info(f"APE CREATE ADDRESS WITH ID: {address_id}! APE KNOW WHERE DELIVER!")

        # Create card using the provided card token
        card_response = terminal_client.card.create(token=card_token)
        card_id = card_response.data.id
        logger.info(f"APE CREATE CARD WITH ID: {card_id}! APE PAY FOR COFFEE!")

        # Direct order creation without cart
        order_response = terminal_client.order.create(
            address_id=address_id,
            card_id=card_id,
            variants={product_variant_id: quantity}
        )
        order_id = order_response.data.id
        logger.info(f"APE ORDER COFFEE! ORDER ID: {order_id}! APE SO HAPPY!")

        patch.status["phase"] = "Ordered"
        patch.status["orderId"] = order_id
        patch.status["message"] = "APE ORDER SUCCESSFUL! COFFEE COMING SOON!"

    except Exception as e:
        logger.error(f"APE SAD! ORDER FAIL: {e}")
        patch.status["phase"] = "Failed"
        patch.status["message"] = f"ORDER ERROR: {e}"
        raise kopf.TemporaryError(f"APE TRY AGAIN LATER! ERROR: {e}", delay=30)