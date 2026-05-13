# HACS Compatibility Auditor

[![HACS Integration](https://img.shields.io/badge/HACS-Integration-blue.svg)](https://hacs.xyz)

Integración de Home Assistant que detecta la versión actual y la próxima versión de Home Assistant, lista todas las integraciones y tarjetas instaladas desde HACS y verifica la compatibilidad de cada paquete consultando sus issues y metadatos en GitHub.

## Características

- **Detección automática de versiones**: Identifica la versión actual de Home Assistant y la próxima versión disponible (incluyendo release candidates).
- **Enumeración de paquetes HACS**: Lista todas las integraciones, tarjetas, temas y otros paquetes instalados desde HACS.
- **Verificación de compatibilidad**: Evalúa cada paquete contra la versión actual y la siguiente de Home Assistant.
- **Análisis de issues en GitHub**: Revisa issues abiertos y recientes para detectar reportes de incompatibilidad, notas de breaking changes y PRs relevantes.
- **Notificaciones**: Eventos automáticos cuando se detectan incompatibilidades con la próxima versión de HA.
- **Servicio de re-escaneo**: Fuerza una comprobación inmediata con el servicio `hacs_compatibility_auditor.check_now`.
- **Lovelace Card**: Incluye una tarjeta personalizada con resumen filtrable, enlaces a repositorios y acciones rápidas. → [Repositorio de la card](https://github.com/RmG152/hacs-compatibility-auditor-card)

## Sensores

La integración crea los siguientes sensores:

| Sensor | Descripción |
|--------|-------------|
| `sensor.ha_version_current` | Versión actual de Home Assistant |
| `sensor.ha_version_next` | Próxima versión disponible (RC o estable) |
| `sensor.hacs_packages_total` | Número total de paquetes HACS instalados |
| `sensor.hacs_incompatible_count` | Número de paquetes incompatibles |

Además, se crea un sensor por cada paquete HACS instalado (`sensor.hacs_compatibility_auditor_package_*`).

## Instalación

### Vía HACS (recomendado)

1. Añade este repositorio como **custom repository** en HACS:
   - HACS → Integraciones → Menú (⋮) → Custom repositories
   - URL: `https://github.com/RmG152/hacs-compatibility-auditor`
   - Categoría: **Integration**
2. Busca "HACS Compatibility Auditor" en HACS → Integraciones.
3. Haz clic en **Instalar**.
4. **Reinicia Home Assistant**.
5. Ve a **Configuración → Dispositivos y servicios → Añadir integración** y busca "HACS Compatibility Auditor".

### Instalación manual

1. Copia la carpeta `custom_components/hacs_compatibility_auditor/` a tu directorio `custom_components/`.
2. Reinicia Home Assistant.
3. Añade la integración desde Configuración → Integraciones.

## Lovelace Card

La integración incluye una tarjeta Lovelace en un repositorio separado:

> **https://github.com/RmG152/hacs-compatibility-auditor-card**

Sigue las instrucciones de instalación y configuración en el README de ese repositorio.

## Configuración

### Config Flow

1. **Token de GitHub** (opcional): Sin token, la API de GitHub permite ~60 peticiones/hora. Con token, ~5000 peticiones/hora. Recomendado para instalaciones con muchos paquetes.
2. **Intervalo de comprobación**: Cada cuántas horas se ejecuta el escaneo automático (por defecto: 12h).
3. **Horas de caché**: Tiempo de caché para consultas a GitHub (por defecto: 12h).
4. **Timeout de GitHub**: Timeout en segundos para consultas (por defecto: 15s).
5. **Reintentos de GitHub**: Número de reintentos ante errores (por defecto: 3).

### Opciones avanzadas

Accede a las opciones desde Configuración → Integraciones → HACS Compatibility Auditor → Configurar:

- **Labels de prioridad**: Labels de GitHub que indican alta severidad (separadas por coma). Por defecto: `breaking-change,breaking,incompatible,upgrade,compatibility`.
- **Lista de ignorados**: Nombres de repositorios a ignorar (separados por coma).

### Token de GitHub

1. Ve a [GitHub Settings > Developer settings > Personal access tokens](https://github.com/settings/tokens).
2. Crea un nuevo token (classic) con permisos mínimos: `public_repo` (solo lectura).
3. Copia el token y pégalo en la configuración de la integración.

## Servicio

### `hacs_compatibility_auditor.check_now`

Fuerza una re-comprobación inmediata de la compatibilidad de todos los paquetes HACS.

```yaml
service: hacs_compatibility_auditor.check_now
```

## Algoritmo de comprobación

1. Obtiene la versión actual de HA desde la API interna.
2. Consulta releases del repositorio `home-assistant/core` en GitHub para determinar la próxima versión.
3. Enumera paquetes HACS desde múltiples fuentes (datos internos de HACS, `.storage`, directorio de repositorios).
4. Para cada paquete:
   - Consulta `hacs.json` / `manifest.json` para comprobar requisitos declarados de versión HA.
   - Obtiene releases/tags más recientes del repositorio.
   - Busca issues abiertos/recientes con labels y keywords de compatibilidad.
   - Analiza notas de release para detectar breaking changes.
   - Determina estado final: `compatible`, `warning` o `incompatible`.
5. Expone resultados en sensores y eventos.

### Criterios de estado

| Estado | Criterio |
|--------|----------|
| `compatible` | Manifest compatible, sin issues relevantes |
| `warning` | Issues de compatibilidad abiertos (prioridad media) o breaking changes en releases recientes |
| `incompatible` | Manifest incompatible con versión actual o issue confirmado con label de alta severidad |
| `unknown` | Error al obtener datos del paquete |

## Eventos

La integración dispara un evento `hacs_compatibility_auditor_incompatibility_detected` cuando se detectan incompatibilidades:

```yaml
- trigger:
    - platform: event
      event_type: hacs_compatibility_auditor_incompatibility_detected
  action:
    - service: notify.mobile_app
      data:
        title: "Incompatibilidad HACS detectada"
        message: >
          Se han detectado {{ trigger.event.data.incompatible_count }} paquetes
          incompatibles con la próxima versión de Home Assistant.
```

## Requisitos

- Home Assistant >= 2024.1.0
- HACS instalado y configurado
- Conexión a Internet (para consultar GitHub API)
- Token de GitHub (opcional pero recomendado)

## Licencia

MIT
