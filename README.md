# HACS Compatibility Auditor

Una integración de Home Assistant que detecta la versión actual y la próxima versión de Home Assistant, lista todas las integraciones y tarjetas instaladas desde HACS y verifica la compatibilidad de cada paquete consultando sus issues y metadatos en GitHub.

## Características

- **Detección automática de versiones**: Identifica la versión actual de Home Assistant y la próxima versión disponible (incluyendo release candidates).
- **Enumeración de paquetes HACS**: Lista todas las integraciones, tarjetas, temas y otros paquetes instalados desde HACS.
- **Verificación de compatibilidad**: Evalúa cada paquete contra la versión actual y la siguiente de Home Assistant.
- **Análisis de issues en GitHub**: Revisa issues abiertos y recientes para detectar reportes de incompatibilidad, notas de breaking changes y PRs relevantes.
- **Panel Lovelace**: Tarjeta personalizada con resumen filtrable, enlaces a repositorios y acciones rápidas.
- **Notificaciones**: Eventos automáticos cuando se detectan incompatibilidades con la próxima versión de HA.
- **Servicio de re-escaneo**: Fuerza una comprobación inmediata con el servicio `hacs_compatibility_auditor.check_now`.

## Sensores

La integración crea los siguientes sensores:

| Sensor | Descripción |
|--------|-------------|
| `sensor.ha_version_current` | Versión actual de Home Assistant |
| `sensor.ha_version_next` | Próxima versión disponible (RC o estable) |
| `sensor.hacs_packages_total` | Número total de paquetes HACS instalados |
| `sensor.hacs_incompatible_count` | Número de paquetes incompatibles |

Además, se crea un sensor por cada paquete HACS instalado (`sensor.hacs_compatibility_auditor_package_*`) con los siguientes atributos:

- `nombre`: Nombre del paquete
- `repositorio`: Repositorio GitHub (owner/repo)
- `tipo`: Tipo de paquete (integración, plugin, tema, etc.)
- `version_instalada`: Versión instalada
- `version_mas_reciente`: Última versión disponible
- `compatible_con_actual`: Compatibilidad con versión actual (bool)
- `compatible_con_siguiente`: Compatibilidad con próxima versión (bool)
- `estado`: `compatible`, `warning`, `incompatible`, `unknown` o `ignored`
- `issues_relevantes`: Lista de issues relacionados con compatibilidad
- `requisito_ha_manifest`: Requisito de versión HA declarado en manifest
- `ultima_comprobacion`: Timestamp de la última verificación

## Instalación

### A través de HACS (recomendado)

1. Añade este repositorio como custom repository en HACS.
2. Busca "HACS Compatibility Auditor" en HACS.
3. Instala la integración.
4. Reinicia Home Assistant.
5. Añade la integración desde Configuración > Integraciones.

### Instalación manual

1. Copia la carpeta `custom_components/hacs_compatibility_auditor/` a tu directorio `custom_components/`.
2. Reinicia Home Assistant.
3. Añade la integración desde Configuración > Integraciones.

### Instalación de la tarjeta Lovelace

1. Copia `hacs-compatibility-auditor-card/dist/hacs-compatibility-auditor-card.js` a tu directorio `www/`.
2. Añade el recurso en tu configuración de Lovelace:
   ```yaml
   resources:
     - url: /local/hacs-compatibility-auditor-card.js
       type: module
   ```
3. Añade la tarjeta a tu dashboard:
   ```yaml
   type: custom:hacs-compatibility-auditor-card
   ```

## Configuración

### Config Flow

La integración se configura mediante el flujo de configuración de Home Assistant:

1. **Token de GitHub** (opcional): Sin token, la API de GitHub permite ~60 peticiones/hora. Con token, ~5000 peticiones/hora. Recomendado para instalaciones con muchos paquetes.
2. **Intervalo de comprobación**: Cada cuántas horas se ejecuta el escaneo automático (por defecto: 12h).
3. **Horas de caché**: Tiempo de caché para consultas a GitHub (por defecto: 12h).
4. **Timeout de GitHub**: Timeout en segundos para consultas (por defecto: 15s).
5. **Reintentos de GitHub**: Número de reintentos ante errores (por defecto: 3).

