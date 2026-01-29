from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Dict
import paho.mqtt.client as mqtt 
import json, csv, threading
from datetime import datetime
from pathlib import Path
from collections import defaultdict

# Dossier de travail
BASE_DIR = Path(__file__).resolve().parent

# Crée l'application web
app = FastAPI(title="WiFi Tracker API")

# Active CORS (Cross-Origin Resource Sharing) pour que le navigateur ne bloque pas les requetes vers l'API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================= DATA =================
# Structure: mac -> {location: str, rssi_avg: float, ssid: str}
mac_db = {}
locations_coords = {}
scan_history = []

# ================= MQTT =================
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_TOPIC = "esp32/wifi/scan"

# ================= MODELS =================
class WiFiNetwork(BaseModel):
    ssid: str
    mac: str
    rssi: int
    channel: int

class ScanData(BaseModel): # pour voir si les données sont typées correctement 
    device_id: str
    timestamp: int
    networks: List[WiFiNetwork]

# ================= LOAD DB =================
def load_wifi_database(filename="wifi_database_clean.csv"):
    """
    Charge la base de données WiFi en indexant par adresse MAC.
    Structure: MAC -> {location: {rssi: int, ssid: str}}
    """
    path = BASE_DIR / filename
    
    print("\nChargement de la base de données WiFi :")
    
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)

        # Pour chaque ligne (c-à-d pour chaque wifi scanné)
        for row in reader:
            if len(row) < 5:
                continue # on ignore les lignes qui ont moins de 5 colonnes (incompletes)
                
            location = row[1].strip() # strip permet d'enlever les espace avant et apres
            ssid = row[2].strip()
            mac = row[3].strip().upper()  # normaliser en majuscules
            rssi = int(row[4])
            
            if not mac or not location:
                continue
            
            """
            maintenant, l'objectif est de construire le disctionnaire mac_db pour avoir cette structure : 
                
                mac_db = {
                    "adr MAC_1": {
                        "TOUR_A": {"rssi": -xy, "ssid": "nom_wifi_1"},
                        "TOUR_B": {"rssi": -y, "ssid": "nom_wifi_1"},
                        ...
                    }
                    "adr MAC_2": {
                        "TOUR_A": {"rssi": -xx, "ssid": "nom_wifi_2"},
                        "TOUR_C": {"rssi": -x, "ssid": "nom_wifi_2"},
                        ...
                    }
                    ...              
                }            
            """
            # si nouvelle adr MAC alors lui créer une cellule
            if mac not in mac_db:
                mac_db[mac] = {}
            
            # coupler l'adr MAC à sa localisation et renseigner la puissance et le nom du wifi
            mac_db[mac][location] = {
                "rssi": rssi,
                "ssid": ssid
            }
    
    print(f"Base de données chargée : {len(mac_db)} adresses MAC uniques")
    
    # statistiques par rapport au nombre de MAC par tour
    location_counts = defaultdict(int)
    for mac, locs in mac_db.items():
        for loc in locs.keys():
            location_counts[loc] += 1
    
    print("\nRépartition par localisation :")
    for loc, count in sorted(location_counts.items()):
        print(f"   {loc}: {count} MACs")

# récupérer la référence json des coordonnées gps pour faire la correspondance : tour <-> coord gps
def load_locations(filename="locations.json"):
    global locations_coords
    with open(BASE_DIR / filename, "r", encoding="utf-8") as f:
        locations_coords = json.load(f)
    
    # définition d'un emplacement par défaut si pas de wifi reconnu
    locations_coords["UNKNOWN"] = {
        "lat": 48.8466,
        "lng": 2.3571
    }
    
    print(f"\nCoordonnées GPS chargées : {len(locations_coords)} lieux\n")

    """
    ça donne :

        locations_coords = {
            "TOUR_56": {"lat": 48.845813, "lng": 2.356219},
            "TOUR_55": {"lat": 48.846120, "lng": 2.356716},
            "ESC": {"lat": 48.845271, "lng": 2.357067},
            "UNKNOWN": {"lat": 48.8466, "lng": 2.3571}
        }    
    """

