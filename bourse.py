import os
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
MONTANT_MAX_PAR_ORDRE = 500.0 # En dollars virtuels ($)

# --- 2. CONNEXION AU COMPTE DE SIMULATION ALPACA (paper=True = FICTIF) ---
trading_client = TradingClient(
    os.environ["ALPACA_API_KEY"],
    os.environ["ALPACA_SECRET_KEY"],
    paper=True
)

compte = trading_client.get_account()
cash_disponible = float(compte.cash)
positions = trading_client.get_all_positions()
portefeuille_str = ", ".join([f"{p.symbol}: {p.qty} actions (valeur {p.market_value}$)" for p in positions]) or "Aucune position"

# --- 3. RÉCUPÉRATION DES COURS DU JOUR ---
donnees_marche = ""
for symbole in ACTIONS_AUTORISEES:
    hist = yf.Ticker(symbole).history(period="5d")
    prix = round(hist["Close"].iloc[-1], 2)
    var_5j = round(((hist["Close"].iloc[-1] - hist["Close"].iloc[0]) / hist["Close"].iloc[0]) * 100, 2)
    donnees_marche += f"- {symbole} : {prix} $ (Variation 5j : {var_5j}%)\n"

# --- 4. DÉCISION DE GEMINI ---
class OrdreBourse(BaseModel):
    decision: str   # "BUY", "SELL" ou "HOLD"
    symbole: str
    montant_usd: float
    justification: str

client_ia = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

prompt = f"""
État de mon portefeuille virtuel :
- Cash disponible : {cash_disponible} $
- Actions détenues : {portefeuille_str}

Données de marché (5 derniers jours) :
{donnees_marche}

Règles : Choisis une seule action parmi {ACTIONS_AUTORISEES}. Si tu achètes (BUY), ne dépasse jamais {MONTANT_MAX_PAR_ORDRE} $. Si tu vends (SELL), vends uniquement une action déjà détenue. Sinon choisis HOLD.
"""

reponse = client_ia.models.generate_content(
    model="gemini-3.0-flash",
    contents=prompt,
    config=types.GenerateContentConfig(
        system_instruction="Tu es un gestionnaire de portefeuille prudent et discipliné.",
        response_mime_type="application/json",
        response_schema=OrdreBourse,
        temperature=0.1,
    ),
)

ordre = OrdreBourse.model_validate_json(reponse.text)
statut_execution = "Aucune opération exécutée (HOLD)."

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
            statut_execution = f"✅ ORDRE VIRTUEL : Achat de {montant_securise} $ sur {ordre.symbole}"

    elif ordre.decision == "SELL":
        actions_detenues = [p.symbol for p in positions]
        if ordre.symbole in actions_detenues:
            trading_client.close_position(ordre.symbole)
            statut_execution = f"✅ ORDRE VIRTUEL : Vente totale de {ordre.symbole}"

# --- 6. RAPPORT SUR TELEGRAM ---
message = (
    f"🧪 RAPPORT SIMULATION (PAPER)\n"
    f"Cash virtuel : {cash_disponible} $\n"
    f"Décision IA : {ordre.decision} ({ordre.symbole})\n"
    f"Exécution : {statut_execution}\n\n"
    f"Analyse : {ordre.justification}"
)

url_tg = f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/sendMessage"
requests.post(url_tg, data={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": message})
