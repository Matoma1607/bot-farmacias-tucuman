"""
farmacias_cercanas.py
Paso 2 del bot de farmacias de turno de Tucuman.

1) Le agrega coordenadas (latitud/longitud) a cada farmacia de turno, usando OpenStreetMap.
2) Dada una ubicacion, te dice cuales son las 3 farmacias de turno mas cercanas.

Uso:
    python farmacias_cercanas.py coordenadas            -> busca las coordenadas de las farmacias de hoy
    python farmacias_cercanas.py cerca -26.8303 -65.2038 -> las 3 mas cercanas a ese punto
    python farmacias_cercanas.py cerca plaza independencia -> tambien acepta un lugar o direccion
    python farmacias_cercanas.py fijar -26.93 -65.34 san isidro -> carga a mano una que no se encontro

Requisito: antes haber corrido farmacias_turno.py (genera farmacias_turno.json).

Las coordenadas se guardan en coordenadas_farmacias.json y se reutilizan:
cada farmacia se busca UNA sola vez, asi no se sobrecarga OpenStreetMap.
Si alguna no se encuentra, la podes cargar a mano en ese archivo (ver al final del script).

Datos de mapas: (c) OpenStreetMap contributors - Nominatim (gratis, sin clave).
No necesita instalar nada.
"""

import json
import math
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request

CARPETA = os.path.dirname(os.path.abspath(__file__))
TURNO = os.path.join(CARPETA, "farmacias_turno.json")
COORDS = os.path.join(CARPETA, "coordenadas_farmacias.json")

NOMINATIM = "https://nominatim.openstreetmap.org/search"
# Nominatim pide identificarse. Cambia el mail por el tuyo.
HEADERS = {"User-Agent": "bot-farmacias-tucuman/1.0 (contacto: tu-mail@ejemplo.com)"}

# Recuadro de la provincia de Tucuman: evita que encuentre una calle igual en otra provincia
VIEWBOX = "-66.25,-26.05,-64.45,-28.05"


def normalizar(texto):
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", t).split())


def clave(farmacia, localidad):
    return f"{normalizar(farmacia['nombre'])}|{normalizar(farmacia['direccion'])}|{normalizar(localidad)}"


def leer_json(ruta, por_defecto):
    if not os.path.exists(ruta):
        return por_defecto
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def guardar_json(ruta, datos):
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- geocodificar

def limpiar_direccion(direccion):
    """Deja la direccion en un formato que OpenStreetMap entienda mejor."""
    d = direccion
    d = re.sub(r",?\s*\b(loc(al)?|dpto|depto|piso|of(icina)?)\.?\s*\w+.*$", "", d, flags=re.I)
    d = re.sub(r",?\s*\bB[°º]\s*.*$|,?\s*\bBarrio\b.*$", "", d, flags=re.I)   # quita "B° Oeste", "Barrio Centro"
    d = re.sub(r"([A-Za-zÁÉÍÓÚáéíóúñÑ])(\d)", r"\1 \2", d)          # "Padilla180" -> "Padilla 180"
    d = re.sub(r"\bAv(da)?[.,]?\s", "Avenida ", d, flags=re.I)
    d = re.sub(r"\bBv\.?\s|\bBoulevar\b|\bBoulevard\b", "Boulevard ", d, flags=re.I)
    d = re.sub(r"\bGral\.?\s", "General ", d, flags=re.I)
    d = re.sub(r"\bPte\.?\s", "Presidente ", d, flags=re.I)
    return " ".join(d.split())


