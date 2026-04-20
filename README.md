# 💸 Finance Bot

> Il tuo commercialista personale su Telegram — ironico, automatico e multi-agente.

Un bot Telegram **AI-powered** che traccia spese, abbonamenti e scadenze in linguaggio naturale, voce o foto scontrino. Costruito con un team di agenti specializzati via **Agno Framework** e **Groq LLM**, con persistenza su **Supabase**.

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
   │                                      │
   ▼                                      ▼
┌────────────┐  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐
│ Contabile  │  │ Consulente  │  │   Storico    │  │    Report    │
│  Agent     │  │   Agent     │  │    Agent     │  │    Agent     │
│ (Parser)   │  │ (Ironico)   │  │  (Trend)     │  │ (Sintesi AI) │
│ → JSON     │  │ → commento  │  │ → confronto  │  │ → didascalia │
└────────────┘  └─────────────┘  └──────────────┘  └──────────────┘
       │
       ▼
  Supabase DB
  (transactions · subscriptions · bills · users_settings)
```

### Agenti nel dettaglio

- **Finance Team** — Smista ogni input verso l'azione corretta, produce JSON strutturato
- **Contabile** — Estrae `amount`, `category`, `merchant`, `description`, `is_bill`
- **Consulente** — Commento ironico in massimo 10 parole + emoji
- **Storico** — Confronta la spesa col trend storico della categoria
- **Report Agent** — Sintesi ironica di 3 righe per il grafico mensile

---

## ⏰ Job automatici (APScheduler)

| Orario | Job |
|---|---|
| Ogni giorno — 09:00 | 🔄 Rinnovo abbonamenti: registra le spese ricorrenti e notifica l'utente |
| Ogni giorno — 18:00 | 👀 Nudge inattività: avvisa se non registri spese da oltre 48 ore |
| Domenica — 21:00 | 📅 Weekly Summary: resoconto settimanale con giudizio (bravo/spendaccione) |
| 1° del mese — 11:00 | 🪱 Monthly Parasite Report: report degli abbonamenti attivi |

---

## 🛠️ Stack tecnologico

- **[python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot)** — interfaccia Telegram
- **[Agno](https://github.com/agno-agi/agno)** — framework multi-agente
- **[Groq](https://groq.com/)** — LLM inference ultra-rapida (modello `openai/gpt-oss-120b`) + Whisper STT
- **[Supabase](https://supabase.com/)** — database PostgreSQL as-a-service
- **[Matplotlib](https://matplotlib.org/)** — generazione grafico donut
- **[APScheduler](https://apscheduler.readthedocs.io/)** — job scheduling asincrono
- **[python-dotenv](https://pypi.org/project/python-dotenv/)** — gestione variabili d'ambiente

---

## 🚀 Setup e avvio

### 1. Clona il repository

```bash
git clone https://github.com/arcangelorosato-dev/personal-finance-bot.git
cd personal-finance-bot

# crea l'ambiente
python3 -m venv venv

# attiva su linux/vps
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
-- Transazioni
create table transactions (
  id uuid primary key default gen_random_uuid(),
  user_id bigint not null,
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
  user_id bigint not null,
  name text not null,
  amount numeric not null,
  renewal_day int not null
);

-- Bollette / scadenze
create table bills (
  id uuid primary key default gen_random_uuid(),
  user_id bigint not null,
  name text not null,
  amount numeric not null,
  due_date date not null,
  status text default 'pending'
);

-- Impostazioni utente
create table users_settings (
  user_id bigint primary key,
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

| Comando | Descrizione |
|---|---|
| `/start` | Avvia il bot e inizializza l'utente |
| `/report` | Genera il grafico donut delle spese mensili |
| `/stats` | Report rapido: totale spese e abbonamenti attivi |
| `/listaspesa` | Dettaglio spese per categoria (interattivo) |
| `/abbonamenti` | Visualizza e gestisci gli abbonamenti ricorrenti |
| `/scadenze` | Visualizza e gestisci le bollette pendenti |
| `/setbudget` | Imposta il budget mensile |
| `/cancella` | Elimina una spesa recente |
| `/reset` | Cancella tutte le spese del mese corrente |
| `/help` | Mostra l'elenco dei comandi |

---

## 🌍 Multilingua (Internationalization)

Il bot è progettato per essere utilizzato in tutto il mondo grazie al supporto nativo per diverse lingue. Il sistema rileva automaticamente la lingua dell'utente o permette di impostarla manualmente.

| Lingua | Codice ISO | Stato |
| :--- | :---: | :--- |
| **Italiano** 🇮🇹 | `it` | Supportato |
| **English** 🇬🇧 | `en` | Supportato |
| **Français** 🇫🇷 | `fr` | Supportato |
| **Español** 🇪🇸 | `es` | Supportato |

### Caratteristiche principali:
* **Rilevamento automatico**: Gli agenti AI riconoscono la lingua dell'input (testo o voce) e rispondono di conseguenza.
* **Persistenza**: La lingua preferita viene salvata nella tabella `users_settings` su Supabase.
* **Localizzazione dinamica**: Tutti i messaggi di sistema, i menu e i grafici vengono tradotti in tempo reale.

---

## 💡 Esempi di utilizzo

```
# Spesa semplice
"ho speso 8€ per la pizza"

# Abbonamento
"aggiungi Netflix 15€ ogni mese"

# Bolletta futura
"ricordami di pagare la bolletta Enel da 120€ il 30 aprile"

# Voce
🎙️ "ho fatto il pieno, 60 euro"

# Foto scontrino
📸 [invia foto] → il bot estrae importo e categoria
```

---

## 📁 Struttura del progetto

```
finance-bot/
├── bot.py          # Entry point, handlers Telegram, scheduler
├── agents.py       # Definizione agenti Agno e Finance Team
├── database.py     # Funzioni CRUD Supabase + generazione grafici
├── requirements.txt
└── .env            # (non committare mai questo file!)
```

---

## ⚠️ Note

Modelli usati tramite Groq

- openai/gpt-oss-120b : Agenti
- meta-llama/llama-4-scout-17b-16e-instruct : OCR
- whisper-large-v3 : Voice

---

## 📄 Licenza

MIT License — fai quello che vuoi, ma non dare la colpa a noi se spendi troppo. 💸
