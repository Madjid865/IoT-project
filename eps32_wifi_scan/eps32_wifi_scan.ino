#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// ========== CONFIGURATION WiFi ==========
const char* ssid = "wifi    // Remplace par ton WiFi
const char* password = "---"" // Remplace par ton mot de passe

// ========== CONFIGURATION MQTT ==========
const char* mqtt_server = "broker.hivemq.com";
const int mqtt_port = 1883;
const char* mqtt_topic = "esp32/wifi/scan";
const char* device_id = "ESP32_TRACKER_01"; // ID unique de ton tracker

// ========== CONFIGURATION SCAN ==========
const int SCAN_INTERVAL = 5000; // Scan toutes les 5 secondes
unsigned long lastScan = 0;

WiFiClient espClient;
PubSubClient client(espClient);

void setup() {
  Serial.begin(115200);
  delay(1000);
  
  Serial.println("\n=================================");
  Serial.println("   ESP32 WiFi Tracker v1.0");
  Serial.println("=================================\n");

  // Connexion WiFi
  connectWiFi();
  
  // Configuration MQTT
  client.setServer(mqtt_server, mqtt_port);
  client.setBufferSize(2048); // Augmenter le buffer pour les gros messages
  
  Serial.println("✓ Système prêt !\n");
}

void loop() {
  // Maintenir la connexion MQTT
  if (!client.connected()) {
    reconnectMQTT();
  }
  client.loop();

  // Scanner les WiFi à intervalle régulier
  if (millis() - lastScan > SCAN_INTERVAL) {
    lastScan = millis();
    scanAndPublish();
  }
}

void connectWiFi() {
  Serial.print("Connexion au WiFi");
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);
  
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 30) {
    delay(500);
    Serial.print(".");
    attempts++;
  }
  
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n✓ WiFi connecté !");
    Serial.print("  IP: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\n✗ Échec connexion WiFi");
    Serial.println("  Vérifiez vos identifiants et redémarrez");
    while(1) delay(1000);
  }
}

void reconnectMQTT() {
  Serial.print("Connexion MQTT");
  
  int attempts = 0;
  while (!client.connected() && attempts < 5) {
    if (client.connect(device_id)) {
      Serial.println(" ✓");
      break;
    } else {
      Serial.print(".");
      delay(2000);
      attempts++;
    }
  }
  
  if (!client.connected()) {
    Serial.println(" ✗");
  }
}

void scanAndPublish() {
  Serial.println("\n🔍 Scan WiFi en cours...");
  
  int n = WiFi.scanNetworks();
  
  if (n == 0) {
    Serial.println("  Aucun réseau trouvé");
    return;
  }
  
  Serial.printf("  %d réseaux détectés\n", n);
  
  // Création du JSON
  StaticJsonDocument<2048> doc;
  doc["device_id"] = device_id;
  doc["timestamp"] = millis();
  
  JsonArray networks = doc.createNestedArray("networks");
  
  // Limiter à 15 réseaux pour éviter de saturer le buffer
  int maxNetworks = min(n, 15);
  
  for (int i = 0; i < maxNetworks; i++) {
    JsonObject net = networks.createNestedObject();
    
    String ssid_str = WiFi.SSID(i);
    if (ssid_str.length() == 0) {
      ssid_str = "";
    }
    
    net["ssid"] = ssid_str;
    net["mac"] = WiFi.BSSIDstr(i);
    net["rssi"] = WiFi.RSSI(i);
    net["channel"] = WiFi.channel(i);
    
    Serial.printf("  [%d] %s | %s | %d dBm\n", 
                  i+1, 
                  ssid_str.c_str(), 
                  WiFi.BSSIDstr(i).c_str(), 
                  WiFi.RSSI(i));
  }
  
  // Sérialisation et envoi MQTT
  String payload;
  serializeJson(doc, payload);
  
  if (client.publish(mqtt_topic, payload.c_str())) {
    Serial.println("  ✓ Données envoyées au serveur MQTT");
  } else {
    Serial.println("  ✗ Échec envoi MQTT");
  }
  
  WiFi.scanDelete();
}