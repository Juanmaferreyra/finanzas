import os
import sqlite3
import re
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, filters, ContextTypes
)

TOKEN = "8460702598:AAHvebY7D9HdBkeoAdeOTK5nx1JuYIoIAms"
DB_PATH = "finanzas.db"

CATEGORIAS = [
    "🏠 Vivienda / Alquiler","🛒 Comida / Supermercado","🚗 Transporte",
    "🏥 Salud","👕 Ropa","💡 Servicios (luz, internet, etc.)","📈 Inversiones",
    "📺 Suscripciones","🎉 Entretenimiento","🔧 Imprevistos / Varios",
    "💳 Deuda","🎓 Universidad","🍻 Salidas","📱 Celular","📦 Otros"
]

PALABRAS_CLAVE = {
    "🏠 Vivienda / Alquiler":            ["alquiler","expensas","inmobiliaria","vivienda"],
    "🛒 Comida / Supermercado":           ["super","supermercado","carrefour","dia","coto","jumbo","verdura","almacen","almacén","comida","mercado","feria","kiosco"],
    "🚗 Transporte":                      ["uber","cabify","taxi","colectivo","subte","tren","nafta","combustible","peaje","remis","sube"],
    "🏥 Salud":                           ["farmacia","medico","médico","doctor","hospital","clinica","clínica","medicamento","dentista","prepaga"],
    "👕 Ropa":                            ["ropa","zapatillas","zapatos","camisa","pantalon","vestido","remera","indumentaria"],
    "💡 Servicios (luz, internet, etc.)": ["luz","gas","agua","internet","wifi","telefono","teléfono","edenor","edesur","metrogas"],
    "📈 Inversiones":                     ["inversion","inversión","plazo fijo","cripto","acciones","fondo","cedear"],
    "📺 Suscripciones":                   ["netflix","spotify","disney","amazon","hbo","youtube","suscripcion","prime"],
    "🎉 Entretenimiento":                 ["cine","teatro","show","recital","evento","juego","steam","playstation"],
    "🔧 Imprevistos / Varios":            ["reparacion","reparación","plomero","electricista","arreglo","imprevisto"],
    "💳 Deuda":                           ["deuda","prestamo","préstamo","tarjeta","credito","crédito"],
    "🎓 Universidad":                     ["universidad","facultad","curso","libro","apunte","fotocopias","inscripcion"],
    "🍻 Salidas":                         ["bar","boliche","restaurante","resto","cerveza","pizza","sushi","cafe","café","salida"],
    "📱 Celular":                         ["celular","movil","móvil","recarga","plan celular"],
    "📦 Otros":                           ["otro","varios"]
}

FORMAS_PAGO = ["Débito","Crédito","Efectivo","Transferencia","Billetera virtual"]
PAGO_KEYWORDS = {
    "Débito":            ["debito","débito","debi"],
    "Crédito":           ["credito","crédito","credi","visa","mastercard"],
    "Efectivo":          ["efectivo","cash","plata"],
    "Transferencia":     ["transferencia","transfer","transf"],
    "Billetera virtual": ["mercadopago","mp","uala","ualá","modo","billetera"]
}

ESPERANDO_MONTO, ESPERANDO_DESC, ESPERANDO_CAT, ESPERANDO_PAGO, ING_MONTO, ING_DESC = range(6)


