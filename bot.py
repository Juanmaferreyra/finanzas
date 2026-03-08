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
EDIT_CAMPO, EDIT_VALOR, EDIT_CAT, EDIT_PAGO = range(10, 14)


# ── BASE DE DATOS ─────────────────────────────────────────────────────────
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
        "SELECT id,fecha,descripcion,categoria,monto,pago,notas,tipo FROM registros WHERE strftime('%Y',fecha)=? AND strftime('%m',fecha)=? ORDER BY fecha DESC, id DESC",
        (str(anio), str(mes).zfill(2))
    )
    rows = cur.fetchall()
    con.close()
    return rows

def obtener_resumen_mes(anio, mes):
    rows = obtener_registros_mes(anio, mes)
    gastos   = [r for r in rows if r[7] == 'gasto']
    ingresos = [r for r in rows if r[7] == 'ingreso']
    total_g  = sum(r[4] for r in gastos)
    total_i  = sum(r[4] for r in ingresos)
    por_cat  = {}
    for r in gastos:
        por_cat[r[3]] = por_cat.get(r[3], 0) + r[4]
    return total_g, total_i, por_cat, len(gastos)

def obtener_ultimo_registro():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT id,fecha,descripcion,categoria,monto,pago,notas,tipo FROM registros ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    con.close()
    return row

def borrar_registro_por_id(rid):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("DELETE FROM registros WHERE id=?", (rid,))
    con.commit()
    con.close()

def borrar_mes(anio, mes):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "DELETE FROM registros WHERE strftime('%Y',fecha)=? AND strftime('%m',fecha)=?",
        (str(anio), str(mes).zfill(2))
    )
    n = cur.rowcount
    con.commit()
    con.close()
    return n

def actualizar_registro(rid, campo, valor):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(f"UPDATE registros SET {campo}=? WHERE id=?", (valor, rid))
    con.commit()
    con.close()


# ── DETECCIÓN ─────────────────────────────────────────────────────────────
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


# ── KEYBOARDS ─────────────────────────────────────────────────────────────
def keyboard_categorias(prefix="cat"):
    botones = []
    fila = []
    for cat in CATEGORIAS:
        fila.append(InlineKeyboardButton(cat, callback_data=f"{prefix}:{cat}"))
        if len(fila) == 2:
            botones.append(fila)
            fila = []
    if fila:
        botones.append(fila)
    botones.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
    return InlineKeyboardMarkup(botones)

def keyboard_pago(prefix="pago"):
    botones = [[InlineKeyboardButton(p, callback_data=f"{prefix}:{p}")] for p in FORMAS_PAGO]
    botones.append([InlineKeyboardButton("❌ Cancelar", callback_data="cancelar")])
    return InlineKeyboardMarkup(botones)

def keyboard_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💸 Cargar gasto",      callback_data="menu:gasto"),
         InlineKeyboardButton("💰 Cargar ingreso",    callback_data="menu:ingreso")],
        [InlineKeyboardButton("📊 Resumen del mes",   callback_data="menu:resumen"),
         InlineKeyboardButton("📋 Listar registros",  callback_data="menu:listar")],
        [InlineKeyboardButton("↩️ Deshacer último",   callback_data="menu:deshacer"),
         InlineKeyboardButton("🗑️ Resetear mes",      callback_data="menu:resetmes")],
        [InlineKeyboardButton("❓ Ayuda",             callback_data="menu:ayuda")]
    ])

def keyboard_confirmar(accion):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirmar", callback_data=f"confirm:{accion}"),
         InlineKeyboardButton("❌ Cancelar",  callback_data="cancelar")]
    ])

def keyboard_editar():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💸 Monto",      callback_data="editcampo:monto"),
         InlineKeyboardButton("📝 Descripción",callback_data="editcampo:descripcion")],
        [InlineKeyboardButton("🏷️ Categoría",  callback_data="editcampo:categoria"),
         InlineKeyboardButton("💳 Pago",       callback_data="editcampo:pago")],
        [InlineKeyboardButton("📅 Fecha",      callback_data="editcampo:fecha"),
         InlineKeyboardButton("❌ Cancelar",   callback_data="cancelar")]
    ])


# ── HELPERS ───────────────────────────────────────────────────────────────
def formato_registro(r):
    emoji = "💸" if r[7] == 'gasto' else "💰"
    return f"{emoji} *{r[1]}* — {r[2][:30]} — *${r[4]:,.0f}* — {r[3]} — {r[5]}"

async def confirmar_registro(update, context):
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


