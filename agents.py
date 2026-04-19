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
        "Estrai: 'amount', 'category', 'merchant', 'description', 'is_bill'.",
        "REGOLE DI ESTRAZIONE:",
        "- 'description': l'oggetto acquistato (es: 'pizza', 'lavaggio auto', 'calzini').",
        "- 'merchant': il nome del negozio/posto se presente (es: 'OVS', 'Enel'). Se non c'è, lascia null.",
        "- 'category': raggruppa in Cibo, Trasporti, Bollette, Shopping, Svago, Altro.",
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
        "1. REGOLA D'ORO: Se vedi un numero seguito o preceduto da una parola (es. 10 euro, calzini 5), è SEMPRE una spesa.",
        "2. Non rispondere MAI 'non ho capito' se nel messaggio è presente una cifra numerica.",
        "3. Se rilevi una spesa, delega IMMEDIATAMENTE al Contabile (parser_agent) per il JSON e al Consulente per il commento.",
        "4. Ignora la cortesia: anche se l'utente scrive male, se c'è un prezzo, estrai i dati.",
        "5. Solo se il messaggio è puramente testuale e privo di cifre (es. 'Ciao', 'Grazie'), rispondi come assistente senza generare JSON.",
        "6. Produci SEMPRE il JSON con virgolette doppie (\")."
    ],
)