def consultar_nominatim(texto):
    params = urllib.parse.urlencode({
        "q": texto, "format": "json", "limit": 1, "countrycodes": "ar",
        "viewbox": VIEWBOX, "bounded": 1,
    })
    req = urllib.request.Request(f"{NOMINATIM}?{params}", headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as r:
        resultados = json.load(r)
    time.sleep(1.1)  # regla de Nominatim: maximo 1 consulta por segundo
    if resultados:
        return float(resultados[0]["lat"]), float(resultados[0]["lon"])
    return None


def geocodificar(direccion, localidad):
    """Prueba primero la direccion exacta y, si no, una aproximada."""
    d = limpiar_direccion(direccion)
    intentos = [(f"{d}, {localidad}, Tucumán, Argentina", False)]

    # Esquinas ("Calle A esq. Calle B" o "Calle A y Calle B"): OpenStreetMap no las entiende,
    # asi que se busca la primera calle (queda aproximada)
    partes = re.split(r"\s+(?:esq(?:uina)?\.?|y)\s+", d, flags=re.I)
    if len(partes) > 1:
        intentos.append((f"{partes[0]}, {localidad}, Tucumán, Argentina", True))

    # Sin numero: solo la calle
    sin_numero = re.sub(r"\s*\d+\s*$", "", d)
    if sin_numero != d:
        intentos.append((f"{sin_numero}, {localidad}, Tucumán, Argentina", True))

    for texto, aproximada in intentos:
        try:
            punto = consultar_nominatim(texto)
        except Exception as e:
            print(f"      (error consultando el mapa: {e})")
            return None
        if punto:
            return {"lat": punto[0], "lon": punto[1], "aproximada": aproximada}
    return None


def cargar_coordenadas():
    turno = leer_json(TURNO, None)
    if not turno:
        print("No encuentro farmacias_turno.json. Primero corre: python farmacias_turno.py")
        return
    coords = leer_json(COORDS, {})

    nuevas = encontradas = faltan = 0
    for localidad, lista in turno["localidades"].items():
        for fa in lista:
            k = clave(fa, localidad)
            if k in coords:
                continue
            nuevas += 1
            if not fa["direccion"]:
                print(f"  ?  {fa['nombre']} ({localidad}): no tiene direccion")
                faltan += 1
                continue
            print(f"  Buscando {fa['nombre']} - {fa['direccion']} ({localidad})...")
            punto = geocodificar(fa["direccion"], localidad)
            if punto:
                coords[k] = {**punto, "nombre": fa["nombre"], "direccion": fa["direccion"], "localidad": localidad}
                encontradas += 1
                aviso = "  (aproximada)" if punto["aproximada"] else ""
                print(f"     OK  {punto['lat']:.5f}, {punto['lon']:.5f}{aviso}")
            else:
                faltan += 1
                print("     X   no encontrada")
            guardar_json(COORDS, coords)  # guarda de a una por si se corta

    total = sum(len(l) for l in turno["localidades"].values())
    print(f"\nFarmacias de hoy: {total} | nuevas buscadas: {nuevas} | "
          f"encontradas: {encontradas} | sin ubicar: {faltan}")
    if faltan:
        print("Las que no se encontraron se pueden cargar a mano en coordenadas_farmacias.json.")


# ---------------------------------------------------------------- mas cercanas

def distancia_km(lat1, lon1, lat2, lon2):
    """Distancia en linea recta entre dos puntos (formula de Haversine)."""
    r = 6371
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def formato_distancia(km):
    return f"{km * 1000:.0f} m" if km < 1 else f"{km:.1f} km".replace(".", ",")


def mas_cercanas(lat, lon, cantidad=3):
    turno = leer_json(TURNO, None)
    coords = leer_json(COORDS, {})
    if not turno:
        print("No encuentro farmacias_turno.json. Primero corre: python farmacias_turno.py")
        return []

    candidatas = []
    sin_ubicar = 0
    for localidad, lista in turno["localidades"].items():
        for fa in lista:
            c = coords.get(clave(fa, localidad))
            if not c:
                sin_ubicar += 1
                continue
            km = distancia_km(lat, lon, c["lat"], c["lon"])
            candidatas.append((km, fa, localidad, c))

    candidatas.sort(key=lambda x: x[0])
    if sin_ubicar:
        print(f"(Ojo: {sin_ubicar} farmacias de hoy no tienen coordenadas y no se tuvieron en cuenta. "
              f"Corre: python farmacias_cercanas.py coordenadas)")
    return candidatas[:cantidad], turno


def mostrar_cercanas(lat, lon):
    resultado = mas_cercanas(lat, lon)
    if not resultado or not resultado[0]:
        print("No hay farmacias con coordenadas todavia.")
        return
    cercanas, turno = resultado

    print(f"\n💊 Farmacias de turno más cercanas ({turno['fecha']}, de 8 a 8 hs)\n")
    for i, (km, fa, localidad, c) in enumerate(cercanas, 1):
        aprox = " (ubicación aproximada)" if c.get("aproximada") else ""
        print(f"{i}. {fa['nombre']} — a {formato_distancia(km)}{aprox}")
        print(f"   📍 {fa['direccion']}, {localidad}")
        if fa["telefono"]:
            print(f"   📞 {fa['telefono']}")
        print(f"   🗺️ https://www.google.com/maps/search/?api=1&query={c['lat']},{c['lon']}")
        print()
    print("Fuente: Colegio de Farmacéuticos de Tucumán. Te recomendamos llamar antes de ir.")


def fijar_a_mano(lat, lon, nombre_buscado):
    """Guarda a mano las coordenadas de una farmacia de hoy que el mapa no encontro."""
    turno = leer_json(TURNO, None)
    if not turno:
        print("No encuentro farmacias_turno.json. Primero corre: python farmacias_turno.py")
        return
    buscado = normalizar(nombre_buscado)
    coincidencias = [(fa, loc) for loc, lista in turno["localidades"].items() for fa in lista
                     if buscado in normalizar(fa["nombre"])]
    if not coincidencias:
        print(f'No hay ninguna farmacia de turno hoy que se llame "{nombre_buscado}".')
        return
    if len(coincidencias) > 1:
        print("Hay varias con ese nombre, escribilo mas completo:")
        for fa, loc in coincidencias:
            print(f"  - {fa['nombre']} ({loc})")
        return
    fa, loc = coincidencias[0]
    coords = leer_json(COORDS, {})
    coords[clave(fa, loc)] = {"lat": lat, "lon": lon, "aproximada": False,
                              "nombre": fa["nombre"], "direccion": fa["direccion"], "localidad": loc}
    guardar_json(COORDS, coords)
    print(f"Listo: {fa['nombre']} ({loc}) guardada en {lat}, {lon}")


def ubicacion_desde_texto(texto):
    """Permite probar con un lugar escrito (ej: 'plaza independencia') en vez de coordenadas."""
    punto = consultar_nominatim(f"{texto}, Tucumán, Argentina")
    if not punto:
        print(f'No encontre "{texto}" en el mapa.')
    return punto


# ---------------------------------------------------------------- principal

def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("coordenadas", "cerca", "fijar"):
        print(__doc__)
        return

    if sys.argv[1] == "fijar":
        try:
            lat, lon = float(sys.argv[2].strip(",")), float(sys.argv[3].strip(","))
            nombre = " ".join(sys.argv[4:])
            if not nombre:
                raise ValueError
        except (IndexError, ValueError):
            print('Uso: python farmacias_cercanas.py fijar -26.9301 -65.3402 san isidro')
            return
        fijar_a_mano(lat, lon, nombre)
        return

    if sys.argv[1] == "coordenadas":
        print("Buscando coordenadas en OpenStreetMap (1 por segundo, puede tardar un poco)...\n")
        cargar_coordenadas()
        return

    resto = sys.argv[2:]
    if len(resto) == 2 and all(re.fullmatch(r"-?\d+(\.\d+)?", x) for x in resto):
        lat, lon = float(resto[0]), float(resto[1])
    elif resto:
        punto = ubicacion_desde_texto(" ".join(resto))
        if not punto:
            return
        lat, lon = punto
    else:
        print("Decime una ubicacion. Ej: python farmacias_cercanas.py cerca -26.8303 -65.2038")
        return
    mostrar_cercanas(lat, lon)


if __name__ == "__main__":
    main()

# ---------------------------------------------------------------------------
# CARGAR UNA FARMACIA A MANO
# Si una farmacia no se encuentra, busca la direccion en Google Maps, hace clic derecho
# sobre el lugar y copia las coordenadas (el primer renglon del menu).
# Despues, en coordenadas_farmacias.json agrega una entrada como esta
# (la clave es: nombre|direccion|localidad en minusculas y sin tildes):
#
#   "susy|av republica del libano 1405|san miguel de tucuman": {
#     "lat": -26.8123, "lon": -65.2345, "aproximada": false,
#     "nombre": "SUSY", "direccion": "Av. República del Líbano 1405",
#     "localidad": "San Miguel de Tucumán"
#   }
# ---------------------------------------------------------------------------