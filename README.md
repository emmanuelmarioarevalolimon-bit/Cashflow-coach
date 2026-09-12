# C1 Tesorería 6.0 — página web integrada

**Versión:** `6.0.0-web-integrada`. Piloto local independiente, sin conexión a cuentas bancarias ni movimientos reales de dinero. Esta entrega integra los archivos de `c1-tesoreria-sqlserver` con el motor histórico de `motor-predictivo-completo`; no obliga a levantar la API separada en el puerto 8787.

## Abrir desde PowerShell

### Opción A: un solo archivo

`ABRIR_C1_WEB.py` contiene una copia comprimida de todo el proyecto. Requiere Python; no es un ejecutable `.exe`. Al ejecutarlo, extrae una copia independiente bajo `%LOCALAPPDATA%\C1Tesoreria\6.0.0-web-integrada` (en Windows), y utiliza su propio entorno virtual. No busca carpetas recursivamente en Descargas, no borra instalaciones anteriores y no incluye claves.

Ejecuta desde la carpeta donde guardaste el archivo:

```powershell
python .\ABRIR_C1_WEB.py --configure
python .\ABRIR_C1_WEB.py
```

El primer comando abre `.env` en el Bloc de notas **sin instalar dependencias primero**. Allí configura SQL Server y Gemini. El segundo prepara dependencias e inicia el servidor. La primera instalación necesita acceso a los repositorios de paquetes de Python.

Para una prueba sin SQL Server, elige explícitamente SQLite en una instalación nueva:

```powershell
python .\ABRIR_C1_WEB.py --demo-local
```

Este modo crea `.env` con SQLite **solo si todavía no existe**. No reemplaza un `.env` ya configurado ni cambia de base cuando SQL Server falla. La web identifica SQLite como prueba local. Se puede abrir después `--configure` para editar la conexión y la clave. Cambiar el tipo de base NO migra los datos.

### Opción B: código completo en ZIP

Extrae `c1-web-integrada.zip` completo en una carpeta nueva. Los archivos del ZIP están directamente en la raíz, sin `.venv`, cachés ni carpeta adicional del mismo nombre. Abre esa carpeta en PowerShell y ejecuta:

```powershell
python .\iniciar.py --configure
python .\iniciar.py
```

También admite `python .\iniciar.py --demo-local` (opción explícita de prueba) y `python .\iniciar.py --check-db`. La carpeta correcta contiene `iniciar.py` y `requirements.txt`. No escribas solo la ruta como si fuera un comando: usa `cd "ruta"` para entrar.

## Configuración

La plantilla predeterminada conserva SQL Server. Necesitas una instancia accesible, una base exclusiva para el piloto y Microsoft ODBC Driver 18. Usa los scripts `sql/01_crear_base.sql` y `sql/02_esquema_inicial.sql` con los permisos apropiados; no ejecutes scripts administrativos contra una base empresarial existente sin revisión.

```env
DB_BACKEND=mssql
DB_SERVER=TU_INSTANCIA_REAL
DB_DATABASE=C1Tesoreria
DB_DRIVER=ODBC Driver 18 for SQL Server
DB_AUTH=windows
DB_USER=
DB_PASSWORD=
DB_TRUST_SERVER_CERTIFICATE=no
AI_API_URL=https://generativelanguage.googleapis.com/v1beta/openai/chat/completions
AI_API_KEY=
AI_MODEL=gemini-3.8-flash
AI_TIMEOUT_SECONDS=60
```

`DB_SERVER` debe ser el nombre que realmente utilizas en tu administrador SQL. `localhost\SQLEXPRESS` es solo un ejemplo posible. Con autenticación SQL usa `DB_AUTH=sql` y credenciales de una cuenta específica del piloto, no `sa`.

La conexión solicita cifrado. Para desarrollo local con certificado autofirmado puedes optar expresamente por `DB_TRUST_SERVER_CERTIFICATE=yes`, entendiendo que omite validar el certificado; no lo uses como solución de producción.

Pega una clave privada nueva exclusivamente después de `AI_API_KEY=` en el Bloc de notas. Guarda `.env`, no `.env.txt`. La clave no va en HTML, en un comando visible, en un informe ni en este chat. Una clave expuesta debe reemplazarse. La configuración local tiene prioridad sobre variables AI heredadas.

La aplicación usa el endpoint de compatibilidad de **Google**; el segmento `/openai/` no implica enviar la petición a OpenAI. El modelo se puede cambiar en `.env`. La disponibilidad, cuota y permisos de tu cuenta se comprueban con **Probar Gemini**, no leyendo la configuración. Esa prueba consume cuota.

