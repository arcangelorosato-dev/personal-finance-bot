import os
import logging
import json
import re
from datetime import datetime
from dotenv import load_dotenv

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
    generate_report_chart
)

# caricamento ambiente
load_dotenv()

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
        BotCommand("reset", "cancella spese del mese"), # nuovo comando
        BotCommand("help", "aiuto")
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

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🤖 **guida rapida:**\n\n"
        "💰 **registra spesa**: scrivi semplicemente '20 euro da OVS' o 'pizza 15€'.\n"
        "📊 **/report**: genera un grafico a torta con l'analisi delle tue spese.\n"
        "💬 **chiacchiere**: puoi anche parlarmi normalmente, risponderò come un assistente!"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        from database import reset_monthly_data
        reset_monthly_data(user_id)
        await update.message.reply_text("🧹 **database resettato!** tutte le spese di questo mese sono state cancellate. pronto per il test.")
    except Exception as e:
        logging.error(f"errore reset: {e}")
        await update.message.reply_text("⚠️ non sono riuscito a resettare i dati.")

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    status_msg = await update.message.reply_text("📊 sto analizzando le tue spese e disegnando il grafico...")
    
    try:
        # 1. recupero dati dal database
        transactions = get_monthly_report_data(user_id)
        
        if not transactions:
            await status_msg.edit_text("non ho ancora dati per questo mese. registra la prima spesa!")
            return
            
        # 2. generazione dell'infografica (grafico a torta)
        chart_buffer = generate_report_chart(transactions)
        
        # 3. analisi testuale tramite l'agente
        data_text = json.dumps(transactions)
        response = report_agent.run(f"analizza queste spese e scrivi una sintesi brevissima: {data_text}")
        
        # 4. invio della foto con il commento
        await status_msg.delete() # rimuove il messaggio "sto analizzando..."
        await update.message.reply_photo(
            photo=chart_buffer,
            caption=f"📈 **il tuo report mensile**\n\n{response.content}",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logging.error(f"errore nel report: {e}")
        await update.message.reply_text("⚠️ scusa, non sono riuscito a generare l'infografica in questo momento.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text
    
    try:
        current_date = datetime.now().strftime("%B %Y")
        response = finance_team.run(f"utente {user_id}: '{user_text}'. data: {current_date}")
        content = response.content

        # cerchiamo se l'agente ha prodotto un JSON (significa che ha rilevato una spesa)
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        
        if json_match:
            # pulizia e caricamento JSON
            json_str = json_match.group().replace("'", '"').replace("True", "true").replace("False", "false")
            transaction_data = json.loads(json_str)

            # Pulisce la categoria: toglie spazi extra e mette la prima lettera maiuscola
            transaction_data['category'] = transaction_data['category'].strip().capitalize()

            # Esempio: " bolletta " diventa "Bolletta", "cibo" diventa "Cibo"
            
            context.user_data['pending_transaction'] = transaction_data
            cat_total = get_category_total(user_id, transaction_data['category'])
            
            # pulizia testo per il commento dell'agente
            display_text = content.replace(json_match.group(), "").strip().split('\n')[0]
            
            keyboard = [[
                InlineKeyboardButton("✅ conferma", callback_data='confirm'),
                InlineKeyboardButton("🗑️ annulla", callback_data='cancel')
            ]]
            
            final_msg = (
                f"💬 {display_text}\n\n"
                f"💰 **{transaction_data['amount']}€** in {transaction_data['category']}\n"
                f"🏢 presso: {transaction_data.get('merchant', 'N/D')}\n"
                f"📅 totale mese: {cat_total + transaction_data['amount']}€"
            )

            await update.message.reply_text(final_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        else:
            # se non c'è JSON, sono chiacchiere: rispondi normalmente
            await update.message.reply_text(content)

    except Exception as e:
        logging.error(f"errore messaggio: {e}")
        await update.message.reply_text("⚠️ non ho capito bene. se è una spesa, prova a scriverla più chiaramente.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'confirm':
        data = context.user_data.get('pending_transaction')
        user_id = update.effective_user.id
        
        if not data:
            await query.edit_message_text("sessione scaduta, riprova.")
            return

        try:
            add_transaction(user_id, data['amount'], data['category'], data.get('merchant', 'Sconosciuto'))
            await query.edit_message_text(f"✅ salvato: {data['amount']}€ in {data['category']}!")
        except Exception:
            await query.edit_message_text("❌ errore durante il salvataggio.")
    else:
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
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('reset', reset_command))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    print("🚀 bot multi-agente operativo (fase infografica)...")
    application.run_polling()