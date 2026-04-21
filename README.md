# 💸 Finance Bot

> Il tuo commercialista personale su Telegram — ironico, automatico, multi-agente e multilingua.

Un bot Telegram **AI-powered** che traccia spese, abbonamenti e scadenze in linguaggio naturale, voce o foto scontrino. Costruito con un team di agenti specializzati via **Agno Framework** e **Groq LLM**, con persistenza su **Supabase**. Supporta **multiutenza reale** e **4 lingue** con localizzazione completa.

---

## ✨ Funzionalità principali

| Feature | Descrizione |
|---|---|
| 💬 **Input testuale** | Scrivi "10€ pizza" o "Netflix abbonamento" — il bot capisce |
| 🎙️ **Input vocale** | Messaggi audio trascritti da Groq Whisper e classificati |
| 🧾 **OCR scontrino** | Invia una foto e l'AI estrae importo e categoria automaticamente |
| 📊 **Report mensile** | Grafico donut per categoria con sintesi ironica generata da AI |
| 🔄 **Abbonamenti** | Traccia rinnovi ricorrenti e li registra automaticamente ogni mese |
| 📅 **Scadenze/Bollette** | Promemoria per pagamenti futuri con notifica il giorno della scadenza |
| 💰 **Budget mensile** | Imposta un tetto di spesa e ricevi alert quando lo superi |
| 🗑️ **Gestione inline** | Cancella spese, abbonamenti e bollette direttamente dai bottoni Telegram |
| 👥 **Multiutenza** | Ogni utente ha i propri dati isolati e impostazioni indipendenti |
| 🌍 **Multilingua** | Interfaccia completamente localizzata in 4 lingue |

---

## 🌍 Multilingua (i18n)

Il bot rileva automaticamente la lingua Telegram dell'utente e risponde nella sua lingua. Tutti i messaggi, i menu, le notifiche e i grafici vengono localizzati dinamicamente tramite `strings.py`.

| Lingua | Codice | Stato |
|:---|:---:|:---|
| 🇮🇹 Italiano | `it` | ✅ Supportato |
| 🇬🇧 English | `en` | ✅ Supportato |
| 🇪🇸 Español | `es` | ✅ Supportato |
| 🇫🇷 Français | `fr` | ✅ Supportato |

**Come funziona:**
- Al primo `/start`, la lingua viene rilevata da `user.language_code` di Telegram e salvata nella tabella `users`
- Ogni messaggio e notifica (rinnovi, nudge, weekly summary) viene inviato nella lingua dell'utente
- Il menu comandi `/` di Telegram viene registrato separatamente per ogni lingua con `set_my_commands(language_code=...)`
- Il fallback è l'inglese per lingue non supportate

---

## 👥 Multiutenza

Il bot è progettato per essere usato da più utenti contemporaneamente, ognuno con dati completamente separati.

- Ogni utente viene registrato automaticamente al primo avvio tramite `register_user()`
- Tutte le query al database filtrano per `user_id` (transazioni, abbonamenti, bollette, impostazioni)
- Le operazioni di eliminazione verificano sempre il `user_id` per impedire accessi incrociati
- I job automatici (APScheduler) iterano su **tutti gli utenti** nel database, ognuno con la propria lingua e i propri dati

---

## 🤖 Architettura Multi-Agente

Il bot è orchestrato da un **Finance Team** (Agno) composto da agenti specializzati:

```
User Input (testo / voce / foto)
        │
        ▼
┌──────────────────────┐
│  Finance Team        │  ◄── Orchestratore & Router
│  (GPT-OSS 120B)      │      Classifica: transaction | subscription | bill
└──────┬───────────────┘
       │
   ┌───┴──────────────────────────────────┐
   │              │                       │
   ▼              ▼                       ▼
┌────────────┐  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐
│ Contabile  │  │ Consulente  │  │   Storico    │  │    Report    │
│  Agent     │  │   Agent     │  │    Agent     │  │    Agent     │
│ (Parser)   │  │ (Ironico)   │  │  (Trend)     │  │ (Sintesi AI) │
│ → JSON     │  │ → commento  │  │ → confronto  │  │ → didascalia │
└────────────┘  └─────────────┘  └──────────────┘  └──────────────┘
       │
       ▼
  Supabase DB
  (users · transactions · subscriptions · bills · users_settings)
```

**Agenti nel dettaglio:**
- **Finance Team** — Smista ogni input verso l'azione corretta, produce JSON strutturato
- **Contabile** — Estrae `amount`, `category`, `merchant`, `description`, `is_bill`
- **Consulente** — Commento ironico in massimo 10 parole + emoji
- **Storico** — Confronta la spesa col trend storico della categoria
- **Report Agent** — Sintesi ironica di 3 righe per il grafico mensile

---

## ⏰ Job automatici (APScheduler)

Tutti i job iterano sull'intero database utenti e inviano le notifiche nella lingua di ciascuno.

| Orario | Job |
|---|---|
| Ogni giorno — 09:00 | 🔄 Rinnovo abbonamenti: registra le spese ricorrenti e notifica |
| Ogni giorno — 18:00 | 👀 Nudge inattività: avvisa se non si registrano spese da 48h |
| Domenica — 21:00 | 📅 Weekly Summary: resoconto con giudizio (bravo/spendaccione) |
| 1° del mese — 11:00 | 🪱 Monthly Parasite Report: check sugli abbonamenti attivi |

---

## 🛠️ Stack tecnologico