No se incluye un formulario web para guardar secretos ni se utiliza la clave en el navegador. Los informes, el chat y la extracción documental llaman al backend autenticado.

## Recorrido de la web

1. Crea una cuenta del prototipo; la contraseña tiene al menos 12 caracteres. No uses tu contraseña bancaria. Ya no hay login falso.
2. En **Documentos e historial**, sube CSV, XLSX, PDF con texto, DOCX o TXT. La carga conserva y extrae el archivo localmente; no envía nada a Google ni confirma movimientos por sí sola.
3. Autoriza Gemini si necesitas interpretar el documento. Revisa las propuestas y sus fuentes; confirma los datos para incorporarlos al historial. Las ventas y utilidades no se suman como caja.
4. Abre **Predicción avanzada**. El botón **Cargar ejemplo sintético** funciona sin una clave de IA. El ejemplo mantiene fechas fijas de marzo a septiembre de 2026; no se importa al libro de tu empresa.
5. Para datos propios, indica comienzo del historial, fecha de pronóstico, saldo y umbral; pulsa **Tomar historial confirmado de mi empresa**. Revisa la agenda propuesta y confirma cobertura completa. Los días sin filas no se consideran automáticamente cero.
6. Selecciona horizonte, simulaciones y modelo; pulsa **Calcular y guardar predicción**. Python genera curvas, probabilidades, recurrencias y comparación de acciones, y guarda una nueva versión en la base.
7. En el copiloto de esa predicción, autoriza el envío del resumen a Google. Pregunta sobre resultados o solicita un horizonte, umbral o retraso de cobro. Gemini propone; **Confirmar y recalcular con Python** crea una nueva versión y actualiza la gráfica. No altera el historial original.
8. Genera un informe con autorización separada. La narrativa usa Gemini; las tablas numéricas del HTML se obtienen del resultado guardado. El informe queda en el historial de informes. Puedes imprimirlo a PDF desde el navegador.

### Revisión de la agenda y acciones

El panel **Agenda, acciones y configuración avanzada** contiene el contrato JSON completo del motor. Puedes revisar o añadir `candidate_actions`, probabilidades de cobro, muestras de retraso y los parámetros de cópula. La interfaz no inventa estas observaciones a partir de textos ni equipara `confidence` del motor viejo con una probabilidad estadística.

Al construir desde historial, los pendientes de contraparte/dirección/categoría coincidentes se proponen como reemplazos (`history_series_key`, `replaces_on`), no como movimientos adicionales. Para una serie sin periodicidad esto excluye toda la serie del modelo de fondo: debes aportar su agenda completa. Revisa esa conciliación antes de calcular; no es conciliación automática de facturas pagadas. Los vencidos anteriores al inicio no se incluyen automáticamente.

El chat admite explícitamente explicación de resultados, horizonte, umbral y retraso total de un cobro identificado. No es un agente general: no ejecuta SQL, no genera código ejecutable, no inventa créditos, no edita historia y no prepara automáticamente todas las combinaciones financieras posibles. Para otras acciones usa el JSON y revisa costos y devolución del principal. Una propuesta estructuralmente válida todavía puede interpretar mal la solicitud; revisa antes de confirmar.

Si Gemini falla, aparece un error. No se sustituye por un párrafo local presentado como IA. Un error no revoca ni borra el último cálculo guardado.

## Datos y límites

El motor avanzado conserva su implementación original: recurrencia, media estacional, STL, SARIMA/Holt-Winters, simulación, cuantiles, riesgo y optimización. No se vuelve a desarrollar la matemática en JavaScript. La página distingue probabilidad de terminar bajo el umbral y probabilidad de cruzarlo en algún cierre diario.

La banda es de cuantiles **marginales diarios**: por ejemplo, 5%–95% cubre 90% marginal, no 95% y no toda la trayectoria simultáneamente. La simulación no captura todos los cambios estructurales ni certifica la precisión futura. El riesgo de cero observaciones en simulaciones no significa riesgo real nulo. La recomendación es la elegida entre acciones declaradas, no entre todas las posibles.

Límites del módulo web: 1500 movimientos históricos, hasta dos años de cobertura, 150 eventos pendientes, 8 acciones candidatas y 4 acciones de escenario; 1–365 días, 100–10 000 simulaciones y como máximo 2 millones de celdas (días × simulaciones); hasta dos acciones en una combinación. Un cálculo simultáneo por proceso. Las funciones HTTP de cálculo son síncronas y trabajan fuera del bucle asíncrono de FastAPI; no es una cola distribuida con cancelación o límites duros de tiempo. SARIMA y selección automática pueden tardar más. Usa 1000 simulaciones y STL para la primera prueba.