# ── COMANDOS BÁSICOS ──────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💰 *fin.control bot*\n\n"
        "📝 *Texto libre:*\n`gasté 3500 en el super con débito`\n\n"
        "🔘 *Comandos:*\n"
        "/gasto — cargar gasto guiado\n"
        "/ingreso — cargar ingreso\n"
        "/resumen — resumen del mes\n"
        "/listar — ver todos los registros del mes\n"
        "/deshacer — borrar el último registro\n"
        "/editar — editar un registro\n"
        "/resetmes — borrar todo el mes\n"
        "/menu — menú con botones\n"
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


# ── TEXTO LIBRE ───────────────────────────────────────────────────────────
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


# ── GASTO GUIADO ──────────────────────────────────────────────────────────
async def cmd_gasto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['gasto'] = {'tipo':'gasto','fecha':datetime.now().strftime("%Y-%m-%d")}
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
        await update.message.reply_text(f"Categoría detectada: *{cat}*\n\n¿Cómo pagaste?", parse_mode="Markdown", reply_markup=keyboard_pago())
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
    context.user_data['gasto']['categoria'] = query.data.replace("cat:", "")
    await query.edit_message_text(f"Categoría: *{query.data.replace('cat:','')}*\n\n¿Cómo pagaste?", parse_mode="Markdown", reply_markup=keyboard_pago())
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


