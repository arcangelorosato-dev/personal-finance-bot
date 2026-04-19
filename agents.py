import os
from agno.agent import Agent
from agno.team.team import Team
from agno.models.groq import Groq
from dotenv import load_dotenv

load_dotenv()


report_agent = Agent(
    name="Analista Senior",
    model=Groq(id="openai/gpt-oss-120b"),
    instructions=[
        "Riceverai una lista di transazioni del mese.",
        "Analizza dove l'utente sta spendendo di più.",
        "Scrivi una sintesi brevissima e ironica (max 3 righe) in italiano.",
        "Questa sintesi sarà la didascalia di un grafico a torta.",
        "Evidenzia la categoria dove l'utente ha esagerato.",
        "Sii colloquiale e usa qualche emoji."
    ],
)

# --- AGENTE 1: IL CONTABILE ---
parser_agent = Agent(
    name="Contabile",
    role="Estrai dati finanziari in formato JSON",
    model=Groq(id="openai/gpt-oss-120b"),
    description="Sei un estrattore di dati puro.",
    instructions=[
        "Estrai 'amount', 'category', 'merchant', 'is_bill'.",
        "LOGICA CATEGORIE: Cerca di raggruppare le spese in queste categorie standard: 'Cibo', 'Trasporti', 'Bollette', 'Shopping', 'Svago', 'Altro'.",
        "Se la spesa non rientra minimamente in queste, crea una nuova categoria specifica (es. 'Salute' o 'Regali').",
        "Usa sempre l'iniziale maiuscola e il singolare (es. 'Bolletta' e non 'bollette').",
        "Restituisci SOLO il JSON con virgolette doppie (\")."
    ],
)

# --- AGENTE 2: IL CONSULENTE ---
analyst_agent = Agent(
    name="Consulente",
    role="Commenta le spese in modo ironico",
    model=Groq(id="openai/gpt-oss-120b"),
    description="Commentatore finanziario ironico.",
    instructions=[
        "Commenta la spesa dell'utente in modo brevissimo (max 10 parole).",
        "Usa l'italiano e aggiungi una emoji.",
        "Non fare domande."
    ],
)

history_agent = Agent(
    name="Storico",
    model=Groq(id="openai/gpt-oss-120b"),
    description="Analista di trend storici.",
    instructions=[
        "Confronta la spesa attuale con il trend della categoria.",
        "Sii estremamente sintetico (una frase).",
        "Se è un saluto o chiacchiera inutile, ignora."
    ],
)

# --- IL TEAM ---
finance_team = Team(
    name="Finance Team",
    model=Groq(id="llama-3.3-70b-versatile"),
    members=[parser_agent, analyst_agent, history_agent],
    description="Sei un contabile che produce SOLO JSON validi e commenti brevi.",
   instructions=[
        "1. Se l'utente ti saluta o fa chiacchiere (es. 'Ciao', 'Come stai'), rispondi gentilmente ma dì che sei qui solo per gestire le finanze.",
        "2. Se il messaggio è una spesa: coordina i membri per ottenere il commento e il JSON.",
        "3. Calcola il totale correttamente (es. 2 x 10€ = 20€).",
        "4. Usa solo le categorie: Cibo, Trasporti, Bollette, Shopping, Altro.",
        "5. Fondamentale: Restituisci SEMPRE il JSON usando virgolette doppie (\").",
        "6. Non fare domande all'utente, limita l'output a: Commento + JSON.",
        "7. Se non è una spesa, non includere alcun JSON."
    ],
)