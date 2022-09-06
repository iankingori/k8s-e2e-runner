# Traefik v2 ingress controller

Deployment steps:

* Install Helm v3. See https://v3.helm.sh/docs/intro/install for instructions.

* Install the Traefik Ingress chart:

    ```bash
    helm repo add traefik https://helm.traefik.io/traefik
    helm repo update

    helm install --wait --values traefik-values.yaml traefik traefik/traefik
    ```

* Create the Prow Traefik ingress route via:

    ```bash
    kubectl apply -f ingress-routes.yaml
    ```
