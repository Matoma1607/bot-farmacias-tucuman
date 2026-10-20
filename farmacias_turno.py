"""
farmacias_turno.py
Paso 1 del bot de farmacias de turno de Tucuman.

Lee la pagina del Colegio de Farmaceuticos de Tucuman (cofatuc.org.ar),
saca las farmacias de turno de hoy por localidad y las guarda en un JSON.

Uso:
    python farmacias_turno.py                -> muestra todas las farmacias de turno de hoy
    python farmacias_turno.py yerba buena    -> muestra solo las de esa localidad
    python farmacias_turno.py --debug        -> guarda archivos para revisar si algo no anda

Genera: farmacias_turno.json
Fuente: Colegio de Farmaceuticos de Tucuman - cofatuc.org.ar/farmacias-de-turno/
No necesita instalar nada: usa solo librerias que ya vienen con Python.
"""

import json
import os
import re
import sys
import unicodedata
import urllib.request
from datetime import datetime
from html.parser import HTMLParser

URL = "https://cofatuc.org.ar/farmacias-de-turno/"
HEADERS = {"User-Agent": "Mozilla/5.0 (bot-farmacias-tucuman)"}
CARPETA = os.path.dirname(os.path.abspath(__file__))
SALIDA = os.path.join(CARPETA, "farmacias_turno.json")

# Localidades de Tucuman (sirven para reconocer los titulos de cada zona)
LOCALIDADES = [
    "San Miguel de Tucumán", "Yerba Buena", "Tafí Viejo", "Banda del Río Salí", "Alderetes",
    "Las Talitas", "Lules", "Famaillá", "Monteros", "Concepción", "Aguilares",
    "Juan Bautista Alberdi", "La Cocha", "Bella Vista", "Simoca", "Villa Carmela",
    "Tafí del Valle", "Trancas", "Burruyacú", "Graneros", "Leales", "Villa Quinteros",
    "Santa Lucía", "Los Ralos", "Ranchillos", "El Manantial", "San Pablo", "Delfín Gallo",
    "Amaicha del Valle", "Lamadrid", "Taco Ralo", "Río Seco", "Los Nogales", "El Cadillal",
    "San Andrés", "Cevil Redondo", "Colombres", "Garmendia", "Acheral", "Santa Ana",
    "Villa Mariano Moreno", "El Mollar", "Raco", "Ticucho", "Mancopa", "Campo de Herrera",
    "Los Sarmientos", "Arcadia", "Romera Pozo", "Lastenia", "Cebil Redondo",
]

ETIQUETAS = re.compile(r"^(tel(efono|éfono)?s?|tel\.|cel(ular)?|direcci[oó]n|dir\.?|domicilio)\s*[:.\-]?\s*",
                       re.IGNORECASE)
ETIQUETAS_EN_LINEA = re.compile(r"\b(tel(efono|éfono)?s?|cel(ular)?|direcci[oó]n|domicilio)\s*[:.]\s*", re.IGNORECASE)
TELEFONO = re.compile(r"(?<!\d)(?:\(?0?\d{2,4}\)?\s*[-\s]\s*)?(?:\d{6,11}|\d{2,4}[\s-]\d{3,4})(?!\d)")
SEPARADORES = re.compile(r"\s*[|–—]\s*|\s+-\s+")


def normalizar(texto):
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", t).split())


LOCALIDADES_NORM = {normalizar(l): l for l in LOCALIDADES}
APODOS = {"smt": "San Miguel de Tucumán", "capital": "San Miguel de Tucumán", "tucuman": "San Miguel de Tucumán",
          "ciudad de tucuman": "San Miguel de Tucumán", "yb": "Yerba Buena", "la banda": "Banda del Río Salí",
          "banda": "Banda del Río Salí", "tafi": "Tafí Viejo", "alberdi": "Juan Bautista Alberdi"}


# ---------------------------------------------------------------- leer la pagina