### Opciones avanzadas

Accede a las opciones de la integración desde Configuración > Integraciones > HACS Compatibility Auditor > Configurar:

- **Labels de prioridad**: Labels de GitHub que indican alta severidad (separadas por coma). Por defecto: `breaking-change,breaking,incompatible,upgrade,compatibility`.
- **Lista de ignorados**: Nombres de repositorios a ignorar (separados por coma).

### Token de GitHub

Para obtener un token de GitHub:

1. Ve a [GitHub Settings > Developer settings > Personal access tokens](https://github.com/settings/tokens).
2. Crea un nuevo token (classic) con permisos mínimos: `public_repo` (solo lectura).
3. No se necesita acceso a repositorios privados.
4. Copia el token y pégalo en la configuración de la integración.

## Servicio

### `hacs_compatibility_auditor.check_now`

Fuerza una re-comprobación inmediata de la compatibilidad de todos los paquetes HACS.

```yaml
service: hacs_compatibility_auditor.check_now
```

También puede llamarse desde el botón de refresco en la tarjeta Lovelace.

## Tarjeta Lovelace

### Configuración de la tarjeta

```yaml
type: custom:hacs-compatibility-auditor-card
title: "Auditoría de Compatibilidad HACS"
show_summary: true    # Mostrar resumen de versiones y conteos
show_filters: true    # Mostrar filtros de estado y tipo
show_issues: true     # Mostrar issues relevantes en detalle de paquete
compact: false        # Modo compacto (menos padding)
```

### Características de la tarjeta

- **Resumen**: Muestra versión actual y próxima de HA, conteo de paquetes por estado.
- **Filtros**: Filtra por estado (compatible, advertencia, incompatible) y tipo (integración, tarjeta, tema).
- **Búsqueda**: Busca paquetes por nombre o repositorio.
- **Detalle expandible**: Haz clic en un paquete para ver detalles completos.
- **Issues relevantes**: Lista de issues de GitHub relacionados con compatibilidad.
- **Acciones rápidas**:
  - Abrir repositorio en GitHub
  - Ignorar paquete (se oculta con opacidad reducida)
  - Marcar como revisado
  - Reportar issue (abre template pre-llenado)

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

## Manejo de errores y rendimiento

- **Caché de consultas**: Las respuestas de GitHub se cachean durante el tiempo configurado (por defecto 12h).
- **Rate limiting**: Backoff automático y respeto de límites de GitHub. Sin token: ~60 req/h. Con token: ~5000 req/h.
- **Timeouts y reintentos**: Configurables. Backoff exponencial en reintentos.
- **Múltiples fuentes de datos HACS**: Si una fuente falla, intenta la siguiente automáticamente.
- **Modo degradado**: Sin token de GitHub, se obtiene menos información pero la integración sigue funcional.

## Estructura del proyecto

```
hacs-compatibility-auditor/
├── custom_components/
│   └── hacs_compatibility_auditor/
│       ├── __init__.py          # Integración principal y servicio
│       ├── manifest.json        # Manifest de HA
│       ├── config_flow.py       # Flujo de configuración
│       ├── const.py             # Constantes
│       ├── strings.json         # Traducciones
│       ├── services.yaml        # Definición del servicio
│       ├── coordinator.py       # DataUpdateCoordinator
│       ├── github_client.py     # Cliente API de GitHub
│       ├── hacs_repository.py   # Lector de datos HACS
│       ├── compatibility.py     # Lógica de compatibilidad
│       └── sensor.py            # Entidades sensor
├── hacs-compatibility-auditor-card/
│   ├── src/
│   │   ├── index.ts
│   │   ├── hacs-compatibility-auditor-card.ts
│   │   └── types.ts
│   ├── dist/                    # Build compilado
│   ├── package.json
│   ├── tsconfig.json
│   └── webpack.config.js
├── tests/
│   ├── __init__.py
│   ├── test_compatibility.py
│   ├── test_github_client.py
│   └── test_sensor.py
├── hacs.json
└── README.md
```

## Requisitos

- Home Assistant >= 2024.1.0
- HACS instalado y configurado
- Conexión a Internet (para consultar GitHub API)
- Token de GitHub (opcional pero recomendado)

## Licencia

MIT
