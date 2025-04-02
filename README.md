# Terminal Operator for Kubernetes

![Terminal Avatar](https://avatars.githubusercontent.com/u/166243908?s=200&v=4)


A Kubernetes operator that provides declarative management of Terminal shop resources via custom resource definitions (CRDs).

## Features

- Full API coverage with declarative management
- Automatic dependency resolution between resources
- Status tracking and error handling
- Secure credential management

## Custom Resources

### Core Resources

- **CoffeeProfile** (`coffeeprofiles.coffee.terminal.sh`)
  - Manages user profile information
  - Required for orders and subscriptions

- **CoffeeAddress** (`coffeeaddresses.coffee.terminal.sh`)
  - Manages shipping addresses
  - Validates addresses with Terminal API

- **CoffeeCard** (`coffeecards.coffee.terminal.sh`)
  - Manages payment cards
  - Securely handles card tokens

### Order Management

- **CoffeeOrder** (`coffeeorders.coffee.terminal.sh`)
  - Places one-time orders
  - Tracks order status and shipping info
  - References profile, address, and card

- **CoffeeSubscription** (`coffeesubscriptions.coffee.terminal.sh`)
  - Manages recurring coffee subscriptions
  - Configurable schedule (weekly/monthly)
  - Tracks next delivery dates
  - References profile, address, and card

- **CoffeeCart** (`coffeecarts.coffee.terminal.sh`)
  - Manages shopping cart state
  - Add multiple items
  - Set shipping address and payment card
  - Convert cart to order
  - Track cart totals and shipping costs

### API Management

- **TerminalToken** (`terminaltokens.coffee.terminal.sh`)
  - Manages Terminal API tokens
  - Tracks token creation and status

- **CoffeeApp** (`coffeeapps.coffee.terminal.sh`)
  - Manages OAuth applications
  - Securely stores client credentials in Kubernetes secrets
  - Configures redirect URIs

## Installation

1. Add the Terminal operator repository:
   ```bash
   helm repo add terminal-operator https://example.com/charts
   ```

2. Create a secret with your Terminal API credentials:
   ```bash
   kubectl create secret generic terminal-api-credentials \
     --from-literal=bearer-token=your-token-here
   ```

3. Install the operator:
   ```bash
   helm install terminal-operator terminal-operator/terminal-operator
   ```

## Usage Examples

### Creating a Subscription

```yaml
apiVersion: coffee.terminal.sh/v1alpha1
kind: CoffeeSubscription
metadata:
  name: weekly-coffee
spec:
  productVariantId: var_01JNH7GTF9FBA62Y0RT0WMK3BT
  quantity: 1
  profileRef:
    name: my-profile
  addressRef:
    name: my-address
  cardRef:
    name: my-card
  schedule:
    type: weekly
    interval: 2  # Every 2 weeks
```

### Managing a Cart

```yaml
apiVersion: coffee.terminal.sh/v1alpha1
kind: CoffeeCart
metadata:
  name: my-cart
spec:
  items:
    - productVariantId: var_01J1JFDMNBXB5GJCQF6C3AEBCQ
      quantity: 1
  addressRef:
    name: my-address
  cardRef:
    name: my-card
  convertToOrder: true  # Automatically convert to order when ready
```

### Creating an OAuth App

```yaml
apiVersion: coffee.terminal.sh/v1alpha1
kind: CoffeeApp
metadata:
  name: my-app
spec:
  name: "My Coffee Shop Integration"
  redirectUri: "https://myapp.example.com/oauth/callback"
```

## Resource Dependencies

Resources often depend on each other. The operator handles these dependencies automatically:

1. Orders and Subscriptions require:
   - Valid CoffeeProfile
   - Verified CoffeeAddress
   - Registered CoffeeCard

2. Carts can be configured incrementally:
   - Add items first
   - Set address and card later
   - Convert to order when ready

## Status Management

Each resource includes detailed status information:

- Current phase (e.g., Pending, Active, Failed)
- Resource-specific IDs from Terminal API
- Error messages and timestamps
- Dependency readiness status

## Security Considerations

- Card tokens are never stored, only passed to Terminal API
- OAuth client secrets are stored in Kubernetes secrets
- API tokens can be managed securely through CRDs

## Contributing

Contributions are welcome! Please see CONTRIBUTING.md for guidelines.

## License

MIT License - see LICENSE for details.