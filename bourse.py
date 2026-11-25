import os
import requests
import yfinance as yf
from google import genai
from google.genai import types

# Liste des actions à surveiller (.PA = Bourse de Paris)
ACTIONS = ["MC.PA", "AI.PA", "TTE.PA"]

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

rapport = ""
for symbole in ACTIONS:
    ticker = yf.Ticker(symbole)
    hist = ticker.history(period="5d")
    prix = round(hist["Close"].iloc[-1], 2)
    var_5j = round(((hist["Close"].iloc[-1] - hist["Close"].iloc[0]) / hist["Close"].iloc[0]) * 100, 2)
    rapport += f"- {symbole} : {prix} € (Variation 5j : {var_5j}%)\n"

# Analyse par Gemini
reponse = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=f"Voici la clôture du jour :\n{rapport}\nFais un point boursier concis (3-4 lignes par action) sur la dynamique récente.",
    config=types.GenerateContentConfig(
        system_instruction="Tu es un analyste boursier synthétique. Réponds en français sans balises Markdown complexes.",
        temperature=0.2,
    ),
)

# Envoi sur votre iPhone via Telegram
url = f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/sendMessage"
requests.post(url, data={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": reponse.text})
