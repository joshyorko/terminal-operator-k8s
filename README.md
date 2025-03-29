# Terminal-Operator-k8s: Kubernetes Coffee Ordering

![Terminal Avatar](https://avatars.githubusercontent.com/u/166243908?s=200&v=4)


terminal-operator-k8s is a Kubernetes operator designed to automate coffee ordering via the Terminal API. It monitors `CoffeeOrder` custom resources within your cluster and processes orders accordingly.

> **Note:** This operator integrates with the Terminal API. The sandbox environment simulates orders without actual charges. Ensure proper API tokens and payment details are configured for production use.

---

## Features

- **Watches `CoffeeOrder` Custom Resources:** Automatically triggers the ordering process upon creation or update of `CoffeeOrder` resources.
- **Terminal API Integration:** Manages Terminal profiles, addresses, payment methods (cards), and places orders.
- **Status Reporting:** Updates the `CoffeeOrder` status sub-resource with relevant details like order ID and current phase (e.g., `Pending`, `Processing`, `Complete`, `Failed`).

---

## Installation

### Prerequisites

- A Kubernetes cluster (e.g., Minikube, Kind, GKE, EKS, AKS)
- `kubectl` configured to interact with your cluster
- Helm v3+

### Step 1: Install the Custom Resource Definition (CRD)

Apply the CRD definition to your cluster:
```bash
kubectl apply -f crds/coffeeorder.yaml
```

### Step 2: Deploy the Operator using Helm

Use the provided Helm chart to deploy the operator:
```bash
helm install kube-brew charts/terminal-operator-k8s \
  --set image.repository=ghcr.io/joshyorko/terminal-operator-k8s \
  --set image.tag=latest \ # Specify the desired image tag
  --set env.TERMINAL_ENVIRONMENT="dev"  # Use "production" for real orders
  # Ensure the secret 'terminal-api-secret' containing the token exists (see Configuration)
```

---

## Configuration

### Step 1: Obtain Terminal API Token

Retrieve your API token from Terminal:

- **Sandbox (Testing):**
  ```bash
  ssh dev.terminal.shop -t tokens
  ```
- **Production (Real Orders):**
  ```bash
  ssh terminal.shop -t tokens
  ```

### Step 2: Create Kubernetes Secret

Store your API token securely in a Kubernetes Secret. The Helm chart expects a secret named `terminal-api-secret` with a key `TERMINAL_BEARER_TOKEN`.

Create the secret in the target namespace (e.g., `default`):
```bash
kubectl create secret generic terminal-api-secret \
  --from-literal=TERMINAL_BEARER_TOKEN='YOUR_TOKEN_HERE' \
  -n default
```

### Step 3: Environment Configuration

The operator's behavior can be configured via environment variables, typically set during Helm deployment:

- `TERMINAL_ENVIRONMENT`: Set to `dev` (sandbox) or `production`. Defaults to `production` if not set.
- `TERMINAL_BEARER_TOKEN`: Injected from the `terminal-api-secret`.

---

## Usage

### Step 1: Create a Coffee Order

Define your coffee order in a YAML file (e.g., `my-coffee-order.yaml`):

```yaml
apiVersion: coffee.terminal.sh/v1alpha1
kind: CoffeeOrder
metadata:
  name: daily-espresso
  namespace: default # Ensure this matches the operator's namespace or is cluster-wide if applicable
spec:
  productVariantId: "var_REPLACE_WITH_VALID_ID"  # Obtain a valid ID from the Terminal API
  quantity: 1
  address:
    name: "Jane Doe"
    street1: "456 Oak Ave"
    city: "Anytown"
    state: "NY"
    zip: "10001"
    country: "US"
  cardToken: "tok_visa"  # Use Stripe test tokens for sandbox; use real card tokens for production
```

Apply the resource to your cluster:
```bash
kubectl apply -f my-coffee-order.yaml
```

### Step 2: Monitor Order Status

Check the status of your order:
```bash
kubectl get coffeeorder daily-espresso -n default -o yaml
```

Inspect the `status` field for the current `phase`, `orderId`, and any relevant messages.

---

## Development

### Building the Container Image

To build and push the operator container image:

1.  **Build the image:**
    ```bash
    docker build -t ghcr.io/YOUR_USERNAME/terminal-operator-k8s:latest .
    ```
2.  **Push the image:**
    ```bash
    docker push ghcr.io/YOUR_USERNAME/terminal-operator-k8s:latest
    ```
    *(Replace `YOUR_USERNAME` with your GitHub username or organization)*

### Local Development (Optional)

Instructions for running the operator locally using tools like `kopf run` could be added here.

---

## Best Practices & Considerations

- **Security:** Always use Kubernetes Secrets for API tokens. Avoid hardcoding sensitive information.
- **Environment:** Test thoroughly in the `dev` (sandbox) environment before deploying to `production`.
- **Idempotency:** Ensure the operator handles resource updates correctly and avoids duplicate orders.
- **Error Handling:** Implement robust error handling and status reporting for failed orders.
- **Resource Monitoring:** Monitor `CoffeeOrder` resources and operator logs to ensure correct operation.
- **Probes:** Add liveness and readiness probes to the operator deployment for better health checking in production.
- **Product IDs:** Verify that `productVariantId` values are correct for the target Terminal environment.

---

## Contributing

Coming soon! Contributions are welcome. Please open issues or pull requests for any enhancements, bug fixes, or suggestions.

---

## License

Apache License 2.0. See the [LICENSE](LICENSE) file for details.