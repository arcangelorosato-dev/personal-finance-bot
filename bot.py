import os
import logging
import json
import re
import base64
from datetime import datetime
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from groq import Groq
# telegram imports
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler,Application

# agno & db imports
from agents import finance_team, report_agent
from database import (
    add_transaction, 
    get_user_settings, 
    create_user_settings, 
    get_category_total, 
    get_monthly_report_data, 
    generate_report_chart,
    get_monthly_total,
    add_transaction_from_ocr
)

# caricamento ambiente
load_dotenv()

GROQ_KEY = os.getenv("GROQ_API_KEY")
groq_client = Groq(api_key=GROQ_KEY)

# configurazione logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)

# funzione per impostare i comandi visibili nel menu "/" di Telegram
async def post_init(application):

    scheduler = AsyncIOScheduler()
     

    # 1. rinnovo abbonamenti (ogni giorno alle 09:00)
    scheduler.add_job(check_subscriptions_renewal, 'cron', hour=9, minute=0, args=[application])
    
    # 2. nudge inattività (ogni giorno alle 18:00 controlla se sei sparito)
    scheduler.add_job(inactivity_nudge, 'cron', hour=18, minute=0, args=[application])
    
    # 3. weekly summary (ogni domenica alle 21:00)
    scheduler.add_job(weekly_summary, 'cron', day_of_week='sun', hour=21, minute=0, args=[application])

    scheduler.add_job(monthly_parasite_report, 'cron', day=1, hour=11, minute=0, args=[application])
    
    scheduler.start()
    print("🚀 scheduler avviato correttamente!")


    commands = [
        BotCommand("start", "avvia il bot"),
        BotCommand("report", "infografica spese"),
        BotCommand("listaspesa", "dettaglio spese per categoria"), # aggiunto qui
        BotCommand("reset", "cancella spese del mese"), # nuovo comando
        BotCommand("cancella", "elimina una spesa"),
        BotCommand("stats", "report rapido: spese ed abbonamenti"),
        BotCommand("scadenze", "gestisci le bollette pendenti"),
        BotCommand("abbonamenti", "gestione abbonamenti"),
        BotCommand("setbudget", "imposta budget mensile"),
        BotCommand("help", "aiuto"),
        
    ]
    await application.bot.set_my_commands(commands)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    settings = get_user_settings(user_id)
    
    if not settings:
        create_user_settings(user_id, budget=0.0)
    
    await update.message.reply_text(
        "👋 ciao! sono il tuo assistente finanziario avanzato.\n\n"
        "scrivimi una spesa (es: '10€ pizza') o usa /report per vedere l'infografica."
    )

async def check_subscriptions_renewal(application: Application):
    from database import supabase, add_transaction
    from datetime import datetime
    
    oggi = datetime.now().day
    data_oggi = datetime.now().strftime("%Y-%m-%d")
    
    # 1. cerca abbonamenti che rinnovano oggi
    response = supabase.table("subscriptions").select("*").eq("renewal_day", oggi).execute()
    subs = response.data
    
    for s in subs:
        # 2. registra la spesa automatica
        add_transaction(
            user_id=s['user_id'],
            category="Abbonamenti",
            description=f"rinnovo: {s['name']}",
            amount=s['amount'],
            date=data_oggi
        )
        
        # 3. avvisa l'utente
        await application.bot.send_message(
            chat_id=s['user_id'],
            text=f"🔄 **rinnovo automatico!**\n\nho registrato la spesa per **{s['name'].capitalize()}** ({s['amount']}€).\nil budget è stato aggiornato.",
            parse_mode='Markdown'
        )


async def weekly_summary(application: Application):
    from database import get_monthly_total # o crea una funzione get_weekly_total
    
    user_ids = [8484337001] 
    
    for uid in user_ids:
        # calcolo veloce (puoi espanderlo con categorie)
        totale = get_monthly_total(uid) # per ora usiamo il totale mese come test
        
        testo = (
            f"📅 **resoconto settimanale**\n"
            f"--------------------------------\n"
            f"questa settimana sei stato... "
            f"{'😇 bravo' if totale < 100 else '😈 spendaccione'}\n\n"
            f"hai accumulato spese per un totale di circa **{totale:.2f}€**.\n\n"
            f"pronto per iniziare la nuova settimana con più controllo?"
        )
        
        await application.bot.send_message(chat_id=uid, text=testo, parse_mode='Markdown')

