import os
import json
import sqlite3
import re
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, filters, ContextTypes
)

# ── CONFIG ────────────────────────────────────────────────────────────────
TOKEN = os.environ.get("BOT_TOKEN", "TU_TOKEN_AQUI")
DB_PATH = "finanzas.db"

# ── CATEGORÍAS Y PALABRAS CLAVE ───────────────────────────────────────────
CATEGORIAS = [
    "🏠 Vivienda / Alquiler",
    "🛒 Comida / Supermercado",
    "🚗 Transporte",
    "🏥 Salud",
    "👕 Ropa",
    "💡 Servicios (luz, internet, etc.)",
    "📈 Inversiones",
    "📺 Suscripciones",
    "🎉 Entretenimiento",
    "🔧 Imprevistos / Varios",
    "💳 Deuda",
    "🎓 Universidad",
    "🍻 Salidas",
    "📱 Celular",
    "📦 Otros"
]

PALABRAS_CLAVE = {
    "🏠 Vivienda / Alquiler":           ["alquiler", "alquier", "expensas", "cuota", "inmobiliaria", "vivienda"],
    "🛒 Comida / Supermercado":          ["super", "supermercado", "carrefour", "dia", "coto", "jumbo", "verdura", "almacen", "almacén", "comida", "mercado", "feria", "kiosco", "kiosko"],
    "🚗 Transporte":                     ["uber", "cabify", "taxi", "colectivo", "subte", "tren", "nafta", "combustible", "peaje", "remis", "sube"],
    "🏥 Salud":                          ["farmacia", "medico", "médico", "doctor", "hospital", "clinica", "clínica", "medicamento", "dentista", "obra social", "prepaga"],
    "👕 Ropa":                           ["ropa", "zapatillas", "zapatos", "camisa", "pantalon", "pantalón", "vestido", "remera", "indumentaria"],
    "💡 Servicios (luz, internet, etc.)":["luz", "gas", "agua", "internet", "wifi", "telefono", "teléfono", "servicio", "edenor", "edesur", "metrogas"],
    "📈 Inversiones":                    ["inversion", "inversión", "plazo fijo", "cripto", "acciones", "fondo", "cedear"],
    "📺 Suscripciones":                  ["netflix", "spotify", "disney", "amazon", "hbo", "youtube", "suscripcion", "suscripción", "prime"],
    "🎉 Entretenimiento":                ["cine", "teatro", "show", "recital", "evento", "juego", "steam", "playstation"],
    "🔧 Imprevistos / Varios":           ["reparacion", "reparación", "plomero", "electricista", "arreglo", "imprevisto"],
    "💳 Deuda":                          ["deuda", "prestamo", "préstamo", "cuota", "tarjeta", "credito", "crédito"],
    "🎓 Universidad":                    ["universidad", "facultad", "curso", "libro", "apunte", "fotocopias", "inscripcion", "inscripción"],
    "🍻 Salidas":                        ["bar", "boliche", "restaurante", "resto", "cerveza", "pizza", "sushi", "cafe", "café", "salida"],
    "📱 Celular":                        ["celular", "movil", "móvil", "recarga", "plan celular"],
    "📦 Otros":                          ["otro", "varios", "miscelaneo", "miscelánea"]
}

FORMAS_PAGO = ["Débito", "Crédito", "Efectivo", "Transferencia", "Billetera virtual"]
PAGO_KEYWORDS = {
    "Débito":           ["debito", "débito", "debi"],
    "Crédito":          ["credito", "crédito", "credi", "visa", "mastercard"],
    "Efectivo":         ["efectivo", "cash", "plata"],
    "Transferencia":    ["transferencia", "transfer", "transf"],
    "Billetera virtual":["mercadopago", "mp", "uala", "ualá", "modo", "billetera"]
}

# Estados del ConversationHandler
(ESPERANDO_MONTO, ESPERANDO_DESC, ESPERANDO_CAT, ESPERANDO_PAGO,
 MENU_PRINCIPAL, ING_MONTO, ING_DESC) = range(7)

