"""
bot_whatsapp.py
Paso 3b del bot de farmacias de turno de Tucuman (version de PRUEBA, corre en tu PC).

Recibe los mensajes de WhatsApp (webhook de Meta) y responde:
  - con la ubicacion que manda el usuario  -> las 3 farmacias de turno mas cercanas
  - con el nombre de una localidad          -> las farmacias de turno de esa localidad
  - "emergencias"                           -> telefonos de emergencia
  - cualquier otra cosa                     -> menu con botones

Ademas actualiza solo las farmacias de turno todos los dias a las 8:05.

Requisitos (en la misma carpeta):
  - farmacias_turno.py y farmacias_cercanas.py
  - config_bot.txt con tus datos (este script lo crea la primera vez)

Uso:
    python bot_whatsapp.py
Despues hay que abrir el "tunel" con cloudflared para que Meta pueda llegar a tu PC
(ver las instrucciones en el chat).

No necesita instalar nada: usa solo librerias que ya vienen con Python.
"""

import hashlib
import hmac
import json
import os
import re
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import farmacias_cercanas as fc
import farmacias_turno as ft

CARPETA = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(CARPETA, "config_bot.txt")
PUERTO = 8000
API = "https://graph.facebook.com/v25.0"

PLANTILLA_CONFIG = """# Configuracion del bot. NO compartas este archivo con nadie.
# Pega los datos despues del signo =, sin comillas ni espacios.

# Token de acceso (Meta > WhatsApp > Configuracion de la API > Token de acceso)
WHATSAPP_TOKEN=

# Phone Number ID del numero de prueba (Meta > Configuracion de la API)
PHONE_NUMBER_ID=

# Una palabra secreta que inventas vos. La misma se pone en Meta al configurar el webhook.
VERIFY_TOKEN=farmacias-tucuman-2026

# Opcional (recomendado): App Secret (Meta > Configuracion de la app > Basica > Clave secreta)
# Sirve para comprobar que los mensajes vienen de verdad de Meta.
APP_SECRET=
"""

EMERGENCIAS = (
    "📞 *Teléfonos de emergencia*\n\n"
    "🚑 *107* — Emergencias médicas\n"
    "🚓 *911* — Policía\n"
    "🚒 *100* — Bomberos\n"
    "⚠️ *103* — Defensa Civil\n"
    "🧒 *102* — Ayuda al niño\n\n"
    "Si es una urgencia, llamá directamente. Este bot no reemplaza a un médico."
)

PALABRAS_SALUD = ("fiebre", "dolor", "que tomo", "qué tomo", "dosis", "pastilla", "sintoma", "síntoma",
                  "me duele", "receta", "remedio para", "medicamento para")


# ---------------------------------------------------------------- configuracion

