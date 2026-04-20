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
    model=Groq(id="openai/gpt-oss-120b"),
    members=[parser_agent, analyst_agent, history_agent],
    description="Sei un contabile che produce SOLO JSON validi e commenti brevi.",
   instructions=[
        "1. REGOLA D'ORO: Ogni cifra numerica nel messaggio deve essere catturata.",
        "2. SMISTAMENTO PRIORITARIO (Rigido):",
        "   a) ABBONAMENTO: Se l'utente cita servizi ricorrenti (Netflix, Spotify, Amazon Prime, DAZN, Disney+, Palestra, Affitto, iCloud) O usa 'abbonamento', 'ogni mese', 'mensile', 'rinnovo' -> action: 'subscription'. È PRIORITARIO su tutto.",
        "   b) SCADENZA: Se l'utente dice 'bolletta', 'da pagare', 'ricordami di' per una spesa futura singola -> action: 'bill'.",
        "   c) TRANSAZIONE: Solo se non rientra nei casi a o b ed è una spesa singola già fatta -> action: 'transaction'.",
        "3. REGOLE JSON SPECIFICHE:",
        "   - subscription: { 'action': 'subscription', 'name': 'nome_servizio', 'amount': valore, 'renewal_day': numero_giorno }",
        "   - bill: { 'action': 'bill', 'name': 'nome', 'amount': valore, 'due_date': 'YYYY-MM-DD' }",
        "   - transaction: { 'action': 'transaction', 'category': 'Categoria', 'description': 'descrizione', 'amount': valore, 'date': 'YYYY-MM-DD' }",
        "4. DATA E GIORNO: Se manca il giorno per l'abbonamento, usa il giorno corrente (20). Se manca la data per la transazione, usa oggi.",
        "5. SERVIZI NOTI: Per Netflix, Spotify, Amazon, DAZN, Palestra, Affitto, usa SOLO il nome come 'name' o 'description' e forza action 'subscription'.",
        "6. FORMATO: Produci SEMPRE E SOLO il JSON tra parentesi graffe, senza alcun testo di cortesia o spiegazione.",
        "7. Se il messaggio non contiene cifre, rispondi come assistente umano senza JSON."
    ],
)