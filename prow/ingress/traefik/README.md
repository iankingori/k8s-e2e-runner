# Traefik ingress controller

Deployment steps:

* Install Helm v3. See [installation instructions](https://v3.helm.sh/docs/intro/install).

* Add the Traefik Helm repository:

    ```bash
    helm repo add traefik https://helm.traefik.io/traefik
    helm repo update
    ```

* Install the Traefik Ingress Controller:

    ```bash
    ./setup.sh
    ```