async def inactivity_nudge(application: Application):
    from database import get_last_transaction_date
    from datetime import datetime, timedelta
    
    # qui dovresti avere una lista di user_id attivi (o prenderli dal database)
    # per ora facciamo l'esempio con il tuo user_id
    user_ids = [8484337001] # sostituisci con la logica per prendere tutti gli utenti
    
    for uid in user_ids:
        last_date_str = get_last_transaction_date(uid)
        if last_date_str:
            last_date = datetime.strptime(last_date_str, "%Y-%m-%d")
            # se l'ultima spesa è di più di 2 giorni fa
            if datetime.now() - last_date > timedelta(days=2):
                await application.bot.send_message(
                    chat_id=uid,
                    text="👀 **ehi, dove sei finito?**\n\nnon segno spese da 48 ore. hai fatto acquisti che hai dimenticato di dirmi? non farmi arrabbiare il portafoglio! 💸"
                )

async def scadenze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    from database import get_all_pending_bills
    
    response = get_all_pending_bills(user_id)
    bills = response.data

    if not bills:
        await update.message.reply_text("✨ non hai scadenze pendenti al momento!")
        return

    testo = "🗓️ **le tue scadenze attive:**\n\n"
    keyboard = []

    for b in bills:
        # formattazione data
        data_dt = datetime.strptime(b['due_date'], "%Y-%m-%d")
        data_f = data_dt.strftime("%d %b")
        
        testo += f"🔹 **{b['name']}**: {b['amount']}€ ({data_f})\n"
        
        # aggiungiamo un bottone per ogni riga per poterla eliminare
        keyboard.append([
            InlineKeyboardButton(f"🗑️ elimina {b['name']}", callback_data=f"del_bill_{b['id']}")
        ])

    await update.message.reply_text(
        testo, 
        reply_markup=InlineKeyboardMarkup(keyboard), 
        parse_mode='Markdown'
    )


