import os
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import datetime
import matplotlib.pyplot as plt
import io

load_dotenv()

# Inizializzazione Supabase
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(url, key)

# --- FUNZIONI DI RECUPERO DATI ---

def get_monthly_report_data(user_id: int):
    """Recupera tutte le transazioni del mese corrente per il report."""
    start_of_month = datetime.now().replace(day=1, hour=0, minute=0, second=0).isoformat()
    
    response = supabase.table("transactions") \
        .select("amount, category, merchant, created_at") \
        .eq("user_id", user_id) \
        .gte("created_at", start_of_month) \
        .execute()
    
    return response.data

def get_category_total(user_id: int, category: str):
    """Calcola il totale speso in una specifica categoria nel mese corrente."""
    try:
        start_of_month = datetime.now().replace(day=1, hour=0, minute=0, second=0).isoformat()
        
        response = supabase.table("transactions") \
            .select("amount") \
            .eq("user_id", user_id) \
            .eq("category", category) \
            .gte("created_at", start_of_month) \
            .execute()
        
        if not response.data:
            return 0.0
            
        total = sum(item['amount'] for item in response.data)
        return float(total)
    except Exception as e:
        print(f"errore nel conteggio categoria: {e}")
        return 0.0

# --- FUNZIONI DI GESTIONE UTENTE ---

def get_user_settings(user_id: int):
    """Recupera budget e valuta dell'utente."""
    response = supabase.table("users_settings").select("*").eq("user_id", user_id).execute()
    return response.data[0] if response.data else None

def create_user_settings(user_id: int, budget: float = 0.0, currency: str = "EUR"):
    """Inizializza un nuovo utente nel sistema."""
    data = {
        "user_id": user_id,
        "budget_monthly": budget,
        "currency": currency
    }
    return supabase.table("users_settings").insert(data).execute()

# --- FUNZIONI DI SCRITTURA TRANSAZIONI E BOLLETTE ---

def add_transaction(user_id: int, amount: float, category: str, merchant: str, source: str = "text"):
    """Salva una transazione confermata nel database."""
    data = {
        "user_id": user_id,
        "amount": amount,
        "category": category,
        "merchant": merchant,
        "source": source
    }
    return supabase.table("transactions").insert(data).execute()

def add_bill(user_id: int, name: str, amount: float, due_date: str):
    """Registra una nuova bolletta in scadenza."""
    data = {
        "user_id": user_id,
        "name": name,
        "amount": amount,
        "due_date": due_date,
        "status": "pending"
    }
    return supabase.table("bills").insert(data).execute()

def update_bill_status(bill_id: str, status: str = "paid"):
    """Aggiorna lo stato di una bolletta (es. segnata come pagata)."""
    return supabase.table("bills").update({"status": status}).eq("id", bill_id).execute()

# --- GENERAZIONE GRAFICI ---

def generate_report_chart(transactions):
    """Genera un grafico a torta basato sulle transazioni fornite."""
    category_totals = {}
    for t in transactions:
        cat = t['category']
        category_totals[cat] = category_totals.get(cat, 0) + t['amount']

    labels = list(category_totals.keys())
    values = list(category_totals.values())
    
    # Configurazione estetica del grafico
    plt.figure(figsize=(8, 6), facecolor='#f0f0f0')
    colors = ['#FF5733', '#33FF57', '#3357FF', '#F333FF', '#FFB833']
    plt.pie(values, labels=labels, autopct='%1.1f%%', startangle=140, colors=colors, shadow=True)
    plt.title("Spese del Mese per Categoria", fontsize=14, fontweight='bold')

    # Salvataggio in buffer di memoria (RAM) per invio immediato via bot
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()
    return buf

def reset_monthly_data(user_id: int):
    """Cancella tutte le transazioni dell'utente per il mese corrente."""
    from datetime import datetime
    start_of_month = datetime.now().replace(day=1, hour=0, minute=0, second=0).isoformat()
    
    return supabase.table("transactions") \
        .delete() \
        .eq("user_id", user_id) \
        .gte("created_at", start_of_month) \
        .execute()