- **[python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot)** — interfaccia Telegram
- **[Agno](https://github.com/agno-agi/agno)** — framework multi-agente
- **[Groq](https://groq.com/)** — LLM inference ultra-rapida + Whisper STT
- **[Supabase](https://supabase.com/)** — database PostgreSQL as-a-service
- **[Matplotlib](https://matplotlib.org/)** — generazione grafico donut
- **[APScheduler](https://apscheduler.readthedocs.io/)** — job scheduling asincrono
- **[python-dotenv](https://pypi.org/project/python-dotenv/)** — gestione variabili d'ambiente

**Modelli Groq utilizzati:**

| Modello | Uso |
|---|---|
| `openai/gpt-oss-120b` | Agenti AI (Finance Team, parser, analyst) |
| `meta-llama/llama-4-scout-17b-16e-instruct` | OCR scontrini (Vision) |
| `whisper-large-v3` | Trascrizione messaggi vocali |

---

## 🚀 Setup e avvio

### 1. Clona il repository

```bash
git clone https://github.com/arcangelorosato-dev/personal-finance-bot.git
cd personal-finance-bot

# crea l'ambiente virtuale
python3 -m venv venv

# attiva su linux/vps/mac
source venv/bin/activate

# attiva su windows
# venv\Scripts\activate
```

### 2. Installa le dipendenze

```bash
pip install -r requirements.txt
```

### 3. Configura le variabili d'ambiente

Crea un file `.env` nella root del progetto:

```env
TELEGRAM_TOKEN=il_tuo_token_da_botfather
GROQ_API_KEY=la_tua_api_key_groq
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_KEY=la_tua_supabase_anon_key
```

### 4. Configura il database Supabase

Crea le seguenti tabelle nel tuo progetto Supabase:

```sql
-- Anagrafica utenti (RICHIESTA per multiutenza e multilingua)
create table users (
  id bigint primary key,
  username text,
  first_name text,
  language_code text default 'it',
  created_at timestamptz default now()
);

-- Transazioni
create table transactions (
  id uuid primary key default gen_random_uuid(),
  user_id bigint not null references users(id),
  amount numeric not null,
  category text,
  description text,
  merchant text,
  transaction_date date,
  created_at timestamptz default now()
);

-- Abbonamenti ricorrenti
create table subscriptions (
  id uuid primary key default gen_random_uuid(),
  user_id bigint not null references users(id),
  name text not null,
  amount numeric not null,
  renewal_day int not null
);

-- Bollette / scadenze
create table bills (
  id uuid primary key default gen_random_uuid(),
  user_id bigint not null references users(id),
  name text not null,
  amount numeric not null,
  due_date date not null,
  status text default 'pending'
);

-- Impostazioni utente
create table users_settings (
  user_id bigint primary key references users(id),
  budget_monthly numeric default 0,
  currency text default 'EUR'
);
```

### 5. Avvia il bot

```bash
python bot.py
```

---

## 📲 Comandi disponibili

I comandi vengono mostrati nella lingua dell'utente direttamente nel menu `/` di Telegram.

| Comando | 🇮🇹 IT | 🇬🇧 EN | 🇪🇸 ES | 🇫🇷 FR |
|---|---|---|---|---|
| `/start` | Avvia il bot | Start the bot | Iniciar el bot | Lancer le bot |
| `/report` | Infografica spese | Expense chart | Gráfico de gastos | Graphique des dépenses |
| `/stats` | Statistiche totali | Total statistics | Estadísticas | Statistiques totales |
| `/listaspesa` | Dettaglio categorie | Details by category | Detalles categoría | Détails par catégorie |
| `/abbonamenti` | Gestione abbonamenti | Manage subscriptions | Suscripciones | Abonnements |
| `/scadenze` | Gestione bollette | Manage bills | Facturas | Factures |
| `/setbudget` | Budget mensile | Monthly budget | Presupuesto | Budget mensuel |
| `/cancella` | Elimina una spesa | Delete an expense | Eliminar gasto | Supprimer dépense |
| `/reset` | Pulisci il mese | Reset monthly data | Resetear mes | Effacer le mois |
| `/help` | Guida ai comandi | Help guide | Ayuda | Aide |

---

## 💡 Esempi di utilizzo

```
# Spesa semplice (qualsiasi lingua supportata)
"ho speso 8€ per la pizza"
"i spent 8€ on pizza"
"he gastado 8€ en pizza"
"j'ai dépensé 8€ pour une pizza"

# Abbonamento
"aggiungi Netflix 15€ ogni mese"

# Bolletta futura
"ricordami di pagare la bolletta Enel da 120€ il 30 aprile"

# Voce
🎙️ "ho fatto il pieno, 60 euro"

# Foto scontrino
📸 [invia foto] → il bot estrae importo, categoria e data
```

---

## 📁 Struttura del progetto

```
finance-bot/
├── bot.py           # Entry point, handlers Telegram, scheduler
├── agents.py        # Definizione agenti Agno e Finance Team
├── database.py      # Funzioni CRUD Supabase + generazione grafici
├── strings.py       # Dizionario i18n (it, en, es, fr)
├── requirements.txt
└── .env             # (non committare mai questo file!)
```

---

## ⚠️ Note

- Aggiungi `.env` al `.gitignore` prima di fare push
- La tabella `users` è **obbligatoria** — è il punto di partenza per multiutenza e localizzazione
- Per aggiungere una nuova lingua: aggiungi un blocco in `strings.py` e registra i comandi in `post_init()` in `bot.py`

---

## 📄 Licenza

MIT License — fai quello che vuoi, ma non dare la colpa a noi se spendi troppo. 💸
