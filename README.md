# Bot de farmacias de turno de Tucumán 💊

Bot de WhatsApp que responde, en segundos, cuáles son las farmacias de turno más cercanas en Tucumán.

## Qué hace

- **📍 Farmacia cercana**: el usuario comparte su ubicación y recibe las 3 farmacias de turno más cercanas, con distancia, teléfono y link a Google Maps.
- **🏘️ Por localidad**: escribiendo "yerba buena", "la banda" o "hay farmacia en yb?" muestra las de turno en esa zona.
- **📞 Emergencias**: teléfonos útiles (107, 911, 100, 103, 102).
- Entiende lenguaje informal y errores de escritura.
- No da consejos médicos: deriva a un profesional y a los teléfonos de emergencia.
- Avisa si los datos del día todavía no se actualizaron.

## Cómo funciona

```
cofatuc.org.ar ──► GitHub Actions (todos los días 8:10) ──► farmacias_turno.json
                    ├─ farmacias_turno.py   (lee los turnos)     coordenadas_farmacias.json
                    └─ farmacias_cercanas.py (OpenStreetMap)            │
                                                                       ▼
WhatsApp ──► Meta (webhook) ──► Cloudflare Worker (worker.js) ──► respuesta
```

| Archivo | Función |
|---|---|
| `farmacias_turno.py` | Lee las farmacias de turno del día desde el Colegio de Farmacéuticos de Tucumán |
| `farmacias_cercanas.py` | Ubica cada farmacia en el mapa (OpenStreetMap / Nominatim) y calcula distancias |
| `worker.js` | El bot: recibe los mensajes de WhatsApp y responde (Cloudflare Workers) |
| `bot_whatsapp.py` | Versión del bot para correr en una PC (pruebas) |
| `.github/workflows/actualizar.yml` | Actualización automática diaria |

Todo funciona con herramientas gratuitas: WhatsApp Cloud API, Cloudflare Workers, GitHub Actions y OpenStreetMap.

## Fuentes

- Farmacias de turno: [Colegio de Farmacéuticos de Tucumán](https://cofatuc.org.ar/farmacias-de-turno/)
- Mapas: © colaboradores de [OpenStreetMap](https://www.openstreetmap.org/copyright)

Los datos son de referencia: se recomienda llamar a la farmacia antes de ir.
