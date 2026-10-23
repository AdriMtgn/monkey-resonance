#!/usr/bin/env bash
# postCreateCommand du devcontainer : importe les credentials OpenCode
# exportés depuis l'hôte, vérifie que l'env de dev est complet.
#
# Une fois sur l'hôte, à la racine du repo :
#   opencode auth export > .devcontainer/opencode-auth.json
# (le fichier est gitignoré, il contient des secrets)
#
# Puis rebuild/recreate le devcontainer, ou relance ce script depuis un
# shell du container :
#   bash .devcontainer/scripts/post-create.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
AUTH_FILE="$REPO_ROOT/.devcontainer/opencode-auth.json"

echo "=== Agent OpenCode dans le container ==="
opencode --version

if [ -f "$AUTH_FILE" ]; then
  echo "Import des credentials depuis $AUTH_FILE ..."
  # --standalone évite de démarrer le service d'arrière-plan partagé ;
  # le fallback couvre les versions sans ce flag sur ce sous-commande.
  if ! opencode auth import --standalone < "$AUTH_FILE"; then
    opencode auth import < "$AUTH_FILE"
  fi
  opencode auth list --standalone 2>/dev/null || opencode auth list || true
else
  echo "Aucun fichier de credentials : $AUTH_FILE"
  echo "Sur l'hôte, à la racine du repo :"
  echo "  opencode auth export > .devcontainer/opencode-auth.json"
  echo "puis dans le container :"
  echo "  bash .devcontainer/scripts/post-create.sh"
fi

echo
echo "=== Env de dev ==="
echo "python : $(python --version 2>&1) ($(command -v python))"
if ! python -m pytest --version >/dev/null 2>&1; then
  echo "pytest absent de l'env courante, installation via requirements-dev.txt..."
  uv pip install -r "$REPO_ROOT/requirements-dev.txt"
else
  echo "pytest : $(python -m pytest --version 2>&1)"
fi
echo "ruff   : $(ruff --version 2>&1 || echo 'ABSENT (make lint échouera)')"

echo
echo "Post-create terminé. Lancer le serveur agent : .devcontainer/scripts/agent-server.sh"