class ExtractorDeLineas(HTMLParser):
    """Convierte el HTML en lineas de texto, recordando si cada linea era un titulo."""
    BLOQUES = {"p", "div", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6",
               "br", "section", "article", "ul", "ol", "table", "span"}
    TITULOS = {"h1", "h2", "h3", "h4", "h5", "h6", "strong", "b"}
    IGNORAR = {"script", "style", "noscript", "header", "footer", "nav", "form"}

    def __init__(self):
        super().__init__()
        self.lineas = []      # (texto, es_titulo)
        self.actual = []
        self.titulo = 0
        self.ignorar = 0

    def cortar(self):
        texto = " ".join("".join(self.actual).split())
        if texto:
            self.lineas.append((texto, self.titulo > 0))
        self.actual = []

    def handle_starttag(self, tag, attrs):
        if tag in self.IGNORAR:
            self.ignorar += 1
        if tag in self.BLOQUES and tag != "span":
            self.cortar()
        if tag in self.TITULOS:
            self.cortar()
            self.titulo += 1

    def handle_endtag(self, tag):
        if tag in self.IGNORAR and self.ignorar:
            self.ignorar -= 1
        if tag in self.TITULOS and self.titulo:
            self.cortar()
            self.titulo -= 1
        elif tag in self.BLOQUES and tag != "span":
            self.cortar()

    def handle_data(self, data):
        if not self.ignorar:
            self.actual.append(data)


