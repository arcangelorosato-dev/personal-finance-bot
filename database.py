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

def delete_subscription(sub_id):
    """elimina un abbonamento ricorrente"""
    return supabase.table("subscriptions").delete().eq("id", sub_id).execute()

def add_subscription(user_id, name, amount, renewal_day):
    """registra un nuovo abbonamento ricorrente"""
    return supabase.table("subscriptions").insert({
        "user_id": user_id,
        "name": name.lower().strip(),
        "amount": amount,
        "renewal_day": renewal_day
    }).execute()

def get_user_subscriptions(user_id):
    # deve puntare alla tabella 'subscriptions' e filtrare per l'utente attuale
    return supabase.table("subscriptions").select("*").eq("user_id", user_id).execute()

def get_all_pending_bills(user_id):
    """recupera tutte le scadenze pendenti ordinate per data"""
    return supabase.table("bills")\
        .select("*")\
        .eq("user_id", user_id)\
        .eq("status", "pending")\
        .order("due_date", desc=False)\
        .execute()

def delete_bill(bill_id):
    """elimina definitivamente una scadenza dal database"""
    return supabase.table("bills").delete().eq("id", bill_id).execute()

def add_bill(user_id, name, amount, due_date):
    """inserisce una nuova scadenza nel database"""
    return supabase.table("bills").insert({
        "user_id": user_id,
        "name": name.lower().strip(), # manteniamo il tuo standard minuscolo
        "amount": amount,
        "due_date": due_date,
        "status": "pending"
    }).execute()

def get_today_bills():
    """recupera le bollette che scadono oggi e sono ancora pendenti"""
    from datetime import date
    today = date.today().isoformat()
    return supabase.table("bills").select("*").eq("due_date", today).eq("status", "pending").execute()

def mark_bill_as_paid(bill_id):
    """aggiorna lo stato della bolletta a pagata"""
    return supabase.table("bills").update({"status": "paid"}).eq("id", bill_id).execute()

def get_existing_categories():
    # recupera tutte le categorie uniche già presenti nel tuo db
    response = supabase.table("transactions").select("category").execute()
    # crea una lista senza duplicati
    categories = list(set([row['category'] for row in response.data]))
    return categories

def update_user_budget(user_id: int, budget: float):
    """aggiorna il budget mensile nella tabella corretta."""
    return supabase.table("users_settings") \
        .update({"budget_monthly": budget}) \
        .eq("user_id", user_id) \
        .execute()

def add_transaction_from_ocr(user_id, amount, category, description, date):
    # normalizzazione forzata
    category_clean = category.lower().strip()
    description_clean = description.lower().strip()
    
    return supabase.table("transactions").insert({
        "user_id": user_id,
        "amount": amount,
        "category": category_clean,
        "description": description_clean,
        "transaction_date": date
    }).execute()

def get_expenses_by_category(user_id: int, category: str):
    """recupera il dettaglio delle spese per una singola categoria nel mese corrente."""
    from datetime import datetime
    inizio_mese = datetime.now().replace(day=1).strftime("%Y-%m-%d")

    response = supabase.table("transactions") \
        .select("amount, description, transaction_date") \
        .eq("user_id", user_id) \
        .ilike("category", category) \
        .gte("transaction_date", inizio_mese) \
        .order("transaction_date", desc=True) \
        .execute()
    
    return response.data

def search_transactions(user_id: int, query: str):
    """Ricerca espansa su merchant, categoria e descrizione."""
    from datetime import datetime
    start_of_month = datetime.now().replace(day=1, hour=0, minute=0, second=0).isoformat()
    
    search_term = f"%{query}%"
    
    # Cerchiamo in tutte e tre le colonne testuali
    response = supabase.table("transactions") \
        .select("*") \
        .eq("user_id", user_id) \
        .gte("created_at", start_of_month) \
        .or_(f"merchant.ilike.{search_term},category.ilike.{search_term},description.ilike.{search_term}") \
        .order("created_at", desc=True) \
        .execute()
        
    return response.data


def get_last_transaction_date(user_id):
    # recupera l'ultima transazione dell'utente per vedere quanto è "vecchia"
    response = supabase.table("transactions")\
        .select("transaction_date")\
        .eq("user_id", user_id)\
        .order("transaction_date", desc=True)\
        .limit(1)\
        .execute()
    return response.data[0]['transaction_date'] if response.data else None