# ================= POSITION =================
def estimate_position_simple(networks: List[WiFiNetwork]) -> tuple: # networks étant les wifi scannés par l'esp
    """
    Version simple basée sur la correspondance RSSI.
    Pour chaque MAC détectée, on compare le RSSI avec chaque localisation
    et on vote pour celle qui correspond le mieux.
    """
    # Scores par localisation
    location_scores = defaultdict(lambda: {
        "score": 0.0,
        "mac_votes": [],
        "mac_count": 0
    })

    """
    on s'attend à avoir : 

        location_scores = {
            "TOUR_56": {
                "score": 0.0,      # Score total accumulé
                "mac_votes": [],   # Détails des votes
                "mac_count": 0     # Nombre de MACs qui votent principalement pour cette tour
            },
            "TOUR_55": {...},
            # ...
        }    
    """
    
    print("\nAnalyse des réseaux détectés :")
    
    matched_networks = 0
    
    for network in networks:
        mac = network.mac.upper().strip()
        rssi_detected = network.rssi
        
        # Chercher cette MAC dans notre base
        if mac in mac_db:
            matched_networks += 1
            mac_info = mac_db[mac]
            
            print(f"\n   MAC : {mac} ({network.ssid}) - RSSI détecté : {rssi_detected} dBm")
            
            # Pour chaque localisation où cette MAC existe
            location_rssi_diffs = []
            
            for location, info in mac_info.items():
                rssi_ref = info["rssi"]
                rssi_diff = abs(rssi_detected - rssi_ref)
                location_rssi_diffs.append((location, rssi_ref, rssi_diff))
            
            # Trier selon différence de puissance (donc la clé d'indice 2 d'où x[2])(la plus petite = la plus proche)
            location_rssi_diffs.sort(key=lambda x: x[2])
            
            # Afficher toutes les localisations possibles
            for location, rssi_ref, rssi_diff in location_rssi_diffs:
                print(f"      • {location}: ref={rssi_ref:.1f} dBm, diff={rssi_diff:.1f} dB")
            
            # Pour ce wifi, la meilleure tour est :
            best_location = location_rssi_diffs[0][0]
            # Avec une différence par rapport à la BDD de référence de :
            best_diff = location_rssi_diffs[0][2]
            
            # Plus la différence est faible, plus le score est élevé
            for location, rssi_ref, rssi_diff in location_rssi_diffs:
                # Score inversement proportionnel à la différence
                if rssi_diff < 30:  # On ignore les différences trop grandes
                    score = 100.0 / (1.0 + rssi_diff)
                    location_scores[location]["score"] += score # au prochain wifi, le score sera rajouter au score de celui d'avant
                    location_scores[location]["mac_votes"].append({
                        "mac": mac,
                        "ssid": network.ssid,
                        "rssi_detected": rssi_detected,
                        "rssi_reference": rssi_ref,
                        "diff": rssi_diff,
                        "score": score
                    })

                    """
                    on s'attend à :

                        location_scores = {
                            "TOUR_46": {
                                "score": 33.33,
                                "mac_votes": [
                                    {
                                        "mac": "00:F6:63:CE:C6:54",
                                        "ssid": "eduroam",
                                        "rssi_detected": -65,
                                        "rssi_reference": -67,
                                        "diff": 2,
                                        "score": 33.33
                                    }
                                ],
                                "mac_count": 0  # sera incrémenté après
                            },
                            "TOUR_56": {
                                "score": 25.00,
                                "mac_votes": [...],
                                "mac_count": 0
                            }
                        }

                        Ceci est fait pour chaque wifi détécté par l'esp
                    """
            
            # Compter les MACs pour la meilleure localisation
            location_scores[best_location]["mac_count"] += 1
            
            print(f"      Vote principal pour : {best_location} (diff={best_diff:.1f} dB)")
        else:
            print(f"   MAC inconnue : {mac} ({network.ssid})")
    
    if not location_scores:
        print("\nAucune correspondance trouvée")
        return "UNKNOWN", 0.0, locations_coords["UNKNOWN"]
    
    # Trier par score total
    sorted_locations = sorted(
        location_scores.items(),
        key=lambda x: x[1]["score"],
        reverse=True
    )
    
    print(f"\nScores finaux par localisation :")
    for loc, data in sorted_locations[:5]:  # Top 5
        print(f"   {loc}: score={data['score']:.1f} ({data['mac_count']} MACs principales)")
    
    # Meilleure correspondance
    best_location = sorted_locations[0][0]
    best_data = sorted_locations[0][1]
    
    # Calculer la confiance
    if len(sorted_locations) > 1:
        second_score = sorted_locations[1][1]["score"]
        # Confiance basée sur l'écart avec le second
        score_ratio = best_data["score"] / (best_data["score"] + second_score)
        confidence = min(100, score_ratio * 100)
    else:
        confidence = 80.0
    
    coords = locations_coords.get(best_location, locations_coords["UNKNOWN"])
    
    print(f"\nPosition estimée : {best_location}")
    print(f"   Confiance : {confidence:.1f}%")
    print(f"   Score total : {best_data['score']:.1f}")
    print(f"   MACs principales : {best_data['mac_count']}/{matched_networks}")
    
    return best_location, round(confidence, 1), coords

# ================= MQTT =================
def on_connect(client, userdata, flags, rc):
    print("OK: MQTT connecté")
    client.subscribe(MQTT_TOPIC) # S'abonne au topic

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode()) # Décode le JSON
        scan = ScanData(**payload) # Valide les données
        
        print(f"\n{'='*60}")
        print(f"Nouveau scan de {scan.device_id}")
        print(f"{'='*60}")
        
        # Estime la position
        location, confidence, coords = estimate_position_simple(scan.networks)
        
        # Stocke dans l'historique
        scan_history.append({
            "device_id": scan.device_id,
            "timestamp": datetime.now().isoformat(),
            "location": location,
            "confidence": confidence,
            "lat": coords["lat"],
            "lng": coords["lng"]
        })
        
        print(f"\nRésultat final : {location} ({confidence}%)")
        print(f"   GPS : [{coords['lat']:.6f}, {coords['lng']:.6f}]")
        print(f"{'='*60}\n")
        
    except Exception as e:
        print("MQTT erreur:", e)
        import traceback
        traceback.print_exc()

mqtt_client = mqtt.Client()
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

def start_mqtt():
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    mqtt_client.loop_forever()

# ================= API =================
@app.on_event("startup")
async def startup():
    load_wifi_database()
    load_locations()
    threading.Thread(target=start_mqtt, daemon=True).start()

@app.get("/")
async def root():
    return FileResponse(BASE_DIR / "static" / "index.html")

@app.get("/api/latest") # pour renvoyer la dernière position si le client demande la position
async def latest():
    if not scan_history:
        raise HTTPException(404, "Aucune donnée")
    return scan_history[-1]

@app.get("/api/history")
async def history(limit: int = 50):
    return scan_history[-limit:]

@app.get("/api/stats")
async def stats():
    """Statistiques sur la base de données"""
    return {
        "total_macs": len(mac_db),
        "locations": list(locations_coords.keys()),
        "scans_received": len(scan_history)
    }

# ================= RUN =================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)