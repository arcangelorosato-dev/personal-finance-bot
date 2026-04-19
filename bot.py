import os
import logging
import json
import re
import base64
from datetime import datetime
from dotenv import load_dotenv
from groq import Groq
# telegram imports
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler

# agno & db imports
from agents import finance_team, report_agent
from database import (
    add_transaction, 
    get_user_settings, 
    create_user_settings, 
    get_category_total, 
    get_monthly_report_data, 
    generate_report_chart,
    get_monthly_total
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
    commands = [
        BotCommand("start", "avvia il bot"),
        BotCommand("report", "infografica spese"),
        BotCommand("listaspesa", "dettaglio spese per categoria"), # aggiunto qui
        BotCommand("reset", "cancella spese del mese"), # nuovo comando
        BotCommand("cancella", "elimina una spesa"),
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

 # --- funzione di supporto per l'immagine ---
def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

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
        
        # 2. recupera categorie esistenti per darle in pasto a groq
        # nota: get_existing_categories() deve essere nel tuo database.py
        from database import get_existing_categories 
        categorie_presenti = get_existing_categories()
        cat_list_str = ", ".join(categorie_presenti)

        # 3. chiamata a llama-4-scout su groq
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

        # negozio: sempre minuscolo (come da tua regola)
        negozio = negozio_raw.lower()

        # categoria: cerca match nel db o crea nuova
        match = next((c for c in categorie_presenti if c.lower() == cat_estratta.lower()), None)
        if match:
            categoria_finale = match # usa quella del db (es. "Cibo")
        else:
            categoria_finale = cat_estratta.capitalize() # nuova (es. "Regali")

        data_scontrino = res.get('data', "2026-01-01")

        # 5. salvataggio temporaneo nei context per il bottone di conferma
        context.user_data['pending_ocr'] = {
            'amount': importo,
            'category': categoria_finale,
            'description': negozio,
            'date': data_scontrino
        }

        # 6. creazione tastiera inline
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
        await status_msg.edit_text("❌ non sono riuscito a leggere lo scontrino. riprova con una foto più chiara.")
    
    finally:
        # pulizia file temporaneo
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

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE,overridden_text=None):
    user_id = update.effective_user.id
    user_text = overridden_text if overridden_text else update.message.text
    
    try:
        current_date = datetime.now().strftime("%B %Y")
        response = finance_team.run(f"utente {user_id}: '{user_text}'. data: {current_date}")
        content = response.content

        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        
        if json_match:
            json_str = json_match.group().replace("'", '"').replace("True", "true").replace("False", "false")
            transaction_data = json.loads(json_str)

            # normalizzazione categoria
            transaction_data['category'] = transaction_data['category'].strip().capitalize()
            
            context.user_data['pending_transaction'] = transaction_data
            
            # --- logica avviso budget (anteprima) ---
            from database import get_category_total, get_user_settings, get_monthly_total
            cat_total = get_category_total(user_id, transaction_data['category'])
            
            settings = get_user_settings(user_id)
            budget_totale = settings[0].get('budget_monthly', 0) if settings else 0
            speso_attuale = get_monthly_total(user_id)
            nuovo_totale_previsto = speso_attuale + transaction_data['amount']
            
            avviso_budget = ""
            if budget_totale > 0:
                rimanente = budget_totale - nuovo_totale_previsto
                if nuovo_totale_previsto > budget_totale:
                    avviso_budget = f"\n⚠️ **attenzione:** con questa spesa saresti fuori budget di {abs(rimanente):.2f}€!"
                else:
                    avviso_budget = f"\n💰 budget residuo dopo questa spesa: **{rimanente:.2f}€**"

            display_text = content.replace(json_match.group(), "").strip().split('\n')[0]
            
            keyboard = [[
                InlineKeyboardButton("✅ conferma", callback_data='confirm'),
                InlineKeyboardButton("🗑️ annulla", callback_data='cancel')
            ]]
            
            cosa = transaction_data.get('description', 'n/d')
            dove = transaction_data.get('merchant', 'n/d')
            
            final_msg = (
                f"💬 {display_text}\n\n"
                f"💰 **{transaction_data['amount']}€** in {transaction_data['category']}\n"
                f"📝 **cosa:** {cosa}\n"
                f"📍 **dove:** {dove}\n"
                f"📅 totale categoria: {cat_total + transaction_data['amount']}€"
                f"{avviso_budget}"
            )
  
            await update.message.reply_text(final_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        else:
            logging.info(f"AI Response senza JSON: {content}")
            await update.message.reply_text(content)

    except Exception as e:
        logging.error(f"errore messaggio: {e}")
        await update.message.reply_text("⚠️ non ho capito bene. se è una spesa, prova a scriverla più chiaramente.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = update.effective_user.id
    await query.answer()

    # --- logica reset (sicurezza) ---
    if data == 'confirm_reset':
        from database import reset_monthly_data
        try:
            reset_monthly_data(user_id)
            await query.edit_message_text("🧹 **database pulito!** tutte le spese del mese sono state rimosse.")
        except Exception as e:
            logging.error(f"errore reset: {e}")
            await query.edit_message_text("❌ errore durante il reset dei dati.")
        return

    if query.data == "confirm_ocr":
        data = context.user_data.get('pending_ocr')
        if data:
            # chiamata al database
            add_transaction_from_ocr(
                user_id=update.effective_user.id,
                amount=data['amount'],
                category=data['category'],
                description=data['description'],
                date=data['date']
            )
            await query.edit_message_text(f"✅ spesa di {data['amount']}€ salvata correttamente!")
            # puliamo i dati temporanei
            del context.user_data['pending_ocr']
            
    elif query.data == "cancel_ocr":
        if 'pending_ocr' in context.user_data:
            del context.user_data['pending_ocr']
        await query.edit_message_text("🗑️ inserimento annullato.")

    if data.startswith("list_"):
        category_name = data.split("_")[1]
        from database import get_expenses_by_category
        from datetime import datetime
        
        expenses = get_expenses_by_category(user_id, category_name)
        
        if not expenses:
            await query.edit_message_text(f"nessuna spesa trovata per {category_name} questo mese.")
            return

        testo = f"📑 **dettaglio {category_name.upper()}**\n"
        testo += "--------------------------------\n"
        totale_cat = 0
        for e in expenses:
            importo = e['amount']
            desc = e.get('description') or "spesa"
            # formattazione data
            data_dt = datetime.strptime(e['transaction_date'], "%Y-%m-%d")
            data_f = data_dt.strftime("%d %b")
            
            totale_cat += importo
            testo += f"▫️ {importo:.2f}€ — {desc} ({data_f})\n"
        
        testo += "--------------------------------\n"
        testo += f"💰 **totale categoria: {totale_cat:.2f}€**"
        
        back_kb = [[InlineKeyboardButton("⬅️ torna alla lista", callback_data="back_to_list")]]
        await query.edit_message_text(testo, reply_markup=InlineKeyboardMarkup(back_kb), parse_mode='Markdown')

    elif data == "back_to_list":
        # usiamo la funzione sopra per rigenerare il menu
        await listaspesa_command(update, context)

    elif data == "back_to_list":
        # per far funzionare questo richiamo, listaspesa_command deve gestire sia 'message' che 'callback_query'
        # o più semplicemente chiamiamo la logica di invio menu:
        await listaspesa_command(update, context)

    if data == 'cancel_reset':
        await query.edit_message_text("operazione annullata. i tuoi dati sono al sicuro. 🛡️")
        return

    # --- logica eliminazione ---
    if data.startswith("del_"):
        transaction_id = data.split("_")[1] 
        from database import delete_transaction_by_id
        try:
            delete_transaction_by_id(transaction_id)
            await query.edit_message_text("✅ spesa eliminata correttamente!")
        except Exception as e:
            logging.error(f"errore eliminazione: {e}")
            await query.edit_message_text("❌ errore durante l'eliminazione.")
        return
    
    # --- logica conferma spesa ---
    if data == 'confirm':
        trans_data = context.user_data.get('pending_transaction')
        
        if not trans_data:
            await query.edit_message_text("sessione scaduta, riprova.")
            return

        try:
            from database import add_transaction, get_user_settings, get_monthly_total
            # salvataggio
            add_transaction(
                user_id, 
                trans_data['amount'], 
                trans_data['category'], 
                trans_data.get('merchant'), 
                trans_data.get('description')
            )
            
            # ricalcolo budget per avviso finale
            settings = get_user_settings(user_id)
            budget_totale = settings[0].get('budget_monthly', 0) if settings else 0
            nuovo_totale = get_monthly_total(user_id)
            
            avviso_finale = ""
            if budget_totale > 0:
                percentuale = (nuovo_totale / budget_totale) * 100
                rimanente = budget_totale - nuovo_totale
                
                if percentuale >= 100:
                    avviso_finale = f"\n\n🚨 **fuori budget!** speso: {nuovo_totale:.2f}€ / {budget_totale:.2f}€"
                elif percentuale >= 80:
                    avviso_finale = f"\n\n🟡 **attenzione:** sei all'80% del budget. restano {rimanente:.2f}€"
                else:
                    avviso_finale = f"\n\n💰 speso nel mese: {nuovo_totale:.2f}€ (restano {rimanente:.2f}€)"

            await query.edit_message_text(
                text=f"✅ **salvato!**\n{trans_data['amount']}€ per {trans_data.get('description', 'spesa')}{avviso_finale}",
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logging.error(f"errore salvataggio: {e}")
            await query.edit_message_text("❌ errore durante il salvataggio.")
            
    elif data == 'cancel':
        context.user_data.pop('pending_transaction', None)
        await query.edit_message_text("operazione annullata. 🗑️")
        await query.edit_message_text("🗑️ operazione annullata.")

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
    application.add_handler(CommandHandler('reset', reset_command))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    print("🚀 bot multi-agente operativo (fase infografica)...")
    application.run_polling()