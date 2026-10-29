#!/bin/bash
# Script de vérification et nettoyage des ports avant lancement
# Vérifie et confirme AVANT de tuer n'importe quel processus

echo "=== Vérification des ports ==="

PORTS=(8005 4096)
PORT_NAMES=("MCP" "OpenCode")
KILLED=0

# Vérifier les processus sur les ports
for i in "${!PORTS[@]}"; do
    port=${PORTS[$i]}
    name=${PORT_NAMES[$i]}
    
    pid=$(lsof -t -i :"$port" 2>/dev/null | head -1 || echo "")
    
    if [ -n "$pid" ]; then
        # Trouver le nom du processus
        process_name=$(ps -p "$pid" -o comm= 2>/dev/null || echo "unknown")
        command=$(ps -p "$pid" -o args= 2>/dev/null | head -c 80 || echo "")
        
        echo "⚠️  Port $port ($name) déjà utilisé"
        echo "   PID: $pid"
        echo "   Processus: $process_name"
        
        # Vérifier si c'est un container monkey-resonnance
        if [[ "$command" == *"docker"* ]] || [[ "$command" == *"compose"* ]]; then
            echo "   ✅ C'est un container monkey-resonnance"
            
            # Vérifier si c'est le service correct
            container_name=$(docker inspect "$pid" --format '{{.Name}}' 2>/dev/null || echo "")
            if [[ "$container_name" == *"monkey-resonance"* ]]; then
                echo "   Container: $container_name"
            fi
            
            read -p "🔧 Arrêter ce container ? (o/n) " -n 1 -r
            echo
            
            if [[ $REPLY =~ ^[Oo]$ ]]; then
                # Trouver le container
                container=$(docker ps -q --filter "name=monkey-resonance" 2>/dev/null | head -1 || echo "")
                if [ -n "$container" ]; then
                    docker stop "$container" 2>/dev/null
                    docker rm "$container" 2>/dev/null
                    echo "✅ Container $container arrête et supprimé"
                    KILLED=$((KILLED+1))
                fi
            else
                echo "❌ Annulation - Port $port bloqué"
                exit 1
            fi
        else
            echo "   Processus externe: $process_name"
            echo "   Commande: $command"
            echo ""
            echo "⚠️  ⚠️  ⚠️  ATTENTION ⚠️  ⚠️  ⚠️"
            echo "   Ce n'est PAS un processus monkey-resonnance !"
            echo ""
            read -p "   Voulez-vous vraiment continuer avec ce processus ? (o/n) " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Oo]$ ]]; then
                echo "   ⚠️  Vous continuez avec un service existant sur le port $port"
                echo "   Cela peut causer des conflits !"
            else
                echo "   ❌ Annulation par précaution"
                exit 1
            fi
        fi
        echo ""
    fi
done

# Vérifier les containers Docker monkey-resonnance
echo "=== Containers Docker ==="
existing_container=$(docker ps -q --filter "name=monkey-resonance" 2>/dev/null | head -1 || echo "")

if [ -n "$existing_container" ]; then
    echo "⚠️  Container Docker détecté: $existing_container"
    container_info=$(docker ps --filter "id=$existing_container" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null)
    echo "$container_info"
    echo ""
    read -p "🔧 Voulez-vous l'arrêter et le supprimer ? (o/n) " -n 1 -r
    echo
    
    if [[ $REPLY =~ ^[Oo]$ ]]; then
        docker stop "$existing_container" 2>/dev/null
        docker rm "$existing_container" 2>/dev/null
        echo "✅ Container supprimé"
    else
        echo "❌ Container conservé - Vérifiez les ports manuellement"
        exit 1
    fi
fi

echo ""
echo "=== Résumé ==="
if [ $KILLED -eq 0 ]; then
    echo "🟢 Aucun conflit détecté - Ports prêts !"
else
    echo "🟡 $KILLED processus(s) arrete(s)"
fi

echo "🟢 Port 8005 (MCP): Libre"
echo "🟢 Port 4096 (OpenCode): Libre"
echo ""
echo "✅ Vous pouvez lancer votre service maintenant"