# ── INGRESO GUIADO ────────────────────────────────────────────────────────
async def cmd_ingreso(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['gasto'] = {'tipo':'ingreso','fecha':datetime.now().strftime("%Y-%m-%d"),'categoria':'💰 Ingreso','pago':'Transferencia'}
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


# ── DESHACER ──────────────────────────────────────────────────────────────
async def cmd_deshacer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    r = obtener_ultimo_registro()
    if not r:
        await update.message.reply_text("No hay registros para deshacer.")
        return
    context.user_data['borrar_id'] = r[0]
    emoji = "💸" if r[7] == 'gasto' else "💰"
    await update.message.reply_text(
        f"↩️ *¿Borrar el último registro?*\n\n"
        f"{emoji} *{r[1]}* — {r[2][:40]}\n"
        f"Categoría: {r[3]}\n"
        f"Monto: *${r[4]:,.0f}*\n"
        f"Pago: {r[5]}",
        parse_mode="Markdown",
        reply_markup=keyboard_confirmar("deshacer")
    )

# ── LISTAR ────────────────────────────────────────────────────────────────
async def cmd_listar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    hoy  = datetime.now()
    rows = obtener_registros_mes(hoy.year, hoy.month)
    if not rows:
        await update.message.reply_text("No hay registros este mes.")
        return
    context.user_data['registros_listados'] = {i+1: r[0] for i,r in enumerate(rows)}
    lineas = []
    for i, r in enumerate(rows):
        emoji = "💸" if r[7] == 'gasto' else "💰"
        lineas.append(f"`{i+1})` {emoji} *{r[1]}* — {r[2][:25]} — *${r[4]:,.0f}* — {r[3][:20]}")
    texto = f"📋 *Registros de {hoy.strftime('%B %Y')}:*\n\n" + "\n".join(lineas)
    texto += "\n\nUsá `/borrar N` para borrar el registro número N\nUsá `/editar N` para editar el registro número N"
    await update.message.reply_text(texto, parse_mode="Markdown")

# ── BORRAR N ──────────────────────────────────────────────────────────────
async def cmd_borrar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usá `/borrar N` donde N es el número del registro.\nPrimero usá /listar para ver los números.", parse_mode="Markdown")
        return
    n = int(args[0])
    registros = context.user_data.get('registros_listados', {})
    if n not in registros:
        await update.message.reply_text("Número inválido. Usá /listar para ver los registros del mes.")
        return
    rid = registros[n]
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT id,fecha,descripcion,categoria,monto,pago,notas,tipo FROM registros WHERE id=?", (rid,))
    r = cur.fetchone()
    con.close()
    if not r:
        await update.message.reply_text("Registro no encontrado.")
        return
    context.user_data['borrar_id'] = rid
    emoji = "💸" if r[7] == 'gasto' else "💰"
    await update.message.reply_text(
        f"🗑️ *¿Borrar este registro?*\n\n"
        f"{emoji} *{r[1]}* — {r[2][:40]}\n"
        f"Categoría: {r[3]}\n"
        f"Monto: *${r[4]:,.0f}*\n"
        f"Pago: {r[5]}",
        parse_mode="Markdown",
        reply_markup=keyboard_confirmar("borrar")
    )

# ── RESETEAR MES ──────────────────────────────────────────────────────────
async def cmd_resetmes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    hoy = datetime.now()
    rows = obtener_registros_mes(hoy.year, hoy.month)
    await update.message.reply_text(
        f"🗑️ *¿Borrar TODOS los registros de {hoy.strftime('%B %Y')}?*\n\n"
        f"Hay *{len(rows)} registros* que se van a eliminar.\n"
        f"Esta acción _no se puede deshacer_.",
        parse_mode="Markdown",
        reply_markup=keyboard_confirmar("resetmes")
    )

# ── EDITAR ────────────────────────────────────────────────────────────────
async def cmd_editar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usá `/editar N` donde N es el número del registro.\nPrimero usá /listar para ver los números.", parse_mode="Markdown")
        return
    n = int(args[0])
    registros = context.user_data.get('registros_listados', {})
    if n not in registros:
        await update.message.reply_text("Número inválido. Usá /listar primero.")
        return
    rid = registros[n]
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT id,fecha,descripcion,categoria,monto,pago,notas,tipo FROM registros WHERE id=?", (rid,))
    r = cur.fetchone()
    con.close()
    if not r:
        await update.message.reply_text("Registro no encontrado.")
        return
    context.user_data['editar_id'] = rid
    context.user_data['editar_registro'] = r
    emoji = "💸" if r[7] == 'gasto' else "💰"
    await update.message.reply_text(
        f"✏️ *Editando registro:*\n\n"
        f"{emoji} *{r[1]}* — {r[2][:40]}\n"
        f"Categoría: {r[3]}\n"
        f"Monto: *${r[4]:,.0f}*\n"
        f"Pago: {r[5]}\n\n"
        f"¿Qué campo querés cambiar?",
        parse_mode="Markdown",
        reply_markup=keyboard_editar()
    )
    return EDIT_CAMPO

async def editar_campo_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "cancelar":
        await query.edit_message_text("❌ Cancelado.")
        return ConversationHandler.END
    campo = query.data.replace("editcampo:", "")
    context.user_data['editar_campo'] = campo
    if campo == "categoria":
        await query.edit_message_text("¿Nueva categoría?", reply_markup=keyboard_categorias("editcat"))
        return EDIT_CAT
    elif campo == "pago":
        await query.edit_message_text("¿Nueva forma de pago?", reply_markup=keyboard_pago("editpago"))
        return EDIT_PAGO
    elif campo == "monto":
        await query.edit_message_text("¿Nuevo monto? (solo el número, ej: `4500`)", parse_mode="Markdown")
        return EDIT_VALOR
    elif campo == "descripcion":
        await query.edit_message_text("¿Nueva descripción?")
        return EDIT_VALOR
    elif campo == "fecha":
        await query.edit_message_text("¿Nueva fecha? (formato: `2026-03-15`)", parse_mode="Markdown")
        return EDIT_VALOR

async def editar_valor_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    campo = context.user_data.get('editar_campo')
    rid   = context.user_data.get('editar_id')
    valor = update.message.text.strip()
    if campo == "monto":
        valor = detectar_monto(valor)
        if not valor:
            await update.message.reply_text("No entendí el monto. Escribí solo el número.")
            return EDIT_VALOR
    actualizar_registro(rid, campo, valor)
    await update.message.reply_text(f"✅ *{campo.capitalize()}* actualizado correctamente.", parse_mode="Markdown")
    return ConversationHandler.END

async def editar_cat_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "cancelar":
        await query.edit_message_text("❌ Cancelado.")
        return ConversationHandler.END
    cat = query.data.replace("editcat:", "")
    rid = context.user_data.get('editar_id')
    actualizar_registro(rid, "categoria", cat)
    await query.edit_message_text(f"✅ Categoría actualizada a *{cat}*", parse_mode="Markdown")
    return ConversationHandler.END

async def editar_pago_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "cancelar":
        await query.edit_message_text("❌ Cancelado.")
        return ConversationHandler.END
    pago = query.data.replace("editpago:", "")
    rid  = context.user_data.get('editar_id')
    actualizar_registro(rid, "pago", pago)
    await query.edit_message_text(f"✅ Forma de pago actualizada a *{pago}*", parse_mode="Markdown")
    return ConversationHandler.END


# ── RESUMEN Y ÚLTIMOS ─────────────────────────────────────────────────────
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
    lineas = [f"{'💸' if r[7]=='gasto' else '💰'} *{r[1]}* — {r[2][:25]} — *${r[4]:,.0f}* — {r[3][:20]}" for r in rows]
    await update.message.reply_text("📋 *Últimos registros:*\n\n" + "\n".join(lineas), parse_mode="Markdown")


# ── CALLBACK GENERAL ──────────────────────────────────────────────────────
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
            f"{emoji} *Registrado*\n\n"
            f"📅 {g.get('fecha')} — {str(g.get('desc',''))[:50]}\n"
            f"🏷️ {g.get('categoria')} — *${float(g.get('monto',0)):,.0f}* — {g.get('pago')}",
            parse_mode="Markdown"
        )

    elif data == "confirm:deshacer":
        rid = context.user_data.get('borrar_id')
        if rid:
            borrar_registro_por_id(rid)
            await query.edit_message_text("↩️ Registro eliminado correctamente.")
        else:
            await query.edit_message_text("No se encontró el registro.")

    elif data == "confirm:borrar":
        rid = context.user_data.get('borrar_id')
        if rid:
            borrar_registro_por_id(rid)
            await query.edit_message_text("🗑️ Registro eliminado correctamente.")
        else:
            await query.edit_message_text("No se encontró el registro.")

    elif data == "confirm:resetmes":
        hoy = datetime.now()
        n   = borrar_mes(hoy.year, hoy.month)
        await query.edit_message_text(f"🗑️ Se eliminaron *{n} registros* de {hoy.strftime('%B %Y')}.", parse_mode="Markdown")

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

    elif data == "menu:listar":
        hoy  = datetime.now()
        rows = obtener_registros_mes(hoy.year, hoy.month)
        if not rows:
            await query.edit_message_text("No hay registros este mes.")
            return
        context.user_data['registros_listados'] = {i+1: r[0] for i,r in enumerate(rows)}
        lineas = []
        for i, r in enumerate(rows):
            emoji = "💸" if r[7] == 'gasto' else "💰"
            lineas.append(f"`{i+1})` {emoji} *{r[1]}* — {r[2][:20]} — *${r[4]:,.0f}*")
        texto = f"📋 *{hoy.strftime('%B %Y')}:*\n\n" + "\n".join(lineas)
        texto += "\n\n`/borrar N` — `/editar N`"
        await query.edit_message_text(texto, parse_mode="Markdown")

    elif data == "menu:deshacer":
        r = obtener_ultimo_registro()
        if not r:
            await query.edit_message_text("No hay registros para deshacer.")
            return
        context.user_data['borrar_id'] = r[0]
        emoji = "💸" if r[7] == 'gasto' else "💰"
        await query.edit_message_text(
            f"↩️ *¿Borrar el último registro?*\n\n"
            f"{emoji} *{r[1]}* — {r[2][:40]}\n"
            f"Monto: *${r[4]:,.0f}* — {r[3]}",
            parse_mode="Markdown",
            reply_markup=keyboard_confirmar("deshacer")
        )

    elif data == "menu:resetmes":
        hoy  = datetime.now()
        rows = obtener_registros_mes(hoy.year, hoy.month)
        await query.edit_message_text(
            f"🗑️ *¿Borrar TODOS los registros de {hoy.strftime('%B %Y')}?*\n\n"
            f"Hay *{len(rows)} registros* que se van a eliminar.\n"
            f"Esta acción _no se puede deshacer_.",
            parse_mode="Markdown",
            reply_markup=keyboard_confirmar("resetmes")
        )

    elif data == "menu:ayuda":
        await query.edit_message_text(
            "❓ *Ejemplos:*\n\n"
            "`gasté 4500 en el super con débito`\n"
            "`uber 1200 efectivo`\n"
            "`netflix 3500`\n\n"
            "Comandos: /gasto /ingreso /resumen /listar /borrar N /editar N /deshacer /resetmes",
            parse_mode="Markdown"
        )


