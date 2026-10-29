#!/bin/bash
# Script de vérification et nettoyage des ports avant lancement
# TUE automatiquement tout processus qui utilise les ports MCP

echo "=== Vérification et nettoyage des ports ==="

# Ports à gérer
PORTS=(8005 4096)
PORT_NAMES=("MCP (Dev/Prod)" "OpenCode Agent")

for i in "${!PORTS[@]}"; do
    port=${PORTS[$i]}
    name=${PORT_NAMES[$i]}
    
    # Trouver le PID qui utilise ce port
    pid=$(lsof -t -i :"$port" 2>/dev/null || echo "")
    
    if [ -n "$pid" ]; then
        echo "⚠️  Port $port ($name) déjà utilisé par PID: $pid"
        
        # Demander confirmation avant de tuer
        read -p "Tuer le processus ($pid) ? (y/n) " -n 1 -r
        echo
        
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            kill -9 "$pid" 2>/dev/null
            echo "✅ Processus $pid tué - Port $port libéré"
        else
            echo "❌ Port $port toujours utilisé - Annulation"
            exit 1
        fi
    fi
done

# Nettoyer les containers Docker existants sur les ports
echo ""
echo "=== Nettoyer les containers Docker ==="

# Trouver les containers mkr ou app existants
existing_container=$(docker ps -q --filter "name=monkey-resonance" 2>/dev/null || echo "")

if [ -n "$existing_container" ]; then
    echo "⚠️  Container Docker existant détecté: $existing_container"
    read -p "Arrêter et supprimer ce container ? (y/n) " -n 1 -r
    echo
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        docker stop "$existing_container" 2>/dev/null
        docker rm "$existing_container" 2>/dev/null
        echo "✅ Container arrête et supprimé"
    else
        echo "❌ Container conservé - Annulation"
        exit 1
    fi
fi

echo ""
echo "=== Ports prêts pour le lancement ==="
echo "🟢 MCP (port 8005): Libre"
echo "🟢 OpenCode Agent (port 4096): Libre"
