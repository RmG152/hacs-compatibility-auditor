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
- **Comprobación por paquete**: Comprueba un paquete HACS específico con `hacs_compatibility_auditor.check_package` sin esperar un escaneo completo.
- **Caché persistente**: Los resultados sobreviven reinicios de HA. Al reiniciar, los datos cacheados se cargan del disco al instante y solo las entradas expiradas se vuelven a consultar.
- **Procesamiento por lotes**: Los paquetes se comprueban en lotes concurrentes (por defecto 5), evitando timeouts en instalaciones grandes. El progreso se guarda tras cada lote.
- **Motor de reglas comunitarias**: Descarga reglas de la comunidad desde un repositorio de GitHub para whitelist, blacklist o ajustar la detección de compatibilidad por paquete. → [Repositorio de reglas](https://github.com/RmG152/hacs-compatibility-auditor-rules)
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
6. **Usar reglas comunitarias**: Activar o desactivar el motor de reglas de la comunidad (por defecto: activado).
7. **Repositorio de reglas**: Repositorio de GitHub para reglas comunitarias en formato `owner/repo` (por defecto: `RmG152/hacs-compatibility-auditor-rules`).

### Opciones avanzadas

Accede a las opciones desde Configuración → Integraciones → HACS Compatibility Auditor → Configurar:

- **Labels de prioridad**: Labels de GitHub que indican alta severidad (separadas por coma). Por defecto: `breaking-change,breaking,incompatible,upgrade,compatibility`.
- **Lista de ignorados**: Nombres de repositorios a ignorar (separados por coma).
- **Repositorio de reglas**: Repositorio de GitHub para reglas comunitarias (por defecto: `RmG152/hacs-compatibility-auditor-rules`).
- **Tamaño de lote**: Número de paquetes a comprobar concurrentemente (por defecto: 5, máximo: 50). Lotes más grandes aceleran el escaneo pero consumen más cuota de la API de GitHub simultáneamente.

### Token de GitHub

1. Ve a [GitHub Settings > Developer settings > Personal access tokens](https://github.com/settings/tokens).
2. Crea un nuevo token (classic) con permisos mínimos: `public_repo` (solo lectura).
3. Copia el token y pégalo en la configuración de la integración.

**Creación de incidencias (report_to_rules / ai_confirm_report):** Estos servicios intentan crear incidencias en el repositorio de reglas mediante la API de GitHub. Si el token no tiene permisos de escritura (p. ej., tokens fine-grained o classic restringidos por política organizativa), los servicios devuelven un **enlace de respaldo** con la incidencia pre-rellenada usando la plantilla correcta. Abre el enlace en tu navegador para completar el envío manualmente.

> Para el esquema completo de la API de servicios, incluyendo formatos de respuesta y ejemplos de uso desde el frontal, consulta [docs/services.md](docs/services.md).

## Servicios

### `hacs_compatibility_auditor.check_now`

Fuerza una re-comprobación inmediata de la compatibilidad de todos los paquetes HACS.

```yaml
service: hacs_compatibility_auditor.check_now
```

### `hacs_compatibility_auditor.check_package`

Comprueba la compatibilidad de un paquete HACS específico seleccionando su sensor.

```yaml
service: hacs_compatibility_auditor.check_package
data:
  entity_id: sensor.hacs_compatibility_auditor_package_owner_repo
```

Devuelve el resultado de compatibilidad para ese paquete.

### `hacs_compatibility_auditor.ai_analyze_package`

Utiliza un proveedor de IA para analizar si un paquete HACS tiene problemas reales de compatibilidad.

```yaml
service: hacs_compatibility_auditor.ai_analyze_package
data:
  entity_id: sensor.hacs_compatibility_auditor_package_owner_repo
  provider: "My OpenAI"  # opcional, usa el primer proveedor configurado
```

### `hacs_compatibility_auditor.ai_categorize_issue`

Categoriza una incidencia específica de GitHub usando IA.

```yaml
service: hacs_compatibility_auditor.ai_categorize_issue
data:
  repository: "owner/repo-name"
  issue_number: 42
  provider: "My OpenAI"  # opcional
```

### `hacs_compatibility_auditor.report_to_rules`

Crea una incidencia en el repositorio de reglas comunitarias con el análisis de IA.

```yaml
service: hacs_compatibility_auditor.report_to_rules
data:
  repository: "owner/repo-name"
  issue_number: 42
  category: "false_positive"
  reasoning: "La IA determinó que esta incidencia es un problema de configuración del usuario"
  action: "add_false_positive"  # o "report_incompatibility"
```

### `hacs_compatibility_auditor.ai_analyze_all`

Ejecuta análisis con IA en todos los paquetes que no sean compatibles o ignorados.

```yaml
service: hacs_compatibility_auditor.ai_analyze_all
data:
  provider: "My OpenAI"  # opcional
```

### `hacs_compatibility_auditor.ai_confirm_report`

Crea una incidencia usando el análisis de IA almacenado para un paquete.

```yaml
service: hacs_compatibility_auditor.ai_confirm_report
data:
  entity_id: sensor.hacs_compatibility_auditor_package_owner_repo
  action: "add_false_positive"  # opcional, se deriva del veredicto si se omite
```

## Caché

La integración utiliza una **caché de dos niveles** para minimizar las llamadas a la API de GitHub y sobrevivir a reinicios:

1. **Caché en memoria** (GitHubClient): Almacena respuestas crudas de la API durante el TTL configurado (por defecto 12h). Se limpia en una comprobación forzada.
2. **Caché persistente en disco** (CacheManager): Almacena resultados individuales de compatibilidad en `.storage/hacs_compatibility_auditor_cache.json`. Sobrevive a reinicios de HA.

**Al reiniciar:**
1. La caché de disco se carga primero — no se necesita acceso a internet.
2. Para cada paquete, si el resultado en caché sigue siendo válido (TTL no expirado Y versión de HA sin cambios), se usa directamente.
3. Solo los paquetes con caché expirada, ausente o invalidada se consultan desde GitHub.
4. Los paquetes se comprueban en lotes (por defecto 5 concurrentes) y la caché de disco se actualiza tras cada lote.

**Invalidación de caché:**
- El TTL se configura mediante la opción `cache_hours` (por defecto: 12h).
- Si la versión de Home Assistant cambia, todas las entradas en caché se invalidan (los resultados pueden diferir por versión de HA).
- Llamar a `check_now` limpia ambas capas de caché y fuerza una actualización completa.

## Reglas Comunitarias

La integración incluye un motor de reglas impulsado por la comunidad que descarga sobreescrituras de compatibilidad desde un repositorio de GitHub. Esto permite ajustar la detección sin necesidad de actualizar la integración.

- **Repositorio por defecto**: [`RmG152/hacs-compatibility-auditor-rules`](https://github.com/RmG152/hacs-compatibility-auditor-rules)
- **Activado por defecto**: Se puede desactivar en las opciones de la integración.
- **Tipos de reglas**:
  - **Whitelist / Blacklist**: Forzar paquetes como compatibles o incompatibles por versión de HA.
  - **Falsos positivos**: Ignorar issues específicos de GitHub que disparan alertas incorrectamente.
  - **Sobreescritura de labels / keywords**: Ajustar pesos de prioridad para labels y keywords por repositorio.
- **Frecuencia de actualización**: Las reglas se descargan del último release de GitHub cada 12 horas.

> Para detalles sobre el algoritmo de comprobación de compatibilidad, consulta [docs/compatibility-flow.md](docs/compatibility-flow.md).

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