# ── MAIN ──────────────────────────────────────────────────────────────────
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

    conv_editar = ConversationHandler(
        entry_points=[CommandHandler("editar", cmd_editar)],
        states={
            EDIT_CAMPO: [CallbackQueryHandler(editar_campo_cb, pattern="^(editcampo:|cancelar)")],
            EDIT_VALOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, editar_valor_texto)],
            EDIT_CAT:   [CallbackQueryHandler(editar_cat_cb,   pattern="^(editcat:|cancelar)")],
            EDIT_PAGO:  [CallbackQueryHandler(editar_pago_cb,  pattern="^(editpago:|cancelar)")],
        },
        fallbacks=[CommandHandler("cancelar", lambda u,c: ConversationHandler.END)]
    )

    app.add_handler(CommandHandler("start",    start))
    app.add_handler(CommandHandler("ayuda",    ayuda))
    app.add_handler(CommandHandler("menu",     menu))
    app.add_handler(CommandHandler("resumen",  cmd_resumen))
    app.add_handler(CommandHandler("ultimos",  cmd_ultimos))
    app.add_handler(CommandHandler("listar",   cmd_listar))
    app.add_handler(CommandHandler("borrar",   cmd_borrar))
    app.add_handler(CommandHandler("deshacer", cmd_deshacer))
    app.add_handler(CommandHandler("resetmes", cmd_resetmes))
    app.add_handler(conv_gasto)
    app.add_handler(conv_ingreso)
    app.add_handler(conv_editar)
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_texto))

    print("Bot corriendo...")
    app.run_polling()

if __name__ == "__main__":
    main()



