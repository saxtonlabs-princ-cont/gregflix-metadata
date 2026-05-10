#!/usr/bin/env bash
set -euo pipefail

# Deploy gregflix-metadata into local K3s.
#
# Assumptions:
# - You run this from the gregflix-metadata project root.
# - Docker is available locally.
# - kubectl is configured for your K3s cluster.
# - Your local registry is registry.home.arpa.
# - Kubernetes manifests live under deploy/k8s.
# - A migration Job manifest exists at deploy/k8s/migration-job.yaml.
# - The app image name in your manifests is registry.home.arpa/gregflix-metadata:latest.
#
# This script uses sudo for docker and kubectl because your current homelab workflow requires it.

APP_NAME="gregflix-metadata"
NAMESPACE="gregflix"
IMAGE_REGISTRY="registry.home.arpa"
IMAGE_NAME="${IMAGE_REGISTRY}/${APP_NAME}:latest"

K8S_DIR="deploy/k8s"
MIGRATION_JOB_NAME="gregflix-metadata-migrate"

echo "==> Verifying project root"

if [[ ! -f "Dockerfile" ]]; then
  echo "ERROR: Dockerfile not found. Run this script from the gregflix-metadata project root."
  exit 1
fi

if [[ ! -d "${K8S_DIR}" ]]; then
  echo "ERROR: ${K8S_DIR} not found."
  exit 1
fi

echo "==> Building Docker image: ${IMAGE_NAME}"
sudo docker build -t "${IMAGE_NAME}" .

echo "==> Pushing image to local registry: ${IMAGE_NAME}"
sudo docker push "${IMAGE_NAME}"

echo "==> Ensuring namespace exists: ${NAMESPACE}"
sudo kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1 || \
  sudo kubectl create namespace "${NAMESPACE}"

echo "==> Applying ConfigMaps, Secrets, PVCs, ServiceAccounts, and base manifests"

# Apply everything except workload resources that should happen after migration.
# This is tolerant of missing files.
for file in \
  "${K8S_DIR}/namespace.yaml" \
  "${K8S_DIR}/configmap.yaml" \
  "${K8S_DIR}/secret.yaml" \
  "${K8S_DIR}/pvc.yaml" \
  "${K8S_DIR}/serviceaccount.yaml" \
  "${K8S_DIR}/rbac.yaml"
do
  if [[ -f "${file}" ]]; then
    echo "Applying ${file}"
    sudo kubectl apply -f "${file}"
  fi
done

echo "==> Removing old migration job if present"
sudo kubectl delete job "${MIGRATION_JOB_NAME}" -n "${NAMESPACE}" --ignore-not-found=true

if [[ ! -f "${K8S_DIR}/migration-job.yaml" ]]; then
  echo "ERROR: ${K8S_DIR}/migration-job.yaml not found."
  exit 1
fi

echo "==> Running database migration job"
sudo kubectl apply -f "${K8S_DIR}/migration-job.yaml"

echo "==> Waiting for migration job to complete"
if ! sudo kubectl wait \
  --for=condition=complete \
  "job/${MIGRATION_JOB_NAME}" \
  -n "${NAMESPACE}" \
  --timeout=180s; then

  echo "ERROR: Migration job failed or timed out."
  echo "==> Migration job details:"
  sudo kubectl describe job "${MIGRATION_JOB_NAME}" -n "${NAMESPACE}" || true

  echo "==> Migration logs:"
  sudo kubectl logs -n "${NAMESPACE}" "job/${MIGRATION_JOB_NAME}" --tail=200 || true

  exit 1
fi

echo "==> Migration logs:"
sudo kubectl logs -n "${NAMESPACE}" "job/${MIGRATION_JOB_NAME}" --tail=100 || true

echo "==> Applying service workload manifests"

for file in \
  "${K8S_DIR}/deployment.yaml" \
  "${K8S_DIR}/service.yaml" \
  "${K8S_DIR}/ingress.yaml"
do
  if [[ -f "${file}" ]]; then
    echo "Applying ${file}"
    sudo kubectl apply -f "${file}"
  fi
done

echo "==> Waiting for deployment rollout"
sudo kubectl rollout status "deployment/${APP_NAME}" -n "${NAMESPACE}" --timeout=180s

echo "==> Current pods"
sudo kubectl get pods -n "${NAMESPACE}" -o wide

echo "==> Current service"
sudo kubectl get svc -n "${NAMESPACE}" "${APP_NAME}" || true

echo "==> Health check through cluster service"

POD_NAME="$(sudo kubectl get pod -n "${NAMESPACE}" -l app.kubernetes.io/name="${APP_NAME}" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"

if [[ -z "${POD_NAME}" ]]; then
  echo "WARNING: Could not find pod with label app=${APP_NAME}. Skipping in-cluster health check."
  exit 0
fi

sudo kubectl exec -n "${NAMESPACE}" "${POD_NAME}" -- \
  python - <<'PY'
import urllib.request
import sys

url = "http://127.0.0.1:8000/health"

try:
    with urllib.request.urlopen(url, timeout=5) as response:
        body = response.read().decode("utf-8", errors="replace")
        print(body)
        sys.exit(0 if response.status < 400 else 1)
except Exception as exc:
    print(f"Health check failed: {exc}")
    sys.exit(1)
PY

echo "==> Deployment complete"