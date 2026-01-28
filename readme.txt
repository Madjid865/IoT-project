STRUCTURE DES FICHIERS
--------------------------
project/
│
├── venv/                           # Environnement virtuel
│
├── server.py                       # Serveur principal
├── wifi_database_clean.csv         # Base de données WiFi
├── locations.json                  # Coordonnées GPS des tours
├── requirements.txt                # Dépendances Python
├── README.txt                      # Ce fichier
│
└── static/
    └── index.html                  # Interface web

================================================================================

Étapes à suivre
-------------------
1. Flasher l'ESP32 pour qu'il envoie des scans via MQTT
2. Ouvrir un terminal dans le dossier du projet
3. Activer l'environnement virtuel : venv\Scripts\activate
4. Lancer le serveur : python server.py
5. Ouvrir le navigateur : http://localhost:8000
6. Le serveur affiche la position estimée
7. L'interface web se met à jour automatiquement

================================================================================

MQTT - CONFIGURATION ESP32
------------------------------
Broker : broker.hivemq.com
Port   : 1883
Topic  : esp32/wifi/scan

Format JSON attendu :
{
  "device_id": "ESP32_001",
  "timestamp": 1738252800,
  "networks": [
    {
      "ssid": "eduroam",
      "mac": "AA:BB:CC:DD:EE:FF",
      "rssi": -65,
      "channel": 11
    }
  ]
}



