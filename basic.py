import os
from terminal_shop import Terminal
from dotenv import load_dotenv
from rich import print

load_dotenv()

client = Terminal(
    bearer_token=os.environ.get("TERMINAL_BEARER_TOKEN"),  # This is the default and can be omitted
    # defaults to "production".
    environment="dev",
)

product = client.product.list()
print(product.data)