#!/bin/bash
# Script de vérification des ports avant lancement

echo "=== Vérification des ports avant lancement ==="

# Ports à vérifier
PORTS=(8005 8006 4096)

# Vérifier si un port est déjà utilisé
for port in "${PORTS[@]}"; do
    if lsof -i :"$port" > /dev/null 2>&1 || ss -tlnp | grep -q ":$port "; then
        echo "⚠️  Port $port déjà utilisé !"
        echo "   Processus utilisant le port:"
        lsof -i :"$port" 2>/dev/null | head -5
        echo "   (ou: lsof -i :$port)"
        echo ""
    fi
done

# Vérifier les containers Docker
echo "=== Containers Docker actifs ==="
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null | head -10

echo ""
echo "=== Résumé ==="
echo "Développer (DEV) : port 8005 (MCP)"
echo "Production (PROD): port 8006 (MCP)"
echo "OpenCode         : port 4096"
echo ""
echo "Pour éviter les conflits, ne lancez pas DEV et PROD en même temps !"