# --- FUNZIONE DI CONTROLLO GIORNALIERO ---
async def check_daily_bills(application: Application):
    from database import get_today_bills
    
    response = get_today_bills()
    bills = response.data
    
    if not bills:
        return

    for bill in bills:
        user_id = bill['user_id']
        bill_id = bill['id']
        
        # tastiera con due opzioni
        keyboard = [[
            InlineKeyboardButton("✅ pagata", callback_data=f"pay_bill_{bill_id}_{bill['amount']}_{bill['name']}"),
            InlineKeyboardButton("🗑️ elimina", callback_data=f"del_bill_{bill_id}")
        ]]
        
        testo = (
            f"⏰ **promemoria scadenza!**\n\n"
            f"📌 bolletta: **{bill['name']}**\n"
            f"💰 importo: **{bill['amount']}€**\n\n"
            f"cosa vuoi fare?"
        )
        
        await application.bot.send_message(
            chat_id=user_id,
            text=testo,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

 # --- funzione di supporto per l'immagine ---
def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')
    

async def abbonamenti_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    from database import get_user_subscriptions
    
    response = get_user_subscriptions(user_id)
    subs = response.data  # <--- ASSICURATI CHE CI SIA .data

    if not subs or len(subs) == 0:
        await update.message.reply_text("📉 non hai abbonamenti registrati nel database.")
        return

    testo = "💳 **i tuoi abbonamenti attivi:**\n\n"
    keyboard = []
    totale_mensile = 0
    
    for s in subs:
        # usa i nomi esatti delle colonne che vedi su supabase
        nome = s.get('name', 'abbonamento')
        prezzo = float(s.get('amount', 0))
        giorno = s.get('renewal_day', '??')
        
        testo += f"• **{nome.capitalize()}**: {prezzo:.2f}€ (giorno {giorno})\n"
        totale_mensile += prezzo
        keyboard.append([InlineKeyboardButton(f"🗑️ elimina {nome}", callback_data=f"del_sub_{s['id']}")])
    
    testo += f"\n--------------------------------\n"
    testo += f"💸 totale mensile: **{totale_mensile:.2f}€**\n"
    testo += f"📅 impatto annuale: **{(totale_mensile * 12):.2f}€**"
    
    await update.message.reply_text(testo, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

# --- funzione principale ---
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    photo_file = await update.message.photo[-1].get_file()
    
    status_msg = await update.message.reply_text("📸 sto leggendo lo scontrino...")
    img_path = f"temp_{user_id}.jpg"
    
    try:
        # 1. scarica la foto localmente
        await photo_file.download_to_drive(img_path)
        base64_img = encode_image(img_path)
        
        # 2. recupera categorie esistenti
        from database import get_existing_categories 
        categorie_presenti = get_existing_categories()
        cat_list_str = ", ".join(categorie_presenti)

        # 3. chiamata a llama-4-scout
        completion = groq_client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "text", 
                        "text": f"estrai dati scontrino in JSON: totale (numero), data (YYYY-MM-DD), descrizione (negozio), categoria. "
                                f"usa una di queste se adatta: [{cat_list_str}]. "
                                f"se è nuova, inventane una breve (max 1 parola)."
                    },
                    {
                        "type": "image_url", 
                        "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}
                    }
                ]
            }],
            response_format={"type": "json_object"},
            temperature=0.1
        )

        res = json.loads(completion.choices[0].message.content)
        
        # 4. normalizzazione intelligente
        importo = res.get('totale', 0)
        negozio_raw = str(res.get('descrizione', 'ignoto'))
        cat_estratta = str(res.get('categoria', 'altro')).strip()

        # negozio: sempre minuscolo
        negozio = negozio_raw.lower()

        # --- focus normalizzazione categorie ---
        # cerchiamo se esiste già nel DB ignorando maiuscole/minuscole
        match = next((c for c in categorie_presenti if c.lower() == cat_estratta.lower()), None)
        
        if match:
            # se esiste "Lavanderia" nel DB e Groq dice "lavanderia", usiamo "Lavanderia"
            categoria_finale = match 
        else:
            # se è nuova, la salviamo con la prima maiuscola per standardizzare il DB
            categoria_finale = cat_estratta.capitalize() 

        data_scontrino = res.get('data', "2026-01-01")

        # 5. salvataggio temporaneo
        context.user_data['pending_ocr'] = {
            'amount': importo,
            'category': categoria_finale,
            'description': negozio,
            'date': data_scontrino
        }

        # 6. tastiera inline
        keyboard = [
            [
                InlineKeyboardButton("✅ conferma e salva", callback_data="confirm_ocr"),
                InlineKeyboardButton("🗑️ elimina", callback_data="cancel_ocr")
            ]
        ]
        
        await status_msg.edit_text(
            f"✅ **scontrino analizzato**\n\n"
            f"💰 importo: **{importo}€**\n"
            f"🛒 negozio: {negozio}\n"
            f"📁 categoria: {categoria_finale}\n"
            f"📅 data: {data_scontrino}\n\n"
            "vuoi salvare questa spesa?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    except Exception as e:
        print(f"errore ocr: {e}")
        await status_msg.edit_text("❌ non sono riuscito a leggere lo scontrino.")
    
    finally:
        if os.path.exists(img_path):
            os.remove(img_path)

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    voice = update.message.voice
    
    # messaggio di feedback iniziale
    status_msg = await update.message.reply_text("🎧 ascolto e trascrivo...")

    # nome temporaneo del file audio
    ogg_file = f"voice_{user_id}.ogg"

    try:
        # 1. scarichiamo il vocale dai server telegram
        file = await context.bot.get_file(voice.file_id)
        await file.download_to_drive(ogg_file)

        # 2. trascrizione ultra-rapida con groq
        with open(ogg_file, "rb") as audio_file:
            transcription = groq_client.audio.transcriptions.create(
                file=(ogg_file, audio_file.read()),
                model="whisper-large-v3", # il top della precisione
                response_format="text",
                language="it"
            )
        
        text = transcription.strip()
        
        if not text:
            await status_msg.edit_text("⚠️ non ho sentito nulla, riprova.")
            return

        await status_msg.edit_text(f"📝 ho capito: \"{text}\"")

        # --- MODIFICA QUI ---
        # invece di modificare l'oggetto message, 
        # chiamiamo una funzione di supporto o adattiamo handle_message
        await handle_message(update, context, overridden_text=text)

    except Exception as e:
        import logging
        logging.error(f"errore vocale: {e}")
        await status_msg.edit_text("⚠️ scusa, c'è stato un errore nel processare l'audio.")
    
    finally:
        # 4. pulizia file per non lasciare tracce
        if os.path.exists(ogg_file):
            os.remove(ogg_file)


async def abbonamenti_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    from database import get_user_subscriptions
    
    response = get_user_subscriptions(user_id)
    subs = response.data

    if not subs:
        await update.message.reply_text("📉 non hai abbonamenti registrati.")
        return

    testo = "💳 **i tuoi abbonamenti attivi:**\n\n"
    keyboard = []
    totale = 0
    
    for s in subs:
        testo += f"• **{s['name'].capitalize()}**: {s['amount']}€ (giorno {s['renewal_day']})\n"
        totale += float(s['amount'])
        # tasto per eliminare ogni singolo abbonamento
        keyboard.append([InlineKeyboardButton(f"🗑️ elimina {s['name']}", callback_data=f"del_sub_{s['id']}")])
    
    testo += f"\n💰 totale mensile: **{totale:.2f}€**"
    await update.message.reply_text(testo, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def set_budget_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        # prende la cifra dopo il comando
        amount = float(context.args[0])
        from database import update_user_budget
        update_user_budget(user_id, amount)
        await update.message.reply_text(f"🎯 **budget mensile impostato:** {amount}€\nda ora il report ti mostrerà quanto ti resta!")
    except (IndexError, ValueError):
        await update.message.reply_text("💡 usa: `/setbudget [cifra]` (es: `/setbudget 500`)")

async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    search_query = " ".join(context.args)
    
    if not search_query:
        await update.message.reply_text("💡 usa: `/cancella [nome]` (es: `/cancella pizza`)")
        return

    from database import search_transactions
    try:
        results = search_transactions(user_id, search_query)
    except Exception as e:
        logging.error(f"Errore DB in ricerca: {e}")
        await update.message.reply_text("⚠️ errore durante la ricerca nel database.")
        return

    if not results:
       await update.message.reply_text(f"❓ non ho trovato nulla per '{search_query}'.")
       return

    await update.message.reply_text(f"🗑️ ho trovato {len(results)} spese. quali vuoi eliminare?")
    
    for t in results:
        try: 
            keyboard = [[InlineKeyboardButton(f"🗑️ elimina {t['amount']}€", callback_data=f"del_{t['id']}")]]
            cosa = t.get('description') or "spesa"
            msg = f"📝 **{cosa}**\n💰 {t['amount']}€"
            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        except Exception as e:
            logging.error(f"Errore visualizzazione singola riga: {e}")
            continue # passa alla prossima transazione se questa ha errori


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🤖 **guida rapida:**\n\n"
        "💰 **registra spesa**: scrivi semplicemente '20 euro da OVS' o 'pizza 15€'.\n"
        "📊 **/report**: genera un grafico a torta con l'analisi delle tue spese.\n"
        "💬 **chiacchiere**: puoi anche parlarmi normalmente, risponderò come un assistente!"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')
    

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[
        InlineKeyboardButton("✅ sì, cancella tutto", callback_data='confirm_reset'),
        InlineKeyboardButton("❌ no, annulla", callback_data='cancel_reset')
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "⚠️ **attenzione!**\nsei sicuro di voler cancellare tutte le spese di questo mese? questa azione non può essere annullata.",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def abbonamenti_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    from database import get_user_subscriptions
    
    response = get_user_subscriptions(user_id)
    subs = response.data

    if not subs:
        await update.message.reply_text(
            "📉 **non hai abbonamenti registrati.**\n\n"
            "prova a dirmi: 'abbonamento netflix 12.99 il giorno 20'",
            parse_mode='Markdown'
        )
        return

    testo = "💳 **i tuoi abbonamenti attivi:**\n\n"
    keyboard = []
    totale_mensile = 0
    
    for s in subs:
        testo += f"• **{s['name'].capitalize()}**: {s['amount']}€ (giorno {s['renewal_day']})\n"
        totale_mensile += float(s['amount'])
        # Aggiungiamo il tasto di eliminazione per ogni riga
        keyboard.append([InlineKeyboardButton(f"🗑️ elimina {s['name']}", callback_data=f"del_sub_{s['id']}")])
    
    testo += f"\n--------------------------------\n"
    testo += f"💸 totale mensile: **{totale_mensile:.2f}€**\n"
    testo += f"📅 impatto annuale: **{(totale_mensile * 12):.2f}€**"
    
    await update.message.reply_text(testo, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def listaspesa_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # rileva se la chiamata arriva da un comando (/listaspesa) o da un pulsante
    query = update.callback_query
    user_id = update.effective_user.id
    
    from database import get_monthly_report_data
    from datetime import datetime
    
    # recuperiamo le categorie con spese nel mese corrente
    categories = get_monthly_report_data(user_id)
    mese_corrente = datetime.now().strftime("%B %Y")
    
    # testo del messaggio
    msg_text = f"📂 **spese di {mese_corrente}**\nseleziona una categoria per il dettaglio:"
    
    if not categories:
        msg_text = f"📭 nessuna spesa registrata per {mese_corrente}."
        if query:
            await query.edit_message_text(msg_text)
        else:
            await update.message.reply_text(msg_text)
        return

    keyboard = []
    for cat in categories:
        nome_cat = cat['category']
        totale = cat['total_amount']
        keyboard.append([InlineKeyboardButton(f"{nome_cat}: {totale:.2f}€", callback_data=f"list_{nome_cat}")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    # se è una callback (pulsante "indietro"), modifichiamo il messaggio esistente
    if query:
        await query.edit_message_text(msg_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        # se è un comando nuovo, inviamo un nuovo messaggio
        await update.message.reply_text(msg_text, reply_markup=reply_markup, parse_mode='Markdown')


async def monthly_parasite_report(application: Application):
    from database import supabase
    # prendiamo tutti gli utenti che hanno abbonamenti
    response = supabase.table("subscriptions").select("user_id").execute()
    users = list(set([r['user_id'] for r in response.data]))
    
    for u_id in users:
        # riutilizziamo la logica del report per ogni utente
        # ... invio messaggio automatico ...
        await application.bot.send_message(
            chat_id=u_id,
            text="📢 **check-up mensile abbonamenti!**\n\nricordati di controllare se usi ancora tutto quello che paghi..."
        )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    from database import get_monthly_total, get_user_subscriptions
    
    # recupero dati
    totale_speso = get_monthly_total(user_id)
    response_subs = get_user_subscriptions(user_id)
    subs = response_subs.data
    
    # calcolo abbonamenti
    num_subs = len(subs)
    totale_subs = sum(float(s['amount']) for s in subs)
    
    testo = f"📊 **report mensile**\n"
    testo += f"--------------------------------\n"
    testo += f"💸 totale speso: **{totale_speso:.2f}€**\n\n"
    
    if num_subs > 0:
        testo += f"🧛 **focus abbonamenti parassiti:**\n"
        testo += f"stai pagando **{num_subs}** abbonamenti per un totale di **{totale_subs:.2f}€/mese**.\n"
        testo += f"⚠️ incidenza annuale: **{(totale_subs * 12):.2f}€/anno**\n"
    else:
        testo += "✅ non hai abbonamenti attivi rilevati."
        
    await update.message.reply_text(testo, parse_mode='Markdown')

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    status_msg = await update.message.reply_text("📊 sto analizzando le tue spese...")
    
    try:
        from database import get_monthly_report_data, get_user_settings, generate_report_chart
        
        # 1. Recupero dati raggruppati
        transactions = get_monthly_report_data(user_id)
        logging.info(f"DEBUG transactions: {transactions}") # Guarda i log qui!

        if not transactions:
            await status_msg.edit_text("non ho dati per questo mese.")
            return

        # 2. Calcolo totale ultra-sicuro
        totale_speso = 0.0
        for t in transactions:
            # Qui usiamo total_amount perché get_monthly_report_data restituisce quella chiave
            totale_speso += t.get('total_amount', 0)

        # 3. Recupero budget
        settings = get_user_settings(user_id)
        budget = settings[0].get('budget_monthly', 0) if (settings and len(settings) > 0) else 0
        
        # 4. Barra di avanzamento
        barra = ""
        if budget > 0:
            percentuale = min(int((totale_speso / budget) * 10), 10)
            rimanente = budget - totale_speso
            barra = f"\n\n💰 **budget:** {totale_speso:.2f}€ / {budget:.2f}€\n"
            barra += f"|{'🔘' * percentuale}{'⚪' * (10 - percentuale)}|\n"
            barra += f"rimanenti: **{rimanente:.2f}€**" if rimanente > 0 else "⚠️ **fuori budget!**"

        # 5. Generazione grafico
        chart_buffer = generate_report_chart(transactions)

        if chart_buffer is None:
            await status_msg.edit_text("i dati di questo mese non sono sufficienti per creare un grafico (importi pari a zero).")
            return
        
        await status_msg.delete()
        await update.message.reply_photo(
            photo=chart_buffer,
            caption=f"📈 **il tuo report mensile**{barra}",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logging.error(f"errore report: {e}", exc_info=True) # exc_info ci dice la riga esatta!
        await update.message.reply_text(f"⚠️ errore nel report: {str(e)}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE, overridden_text=None):
    user_id = update.effective_user.id
    user_text = overridden_text if overridden_text else update.message.text
    
    try:
        current_date = datetime.now().strftime("%d %B %Y")
        # invio richiesta al team finance
        response = finance_team.run(f"utente {user_id}: '{user_text}'. oggi è: {current_date}")
        content = response.content

        # estrazione del json dalla risposta
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        
        if json_match:
            json_str = json_match.group().replace("'", '"').replace("True", "true").replace("False", "false")
            extracted_data = json.loads(json_str)
            
            # prendiamo l'azione pura (senza default) per evitare errori di smistamento
            action = extracted_data.get("action")
            logging.info(f"debug ai - azione rilevata: {action}")

            # --- 1. CASO ABBONAMENTO (PRIORITÀ ASSOLUTA) ---
            if action == "subscription":
                sub_name = extracted_data.get('name', 'abbonamento').lower().strip()
                amount = float(extracted_data.get('amount', 0.0))
                renewal_day = int(extracted_data.get('renewal_day', datetime.now().day))

                context.user_data['pending_subscription'] = {
                    'name': sub_name,
                    'amount': amount,
                    'renewal_day': renewal_day
                }

                keyboard = [[
                    InlineKeyboardButton("✅ registra abbonamento", callback_data='confirm_sub'),
                    InlineKeyboardButton("🗑️ annulla", callback_data='cancel_sub')
                ]]

                await update.message.reply_text(
                    f"💳 **nuovo abbonamento rilevato**\n\n"
                    f"📌 servizio: **{sub_name.capitalize()}**\n"
                    f"💰 quota mensile: **{amount:.2f}€**\n"
                    f"🔄 rinnovo: ogni **giorno {renewal_day}** del mese\n\n"
                    "vuoi registrarlo tra le uscite ricorrenti?",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )

            # --- 2. CASO BOLLETTA / SCADENZA (BILL) ---
            elif action == "bill":
                bill_name = extracted_data.get('name', 'bolletta').lower().strip()
                amount = float(extracted_data.get('amount', 0.0))
                due_date = extracted_data.get('due_date', '2026-01-01')

                context.user_data['pending_bill'] = {
                    'name': bill_name,
                    'amount': amount,
                    'due_date': due_date
                }

                keyboard = [[
                    InlineKeyboardButton("✅ imposta promemoria", callback_data='confirm_bill'),
                    InlineKeyboardButton("🗑️ annulla", callback_data='cancel_bill')
                ]]

                await update.message.reply_text(
                    f"📅 **nuova scadenza rilevata**\n\n"
                    f"📌 **{bill_name}**\n"
                    f"💰 importo: **{amount:.2f}€**\n"
                    f"🗓️ scadenza: **{due_date}**\n\n"
                    "vuoi un promemoria la mattina del pagamento?",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )

            # --- 3. CASO SPESA NORMALE (TRANSACTION) ---
            elif action == "transaction" or (action is None and 'amount' in extracted_data):
                cat_raw = extracted_data.get('category', 'Altro')
                extracted_data['category'] = cat_raw.strip().capitalize()
                
                desc_raw = extracted_data.get('description', extracted_data.get('name', 'spesa'))
                extracted_data['description'] = desc_raw.lower().strip()
                extracted_data['amount'] = float(extracted_data.get('amount', 0.0))
                
                context.user_data['pending_transaction'] = extracted_data
                
                from database import get_category_total, get_user_settings, get_monthly_total
                cat_total = get_category_total(user_id, extracted_data['category'])
                
                settings = get_user_settings(user_id)
                budget_totale = settings[0].get('budget_monthly', 0) if settings else 0
                speso_attuale = get_monthly_total(user_id)
                nuovo_totale_previsto = speso_attuale + extracted_data['amount']
                
                avviso_budget = ""
                if budget_totale > 0:
                    rimanente = budget_totale - nuovo_totale_previsto
                    if nuovo_totale_previsto > budget_totale:
                        avviso_budget = f"\n⚠️ **attenzione:** fuori budget di {abs(rimanente):.2f}€!"
                    else:
                        avviso_budget = f"\n💰 budget residuo: **{rimanente:.2f}€**"

                display_text = content.replace(json_match.group(), "").strip().split('\n')[0]
                if not display_text: display_text = "ho capito questo:"
                
                keyboard = [[
                    InlineKeyboardButton("✅ conferma", callback_data='confirm'),
                    InlineKeyboardButton("🗑️ annulla", callback_data='cancel')
                ]]
                
                final_msg = (
                    f"💬 {display_text}\n\n"
                    f"💰 **{extracted_data['amount']:.2f}€** in {extracted_data['category']}\n"
                    f"📝 **cosa:** {extracted_data['description']}\n"
                    f"📅 totale categoria: {cat_total + extracted_data['amount']:.2f}€"
                    f"{avviso_budget}"
                )
      
                await update.message.reply_text(final_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            
            else:
                # se c'è un json ma l'action è ignota, rispondi col testo dell'ai
                await update.message.reply_text(content)
        
        else:
            # risposta puramente testuale
            await update.message.reply_text(content)

    except Exception as e:
        logging.error(f"errore messaggio: {e}")
        await update.message.reply_text("⚠️ non ho capito bene. riprova scrivendo i dettagli più chiaramente.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = update.effective_user.id
    await query.answer()

    

    # --- 1. GESTIONE TRANSAZIONI (TESTO/VOCE) ---
    
    if data == 'confirm':
        trans_data = context.user_data.pop('pending_transaction', None)
        if not trans_data:
            await query.edit_message_text("sessione scaduta, riprova.")
            return
        try:
            from database import add_transaction, get_user_settings, get_monthly_total
            add_transaction(
                user_id, 
                trans_data['amount'], 
                trans_data['category'], 
                trans_data.get('merchant'), 
                trans_data.get('description')
            )
            settings = get_user_settings(user_id)
            budget_totale = settings[0].get('budget_monthly', 0) if settings else 0
            nuovo_totale = get_monthly_total(user_id)
            
            avviso = f"\n\n💰 speso nel mese: {nuovo_totale:.2f}€"
            if budget_totale > 0:
                rimanente = budget_totale - nuovo_totale
                avviso = f"\n\n🚨 **fuori budget!** (-{abs(rimanente):.2f}€)" if rimanente < 0 else f"\n\n💰 restano: {rimanente:.2f}€"

            await query.edit_message_text(f"✅ **salvato!**\n{trans_data['amount']}€ per {trans_data.get('description', 'spesa')}{avviso}", parse_mode='Markdown')
        except Exception as e:
            logging.error(f"errore salvataggio: {e}"); await query.edit_message_text("❌ errore salvataggio.")

    elif data == 'cancel':
        context.user_data.pop('pending_transaction', None)
        await query.edit_message_text("🗑️ operazione annullata.")

    # --- 2. GESTIONE OCR (SCONTRINI) ---
    elif data == "confirm_ocr":
        ocr_data = context.user_data.pop('pending_ocr', None)
        if ocr_data:
            from database import add_transaction_from_ocr
            add_transaction_from_ocr(user_id, ocr_data['amount'], ocr_data['category'], ocr_data['description'], ocr_data['date'])
            await query.edit_message_text(f"✅ spesa di {ocr_data['amount']}€ salvata correttamente!")

    elif data == "cancel_ocr":
        context.user_data.pop('pending_ocr', None)
        await query.edit_message_text("🗑️ inserimento annullato.")

    # --- 3. GESTIONE BOLLETTE (BILLS) ---
    elif data == "confirm_bill":
        bill_data = context.user_data.pop('pending_bill', None)
        if bill_data:
            from database import add_bill
            add_bill(user_id, bill_data['name'], bill_data['amount'], bill_data['due_date'])
            await query.edit_message_text(f"📅 **promemoria impostato!**\nti avviserò la mattina del {bill_data['due_date']}.")

    elif data == "cancel_bill":
        context.user_data.pop('pending_bill', None)
        await query.edit_message_text("🗑️ promemoria annullato.")

    elif data == 'confirm_sub':
        sub_data = context.user_data.get('pending_subscription')
        if sub_data:
            from database import add_subscription
            add_subscription(
                user_id=user_id,
                name=sub_data['name'],
                amount=sub_data['amount'],
                renewal_day=sub_data['renewal_day']
            )
            await query.edit_message_text(f"✅ abbonamento a **{sub_data['name']}** salvato correttamente!")
            context.user_data.pop('pending_subscription', None)

    elif data == 'cancel_sub':
        await query.edit_message_text("🗑️ inserimento abbonamento annullato.")
        context.user_data.pop('pending_subscription', None)

    # --- ELIMINAZIONE SCADENZA ---
    elif data.startswith("del_bill_"):
        bill_id = data.split("_")[2]
        try:
            from database import delete_bill
            delete_bill(bill_id)
            
            # invece di un semplice messaggio, aggiorniamo la lista
            await query.edit_message_text("🗑️ scadenza eliminata!")
            # opzionale: potresti richiamare la logica di scadenze_command qui 
            # per mostrare la lista aggiornata immediatamente
        except Exception as e:
            logging.error(f"errore elimina bill: {e}")
            await query.edit_message_text("❌ errore durante l'eliminazione.")

    elif data.startswith("del_sub_"):
        sub_id = data.split("_")[2]
        try:
            from database import delete_subscription
            delete_subscription(sub_id)
            await query.edit_message_text("🗑️ abbonamento rimosso dalle ricorrenze!")
        except Exception as e:
            logging.error(f"errore elimina sub: {e}")
            await query.edit_message_text("❌ errore durante l'eliminazione.")
    
    # --- 4. TRASFORMA BOLLETTA IN SPESA (DA NOTIFICA) ---
    elif data.startswith("pay_bill_"):
        # Formato atteso: pay_bill_ID_AMOUNT_NAME
        parts = data.split("_")
        bill_id, amount, b_name = parts[2], float(parts[3]), parts[4]
        try:
            from database import mark_bill_as_paid, add_transaction_from_ocr
            from datetime import datetime
            mark_bill_as_paid(bill_id)
            # La inseriamo nelle transazioni reali
            add_transaction_from_ocr(user_id, amount, "Bollette", b_name, datetime.now().strftime("%Y-%m-%d"))
            await query.edit_message_text(f"✅ bolletta '{b_name}' segnata come pagata e aggiunta alle spese!")
        except Exception as e:
            logging.error(f"errore pay_bill: {e}"); await query.edit_message_text("❌ errore nell'aggiornamento.")

    # --- 5. VISUALIZZAZIONE LISTE E DETTAGLI ---
    elif data.startswith("list_"):
        category_name = data.split("_")[1]
        from database import get_expenses_by_category
        from datetime import datetime
        expenses = get_expenses_by_category(user_id, category_name)
        if not expenses:
            await query.edit_message_text(f"nessuna spesa per {category_name} questo mese.")
            return

        testo = f"📑 **dettaglio {category_name.upper()}**\n{'-'*20}\n"
        totale_cat = 0
        for e in expenses:
            totale_cat += e['amount']
            data_f = datetime.strptime(e['transaction_date'], "%Y-%m-%d").strftime("%d %b")
            testo += f"▫️ {e['amount']:.2f}€ — {e.get('description', 'spesa')} ({data_f})\n"
        testo += f"{'-'*20}\n💰 **totale: {totale_cat:.2f}€**"
        
        back_kb = [[InlineKeyboardButton("⬅️ torna alla lista", callback_data="back_to_list")]]
        await query.edit_message_text(testo, reply_markup=InlineKeyboardMarkup(back_kb), parse_mode='Markdown')

    elif data == "back_to_list":
        # Richiama il comando della lista
        from bot import listaspesa_command
        await listaspesa_command(update, context)

    # --- 6. RESET E CANCELLAZIONE ---
    elif data == 'confirm_reset':
        from database import reset_monthly_data
        reset_monthly_data(user_id)
        await query.edit_message_text("🧹 **database pulito!**")

    elif data == 'cancel_reset':
        await query.edit_message_text("operazione annullata. 🛡️")

    elif data.startswith("del_"):
        transaction_id = data.split("_")[1]
        from database import delete_transaction_by_id
        delete_transaction_by_id(transaction_id)
        await query.edit_message_text("✅ spesa eliminata!")

if __name__ == '__main__':
    token = os.environ.get("TELEGRAM_TOKEN")
    
    if not token:
        print("token mancante!")
        exit()

    # inizializzazione con post_init per i comandi menu
    application = ApplicationBuilder().token(token).post_init(post_init).build()

 
    
    # handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('report', report_command))
    application.add_handler(CommandHandler('cancella', delete_command))
    application.add_handler(CommandHandler("listaspesa", listaspesa_command))
    application.add_handler(CommandHandler('setbudget', set_budget_command))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler("abbonamenti", abbonamenti_command))
    application.add_handler(CommandHandler('reset', reset_command))
    application.add_handler(CommandHandler('stats', stats_command))
    application.add_handler(CommandHandler("scadenze", scadenze_command))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    print("🚀 bot multi-agente operativo (fase infografica)...")
    application.run_polling()


def context_type_wrapper(app):
    from telegram.ext import CallbackContext
    return CallbackContext(app)