def leer_config():
    if not os.path.exists(CONFIG):
        with open(CONFIG, "w", encoding="utf-8") as f:
            f.write(PLANTILLA_CONFIG)
        print("Cree el archivo config_bot.txt. Completalo con tus datos y volve a correr el bot.")
        return None
    datos = {}
    with open(CONFIG, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if linea and not linea.startswith("#") and "=" in linea:
                k, v = linea.split("=", 1)
                datos[k.strip()] = v.strip()
    faltan = [k for k in ("WHATSAPP_TOKEN", "PHONE_NUMBER_ID", "VERIFY_TOKEN") if not datos.get(k)]
    if faltan:
        print(f"Faltan datos en config_bot.txt: {', '.join(faltan)}")
        return None
    return datos


CFG = {}


# ---------------------------------------------------------------- enviar mensajes

def llamar_api(cuerpo):
    req = urllib.request.Request(
        f"{API}/{CFG['PHONE_NUMBER_ID']}/messages",
        data=json.dumps(cuerpo).encode("utf-8"),
        headers={"Authorization": f"Bearer {CFG['WHATSAPP_TOKEN']}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return True, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            detalle = json.load(e)
        except Exception:
            detalle = {"error": {"message": str(e)}}
        return False, detalle


formato_que_funciona = {}   # numero que llega de WhatsApp -> formato con el que se pudo responder


def variantes_argentina(numero):
    """WhatsApp manda los celulares argentinos como 549 + area + numero (ej: 5493815755909),
    pero la lista de prueba de Meta los guarda con el 15 (ej: 54 381 15 5755909).
    Como el codigo de area puede tener 2, 3 o 4 cifras, se prueban las combinaciones."""
    if not numero.startswith("549"):
        return []
    resto = numero[3:]
    opciones = [f"54{resto[:largo]}15{resto[largo:]}" for largo in (3, 2, 4)]
    opciones.append("54" + resto)
    return opciones


def enviar(numero, cuerpo):
    """Envia un mensaje. Con celulares argentinos prueba los distintos formatos del numero."""
    destino = formato_que_funciona.get(numero, numero)
    cuerpo = {"messaging_product": "whatsapp", "to": destino, **cuerpo}
    ok, resp = llamar_api(cuerpo)
    if ok:
        return True
    codigo = resp.get("error", {}).get("code")
    if codigo == 131030 and destino == numero:   # "el numero no esta en la lista permitida"
        for otro in variantes_argentina(numero):
            ok, resp2 = llamar_api({**cuerpo, "to": otro})
            if ok:
                formato_que_funciona[numero] = otro
                print(f"  (respondiendo a {numero} con el formato {otro})")
                return True
            resp = resp2
    print(f"  ! Error enviando a {numero}: {resp.get('error', {}).get('message', resp)}")
    if codigo == 190:
        print("  ! El token vencio. Genera uno nuevo en Meta y pegalo en config_bot.txt.")
    return False


def enviar_texto(numero, texto):
    return enviar(numero, {"type": "text", "text": {"body": texto, "preview_url": False}})


def enviar_menu(numero, saludo=True):
    texto = ("👋 Hola, soy el bot de *farmacias de turno de Tucumán*.\n\n" if saludo else "") + \
            "¿Qué necesitás?\n\nTambién podés escribir tu localidad (ej: *Yerba Buena*) " \
            "o mandarme tu ubicación 📍."
    ok = enviar(numero, {
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": texto},
            "footer": {"text": "Datos: Colegio de Farmacéuticos de Tucumán"},
            "action": {"buttons": [
                {"type": "reply", "reply": {"id": "cercana", "title": "📍 Farmacia cercana"}},
                {"type": "reply", "reply": {"id": "localidad", "title": "🏘️ Por localidad"}},
                {"type": "reply", "reply": {"id": "emergencias", "title": "📞 Emergencias"}},
            ]},
        },
    })
    if not ok:  # si los botones fallan, manda el menu como texto
        enviar_texto(numero, texto + "\n\nEscribí: *farmacia*, tu *localidad* o *emergencias*.")


def pedir_ubicacion(numero):
    texto = ("📍 Mandame tu ubicación y te digo las farmacias de turno más cercanas.\n\n"
             "Tocá el botón de abajo, o el 📎 clip → *Ubicación* → *Enviar tu ubicación actual*.")
    ok = enviar(numero, {
        "type": "interactive",
        "interactive": {
            "type": "location_request_message",
            "body": {"text": texto},
            "action": {"name": "send_location"},
        },
    })
    if not ok:
        enviar_texto(numero, texto)


# ---------------------------------------------------------------- armar respuestas

def datos_turno():
    return fc.leer_json(fc.TURNO, None)


def respuesta_cercanas(lat, lon):
    resultado = fc.mas_cercanas(lat, lon)
    if not resultado or not resultado[0]:
        return "No tengo las farmacias de turno de hoy cargadas. Probá en un rato 🙏"
    cercanas, turno = resultado
    lineas = [f"💊 *Farmacias de turno más cercanas*\n_{turno['fecha']}, de 8 a 8 hs_\n"]
    for i, (km, fa, localidad, c) in enumerate(cercanas, 1):
        aprox = " _(ubicación aproximada)_" if c.get("aproximada") else ""
        lineas.append(f"*{i}. {fa['nombre']}* — a {fc.formato_distancia(km)}{aprox}")
        lineas.append(f"📍 {fa['direccion']}, {localidad}")
        if fa["telefono"]:
            lineas.append(f"📞 {fa['telefono']}")
        lineas.append(f"🗺️ https://www.google.com/maps/search/?api=1&query={c['lat']},{c['lon']}\n")
    lineas.append("ℹ️ Te recomendamos llamar antes de ir. Fuente: Colegio de Farmacéuticos de Tucumán.")
    return "\n".join(lineas)


def respuesta_localidad(localidad):
    turno = datos_turno()
    if not turno:
        return "No tengo las farmacias de turno de hoy cargadas. Probá en un rato 🙏"
    lista = turno["localidades"].get(localidad)
    if not lista:
        return (f"Hoy no figuran farmacias de turno en *{localidad}*.\n"
                "Mandame tu ubicación 📍 y te digo las más cercanas, aunque sean de otra localidad.")
    lineas = [f"💊 *Farmacias de turno en {localidad}*\n_{turno['fecha']}, de 8 a 8 hs_\n"]
    for fa in lista:
        lineas.append(f"*{fa['nombre']}*")
        lineas.append(f"📍 {fa['direccion']}")
        if fa["telefono"]:
            lineas.append(f"📞 {fa['telefono']}")
        lineas.append("")
    lineas.append("ℹ️ Te recomendamos llamar antes de ir. Fuente: Colegio de Farmacéuticos de Tucumán.")
    return "\n".join(lineas)


def detectar_localidad(texto):
    """Busca una localidad dentro de lo que escribio el usuario ('hay farmacia en yb?')."""
    n = ft.normalizar(texto)
    for clave_loc, nombre in sorted(ft.LOCALIDADES_NORM.items(), key=lambda x: -len(x[0])):
        if re.search(rf"\b{re.escape(clave_loc)}\b", n):
            return nombre
    for apodo, nombre in sorted(ft.APODOS.items(), key=lambda x: -len(x[0])):
        if re.search(rf"\b{re.escape(apodo)}\b", n):
            return nombre
    return ft.buscar_localidad(texto) if len(n) >= 4 else None


# ---------------------------------------------------------------- procesar mensajes

procesados = set()
esperando_localidad = set()


def procesar_mensaje(msg):
    if msg.get("id") in procesados:   # Meta a veces reenvia el mismo mensaje
        return
    procesados.add(msg.get("id"))
    numero = msg.get("from")
    tipo = msg.get("type")
    print(f"[{datetime.now():%H:%M:%S}] Mensaje de ...{numero[-4:]} ({tipo})")

    if tipo == "location":
        loc = msg["location"]
        esperando_localidad.discard(numero)
        enviar_texto(numero, respuesta_cercanas(float(loc["latitude"]), float(loc["longitude"])))
        return

    if tipo == "interactive":
        boton = msg["interactive"].get("button_reply", {}).get("id")
        if boton == "cercana":
            pedir_ubicacion(numero)
        elif boton == "localidad":
            esperando_localidad.add(numero)
            enviar_texto(numero, "🏘️ Escribime tu localidad. Por ejemplo: *Yerba Buena*, *La Banda*, "
                                 "*Tafí Viejo*, *Concepción* o *Capital*.")
        elif boton == "emergencias":
            enviar_texto(numero, EMERGENCIAS)
        else:
            enviar_menu(numero)
        return

    if tipo != "text":
        enviar_menu(numero)
        return

    texto = msg["text"]["body"]
    n = ft.normalizar(texto)

    if any(p in texto.lower() for p in PALABRAS_SALUD):
        enviar_texto(numero, "⚕️ No puedo dar consejos médicos ni recomendar medicamentos. "
                             "Consultá con un farmacéutico o un médico.\n\n" + EMERGENCIAS)
        return

    if re.search(r"\b(emergencia|emergencias|urgencia|ambulancia|policia|bomberos|107|911)\b", n):
        enviar_texto(numero, EMERGENCIAS)
        return

    localidad = detectar_localidad(texto)
    if localidad:
        esperando_localidad.discard(numero)
        enviar_texto(numero, respuesta_localidad(localidad))
        return

    if numero in esperando_localidad:
        enviar_texto(numero, "No reconocí esa localidad 🤔. Probá escribiéndola completa "
                             "(ej: *Banda del Río Salí*) o mandame tu ubicación 📍.")
        return

    if re.search(r"\b(farmacia|farmacias|farmasia|turno|cercana|cerca)\b", n):
        pedir_ubicacion(numero)
        return

    enviar_menu(numero)


def procesar_webhook(datos):
    try:
        for entry in datos.get("entry", []):
            for change in entry.get("changes", []):
                for msg in change.get("value", {}).get("messages", []):
                    procesar_mensaje(msg)
    except Exception:
        traceback.print_exc()


# ---------------------------------------------------------------- servidor web (webhook)

class Webhook(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # no llenar la consola

    def responder(self, codigo, texto=""):
        self.send_response(codigo)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(texto.encode("utf-8"))

    def do_GET(self):
        # Meta llama aca una sola vez para verificar el webhook
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if q.get("hub.mode", [""])[0] == "subscribe" and q.get("hub.verify_token", [""])[0] == CFG["VERIFY_TOKEN"]:
            print("Webhook verificado por Meta ✔")
            self.responder(200, q.get("hub.challenge", [""])[0])
        elif self.path in ("/", "/webhook"):
            self.responder(200, "Bot de farmacias funcionando")
        else:
            self.responder(403, "Token de verificacion incorrecto")

    def do_POST(self):
        largo = int(self.headers.get("Content-Length", 0))
        cuerpo = self.rfile.read(largo)

        secreto = CFG.get("APP_SECRET")
        if secreto:
            firma = self.headers.get("X-Hub-Signature-256", "")
            esperada = "sha256=" + hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(firma, esperada):
                print("  ! Llego un mensaje con firma invalida (no es de Meta). Ignorado.")
                self.responder(403)
                return

        self.responder(200, "OK")  # Meta necesita respuesta rapida; procesamos aparte
        try:
            datos = json.loads(cuerpo or b"{}")
        except json.JSONDecodeError:
            return
        threading.Thread(target=procesar_webhook, args=(datos,), daemon=True).start()


# ---------------------------------------------------------------- actualizacion diaria 8:05

def actualizar_farmacias():
    print(f"\n[{datetime.now():%d/%m %H:%M}] Actualizando farmacias de turno...")
    try:
        import sys
        argv = sys.argv
        sys.argv = ["farmacias_turno.py"]
        ft.main()
        sys.argv = argv
        fc.cargar_coordenadas()
    except Exception:
        traceback.print_exc()


def actualizador():
    ultimo = None
    while True:
        ahora = datetime.now()
        if (ahora.hour, ahora.minute) >= (8, 5) and ultimo != ahora.date():
            actualizar_farmacias()
            turno = datos_turno()
            hoy = ahora.strftime("%d/%m/%Y")
            if turno and turno.get("fecha") == hoy:
                ultimo = ahora.date()
            else:
                print("  La pagina todavia no tiene los turnos de hoy. Reintento en 15 minutos.")
                time.sleep(15 * 60)
                continue
        time.sleep(60)


# ---------------------------------------------------------------- principal

def main():
    global CFG
    CFG = leer_config()
    if not CFG:
        return
    if not datos_turno():
        print("No hay farmacias cargadas todavia. Primero corre: python farmacias_turno.py")
        return

    threading.Thread(target=actualizador, daemon=True).start()
    servidor = ThreadingHTTPServer(("0.0.0.0", PUERTO), Webhook)
    print("=" * 60)
    print(f" Bot de farmacias escuchando en http://localhost:{PUERTO}/webhook")
    print(" Deja esta ventana abierta. Para apagarlo: Ctrl + C")
    print("=" * 60)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nBot apagado.")


if __name__ == "__main__":
    main()
