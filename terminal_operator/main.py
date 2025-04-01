import os
import logging

import kopf
from dotenv import load_dotenv
from terminal_shop import Terminal

# Load environment variables from .env file (set externally to .env.dev or .env.prod)
load_dotenv()

# Check for required environment variable
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
    name = meta.get("name")
    generation = meta.get("generation")
    logger.info(f"HANDLE ORDER {name} (gen: {generation})! HUNGRY FOR COFFEE!")

    # If the order has already been created, do nothing (idempotency)
    if status.get("orderId"):
        logger.info(f"ALREADY MAKE ORDER WITH ID {status['orderId']}! NO ORDER TWICE!")
        return

    # Extract spec details with defaults
    product_variant_id = spec.get("productVariantId")
    quantity = spec.get("quantity", 1)
    address_spec = spec.get("address", {})
    card_token = spec.get("cardToken")

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

    # Update initial status
    patch.status["phase"] = "Processing"
    patch.status["message"] = "WORKING HARD TO GET COFFEE!"
    patch.status["observedGeneration"] = generation

    try:
        # Extract email from spec
        email = spec.get("email")
        if not email:
            msg = "NEED EMAIL FOR ORDER! NO email IN SPEC!"
            logger.error(msg)
            patch.status["phase"] = "Failed"
            patch.status["message"] = msg
            raise kopf.PermanentError(msg)

        # Update user profile with email
        terminal_client.profile.update(name="MIGHTY KUBE GORILLA", email=email)
        logger.info("UPDATE PROFILE! FAMOUS NOW!")

        # Create shipping address using provided spec
        address_response = terminal_client.address.create(**address_spec)
        address_id = address_response.data.id
        logger.info(f"CREATE ADDRESS WITH ID: {address_id}! KNOW WHERE DELIVER!")

        # Create card using the provided card token
        card_response = terminal_client.card.create(token=card_token)
        card_id = card_response.data.id
        logger.info(f"CREATE CARD WITH ID: {card_id}! PAY FOR COFFEE!")

        # Direct order creation without cart
        order_response = terminal_client.order.create(
            address_id=address_id,
            card_id=card_id,
            variants={product_variant_id: quantity}
        )
        order_id = order_response.data.id
        logger.info(f"ORDER COFFEE! ORDER ID: {order_id}! SO HAPPY!")

        patch.status["phase"] = "Ordered"
        patch.status["orderId"] = order_id
        patch.status["message"] = "ORDER SUCCESSFUL! COFFEE COMING SOON!"

    except Exception as e:
        logger.error(f"SAD! ORDER FAIL: {e}")
        patch.status["phase"] = "Failed"
        patch.status["message"] = f"ORDER ERROR: {e}"
        raise kopf.TemporaryError(f"TRY AGAIN LATER! ERROR: {e}", delay=30)