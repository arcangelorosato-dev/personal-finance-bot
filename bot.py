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
from strings import get_text
# agno & db imports
from agents import finance_team, report_agent
from database import (
    register_user,           # <--- nuova
    get_all_users,           # <--- nuova
    get_user_language,       # <--- nuova
    get_last_transaction_date, # <--- nuova
    add_transaction, 
    get_user_settings, 
    update_user_budget, 
    get_category_total, 
    get_monthly_report_data, 
    generate_report_chart,
    get_monthly_total,
    add_transaction_from_ocr,
    get_user_subscriptions,  # <--- assicurati ci siano tutte
    add_subscription,
    delete_subscription,
    add_bill,
    get_all_pending_bills,
    supabase # per query dirette
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
     
    # job dello scheduler
    scheduler.add_job(check_subscriptions_renewal, 'cron', hour=9, minute=0, args=[application])
    scheduler.add_job(inactivity_nudge, 'cron', hour=18, minute=0, args=[application])
    scheduler.add_job(weekly_summary, 'cron', day_of_week='sun', hour=21, minute=0, args=[application])
    scheduler.add_job(monthly_parasite_report, 'cron', day=1, hour=11, minute=0, args=[application])
    scheduler.add_job(check_bill_reminders, 'cron', hour=9, minute=0, args=[application])
    
    scheduler.start()
    print("🚀 scheduler avviato correttamente!")

    # comandi standard (puoi localizzarli volendo usando set_my_commands per ogni lingua)
    commands_it = [
        BotCommand("start", "avvia il bot"),
        BotCommand("report", "genera infografica spese"),
        BotCommand("listaspesa", "mostra dettagli per categoria"),
        BotCommand("reset", "pulisci i dati del mese"),
        BotCommand("cancella", "elimina una spesa specifica"),
        BotCommand("stats", "statistiche totali"),
        BotCommand("scadenze", "gestione bollette"),
        BotCommand("abbonamenti", "gestione abbonamenti"),
        BotCommand("setbudget", "imposta budget mensile"),
        BotCommand("help", "guida ai comandi"),
    ]
    await application.bot.set_my_commands(commands_it, language_code='it')

    # --- 2. SPAGNOLO (es) ---
    commands_es = [
        BotCommand("start", "iniciar el bot"),
        BotCommand("report", "generar gráfico de gastos"),
        BotCommand("listaspesa", "ver detalles por categoría"),
        BotCommand("reset", "limpiar datos del mes"),
        BotCommand("cancella", "eliminar un gasto"),
        BotCommand("stats", "estadísticas totales"),
        BotCommand("scadenze", "gestión de facturas"),
        BotCommand("abbonamenti", "gestión de suscripciones"),
        BotCommand("setbudget", "establecer presupuesto"),
        BotCommand("help", "guía de ayuda"),
    ]
    await application.bot.set_my_commands(commands_es, language_code='es')

    # --- 3. FRANCESE (fr) ---
    commands_fr = [
        BotCommand("start", "lancer le bot"),
        BotCommand("report", "générer le graphique des dépenses"),
        BotCommand("listaspesa", "détails par catégorie"),
        BotCommand("reset", "effacer les données du mois"),
        BotCommand("cancella", "supprimer une dépense"),
        BotCommand("stats", "statistiques totales"),
        BotCommand("scadenze", "gestion des factures"),
        BotCommand("abbonamenti", "gestion des abonnements"),
        BotCommand("setbudget", "définir le budget mensuel"),
        BotCommand("help", "aide et commandes"),
    ]
    await application.bot.set_my_commands(commands_fr, language_code='fr')

    # --- 4. INGLESE / DEFAULT (en) ---
    commands_en = [
        BotCommand("start", "start the bot"),
        BotCommand("report", "generate expense chart"),
        BotCommand("listaspesa", "view details by category"),
        BotCommand("reset", "reset monthly data"),
        BotCommand("cancella", "delete an expense"),
        BotCommand("stats", "total statistics"),
        BotCommand("scadenze", "manage bills"),
        BotCommand("abbonamenti", "manage subscriptions"),
        BotCommand("setbudget", "set monthly budget"),
        BotCommand("help", "help guide"),
    ]
    # Questo viene mostrato a chiunque non rientri nelle lingue sopra
    await application.bot.set_my_commands(commands_en)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    # registriamo l'utente con la sua lingua originale
    register_user(user.id, user.username, user.first_name, user.language_code)
    
    # recuperiamo il testo di benvenuto tradotto
    benvenuto = get_text('welcome', lang=user.language_code, name=user.first_name)
    
    await update.message.reply_text(benvenuto)

async def check_subscriptions_renewal(application: Application):
    oggi_giorno = datetime.now().day
    data_iso = datetime.now().strftime("%Y-%m-%d")
    
    # cerchiamo abbonamenti. nota: assicurati che la tabella users sia joinata 
    # o di recuperare la lingua dell'utente s['user_id']
    response = supabase.table("subscriptions").select("*").eq("renewal_day", oggi_giorno).execute()
    
    for s in response.data:
        # aggiungiamo la transazione
        add_transaction(s['user_id'], s['amount'], "abbonamenti", s['name'], f"rinnovo {s['name']}", data_iso)
        
        # recuperiamo la lingua dell'utente per inviare la notifica corretta
        user_lang = get_user_language(s['user_id']) 
        
        # usiamo una chiave specifica in strings.py (es: 'subscription_renewed')
        msg = get_text('subscription_renewed', lang=user_lang, name=s['name'], amount=s['amount'])
        
        try:
            await application.bot.send_message(
                chat_id=s['user_id'],
                text=msg,
                parse_mode='Markdown'
            )
        except Exception as e:
            print(f"errore invio notifica a {s['user_id']}: {e}")
            continue


async def check_bill_reminders(application):
    from datetime import date
    today = date.today().isoformat()
    
    # recuperiamo bollette oggi o passate (pending)
    response = supabase.table("bills").select("*").lte("due_date", today).eq("status", "pending").execute()
    bills = response.data
    
    if not bills:
        return
        
    for bill in bills:
        # recuperiamo la lingua dell'utente salvata nel DB
        user_lang = get_user_language(bill['user_id'])
        
        # usiamo la chiave 'bill_reminder' dal tuo file strings.py
        msg = get_text(
            'bill_reminder', 
            lang=user_lang, 
            name=bill['name'], 
            amount=bill['amount'], 
            due_date=bill['due_date']
        )
        
        try:
            await application.bot.send_message(
                chat_id=bill['user_id'],
                text=msg,
                parse_mode='Markdown'
            )
        except Exception as e:
            print(f"errore invio reminder a {bill['user_id']}: {e}")

async def inactivity_nudge(application: Application):
    users = get_all_users() # assicurati che questa funzione restituisca anche 'language_code'
    for u in users:
        last_date = get_last_transaction_date(u['id'])
        if last_date:
            from datetime import timedelta
            if datetime.now() - datetime.strptime(last_date, "%Y-%m-%d") > timedelta(days=2):
                # recuperiamo la lingua dell'utente corrente
                user_lang = u.get('language_code', 'it')
                msg = get_text('inactivity_msg', lang=user_lang)
                
                try:
                    await application.bot.send_message(
                        chat_id=u['id'],
                        text=msg,
                        parse_mode='Markdown'
                    )
                except Exception: continue

async def weekly_summary(application: Application):
    users = get_all_users()
    for u in users:
        totale = get_monthly_total(u['id'])
        
        # recuperiamo la lingua dell'utente corrente
        user_lang = u.get('language_code', 'it')
        msg = get_text('weekly_report', lang=user_lang, total=f"{totale:.2f}")
        
        try:
            await application.bot.send_message(
                chat_id=u['id'],
                text=msg,
                parse_mode='Markdown'
            )
        except Exception: continue

async def scadenze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # recuperiamo la lingua dell'utente dal db
    lang = get_user_language(user_id)
    
    from database import get_all_pending_bills
    response = get_all_pending_bills(user_id)
    bills = response.data

    if not bills:
        # chiave in strings.py: 'no_bills'
        await update.message.reply_text(get_text('no_bills', lang=lang))
        return

    # chiave in strings.py: 'bills_title'
    testo = get_text('bills_title', lang=lang) + "\n\n"
    keyboard = []

    for b in bills:
        data_dt = datetime.strptime(b['due_date'], "%Y-%m-%d")
        data_f = data_dt.strftime("%d %b")
        
        testo += f"🔹 **{b['name']}**: {b['amount']}€ ({data_f})\n"
        
        # chiave in strings.py: 'delete_btn' (es. "🗑️ elimina {name}")
        btn_text = get_text('delete_btn', lang=lang, name=b['name'])
        keyboard.append([
            InlineKeyboardButton(btn_text, callback_data=f"del_bill_{b['id']}")
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
        # recuperiamo la lingua specifica di questo utente
        lang = get_user_language(user_id)
        
        # chiavi in strings.py: 'pay_btn', 'delete_simple_btn'
        keyboard = [[
            InlineKeyboardButton(get_text('pay_btn', lang=lang), 
                                 callback_data=f"pay_bill_{bill_id}_{bill['amount']}_{bill['name']}"),
            InlineKeyboardButton(get_text('delete_simple_btn', lang=lang), 
                                 callback_data=f"del_bill_{bill_id}")
        ]]
        
        # chiave in strings.py: 'bill_reminder'
        testo = get_text('bill_reminder', lang=lang, name=bill['name'], amount=bill['amount'])
        
        try:
            await application.bot.send_message(
                chat_id=user_id,
                text=testo,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        except Exception: continue

 # --- funzione di supporto per l'immagine ---
def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')
    

async def abbonamenti_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_language(user_id) # recuperiamo la lingua dell'utente
    
    from database import get_user_subscriptions
    response = get_user_subscriptions(user_id)
    subs = response.data

    if not subs or len(subs) == 0:
        # chiave: 'no_subs'
        await update.message.reply_text(get_text('no_subs', lang=lang))
        return

    # chiave: 'subs_title'
    testo = get_text('subs_title', lang=lang) + "\n\n"
    keyboard = []
    totale_mensile = 0
    
    for s in subs:
        nome = s.get('name', 'abbonamento')
        prezzo = float(s.get('amount', 0))
        giorno = s.get('renewal_day', '??')
        
        # riga singola dell'elenco
        testo += f"• **{nome.capitalize()}**: {prezzo:.2f}€ ({get_text('day_label', lang=lang)} {giorno})\n"
        totale_mensile += prezzo
        
        # bottone per eliminare
        btn_text = get_text('delete_btn', lang=lang, name=nome)
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"del_sub_{s['id']}")])
    
    # riga di riepilogo finale
    testo += f"\n--------------------------------\n"
    testo += get_text('monthly_total_label', lang=lang, total=f"{totale_mensile:.2f}") + "\n"
    testo += get_text('yearly_impact_label', lang=lang, total=f"{(totale_mensile * 12):.2f}")
    
    await update.message.reply_text(
        testo, 
        reply_markup=InlineKeyboardMarkup(keyboard), 
        parse_mode='Markdown'
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # recuperiamo la lingua dell'utente per localizzare l'esperienza
    lang = get_user_language(user_id)
    
    photo_file = await update.message.photo[-1].get_file()
    
    # chiave: 'ocr_processing' (es: "📸 sto leggendo lo scontrino...")
    status_msg = await update.message.reply_text(get_text('ocr_processing', lang=lang))
    img_path = f"temp_{user_id}.jpg"
    
    try:
        # 1. scarica la foto localmente
        await photo_file.download_to_drive(img_path)
        base64_img = encode_image(img_path)
        
        # 2. recupera categorie esistenti
        from database import get_existing_categories 
        categorie_presenti = get_existing_categories()
        cat_list_str = ", ".join(categorie_presenti)

        # 3. chiamata a llama-4-scout (istruito sulla lingua)
        completion = groq_client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "text", 
                        "text": f"extract receipt data in JSON: totale (number), data (YYYY-MM-DD), descrizione (shop name), categoria. "
                                f"context language: {lang}. "
                                f"use one of these if suitable: [{cat_list_str}]. "
                                f"if new, invent a short one (max 1 word)."
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
        
        # 4. normalizzazione
        importo = res.get('totale', 0)
        negozio_raw = str(res.get('descrizione', 'ignoto'))
        cat_estratta = str(res.get('categoria', 'altro')).strip()

        negozio = negozio_raw.lower()
        match = next((c for c in categorie_presenti if c.lower() == cat_estratta.lower()), None)
        categoria_finale = match if match else cat_estratta.capitalize() 
        data_scontrino = res.get('data', datetime.now().strftime("%Y-%m-%d"))

        # 5. salvataggio temporaneo
        context.user_data['pending_ocr'] = {
            'amount': importo,
            'category': categoria_finale,
            'description': negozio,
            'date': data_scontrino
        }

        # 6. tastiera inline localizzata
        keyboard = [
            [
                InlineKeyboardButton(get_text('confirm_btn', lang=lang), callback_data="confirm_ocr"),
                InlineKeyboardButton(get_text('cancel_btn', lang=lang), callback_data="cancel_ocr")
            ]
        ]
        
        # chiave: 'ocr_success_msg'
        await status_msg.edit_text(
            get_text('ocr_success_msg', 
                     lang=lang, 
                     amount=importo, 
                     merchant=negozio, 
                     category=categoria_finale, 
                     date=data_scontrino),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    except Exception as e:
        print(f"errore ocr: {e}")
        # chiave: 'ocr_error'
        await status_msg.edit_text(get_text('ocr_error', lang=lang))
    
    finally:
        if os.path.exists(img_path):
            os.remove(img_path)

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_language(user_id) # recuperiamo la lingua (it, en, es, ecc.)
    voice = update.message.voice
    
    # chiave: 'voice_listening' (es: "🎧 ascolto e trascrivo...")
    status_msg = await update.message.reply_text(get_text('voice_listening', lang=lang))

    ogg_file = f"voice_{user_id}.ogg"

    try:
        # 1. scarichiamo il vocale
        file = await context.bot.get_file(voice.file_id)
        await file.download_to_drive(ogg_file)

        # 2. trascrizione con groq (passando la lingua dell'utente)
        with open(ogg_file, "rb") as audio_file:
            transcription = groq_client.audio.transcriptions.create(
                file=(ogg_file, audio_file.read()),
                model="whisper-large-v3",
                response_format="text",
                language=lang # ora whisper si aspetta la lingua corretta
            )
        
        text = transcription.strip()
        
        if not text:
            # chiave: 'voice_empty'
            await status_msg.edit_text(get_text('voice_empty', lang=lang))
            return

        # chiave: 'voice_understood' (es: "📝 ho capito: \"{text}\"")
        msg_understood = get_text('voice_understood', lang=lang, text=text)
        await status_msg.edit_text(msg_understood)

        # 3. inoltro al processore di messaggi
        await handle_message(update, context, overridden_text=text)

    except Exception as e:
        import logging
        logging.error(f"errore vocale: {e}")
        # chiave: 'voice_error'
        await status_msg.edit_text(get_text('voice_error', lang=lang))
    
    finally:
        if os.path.exists(ogg_file):
            os.remove(ogg_file)


async def abbonamenti_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_language(user_id)
    
    from database import get_user_subscriptions
    response = get_user_subscriptions(user_id)
    subs = response.data

    if not subs:
        await update.message.reply_text(get_text('no_subs', lang=lang))
        return

    testo = get_text('subs_title', lang=lang) + "\n\n"
    keyboard = []
    totale = 0
    
    for s in subs:
        nome = s.get('name', 'sub')
        prezzo = float(s.get('amount', 0))
        giorno = s.get('renewal_day', '??')
        
        # riga dell'elenco localizzata
        testo += f"• **{nome.capitalize()}**: {prezzo:.2f}€ ({get_text('day_label', lang=lang)} {giorno})\n"
        totale += prezzo
        
        # bottone elimina localizzato
        btn_text = get_text('delete_btn', lang=lang, name=nome)
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"del_sub_{s['id']}")])
    
    testo += f"\n" + get_text('monthly_total_label', lang=lang, total=f"{totale:.2f}")
    await update.message.reply_text(testo, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def set_budget_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_language(user_id)
    
    try:
        amount = float(context.args[0])
        from database import update_user_budget
        update_user_budget(user_id, amount)
        
        # chiave: 'budget_set_ok'
        await update.message.reply_text(get_text('budget_set_ok', lang=lang, amount=amount))
        
    except (IndexError, ValueError):
        # chiave: 'budget_usage'
        await update.message.reply_text(get_text('budget_usage', lang=lang))

async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_language(user_id)
    search_query = " ".join(context.args)
    
    if not search_query:
        # chiave: 'delete_usage'
        await update.message.reply_text(get_text('delete_usage', lang=lang))
        return

    from database import search_transactions
    try:
        results = search_transactions(user_id, search_query)
    except Exception as e:
        logging.error(f"errore db in ricerca: {e}")
        await update.message.reply_text(get_text('error', lang=lang))
        return

    if not results:
       # chiave: 'no_results'
       await update.message.reply_text(get_text('no_results', lang=lang, query=search_query))
       return

    # chiave: 'results_found'
    await update.message.reply_text(get_text('results_found', lang=lang, count=len(results)))
    
    for t in results:
        try: 
            # bottone elimina specifico per la spesa
            btn_text = get_text('delete_amount_btn', lang=lang, amount=t['amount'])
            keyboard = [[InlineKeyboardButton(btn_text, callback_data=f"del_{t['id']}")]]
            
            cosa = t.get('description') or get_text('generic_expense', lang=lang)
            msg = f"📝 **{cosa}**\n💰 {t['amount']}€"
            
            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        except Exception as e:
            logging.error(f"errore visualizzazione riga: {e}")
            continue


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_language(user_id)
    
    # chiave: 'help_text'
    await update.message.reply_text(get_text('help_text', lang=lang), parse_mode='Markdown')
    

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_language(user_id)
    
    # tastiera localizzata - chiavi: 'confirm_reset_btn', 'cancel_btn'
    keyboard = [[
        InlineKeyboardButton(get_text('confirm_reset_btn', lang=lang), callback_data='confirm_reset'),
        InlineKeyboardButton(get_text('cancel_btn', lang=lang), callback_data='cancel_reset')
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # chiave: 'reset_warning'
    await update.message.reply_text(
        get_text('reset_warning', lang=lang),
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def abbonamenti_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_language(user_id)
    
    from database import get_user_subscriptions
    response = get_user_subscriptions(user_id)
    subs = response.data

    if not subs:
        # chiave: 'no_subs_hint'
        await update.message.reply_text(get_text('no_subs_hint', lang=lang), parse_mode='Markdown')
        return

    testo = get_text('subs_title', lang=lang) + "\n\n"
    keyboard = []
    totale_mensile = 0
    
    for s in subs:
        nome = s.get('name', 'sub')
        prezzo = float(s.get('amount', 0))
        giorno = s.get('renewal_day', '??')
        
        testo += f"• **{nome.capitalize()}**: {prezzo:.2f}€ ({get_text('day_label', lang=lang)} {giorno})\n"
        totale_mensile += prezzo
        
        # chiave: 'delete_btn'
        keyboard.append([InlineKeyboardButton(get_text('delete_btn', lang=lang, name=nome), 
                                              callback_data=f"del_sub_{s['id']}")])
    
    testo += f"\n--------------------------------\n"
    testo += get_text('monthly_total_label', lang=lang, total=f"{totale_mensile:.2f}") + "\n"
    testo += get_text('yearly_impact_label', lang=lang, total=f"{(totale_mensile * 12):.2f}")
    
    await update.message.reply_text(testo, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def listaspesa_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    lang = get_user_language(user_id)
    
    from database import get_monthly_report_data
    from datetime import datetime
    import locale # utile se vuoi nomi mesi automatici, ma strings.py è più sicuro

    categories = get_monthly_report_data(user_id)
    # recuperiamo il nome del mese tradotto (se lo hai in strings.py) o usiamo lo standard
    mese_corrente = datetime.now().strftime("%m/%Y") 
    
    if not categories:
        msg_text = get_text('no_expenses_month', lang=lang, month=mese_corrente)
        if query:
            await query.edit_message_text(msg_text)
        else:
            await update.message.reply_text(msg_text)
        return

    msg_text = get_text('list_expenses_title', lang=lang, month=mese_corrente)
    keyboard = []
    for cat in categories:
        nome_cat = cat['category']
        totale = cat['total_amount']
        keyboard.append([InlineKeyboardButton(f"{nome_cat}: {totale:.2f}€", callback_data=f"list_{nome_cat}")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        await query.edit_message_text(msg_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(msg_text, reply_markup=reply_markup, parse_mode='Markdown')


async def monthly_parasite_report(application: Application):
    from database import supabase
    response = supabase.table("subscriptions").select("user_id").execute()
    users = list(set([r['user_id'] for r in response.data]))
    
    for u_id in users:
        lang = get_user_language(u_id)
        msg = get_text('parasite_report_alert', lang=lang)
        try:
            await application.bot.send_message(chat_id=u_id, text=msg)
        except Exception: continue

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_language(user_id)
    from database import get_monthly_total, get_user_subscriptions
    
    totale_speso = get_monthly_total(user_id)
    response_subs = get_user_subscriptions(user_id)
    subs = response_subs.data
    
    num_subs = len(subs)
    totale_subs = sum(float(s['amount']) for s in subs)
    
    # costruiamo il report usando le chiavi di strings.py
    testo = get_text('stats_header', lang=lang) + "\n"
    testo += "--------------------------------\n"
    testo += get_text('stats_total_spent', lang=lang, total=f"{totale_speso:.2f}") + "\n\n"
    
    if num_subs > 0:
        testo += get_text('stats_subs_focus', lang=lang, count=num_subs, total=f"{totale_subs:.2f}") + "\n"
        testo += get_text('yearly_impact_label', lang=lang, total=f"{(totale_subs * 12):.2f}")
    else:
        testo += get_text('no_subs_active', lang=lang)
        
    await update.message.reply_text(testo, parse_mode='Markdown')

 

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_language(user_id)
    
    # chiave: 'analyzing_data'
    status_msg = await update.message.reply_text(get_text('analyzing_data', lang=lang))
    
    try:
        from database import get_monthly_report_data, get_user_settings, generate_report_chart
        transactions = get_monthly_report_data(user_id)

        if not transactions:
            await status_msg.edit_text(get_text('no_data', lang=lang))
            return

        totale_speso = sum(t.get('total_amount', 0) for t in transactions)
        settings = get_user_settings(user_id)
        budget = settings[0].get('budget_monthly', 0) if (settings and len(settings) > 0) else 0
        
        barra = ""
        if budget > 0:
            percentuale = min(int((totale_speso / budget) * 10), 10)
            rimanente = budget - totale_speso
            
            # chiave: 'budget_status'
            status_text = get_text('budget_remaining', lang=lang, amount=f"{rimanente:.2f}") if rimanente > 0 else get_text('over_budget', lang=lang)
            
            barra = f"\n\n💰 **budget:** {totale_speso:.2f}€ / {budget:.2f}€\n"
            barra += f"|{'🔘' * percentuale}{'⚪' * (10 - percentuale)}|\n"
            barra += status_text

        chart_buffer = generate_report_chart(transactions)

        if chart_buffer is None:
            await status_msg.edit_text(get_text('chart_error', lang=lang))
            return
        
        await status_msg.delete()
        # chiave: 'report_caption'
        await update.message.reply_photo(
            photo=chart_buffer,
            caption=get_text('report_caption', lang=lang) + barra,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logging.error(f"errore report: {e}")
        await update.message.reply_text(get_text('error', lang=lang))

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE, overridden_text=None):
    user_id = update.effective_user.id
    user_text = overridden_text if overridden_text else update.message.text
    # recupera la lingua salvata nel db per questo utente
    lang = get_user_language(user_id)
    
    try:
        current_date = datetime.now().strftime("%d %B %Y")
        # invio richiesta al team finance
        response = finance_team.run(f"utente {user_id} (lingua: {lang}). oggi è {current_date}. testo: '{user_text}'")
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
    lang = get_user_language(user_id) # recupero lingua utente
    await query.answer()

    # --- 1. GESTIONE TRANSAZIONI (TESTO/VOCE) ---
    if data == 'confirm':
        trans_data = context.user_data.pop('pending_transaction', None)
        if not trans_data:
            await query.edit_message_text(get_text('session_expired', lang=lang))
            return
        try:
            from database import add_transaction, get_user_settings, get_monthly_total
            add_transaction(
                user_id, 
                trans_data.get('amount'), 
                trans_data.get('category', 'altro'), 
                trans_data.get('merchant', ''), 
                trans_data.get('description', '')
            )
            settings = get_user_settings(user_id)
            budget_totale = settings[0].get('budget_monthly', 0) if settings else 0
            nuovo_totale = get_monthly_total(user_id)
            
            # logica budget localizzata
            avviso = f"\n\n" + get_text('monthly_spent_label', lang=lang, total=f"{nuovo_totale:.2f}")
            if budget_totale > 0:
                rimanente = budget_totale - nuovo_totale
                if rimanente < 0:
                    avviso = f"\n\n" + get_text('over_budget_alert', lang=lang, amount=f"{abs(rimanente):.2f}")
                else:
                    avviso = f"\n\n" + get_text('budget_left_label', lang=lang, amount=f"{rimanente:.2f}")

            await query.edit_message_text(
                get_text('save_confirm_msg', lang=lang, amount=trans_data['amount'], desc=trans_data.get('description', 'spesa'), budget_info=avviso),
                parse_mode='Markdown'
            )
        except Exception as e:
            logging.error(f"errore salvataggio: {e}")
            await query.edit_message_text(get_text('save_error', lang=lang))

    elif data == 'cancel':
        context.user_data.pop('pending_transaction', None)
        await query.edit_message_text(get_text('cancelled', lang=lang))

    # --- 2. GESTIONE OCR (SCONTRINI) ---
    elif data == "confirm_ocr":
        ocr_data = context.user_data.pop('pending_ocr', None)
        if ocr_data:
            from database import add_transaction_from_ocr
            add_transaction_from_ocr(user_id, ocr_data['amount'], ocr_data['category'], ocr_data['description'], ocr_data['date'])
            await query.edit_message_text(get_text('ocr_saved_ok', lang=lang, amount=ocr_data['amount']))

    elif data == "cancel_ocr":
        context.user_data.pop('pending_ocr', None)
        await query.edit_message_text(get_text('cancelled', lang=lang))

    # --- 3. GESTIONE BOLLETTE (BILLS) ---
    elif data == "confirm_bill":
        bill_data = context.user_data.pop('pending_bill', None)
        if bill_data:
            from database import add_bill
            add_bill(user_id, bill_data['name'], bill_data['amount'], bill_data['due_date'])
            await query.edit_message_text(get_text('bill_set_ok', lang=lang, date=bill_data['due_date']))

    elif data == "cancel_bill":
        context.user_data.pop('pending_bill', None)
        await query.edit_message_text(get_text('cancelled', lang=lang))

    elif data == 'confirm_sub':
        sub_data = context.user_data.get('pending_subscription')
        if sub_data:
            from database import add_subscription
            add_subscription(user_id=user_id, name=sub_data['name'], amount=sub_data['amount'], renewal_day=sub_data['renewal_day'])
            await query.edit_message_text(get_text('sub_saved_ok', lang=lang, name=sub_data['name']))
            context.user_data.pop('pending_subscription', None)

    elif data == 'cancel_sub':
        context.user_data.pop('pending_subscription', None)
        await query.edit_message_text(get_text('cancelled', lang=lang))

    # --- ELIMINAZIONE ---
    elif data.startswith("del_bill_"):
        bill_id = data.split("_")[2]
        try:
            from database import delete_bill
            delete_bill(bill_id)
            await query.edit_message_text(get_text('deleted_ok', lang=lang))
        except Exception as e:
            logging.error(f"errore elimina bill: {e}")
            await query.edit_message_text(get_text('error', lang=lang))

    elif data.startswith("del_sub_"):
        sub_id = data.split("_")[2]
        try:
            from database import delete_subscription
            delete_subscription(sub_id)
            await query.edit_message_text(get_text('sub_removed_ok', lang=lang))
        except Exception as e:
            logging.error(f"errore elimina sub: {e}")
            await query.edit_message_text(get_text('error', lang=lang))
    
    # --- 4. TRASFORMA BOLLETTA IN SPESA ---
    elif data.startswith("pay_bill_"):
        parts = data.split("_")
        bill_id, amount, b_name = parts[2], float(parts[3]), parts[4]
        try:
            from database import mark_bill_as_paid, add_transaction_from_ocr
            from datetime import datetime
            mark_bill_as_paid(bill_id)
            add_transaction_from_ocr(user_id, amount, "Bollette", b_name, datetime.now().strftime("%Y-%m-%d"))
            await query.edit_message_text(get_text('bill_paid_ok', lang=lang, name=b_name))
        except Exception as e:
            logging.error(f"errore pay_bill: {e}")
            await query.edit_message_text(get_text('error', lang=lang))

    # --- 5. VISUALIZZAZIONE LISTE ---
    elif data.startswith("list_"):
        category_name = data.split("_")[1]
        from database import get_expenses_by_category
        expenses = get_expenses_by_category(user_id, category_name)
        if not expenses:
            await query.edit_message_text(get_text('no_expenses_cat', lang=lang, cat=category_name))
            return

        testo = f"📑 **{get_text('detail_label', lang=lang)} {category_name.upper()}**\n{'-'*20}\n"
        totale_cat = 0
        for e in expenses:
            totale_cat += e['amount']
            data_f = datetime.strptime(e['transaction_date'], "%Y-%m-%d").strftime("%d %b")
            testo += f"▫️ {e['amount']:.2f}€ — {e.get('description', 'spesa')} ({data_f})\n"
        testo += f"{'-'*20}\n💰 **{get_text('total_label', lang=lang)}: {totale_cat:.2f}€**"
        
        back_kb = [[InlineKeyboardButton(get_text('back_btn', lang=lang), callback_data="back_to_list")]]
        await query.edit_message_text(testo, reply_markup=InlineKeyboardMarkup(back_kb), parse_mode='Markdown')

    elif data == "back_to_list":
        from bot import listaspesa_command
        await listaspesa_command(update, context)

    # --- 6. RESET ---
    elif data == 'confirm_reset':
        from database import reset_monthly_data
        reset_monthly_data(user_id)
        await query.edit_message_text(get_text('reset_ok', lang=lang))

    elif data == 'cancel_reset':
        await query.edit_message_text(get_text('cancelled', lang=lang))

    elif data.startswith("del_"):
        transaction_id = data.split("_")[1]
        from database import delete_transaction_by_id
        delete_transaction_by_id(transaction_id)
        await query.edit_message_text(get_text('deleted_ok', lang=lang))

if __name__ == '__main__':
    token = os.environ.get("TELEGRAM_TOKEN")
    
    if not token:
        # qui usiamo un print perché il bot non è ancora partito
        print("❌ errore: variabile d'ambiente TELEGRAM_TOKEN non trovata!")
        exit()

    # inizializzazione dell'applicazione
    # post_init è fondamentale per caricare i comandi nel menu di telegram
    application = ApplicationBuilder().token(token).post_init(post_init).build()
    
    # --- registrazione degli handler ---
    # comandi principali
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
    
    # gestione input multimediali e testi
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    # gestione interazioni (pulsanti inline)
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # log di avvio
    print("🚀 bot operativo e pronto a gestire più lingue...")
    
    # avvio del polling (ascolto dei messaggi)
    application.run_polling()