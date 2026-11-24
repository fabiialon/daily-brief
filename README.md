# daily-brief

Scripts en Python que devuelven en JSON, ya limpios, los datos de un resumen diario:

- **Blackboard**: eventos de hoy y de mañana del feed iCal (clases, entregas y exámenes), con las horas en Europe/Madrid.
- **Clima de Madrid**: previsión del día desde [Open-Meteo](https://open-meteo.com/), que no necesita API key.

Si una de las dos fuentes falla, el programa no se rompe: su bloque sale como `null`, el error se anota en `errores` y el código de salida es 0.

## Instalación

Necesitas Python 3.11 o superior.

```bash
pip install -r requirements.txt        # para ejecutarlo
pip install -r requirements-dev.txt    # para los tests
```

## Uso

```bash
export BLACKBOARD_ICS_URL='...'        # URL de tu feed iCal (secreta)
python -m brief                        # hoy (fecha de Europe/Madrid)
python -m brief --date 2026-11-24
pytest -q                              # sin conexión a internet
```

## Variables de entorno

| Variable | Qué es |
|---|---|
| `BLACKBOARD_ICS_URL` | URL del feed iCal de Blackboard. Es un secreto: no la guardes en el repo (`.env` está en `.gitignore`). Si falta, sale un error de la fuente `blackboard`. |

## Ejemplo de salida (datos inventados)

```json
{
  "fecha": "2026-11-24",
  "manana": "2026-11-25",
  "blackboard": {
    "hoy": [
      {
        "asignatura": "MANAGEMENT TOOLS & PRINCIPLES",
        "sesion": 26,
        "inicio": "2026-11-24T10:30:00+01:00",
        "fin": "2026-11-24T11:50:00+01:00",
        "aula": "Z-02.03",
        "tipo": "clase_presencial"
      },
      {
        "asignatura": "Group Homework",
        "sesion": null,
        "inicio": "2026-11-24T23:59:00+01:00",
        "fin": "2026-11-24T23:59:00+01:00",
        "aula": null,
        "tipo": "entrega"
      }
    ],
    "manana": [],
    "hay_management_hoy": true
  },
  "clima": {
    "max": 9,
    "min": 6,
    "prob_lluvia_max": 90,
    "tramos_lluvia": ["13–17 h"],
    "descripcion": "☁️ nublado",
    "paraguas": true,
    "linea": "🌡️ 6–9 °C · nublado, lluvia 13–17 h ☔ (llévate paraguas)"
  },
  "errores": []
}
```

Tipos de evento: `examen`, `entrega`, `clase_presencial`, `clase_asincrona` y `otro`.

`ROUTINE_PROMPT.md` contiene el prompt de la tarea programada que usa este script.
