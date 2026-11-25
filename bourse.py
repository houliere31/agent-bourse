import os
import time
import requests
import yfinance as yf
from pydantic import BaseModel
from google import genai
from google.genai import types
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# --- 1. PARAMÈTRES DU PORTEFEUILLE VIRTUEL ---
ACTIONS_AUTORISEES = ["AAPL", "MSFT", "NVDA", "SPY"]
MONTANT_MAX_PAR_ORDRE = 2000.0  # Plafond relevé à 2000 $

# --- 2. CONNEXION AU COMPTE DE SIMULATION ALPACA ---
trading_client = TradingClient(
    os.environ["ALPACA_API_KEY"],
    os.environ["ALPACA_SECRET_KEY"],
    paper=True
)

# Vérifie si la bourse américaine (NYSE/NASDAQ) est actuellement ouverte
horloge = trading_client.get_clock()
if not horloge.is_open:
    print("Marché américain fermé. Aucune analyse effectuée.")
    exit(0)

compte = trading_client.get_account()
cash_disponible = float(compte.cash)
positions = trading_client.get_all_positions()
portefeuille_str = ", ".join(
    [f"{p.symbol}: {p.qty} actions (valeur {p.market_value}$)" for p in positions]
) or "Aucune position"

# --- 3. RÉCUPÉRATION DES COURS EN DIRECT (INTERVALLE 15 MINUTES) ---
donnees_marche = ""
for symbole in ACTIONS_AUTORISEES:
    hist = yf.Ticker(symbole).history(period="1d", interval="15m")
    if len(hist) >= 2:
        prix_actuel = round(hist["Close"].iloc[-1], 2)
        prix_ouverture = round(hist["Open"].iloc[0], 2)
        var_jour = round(((prix_actuel - prix_ouverture) / prix_ouverture) * 100, 2)
        var_15m = round(((prix_actuel - hist["Close"].iloc[-2]) / hist["Close"].iloc[-2]) * 100, 2)
        donnees_marche += f"- {symbole} : {prix_actuel} $ (Jour : {var_jour}%, Dernières 15 min : {var_15m}%)\n"

# --- 4. DÉCISION DE GEMINI ---
class OrdreBourse(BaseModel):
    decision: str   # "BUY", "SELL" ou "HOLD"
    symbole: str
    montant_usd: float
    justification: str

client_ia = genai.Client(
    api_key=os.environ["GEMINI_API_KEY"],
    http_options={"api_version": "v1beta"}
)

prompt = f"""
État de mon portefeuille virtuel :
- Cash disponible : {cash_disponible} $
- Actions détenues : {portefeuille_str}

Données de marché en direct (séance en cours, pas de 15 min) :
{donnees_marche}

Règles : Tu surveilles le marché en continu. Choisis une seule action parmi {ACTIONS_AUTORISEES}.
- N'achète (BUY, max {MONTANT_MAX_PAR_ORDRE} $) que si tu détectes une vraie opportunité ou un signal clair sur la séance (évite d'acheter la même action en boucle si tu en détiens déjà beaucoup).
- Ne vends (SELL) qu'une action déjà détenue si le mouvement se retourne ou pour sécuriser des gains.
- Dans la majorité des cas, si rien de décisif ne se passe, réponds HOLD.
"""

modeles_disponibles = [
    m.name for m in client_ia.models.list()
    if "gemini" in m.name.lower()
    and "generateContent" in (m.supported_actions or [])
    and not any(x in m.name.lower() for x in ["embedding", "imagen", "veo", "audio", "tts", "robotics"])
]

reponse = None
modele_utilise = ""
erreurs_log = []

for modele in modeles_disponibles:
    try:
        reponse = client_ia.models.generate_content(
            model=modele,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction="Tu es un trader intraday discipliné et sélectif. Tu n'interviens que lorsqu'un signal est pertinent.",
                response_mime_type="application/json",
                response_schema=OrdreBourse,
                temperature=0.1,
            ),
        )
        modele_utilise = modele
        break
    except Exception as e:
        erreurs_log.append(f"{modele}: {e}")
        time.sleep(2)
        continue

if reponse is None:
    raise RuntimeError("Échec sur tous les modèles : " + " | ".join(erreurs_log))

ordre = OrdreBourse.model_validate_json(reponse.text)
statut_execution = None

# --- 5. EXÉCUTION DE L'ORDRE VIRTUEL ---
if ordre.symbole in ACTIONS_AUTORISEES:
    if ordre.decision == "BUY":
        montant_securise = min(ordre.montant_usd, MONTANT_MAX_PAR_ORDRE)
        if cash_disponible >= montant_securise and montant_securise >= 1.0:
            requete_achat = MarketOrderRequest(
                symbol=ordre.symbole,
                notional=round(montant_securise, 2),
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY
            )
            trading_client.submit_order(order_data=requete_achat)
            statut_execution = f"✅ ACHAT : {montant_securise} $ sur {ordre.symbole}"

    elif ordre.decision == "SELL":
        actions_detenues = [p.symbol for p in positions]
        if ordre.symbole in actions_detenues:
            trading_client.close_position(ordre.symbole)
            statut_execution = f"✅ VENTE TOTALE : {ordre.symbole}"

# --- 6. NOTIFICATION TELEGRAM UNIQUEMENT SI UN ORDRE EST PASSÉ ---
if statut_execution:
    message = (
        f"⚡ ALERTE TRADING EN DIRECT\n"
        f"Modèle : {modele_utilise}\n"
        f"{statut_execution}\n"
        f"Cash restant : {round(cash_disponible, 2)} $\n\n"
        f"Raison : {ordre.justification}"
    )
    url_tg = f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/sendMessage"
    requests.post(url_tg, data={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": message})
else:
    print(f"HOLD sur {ordre.symbole} : {ordre.justification}")