def descargar():
    req = urllib.request.Request(URL, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


# ---------------------------------------------------------------- interpretar

def es_localidad(texto):
    n = normalizar(texto)
    n = re.sub(r"^(localidad|zona)\s+", "", n)
    if n in LOCALIDADES_NORM:
        return LOCALIDADES_NORM[n]
    return None


def es_telefono(texto):
    solo = ETIQUETAS.sub("", texto).strip()
    digitos = re.sub(r"\D", "", solo)
    return len(digitos) >= 6 and len(re.sub(r"[\d\s\-().+/]", "", solo)) == 0


def limpiar_telefono(texto):
    return " ".join(ETIQUETAS.sub("", texto).split())


def es_mayusculas(texto):
    """Los nombres de farmacias vienen en mayusculas (ej: SANTO TOMAS); las direcciones no."""
    letras = [c for c in texto if c.isalpha()]
    return bool(letras) and sum(c.isupper() for c in letras) / len(letras) >= 0.8


def linea_completa(texto):
    """Interpreta una linea con todo junto: 'NOMBRE - Tel: 4223073 - Av. Sarmiento 955'."""
    limpio = ETIQUETAS_EN_LINEA.sub("", texto)
    telefono = ""
    m = TELEFONO.search(limpio)
    if m:
        telefono = " ".join(m.group(0).split())
        limpio = limpio[:m.start()] + " - " + limpio[m.end():]
    partes = [p.strip(" -,") for p in SEPARADORES.split(limpio) if p.strip(" -,")]
    if not partes:
        return None
    return {"nombre": partes[0], "telefono": telefono, "direccion": ", ".join(partes[1:])}


def interpretar(lineas):
    fecha = None
    resultado = {}
    localidad = None
    farmacia = None
    en_turnos = False   # la seccion "Turnos para..." solo lista zonas, no farmacias

    def guardar():
        nonlocal farmacia
        if farmacia and localidad and farmacia.get("nombre"):
            resultado.setdefault(localidad, []).append(farmacia)
        farmacia = None

    # La pagina de cofatuc pone una etiqueta "Farmacia:" antes de cada farmacia,
    # seguida de: NOMBRE, telefono y direccion. Si existe esa etiqueta, se usa ese formato.
    modo_etiqueta = any(normalizar(t) == "farmacia" for t, _ in lineas)
    ETIQUETAS_SOLAS = {"telefono", "tel", "telefonos", "direccion", "domicilio", "dir"}

    for texto, es_titulo in lineas:
        n = normalizar(texto)

        if not fecha:
            m = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", texto)
            if m:
                fecha = m.group(1)

        # Secciones que no son farmacias: "Turnos para...", "Turno 17 para:", buscador, etc.
        if (n.startswith(("turnos para", "buscar farmacia", "consultar farmacia", "escriba el nombre"))
                or re.match(r"^turno \d+", n)):
            guardar()
            en_turnos = True
            continue

        loc = es_localidad(texto)
        if loc:
            guardar()
            localidad = loc
            en_turnos = False
            continue

        if en_turnos or not localidad:
            continue

        if n.startswith(("horario", "desde", "hasta", "las farmacias", "los turnos", "los horarios")):
            continue

        if modo_etiqueta:
            if n == "farmacia" or n.startswith("farmacia ") and texto.lower().startswith("farmacia:"):
                guardar()
                farmacia = {"nombre": "", "telefono": "", "direccion": ""}
                resto = texto.split(":", 1)[1].strip() if ":" in texto else ""
                if resto:
                    farmacia["nombre"] = resto
            elif farmacia is None or n in ETIQUETAS_SOLAS:
                continue
            elif es_telefono(texto):
                farmacia["telefono"] = limpiar_telefono(texto)
            elif re.match(r"^(direcci[oó]n|dir\.?|domicilio)\s*:", texto, re.I):
                farmacia["direccion"] = ETIQUETAS.sub("", texto).strip()
            elif not farmacia["nombre"]:
                farmacia["nombre"] = texto.strip()
            elif not farmacia["direccion"]:
                farmacia["direccion"] = texto.strip()
            continue

        # Lineas que traen todo junto: "NOMBRE - Tel: 4223073 - Av. Sarmiento 955"
        primera = SEPARADORES.split(texto)[0]
        if SEPARADORES.search(texto) and es_mayusculas(primera) and not es_telefono(texto):
            guardar()
            farmacia = linea_completa(texto)
            guardar()
            continue

        # Lineas sueltas: nombre, telefono y direccion en renglones distintos
        if es_telefono(texto):
            if farmacia is not None:
                farmacia["telefono"] = limpiar_telefono(texto)
        elif re.match(r"^(direcci[oó]n|dir\.?|domicilio)\b", texto, re.I):
            if farmacia is not None:
                farmacia["direccion"] = ETIQUETAS.sub("", texto).strip()
        elif (es_titulo or es_mayusculas(texto)) and len(texto) <= 60:
            guardar()
            farmacia = {"nombre": texto.strip(), "telefono": "", "direccion": ""}
        elif farmacia is not None and not farmacia["direccion"]:
            farmacia["direccion"] = texto.strip()
        elif len(texto) <= 60:
            guardar()
            farmacia = {"nombre": texto.strip(), "telefono": "", "direccion": ""}

    guardar()
    return fecha, resultado


# ---------------------------------------------------------------- principal

def buscar_localidad(texto):
    n = normalizar(texto)
    if n in APODOS:
        return APODOS[n]
    for clave, nombre in LOCALIDADES_NORM.items():
        if n == clave or n in clave:
            return nombre
    return None


def main():
    args = [a for a in sys.argv[1:] if a != "--debug"]
    debug = "--debug" in sys.argv

    print("Leyendo farmacias de turno de cofatuc.org.ar...")
    try:
        html = descargar()
    except Exception as e:
        print(f"No pude abrir la pagina: {e}")
        return

    extractor = ExtractorDeLineas()
    extractor.feed(html)
    extractor.cortar()
    fecha, farmacias = interpretar(extractor.lineas)

    total = sum(len(v) for v in farmacias.values())
    if debug or total == 0:
        with open(os.path.join(CARPETA, "debug_pagina.html"), "w", encoding="utf-8") as f:
            f.write(html)
        with open(os.path.join(CARPETA, "debug_lineas.txt"), "w", encoding="utf-8") as f:
            for texto, titulo in extractor.lineas:
                f.write(f"{'[T] ' if titulo else '    '}{texto}\n")
        print("Guarde debug_pagina.html y debug_lineas.txt para revisar.")
    if total == 0:
        print("No encontre farmacias. Pasame el archivo debug_lineas.txt y lo ajusto.")
        return

    datos = {
        "fecha": fecha or datetime.now().strftime("%d/%m/%Y"),
        "turno": "de 08:00 de ese dia a 08:00 del dia siguiente",
        "fuente": URL,
        "actualizado": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "localidades": farmacias,
    }
    with open(SALIDA, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)

    elegida = None
    if args:
        elegida = buscar_localidad(" ".join(args))
        if not elegida:
            print(f'No reconozco la localidad "{" ".join(args)}".')
            return

    print(f"\nFARMACIAS DE TURNO - {datos['fecha']} (08:00 a 08:00)")
    print("=" * 60)
    for loc, lista in farmacias.items():
        if elegida and loc != elegida:
            continue
        print(f"\n{loc.upper()}")
        for fa in lista:
            print(f"  - {fa['nombre']}")
            if fa["direccion"]:
                print(f"      {fa['direccion']}")
            if fa["telefono"]:
                print(f"      Tel: {fa['telefono']}")
    if elegida and elegida not in farmacias:
        print(f"\nHoy no hay farmacias de turno cargadas para {elegida}.")
    print("\n" + "=" * 60)
    print(f"{total} farmacias en {len(farmacias)} localidades | guardado en farmacias_turno.json")


if __name__ == "__main__":
    main()