def get_monthly_total(user_id: int):
    """calcola la somma totale spesa dall'utente nel mese corrente."""
    response = supabase.table("transactions") \
        .select("amount") \
        .eq("user_id", user_id) \
        .execute()
    
    return sum(float(item.get('amount', 0)) for item in response.data)

def delete_transaction_by_id(transaction_id: str):
    """elimina una transazione specifica tramite il suo UUID."""
    # transaction_id qui deve essere la stringa dell'UUID
    return supabase.table("transactions").delete().eq("id", transaction_id).execute()

def get_monthly_report_data(user_id: int):
    """recupera le spese e le raggruppa in modo ultra-sicuro."""
    from datetime import datetime
    start_of_month = datetime.now().replace(day=1, hour=0, minute=0, second=0).isoformat()
    
    response = supabase.table("transactions") \
        .select("category, amount") \
        .eq("user_id", user_id) \
        .execute()
    
    if not response.data:
        return []

    report_dict = {}
    for item in response.data:
        cat = item.get('category', 'Altro')
        # FIX: usiamo 'amount' (come visto nel debug) e non 'total_amount' qui!
        try:
            amt = float(item.get('amount', 0))
        except (ValueError, TypeError):
            amt = 0.0
            
        report_dict[cat] = report_dict.get(cat, 0) + amt
    
    # qui creiamo la lista per il grafico e il report
    formatted_data = [
        {'category': k, 'total_amount': v} 
        for k, v in report_dict.items()
    ]
    return formatted_data

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
    """assicurati che anche questa usi users_settings."""
    response = supabase.table("users_settings") \
        .select("*") \
        .eq("user_id", user_id) \
        .execute()
    return response.data

def create_user_settings(user_id: int, budget: float = 0.0, currency: str = "EUR"):
    """Inizializza un nuovo utente nel sistema."""
    data = {
        "user_id": user_id,
        "budget_monthly": budget,
        "currency": currency
    }
    return supabase.table("users_settings").insert(data).execute()

# --- FUNZIONI DI SCRITTURA TRANSAZIONI E BOLLETTE ---

def add_transaction(user_id, category, description, amount, date=None):
    # Se la funzione non riceve la data, usiamo oggi
    if date is None:
        from datetime import datetime
        date = datetime.now().strftime("%Y-%m-%d")
        
    data = {
        "user_id": user_id,
        "category": category,
        "description": description,
        "amount": amount,
        "transaction_date": date
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
    """genera il grafico a torta filtrando i dati ed evitando errori nan."""
    import matplotlib
    matplotlib.use('Agg') # fondamentale per server e bot
    import matplotlib.pyplot as plt
    import io

    # 1. pulizia e conversione dati
    valid_data = []
    for t in transactions:
        try:
            # forziamo la conversione in float per sicurezza
            amount = float(t.get('total_amount', 0))
            if amount > 0:
                valid_data.append({
                    'category': t.get('category', 'Altro'),
                    'total_amount': amount
                })
        except (ValueError, TypeError):
            continue

    # 2. se non ci sono dati validi, usciamo subito
    if not valid_data:
        return None 

    # 3. preparazione liste per il grafico
    labels = [t['category'] for t in valid_data]
    values = [t['total_amount'] for t in valid_data]
    
    # 4. creazione del grafico
    plt.figure(figsize=(8, 6), facecolor='#f0f0f0')
    colors = ['#ff9999','#66b3ff','#99ff99','#ffcc99','#c2c2f0','#ffb3e6']
    
    plt.pie(
        values, 
        labels=labels, 
        autopct='%1.1f%%', 
        startangle=140, 
        colors=colors,
        pctdistance=0.85
    )
    
    # stile donut (ciambella)
    centre_circle = plt.Circle((0,0), 0.70, fc='#f0f0f0')
    fig = plt.gcf()
    fig.gca().add_artist(centre_circle)

    plt.title("riepilogo spese mensili", fontsize=14, fontweight='bold')
    plt.axis('equal') 

    # 5. salvataggio in buffer memoria
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    buf.seek(0)
    plt.close() # libera memoria
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