def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS registros (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT, descripcion TEXT, categoria TEXT,
            monto REAL, pago TEXT, notas TEXT,
            tipo TEXT DEFAULT 'gasto', created_at TEXT
        )
    """)
    con.commit()
    con.close()


def guardar_registro(fecha, desc, cat, monto, pago, notas="", tipo="gasto"):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "INSERT INTO registros (fecha,descripcion,categoria,monto,pago,notas,tipo,created_at) VALUES (?,?,?,?,?,?,?,?)",
        (fecha, desc, cat, monto, pago, notas, tipo, datetime.now().isoformat())
    )
    con.commit()
    con.close()


def obtener_registros_mes(anio, mes):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "SELECT fecha,descripcion,categoria,monto,pago,notas,tipo FROM registros WHERE strftime('%Y',fecha)=? AND strftime('%m',fecha)=? ORDER BY fecha DESC",
        (str(anio), str(mes).zfill(2))
    )
    rows = cur.fetchall()
    con.close()
    return rows


def obtener_resumen_mes(anio, mes):
    rows = obtener_registros_mes(anio, mes)
    gastos   = [r for r in rows if r[6] == 'gasto']
    ingresos = [r for r in rows if r[6] == 'ingreso']
    total_g  = sum(r[3] for r in gastos)
    total_i  = sum(r[3] for r in ingresos)
    por_cat  = {}
    for r in gastos:
        por_cat[r[2]] = por_cat.get(r[2], 0) + r[3]
    return total_g, total_i, por_cat, len(gastos)


def detectar_monto(texto):
    texto = texto.lower().replace("$","").replace(".","").replace(",","")
    numeros = re.findall(r'\d+', texto)
    if numeros:
        candidatos = [int(n) for n in numeros if int(n) >= 10]
        return max(candidatos) if candidatos else None
    return None


def detectar_categoria(texto):
    texto = texto.lower()
    for cat, palabras in PALABRAS_CLAVE.items():
        for palabra in palabras:
            if palabra in texto:
                return cat
    return None


def detectar_pago(texto):
    texto = texto.lower()
    for pago, palabras in PAGO_KEYWORDS.items():
        for palabra in palabras:
            if palabra in texto:
                return pago
    return "Débito"


def keyboard_categorias():
    botones = []
    fila = []
    for i, cat in enumerate(CATEGORIAS):
        fila.append(InlineKeyboardButton(cat, callback_data=f"cat:{cat}"))
        if len(fila) == 2:
            botones.append(fila)
            fila = []
    if fila:
        botones.append(fila)
    botones.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
    return InlineKeyboardMarkup(botones)


def keyboard_pago():
    botones = [[InlineKeyboardButton(p, callback_data=f"pago:{p}")] for p in FORMAS_PAGO]
    botones.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
    return InlineKeyboardMarkup(botones)


def keyboard_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💸 Cargar gasto",    callback_data="menu:gasto"),
         InlineKeyboardButton("💰 Cargar ingreso",  callback_data="menu:ingreso")],
        [InlineKeyboardButton("📊 Resumen del mes", callback_data="menu:resumen"),
         InlineKeyboardButton("📋 Últimos registros", callback_data="menu:ultimos")],
        [InlineKeyboardButton("❓ Ayuda",           callback_data="menu:ayuda")]
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💰 *fin.control bot*\n\n"
        "Podés cargar gastos de dos formas:\n\n"
        "📝 *Texto libre:*\n`gasté 3500 en el super con débito`\n\n"
        "🔘 *Menú guiado:* /gasto o /ingreso\n\n"
        "Otros comandos:\n"
        "/resumen — resumen del mes\n"
        "/ultimos — últimos registros\n"
        "/menu — menú principal\n"
        "/ayuda — ejemplos",
        parse_mode="Markdown"
    )


async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❓ *Ejemplos de texto libre:*\n\n"
        "`gasté 4500 en el super con débito`\n"
        "`uber 1200 efectivo`\n"
        "`netflix 3500`\n"
        "`pagué 80000 de alquiler con transferencia`\n"
        "`farmacia 2300 credito`\n\n"
        "🔘 Menú guiado: /gasto o /ingreso",
        parse_mode="Markdown"
    )


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¿Qué querés hacer?", reply_markup=keyboard_menu())


async def confirmar_registro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    g = context.user_data.get('gasto', {})
    msg = (
        "✅ *¿Confirmar registro?*\n\n"
        f"📅 Fecha: {g.get('fecha')}\n"
        f"📝 Detalle: {str(g.get('desc',''))[:50]}\n"
        f"🏷️ Categoría: {g.get('categoria')}\n"
        f"💸 Monto: *${float(g.get('monto',0)):,.0f}*\n"
        f"💳 Pago: {g.get('pago')}"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirmar", callback_data="confirm:si"),
         InlineKeyboardButton("❌ Cancelar",  callback_data="cancelar")]
    ])
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, parse_mode="Markdown", reply_markup=keyboard)
    else:
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=keyboard)


async def manejar_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text
    monto     = detectar_monto(texto)
    categoria = detectar_categoria(texto)
    pago      = detectar_pago(texto)

    if not monto:
        await update.message.reply_text(
            "No encontré el monto.\nProbá: `gasté 3500 en el super` o usá /gasto",
            parse_mode="Markdown"
        )
        return

    context.user_data['gasto'] = {
        'monto': monto, 'desc': texto, 'pago': pago,
        'fecha': datetime.now().strftime("%Y-%m-%d"), 'tipo': 'gasto'
    }

    if categoria:
        context.user_data['gasto']['categoria'] = categoria
        await confirmar_registro(update, context)
    else:
        await update.message.reply_text(
            f"💸 Monto: *${monto:,.0f}*\n💳 Pago: {pago}\n\nNo reconocí la categoría. ¿Cuál es?",
            parse_mode="Markdown",
            reply_markup=keyboard_categorias()
        )


async def cmd_gasto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['gasto'] = {'tipo': 'gasto', 'fecha': datetime.now().strftime("%Y-%m-%d")}
    await update.message.reply_text("💸 *Nuevo gasto*\n\n¿Cuánto gastaste?", parse_mode="Markdown")
    return ESPERANDO_MONTO


async def gasto_monto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    monto = detectar_monto(update.message.text)
    if not monto:
        await update.message.reply_text("No entendí el monto. Escribí solo el número, ej: `3500`", parse_mode="Markdown")
        return ESPERANDO_MONTO
    context.user_data['gasto']['monto'] = monto
    await update.message.reply_text(f"Monto: *${monto:,.0f}*\n\n¿En qué lo gastaste?", parse_mode="Markdown")
    return ESPERANDO_DESC


async def gasto_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    desc = update.message.text
    context.user_data['gasto']['desc'] = desc
    cat = detectar_categoria(desc)
    if cat:
        context.user_data['gasto']['categoria'] = cat
        await update.message.reply_text(f"Categoría: *{cat}*\n\n¿Cómo pagaste?", parse_mode="Markdown", reply_markup=keyboard_pago())
        return ESPERANDO_PAGO
    else:
        await update.message.reply_text("¿En qué categoría entra?", reply_markup=keyboard_categorias())
        return ESPERANDO_CAT


async def gasto_cat_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "cancelar":
        await query.edit_message_text("❌ Cancelado.")
        return ConversationHandler.END
    cat = query.data.replace("cat:", "")
    context.user_data['gasto']['categoria'] = cat
    await query.edit_message_text(f"Categoría: *{cat}*\n\n¿Cómo pagaste?", parse_mode="Markdown", reply_markup=keyboard_pago())
    return ESPERANDO_PAGO


async def gasto_pago_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "cancelar":
        await query.edit_message_text("❌ Cancelado.")
        return ConversationHandler.END
    context.user_data['gasto']['pago'] = query.data.replace("pago:", "")
    await confirmar_registro(update, context)
    return ConversationHandler.END


async def cmd_ingreso(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['gasto'] = {
        'tipo': 'ingreso', 'fecha': datetime.now().strftime("%Y-%m-%d"),
        'categoria': '💰 Ingreso', 'pago': 'Transferencia'
    }
    await update.message.reply_text("💰 *Nuevo ingreso*\n\n¿Cuánto recibiste?", parse_mode="Markdown")
    return ING_MONTO


async def ingreso_monto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    monto = detectar_monto(update.message.text)
    if not monto:
        await update.message.reply_text("Escribí solo el número, ej: `150000`", parse_mode="Markdown")
        return ING_MONTO
    context.user_data['gasto']['monto'] = monto
    await update.message.reply_text(f"Monto: *${monto:,.0f}*\n\n¿De qué fuente? (sueldo, freelance, etc.)", parse_mode="Markdown")
    return ING_DESC


async def ingreso_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['gasto']['desc'] = update.message.text
    await confirmar_registro(update, context)
    return ConversationHandler.END


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data

    if data == "confirm:si":
        g = context.user_data.get('gasto', {})
        guardar_registro(
            fecha  = g.get('fecha', datetime.now().strftime("%Y-%m-%d")),
            desc   = g.get('desc', ''),
            cat    = g.get('categoria', '📦 Otros'),
            monto  = float(g.get('monto', 0)),
            pago   = g.get('pago', 'Efectivo'),
            tipo   = g.get('tipo', 'gasto')
        )
        emoji = "💸" if g.get('tipo') == 'gasto' else "💰"
        await query.edit_message_text(
            f"{emoji} *Registrado*\n\n${float(g.get('monto',0)):,.0f} — {g.get('categoria')}\n_{str(g.get('desc',''))[:60]}_",
            parse_mode="Markdown"
        )

    elif data == "cancelar":
        await query.edit_message_text("❌ Cancelado.")

    elif data.startswith("cat:"):
        context.user_data['gasto']['categoria'] = data.replace("cat:", "")
        await query.edit_message_text(
            f"Categoría: *{data.replace('cat:','')}*\n\n¿Cómo pagaste?",
            parse_mode="Markdown", reply_markup=keyboard_pago()
        )

    elif data.startswith("pago:"):
        context.user_data['gasto']['pago'] = data.replace("pago:", "")
        await confirmar_registro(update, context)

    elif data == "menu:gasto":
        context.user_data['gasto'] = {'tipo':'gasto','fecha':datetime.now().strftime("%Y-%m-%d")}
        await query.edit_message_text("💸 *Nuevo gasto*\n\n¿Cuánto gastaste?", parse_mode="Markdown")

    elif data == "menu:ingreso":
        context.user_data['gasto'] = {'tipo':'ingreso','fecha':datetime.now().strftime("%Y-%m-%d"),'categoria':'💰 Ingreso','pago':'Transferencia'}
        await query.edit_message_text("💰 *Nuevo ingreso*\n\n¿Cuánto recibiste?", parse_mode="Markdown")

    elif data == "menu:resumen":
        hoy = datetime.now()
        total_g, total_i, por_cat, n = obtener_resumen_mes(hoy.year, hoy.month)
        balance = total_i - total_g
        lineas  = [f"  {cat}: *${v:,.0f}*" for cat,v in sorted(por_cat.items(), key=lambda x:-x[1])]
        texto   = (
            f"📊 *Resumen {hoy.strftime('%B %Y')}*\n\n"
            f"💰 Ingresos: *${total_i:,.0f}*\n"
            f"💸 Gastos: *${total_g:,.0f}* ({n} registros)\n"
            f"{'✅' if balance>=0 else '⚠️'} Balance: *${balance:,.0f}*"
        )
        if lineas:
            texto += "\n\n*Por categoría:*\n" + "\n".join(lineas)
        await query.edit_message_text(texto, parse_mode="Markdown")

    elif data == "menu:ultimos":
        hoy  = datetime.now()
        rows = obtener_registros_mes(hoy.year, hoy.month)[:5]
        if not rows:
            await query.edit_message_text("No hay registros este mes.")
            return
        lineas = [f"{'💸' if r[6]=='gasto' else '💰'} *{r[0]}* — {r[1][:25]} — *${r[3]:,.0f}* — {r[4]}" for r in rows]
        await query.edit_message_text("📋 *Últimos registros:*\n\n" + "\n".join(lineas), parse_mode="Markdown")

    elif data == "menu:ayuda":
        await query.edit_message_text(
            "❓ *Ejemplos:*\n\n"
            "`gasté 4500 en el super con débito`\n"
            "`uber 1200 efectivo`\n"
            "`netflix 3500`\n\n"
            "Comandos: /gasto /ingreso /resumen /ultimos",
            parse_mode="Markdown"
        )


async def cmd_resumen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    hoy = datetime.now()
    total_g, total_i, por_cat, n = obtener_resumen_mes(hoy.year, hoy.month)
    balance = total_i - total_g
    lineas  = [f"  {cat}: *${v:,.0f}*" for cat,v in sorted(por_cat.items(), key=lambda x:-x[1])]
    texto   = (
        f"📊 *Resumen {hoy.strftime('%B %Y')}*\n\n"
        f"💰 Ingresos: *${total_i:,.0f}*\n"
        f"💸 Gastos: *${total_g:,.0f}* ({n} registros)\n"
        f"{'✅' if balance>=0 else '⚠️'} Balance: *${balance:,.0f}*"
    )
    if lineas:
        texto += "\n\n*Por categoría:*\n" + "\n".join(lineas)
    await update.message.reply_text(texto, parse_mode="Markdown")


async def cmd_ultimos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    hoy  = datetime.now()
    rows = obtener_registros_mes(hoy.year, hoy.month)[:5]
    if not rows:
        await update.message.reply_text("No hay registros este mes.")
        return
    lineas = [f"{'💸' if r[6]=='gasto' else '💰'} {r[0]} — {r[1][:25]} — *${r[3]:,.0f}*" for r in rows]
    await update.message.reply_text("📋 *Últimos registros:*\n\n" + "\n".join(lineas), parse_mode="Markdown")


def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

    conv_gasto = ConversationHandler(
        entry_points=[CommandHandler("gasto", cmd_gasto)],
        states={
            ESPERANDO_MONTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, gasto_monto)],
            ESPERANDO_DESC:  [MessageHandler(filters.TEXT & ~filters.COMMAND, gasto_desc)],
            ESPERANDO_CAT:   [CallbackQueryHandler(gasto_cat_cb,  pattern="^(cat:|cancelar)")],
            ESPERANDO_PAGO:  [CallbackQueryHandler(gasto_pago_cb, pattern="^(pago:|cancelar)")],
        },
        fallbacks=[CommandHandler("cancelar", lambda u,c: ConversationHandler.END)]
    )

    conv_ingreso = ConversationHandler(
        entry_points=[CommandHandler("ingreso", cmd_ingreso)],
        states={
            ING_MONTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, ingreso_monto)],
            ING_DESC:  [MessageHandler(filters.TEXT & ~filters.COMMAND, ingreso_desc)],
        },
        fallbacks=[CommandHandler("cancelar", lambda u,c: ConversationHandler.END)]
    )

    app.add_handler(CommandHandler("start",   start))
    app.add_handler(CommandHandler("ayuda",   ayuda))
    app.add_handler(CommandHandler("menu",    menu))
    app.add_handler(CommandHandler("resumen", cmd_resumen))
    app.add_handler(CommandHandler("ultimos", cmd_ultimos))
    app.add_handler(conv_gasto)
    app.add_handler(conv_ingreso)
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_texto))

    print("Bot corriendo...")
    app.run_polling()


if __name__ == "__main__":

    main()