# ── BASE DE DATOS ─────────────────────────────────────────────────────────
def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS registros (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT,
            descripcion TEXT,
            categoria TEXT,
            monto REAL,
            pago TEXT,
            notas TEXT,
            tipo TEXT DEFAULT 'gasto',
            created_at TEXT
        )
    """)
    con.commit()
    con.close()

def guardar_registro(fecha, desc, cat, monto, pago, notas="", tipo="gasto"):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "INSERT INTO registros (fecha, descripcion, categoria, monto, pago, notas, tipo, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (fecha, desc, cat, monto, pago, notas, tipo, datetime.now().isoformat())
    )
    con.commit()
    con.close()

def obtener_registros_mes(anio, mes):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "SELECT fecha, descripcion, categoria, monto, pago, notas, tipo FROM registros WHERE strftime('%Y', fecha)=? AND strftime('%m', fecha)=? ORDER BY fecha DESC",
        (str(anio), str(mes).zfill(2))
    )
    rows = cur.fetchall()
    con.close()
    return rows

def obtener_resumen_mes(anio, mes):
    rows = obtener_registros_mes(anio, mes)
    gastos = [r for r in rows if r[6] == 'gasto']
    ingresos = [r for r in rows if r[6] == 'ingreso']
    total_g = sum(r[3] for r in gastos)
    total_i = sum(r[3] for r in ingresos)
    por_cat = {}
    for r in gastos:
        por_cat[r[2]] = por_cat.get(r[2], 0) + r[3]
    return total_g, total_i, por_cat, len(gastos)

# ── DETECCIÓN AUTOMÁTICA ──────────────────────────────────────────────────
def detectar_monto(texto):
    """Extrae el monto del texto. Ej: '3500', '3.500', '3,500'"""
    texto = texto.lower().replace("$", "").replace(".", "").replace(",", "")
    numeros = re.findall(r'\d+', texto)
    if numeros:
        # Toma el número más grande que parezca un monto
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
    return "Débito"  # default

def parsear_texto_libre(texto):
    """Intenta extraer todos los datos de un mensaje de texto libre."""
    monto = detectar_monto(texto)
    categoria = detectar_categoria(texto)
    pago = detectar_pago(texto)
    return monto, categoria, pago

# ── KEYBOARDS ─────────────────────────────────────────────────────────────
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
        [InlineKeyboardButton("💸 Cargar gasto", callback_data="menu:gasto"),
         InlineKeyboardButton("💰 Cargar ingreso", callback_data="menu:ingreso")],
        [InlineKeyboardButton("📊 Resumen del mes", callback_data="menu:resumen"),
         InlineKeyboardButton("📋 Últimos registros", callback_data="menu:ultimos")],
        [InlineKeyboardButton("❓ Ayuda", callback_data="menu:ayuda")]
    ])

# ── HANDLERS ──────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💰 *fin.control bot*\n\n"
        "Podés cargar gastos de dos formas:\n\n"
        "📝 *Texto libre:* escribí directamente\n"
        "`gasté 3500 en el super con débito`\n\n"
        "🔘 *Menú guiado:* usá /gasto o /ingreso\n\n"
        "Otros comandos:\n"
        "/resumen — resumen del mes\n"
        "/ultimos — últimos 5 registros\n"
        "/menu — menú principal\n"
        "/ayuda — ejemplos de uso",
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
        "🔘 *Menú guiado:* /gasto o /ingreso\n\n"
        "📊 *Consultas:*\n"
        "/resumen — gastos e ingresos del mes\n"
        "/ultimos — últimos 5 movimientos",
        parse_mode="Markdown"
    )

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¿Qué querés hacer?", reply_markup=keyboard_menu())

# ── TEXTO LIBRE ───────────────────────────────────────────────────────────
async def manejar_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text
    monto, categoria, pago = parsear_texto_libre(texto)

    if not monto:
        await update.message.reply_text(
            "No encontré el monto 🤔\n"
            "Probá: `gasté 3500 en el super` o usá /gasto para el menú guiado.",
            parse_mode="Markdown"
        )
        return

    context.user_data['gasto'] = {
        'monto': monto,
        'desc': texto,
        'pago': pago,
        'fecha': datetime.now().strftime("%Y-%m-%d"),
        'tipo': 'gasto'
    }

    if categoria:
        # Todo detectado, pedir confirmación
        context.user_data['gasto']['categoria'] = categoria
        await confirmar_registro(update, context)
    else:
        # No se detectó categoría, mostrar botones
        await update.message.reply_text(
            f"💸 Monto: *${monto:,.0f}*\n"
            f"💳 Pago: {pago}\n\n"
            "No reconocí la categoría. ¿Cuál es?",
            parse_mode="Markdown",
            reply_markup=keyboard_categorias()
        )
        return ConversationHandler.END

async def confirmar_registro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    g = context.user_data.get('gasto', {})
    msg = (
        f"✅ *¿Confirmar registro?*\n\n"
        f"📅 Fecha: {g.get('fecha')}\n"
        f"📝 Detalle: {g.get('desc', '')[:50]}\n"
        f"🏷️ Categoría: {g.get('categoria')}\n"
        f"💸 Monto: *${float(g.get('monto', 0)):,.0f}*\n"
        f"💳 Pago: {g.get('pago')}"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirmar", callback_data="confirm:si"),
         InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")]
    ])
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, parse_mode="Markdown", reply_markup=keyboard)
    else:
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=keyboard)

# ── MENÚ GUIADO — GASTO ───────────────────────────────────────────────────
async def cmd_gasto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['gasto'] = {'tipo': 'gasto', 'fecha': datetime.now().strftime("%Y-%m-%d")}
    await update.message.reply_text("💸 *Nuevo gasto*\n\n¿Cuánto gastaste? (solo el número)", parse_mode="Markdown")
    return ESPERANDO_MONTO

async def gasto_monto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    monto = detectar_monto(update.message.text)
    if not monto:
        await update.message.reply_text("No entendí el monto. Escribí solo el número, ej: `3500`", parse_mode="Markdown")
        return ESPERANDO_MONTO
    context.user_data['gasto']['monto'] = monto
    await update.message.reply_text(f"Monto: *${monto:,.0f}*\n\n¿En qué lo gastaste? (descripción breve)", parse_mode="Markdown")
    return ESPERANDO_DESC

async def gasto_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    desc = update.message.text
    context.user_data['gasto']['desc'] = desc
    cat_detectada = detectar_categoria(desc)
    if cat_detectada:
        context.user_data['gasto']['categoria'] = cat_detectada
        await update.message.reply_text(
            f"Categoría detectada: *{cat_detectada}*\n\n¿Cómo pagaste?",
            parse_mode="Markdown",
            reply_markup=keyboard_pago()
        )
        return ESPERANDO_PAGO
    else:
        await update.message.reply_text("¿En qué categoría entra?", reply_markup=keyboard_categorias())
        return ESPERANDO_CAT

async def gasto_cat_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "cancelar":
        await query.edit_message_text("❌ Cancelado.")
        return ConversationHandler.END
    cat = query.data.replace("cat:", "")
    context.user_data['gasto']['categoria'] = cat
    await query.edit_message_text(f"Categoría: *{cat}*\n\n¿Cómo pagaste?", parse_mode="Markdown", reply_markup=keyboard_pago())
    return ESPERANDO_PAGO

async def gasto_pago_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "cancelar":
        await query.edit_message_text("❌ Cancelado.")
        return ConversationHandler.END
    pago = query.data.replace("pago:", "")
    context.user_data['gasto']['pago'] = pago
    await confirmar_registro(update, context)
    return ConversationHandler.END

# ── MENÚ GUIADO — INGRESO ─────────────────────────────────────────────────
async def cmd_ingreso(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['gasto'] = {'tipo': 'ingreso', 'fecha': datetime.now().strftime("%Y-%m-%d"), 'categoria': '💰 Ingreso', 'pago': 'Transferencia'}
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

# ── CALLBACK CONFIRMACIÓN Y MENÚ ─────────────────────────────────────────
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "confirm:si":
        g = context.user_data.get('gasto', {})
        guardar_registro(
            fecha=g.get('fecha', datetime.now().strftime("%Y-%m-%d")),
            desc=g.get('desc', ''),
            cat=g.get('categoria', '📦 Otros'),
            monto=float(g.get('monto', 0)),
            pago=g.get('pago', 'Efectivo'),
            tipo=g.get('tipo', 'gasto')
        )
        tipo_emoji = "💸" if g.get('tipo') == 'gasto' else "💰"
        await query.edit_message_text(
            f"{tipo_emoji} *¡Registrado!*\n\n"
            f"${float(g.get('monto', 0)):,.0f} — {g.get('categoria')}\n"
            f"_{g.get('desc', '')[:60]}_",
            parse_mode="Markdown"
        )

    elif data == "cancelar":
        await query.edit_message_text("❌ Cancelado.")

    elif data == "menu:gasto":
        context.user_data['gasto'] = {'tipo': 'gasto', 'fecha': datetime.now().strftime("%Y-%m-%d")}
        await query.edit_message_text("💸 *Nuevo gasto*\n\n¿Cuánto gastaste?", parse_mode="Markdown")
        return ESPERANDO_MONTO

    elif data == "menu:ingreso":
        context.user_data['gasto'] = {'tipo': 'ingreso', 'fecha': datetime.now().strftime("%Y-%m-%d"), 'categoria': '💰 Ingreso', 'pago': 'Transferencia'}
        await query.edit_message_text("💰 *Nuevo ingreso*\n\n¿Cuánto recibiste?", parse_mode="Markdown")
        return ING_MONTO

    elif data == "menu:resumen":
        hoy = datetime.now()
        total_g, total_i, por_cat, n = obtener_resumen_mes(hoy.year, hoy.month)
        lineas = [f"  {cat}: *${v:,.0f}*" for cat, v in sorted(por_cat.items(), key=lambda x: -x[1])]
        balance = total_i - total_g
        bal_emoji = "✅" if balance >= 0 else "⚠️"
        texto = (
            f"📊 *Resumen {hoy.strftime('%B %Y')}*\n\n"
            f"💰 Ingresos: *${total_i:,.0f}*\n"
            f"💸 Gastos: *${total_g:,.0f}* ({n} registros)\n"
            f"{bal_emoji} Balance: *${balance:,.0f}*\n\n"
        )
        if lineas:
            texto += "*Por categoría:*\n" + "\n".join(lineas)
        await query.edit_message_text(texto, parse_mode="Markdown")

    elif data == "menu:ultimos":
        hoy = datetime.now()
        rows = obtener_registros_mes(hoy.year, hoy.month)[:5]
        if not rows:
            await query.edit_message_text("No hay registros este mes.")
            return
        lineas = []
        for r in rows:
            emoji = "💸" if r[6] == 'gasto' else "💰"
            lineas.append(f"{emoji} {r[0]} — {r[1][:25]} — *${r[3]:,.0f}*")
        await query.edit_message_text("📋 *Últimos registros:*\n\n" + "\n".join(lineas), parse_mode="Markdown")

    elif data == "menu:ayuda":
        await query.edit_message_text(
            "❓ *Ejemplos de texto libre:*\n\n"
            "`gasté 4500 en el super con débito`\n"
            "`uber 1200 efectivo`\n"
            "`netflix 3500`\n"
            "`pagué 80000 de alquiler con transferencia`\n\n"
            "🔘 Comandos: /gasto /ingreso /resumen /ultimos",
            parse_mode="Markdown"
        )

    elif data.startswith("cat:"):
        cat = data.replace("cat:", "")
        context.user_data['gasto']['categoria'] = cat
        await query.edit_message_text(
            f"Categoría: *{cat}*\n\n¿Cómo pagaste?",
            parse_mode="Markdown",
            reply_markup=keyboard_pago()
        )

    elif data.startswith("pago:"):
        pago = data.replace("pago:", "")
        context.user_data['gasto']['pago'] = pago
        await confirmar_registro(update, context)

# ── RESUMEN Y ÚLTIMOS ─────────────────────────────────────────────────────
async def cmd_resumen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    hoy = datetime.now()
    total_g, total_i, por_cat, n = obtener_resumen_mes(hoy.year, hoy.month)
    lineas = [f"  {cat}: *${v:,.0f}*" for cat, v in sorted(por_cat.items(), key=lambda x: -x[1])]
    balance = total_i - total_g
    bal_emoji = "✅" if balance >= 0 else "⚠️"
    texto = (
        f"📊 *Resumen {hoy.strftime('%B %Y')}*\n\n"
        f"💰 Ingresos: *${total_i:,.0f}*\n"
        f"💸 Gastos: *${total_g:,.0f}* ({n} registros)\n"
        f"{bal_emoji} Balance: *${balance:,.0f}*\n\n"
    )
    if lineas:
        texto += "*Por categoría:*\n" + "\n".join(lineas)
    await update.message.reply_text(texto, parse_mode="Markdown")

async def cmd_ultimos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    hoy = datetime.now()
    rows = obtener_registros_mes(hoy.year, hoy.month)[:5]
    if not rows:
        await update.message.reply_text("No hay registros este mes.")
        return
    lineas = []
    for r in rows:
        emoji = "💸" if r[6] == 'gasto' else "💰"
        lineas.append(f"{emoji} {r[0]} — {r[1][:25]} — *${r[3]:,.0f}*")
    await update.message.reply_text("📋 *Últimos registros:*\n\n" + "\n".join(lineas), parse_mode="Markdown")

# ── MAIN ──────────────────────────────────────────────────────────────────
def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

    # ConversationHandler para /gasto guiado
    conv_gasto = ConversationHandler(
        entry_points=[CommandHandler("gasto", cmd_gasto)],
        states={
            ESPERANDO_MONTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, gasto_monto)],
            ESPERANDO_DESC:  [MessageHandler(filters.TEXT & ~filters.COMMAND, gasto_desc)],
            ESPERANDO_CAT:   [CallbackQueryHandler(gasto_cat_callback, pattern="^(cat:|cancelar)")],
            ESPERANDO_PAGO:  [CallbackQueryHandler(gasto_pago_callback, pattern="^(pago:|cancelar)")],
        },
        fallbacks=[CommandHandler("cancelar", lambda u, c: ConversationHandler.END)]
    )

    # ConversationHandler para /ingreso guiado
    conv_ingreso = ConversationHandler(
        entry_points=[CommandHandler("ingreso", cmd_ingreso)],
        states={
            ING_MONTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, ingreso_monto)],
            ING_DESC:  [MessageHandler(filters.TEXT & ~filters.COMMAND, ingreso_desc)],
        },
        fallbacks=[CommandHandler("cancelar", lambda u, c: ConversationHandler.END)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ayuda", ayuda))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("resumen", cmd_resumen))
    app.add_handler(CommandHandler("ultimos", cmd_ultimos))
    app.add_handler(conv_gasto)
    app.add_handler(conv_ingreso)
    app.add_handler(CallbackQueryHandler(callback_handler))
    # Texto libre — va al final para no interferir con conversations
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_texto))

    print("Bot corriendo...")
    app.run_polling()

if __name__ == "__main__":
    main()
```

---

## 📁 ARCHIVO 5 — `requirements.txt` (para Railway)
```
python-telegram-bot==20.7