La etiqueta de procedencia de un análisis refleja el origen declarado de una entrada editable; **no certifica que el JSON sea idéntico al documento**. Las predicciones se guardan como snapshots con entradas y resultados. Los informes no recalculan las predicciones estadísticas al redactarse: conservan el ID y la fecha de la versión fuente.

La extracción documental conserva los límites del piloto anterior: 10 MB; PDF con texto (no escaneado ni imágenes de gráficos), DOCX/TXT y tablas CSV/XLSX. Los archivos originales se guardan en la base. No se ejecutan macros ni fórmulas. La interpretación de documentos puede perder estructura y necesita revisión humana.

## Almacenamiento y compatibilidad

Se conserva el esquema del proyecto SQL Server v4. Las nuevas predicciones usan `analysis_runs` con `engine_version=predictive-6.0-web`. Los planes deterministas continúan separados en su página y sus endpoints. No se añadieron tablas ni se sobrescriben entradas anteriores; `init_db()` no es un mecanismo general de migraciones.

Para reutilizar tu base del piloto, respáldala primero, usa una carpeta nueva para el código y configura los mismos datos de conexión. No copies `.venv` o `__pycache__` de una versión anterior. No incluyas tus credenciales en el ZIP. Las cuentas y documentos están en la base, no en el código. Usar otro archivo SQLite o instancia SQL abre una base distinta, no recupera automáticamente el historial.

## Código principal

- `app/engine/predictive_engine.py`: copia del motor avanzado entregado anteriormente.
- `app/predictions.py`: validación, puente a la base, ejecución, snapshots, propuestas Gemini, confirmación e informes.
- `app/static/predictions.html`, `css/predictions.css`, `js/predictions.js`: interfaz nueva conectada a las rutas del mismo servidor.
- `app/main.py`: registro de la página y API, autenticación y protecciones existentes.
- `app/document_ai.py`: extracción e informes, transportador Gemini compartido.
- `app/workspace.py`: documentos/historia/planes antiguos e informes con tabla predictiva.
- `iniciar.py`: instalación local y configuración mediante Bloc de notas.

Rutas nuevas, todas requieren sesión:

```
GET  /predictions
GET  /api/predictions/demo-input
POST /api/predictions/from-history
POST /api/predictions/analyze
GET  /api/predictions
GET  /api/predictions/{id}
GET  /api/predictions/{id}/download
POST /api/predictions/{id}/assistant
POST /api/predictions/{id}/apply
POST /api/predictions/{id}/report
```

Las escrituras JSON requieren `X-C1-Request: 1`, comprobación de origen cuando corresponde y sesión autenticada. El cliente web ya los envía. El ID de empresa se obtiene de la sesión, no se acepta del navegador. La documentación Swagger es una herramienta de desarrollo; sus llamadas también están sujetas a esos encabezados.

## Validación y límites de entrega

Ver `pruebas/ALCANCE.txt`. Se ejecutaron 171 pruebas de Python/API, 11 comprobaciones DOM, un servidor Uvicorn real con HTTP local y comprobaciones de sintaxis. SQLite temporal y Gemini simulado en pruebas; motor estadístico real. No se utilizó una clave real, ni una instancia real de SQL Server. No se validó el iniciador en Windows; las instrucciones y ramas de Windows requieren prueba allí.

La navegación HTTP de Chromium hacia localhost fue bloqueada por la política del entorno. No se desactivó. La prueba DOM cargó HTML/CSS/JS reales en memoria y conectó fetch a TestClient; esa prueba NO equivale a navegación end-to-end real. Se conserva el registro del intento fallido y el script opcional para ejecutarlo en otro entorno.

`C1_PUBLIC_MODE=1` continúa bloqueando la publicación. Antes de datos reales por internet se necesitan auditoría de seguridad, HTTPS, autorizaciones empresariales, backups restaurables, autenticación/recuperación completas, retención, protección de parsers, límites persistentes y evaluación del modelo. No se entregan como resueltos. Usa documentos sintéticos o anonimizados hasta revisar las condiciones de tratamiento de datos de Gemini y la autorización de la empresa.

## Documentación técnica consultada

- Gemini, compatibilidad y salida estructurada: https://ai.google.dev/gemini-api/docs/openai
- Gemini, límites de las salidas estructuradas: https://ai.google.dev/gemini-api/docs/generate-content/structured-output
- FastAPI, operaciones síncronas y concurrencia: https://fastapi.tiangolo.com/async/
- Gemini, modelos: https://ai.google.dev/gemini-api/docs/models

Las credenciales, la disponibilidad y la cuota de tu proyecto son configuraciones de tu equipo; el código descargado no conecta tu cuenta por sí solo.
