# Terminal-Operator-k8s: Kubernetes Coffee Ordering

![Terminal Avatar](https://avatars.githubusercontent.com/u/166243908?s=200&v=4)

terminal-operator-k8s is a Kubernetes operator designed to automate coffee ordering via the Terminal API. It monitors `CoffeeOrder` custom resources within your cluster and processes orders accordingly.

## Quick Start Guide

### Prerequisites

- A Kubernetes cluster (e.g., Minikube, Kind, GKE, EKS, AKS)
- `kubectl` configured to interact with your cluster
- Helm v3+

### Setup Steps

1. Create the namespace for the terminal shop:
   ```bash
   kubectl create ns terminal-shop-dev
   ```

2. Create the Terminal API secret:
   - Copy the example secret file:
     ```bash
     cp terminal-api-secret-example.yaml terminal-api-secret.yaml
     ```
   - Edit `terminal-api-secret.yaml` and replace the placeholder token with your actual Terminal API token
   - Apply the secret:
     ```bash
     kubectl apply -f terminal-api-secret.yaml -n terminal-shop-dev
     ```

3. Install/Upgrade the operator using Helm:
   ```bash
   helm upgrade -i terminal-operator charts/terminal-operator --namespace terminal-shop-dev --values charts/terminal-operator/values.yaml
   ```

4. Create required resources (profile, address, and payment card):
   ```bash
   kubectl apply -f examples/common/ -n terminal-shop-dev
   ```

5. Place a coffee order:
   ```bash
   kubectl apply -f examples/orders/order-artisan.yaml -n terminal-shop-dev
   ```

## Monitor Your Order

Check the status of your order:
```bash
kubectl get coffeeorder -n terminal-shop-dev
```

For detailed order status:
```bash
kubectl describe coffeeorder <order-name> -n terminal-shop-dev
```

## Examples

The `examples/` directory contains:
- `common/`: Basic resources needed for ordering (profiles, addresses, cards)
- `orders/`: Sample coffee order configurations
  - `order-artisan.yaml`: Artisan coffee order
  - `order-dark-mode.yaml`: Dark roast coffee order
  - And more...

## Configuration

The operator uses a Kubernetes secret (`terminal-api-secret`) containing your Terminal API token. See `terminal-api-secret-example.yaml` for the required format.

## License

Apache License 2.0. See the [LICENSE](LICENSE) file for details.