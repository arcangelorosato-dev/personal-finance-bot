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

# --- 1. GESTIONE UTENTE (ANAGRAFICA & MULTILINGUA) ---

def register_user(user_id, username, first_name, lang):
    """registra o aggiorna l'utente nella tabella centrale."""
    lang_clean = lang[:2] if lang else 'it'
    data = {
        "id": user_id,
        "username": username,
        "first_name": first_name,
        "language_code": lang_clean
    }
    return supabase.table("users").upsert(data).execute()

def get_user_language(user_id):
    """recupera la lingua dell'utente."""
    response = supabase.table("users").select("language_code").eq("id", user_id).execute()
    return response.data[0]['language_code'] if response.data else 'it'

def get_all_users():
    # recuperiamo sia l'id che il codice lingua in un'unica chiamata
    response = supabase.table("users").select("id, language_code").execute()
    return response.data

# --- 2. GESTIONE TRANSAZIONI (MULTIUTENZA) ---

def get_category_total(user_id: int, category: str):
    """calcola il totale speso in una specifica categoria nel mese corrente."""
    from datetime import datetime
    inizio_mese = datetime.now().replace(day=1).strftime("%Y-%m-%d")
    
    response = supabase.table("transactions") \
        .select("amount") \
        .eq("user_id", user_id) \
        .ilike("category", category) \
        .gte("transaction_date", inizio_mese) \
        .execute()
    
    if not response.data:
        return 0.0
        
    return sum(float(item['amount']) for item in response.data)

def add_transaction(user_id, amount, category, merchant=None, description=None, date=None):
    if date is None:
        from datetime import datetime
        date = datetime.now().strftime("%Y-%m-%d")
        
    data = {
        "user_id": user_id,
        "amount": float(amount),
        "category": str(category or "altro").lower().strip(),
        "merchant": str(merchant or "").lower().strip(),
        "description": str(description or "").lower().strip(),
        "transaction_date": date
    }
    return supabase.table("transactions").insert(data).execute()

def add_transaction_from_ocr(user_id, amount, category, description, date):
    """normalizzazione forzata per flussi OCR."""
    return add_transaction(user_id, category, description, amount, date)

def get_monthly_total(user_id: int):
    """calcola il totale speso nel mese corrente dall'utente."""
    inizio_mese = datetime.now().replace(day=1).strftime("%Y-%m-%d")
    response = supabase.table("transactions") \
        .select("amount") \
        .eq("user_id", user_id) \
        .gte("transaction_date", inizio_mese) \
        .execute()
    return sum(float(item.get('amount', 0)) for item in response.data)

def get_expenses_by_category(user_id: int, category: str):
    """dettaglio spese per singola categoria (mese corrente)."""
    inizio_mese = datetime.now().replace(day=1).strftime("%Y-%m-%d")
    return supabase.table("transactions") \
        .select("amount, description, transaction_date") \
        .eq("user_id", user_id) \
        .ilike("category", category) \
        .gte("transaction_date", inizio_mese) \
        .order("transaction_date", desc=True) \
        .execute().data

def search_transactions(user_id: int, query: str):
    """ricerca globale su merchant, categoria e descrizione."""
    search_term = f"%{query}%"
    return supabase.table("transactions") \
        .select("*") \
        .eq("user_id", user_id) \
        .or_(f"category.ilike.{search_term},description.ilike.{search_term}") \
        .order("transaction_date", desc=True) \
        .execute().data

def delete_transaction_by_id(transaction_id: str, user_id: int):
    """elimina spesa specifica verificando il proprietario."""
    return supabase.table("transactions").delete().eq("id", transaction_id).eq("user_id", user_id).execute()

def reset_monthly_data(user_id: int):
    """pulisce le transazioni del mese corrente per l'utente."""
    inizio_mese = datetime.now().replace(day=1).strftime("%Y-%m-%d")
    return supabase.table("transactions").delete().eq("user_id", user_id).gte("transaction_date", inizio_mese).execute()

# --- 3. ABBONAMENTI & SCADENZE (MULTIUTENZA) ---

def add_subscription(user_id, name, amount, renewal_day):
    return supabase.table("subscriptions").insert({
        "user_id": user_id, "name": name.lower().strip(), "amount": amount, "renewal_day": renewal_day
    }).execute()

def get_user_subscriptions(user_id):
    return supabase.table("subscriptions").select("*").eq("user_id", user_id).execute()

def delete_subscription(sub_id, user_id):
    return supabase.table("subscriptions").delete().eq("id", sub_id).eq("user_id", user_id).execute()

def add_bill(user_id, name, amount, due_date):
    return supabase.table("bills").insert({
        "user_id": user_id, "name": name.lower().strip(), "amount": amount, "due_date": due_date, "status": "pending"
    }).execute()

def get_all_pending_bills(user_id):
    return supabase.table("bills").select("*").eq("user_id", user_id).eq("status", "pending").order("due_date").execute()

def mark_bill_as_paid(bill_id, user_id):
    return supabase.table("bills").update({"status": "paid"}).eq("id", bill_id).eq("user_id", user_id).execute()

def delete_bill(bill_id, user_id):
    return supabase.table("bills").delete().eq("id", bill_id).eq("user_id", user_id).execute()

# --- 4. IMPOSTAZIONI & REPORTISTICA ---

def update_user_budget(user_id: int, budget: float):
    return supabase.table("users_settings").upsert({"user_id": user_id, "budget_monthly": budget}).execute()

def get_user_settings(user_id: int):
    return supabase.table("users_settings").select("*").eq("user_id", user_id).execute().data

def get_monthly_report_data(user_id: int):
    inizio_mese = datetime.now().replace(day=1).strftime("%Y-%m-%d")
    response = supabase.table("transactions").select("category, amount").eq("user_id", user_id).gte("transaction_date", inizio_mese).execute()
    
    if not response.data: return []
    report_dict = {}
    for item in response.data:
        cat = item.get('category', 'altro').capitalize()
        report_dict[cat] = report_dict.get(cat, 0) + float(item.get('amount', 0))
    return [{'category': k, 'total_amount': v} for k, v in report_dict.items()]

def get_last_transaction_date(user_id):
    response = supabase.table("transactions").select("transaction_date").eq("user_id", user_id).order("transaction_date", desc=True).limit(1).execute()
    return response.data[0]['transaction_date'] if response.data else None

# --- 5. GENERAZIONE GRAFICI ---

def generate_report_chart(transactions):
    import matplotlib
    matplotlib.use('Agg')
    valid_data = [t for t in transactions if float(t.get('total_amount', 0)) > 0]
    if not valid_data: return None 

    labels = [t['category'] for t in valid_data]
    values = [t['total_amount'] for t in valid_data]
    
    plt.figure(figsize=(8, 6), facecolor='#f0f0f0')
    plt.pie(values, labels=labels, autopct='%1.1f%%', startangle=140, colors=['#ff9999','#66b3ff','#99ff99','#ffcc99','#c2c2f0'])
    plt.gca().add_artist(plt.Circle((0,0), 0.70, fc='#f0f0f0'))
    plt.title("riepilogo spese mensili", fontsize=14, fontweight='bold')
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    buf.seek(0)
    plt.close()
    return buf