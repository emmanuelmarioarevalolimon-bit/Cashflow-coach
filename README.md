# COMPRIA

Para desplegarla en Render con el dominio `compria.tech`, consulta [docs/DEPLOY_RENDER.md](docs/DEPLOY_RENDER.md).

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
AI_ASSISTANT_INSTRUCTIONS_FILE=assistant_instructions.txt
```

`DB_SERVER` debe ser el nombre que realmente utilizas en tu administrador SQL. `localhost\SQLEXPRESS` es solo un ejemplo posible. Con autenticación SQL usa `DB_AUTH=sql` y credenciales de una cuenta específica del piloto, no `sa`.

La conexión solicita cifrado. Para desarrollo local con certificado autofirmado puedes optar expresamente por `DB_TRUST_SERVER_CERTIFICATE=yes`, entendiendo que omite validar el certificado; no lo uses como solución de producción.

Pega una clave privada nueva exclusivamente después de `AI_API_KEY=` en el Bloc de notas. Guarda `.env`, no `.env.txt`. La clave no va en HTML, en un comando visible, en un informe ni en este chat. Una clave expuesta debe reemplazarse. La configuración local tiene prioridad sobre variables AI heredadas.

La aplicación usa el endpoint de compatibilidad de **Google**; el segmento `/openai/` no implica enviar la petición a OpenAI. El modelo se puede cambiar en `.env`. La disponibilidad, cuota y permisos de tu cuenta se comprueban con **Probar Gemini**, no leyendo la configuración. Esa prueba consume cuota.

Si esa vía devuelve HTTP 502, 503 o 504, el chat y los análisis estructurados hacen un único intento de recuperación por `generateContent`, la API nativa de Google, con el mismo modelo, instrucciones y datos. Ambos intentos cuentan en los límites locales y comparten el tiempo máximo configurado. No se reintentan errores de clave, permisos o cuota ni se generan respuestas locales. Si las dos vías fallan, se muestra el error. La prueba de conexión puede consumir hasta cuatro llamadas si también necesita corregir una propuesta.

El chat muestra Markdown y fórmulas LaTeX de forma segura. `assistant_instructions.txt` contiene el estilo académico editable y se vuelve a leer en cada consulta. Para crear la clave, probar instrucciones de sistema en Google AI Studio y llevar el estilo elegido a la aplicación, sigue [docs/CONFIGURAR_GEMINI_Y_ESTILO_ACADEMICO.md](docs/CONFIGURAR_GEMINI_Y_ESTILO_ACADEMICO.md).

No se incluye un formulario web para guardar secretos ni se utiliza la clave en el navegador. Los informes, el chat y la extracción documental llaman al backend autenticado.

## Recorrido de la web

1. Crea una cuenta del prototipo; la contraseña tiene al menos 12 caracteres. No uses tu contraseña bancaria. Ya no hay login falso.
2. En **Documentos e historial**, sube CSV, XLSX, PDF con texto, DOCX o TXT. La carga conserva y extrae el archivo localmente; no envía nada a Google ni confirma movimientos por sí sola.
3. Autoriza Gemini si necesitas interpretar el documento. El modo analista clasifica también contratos, políticas, inventarios y otros archivos con valor financiero indirecto; Python calcula caja, estadística descriptiva, concentración y escenarios. Si proporcionas juntos saldo inicial y umbral, ejecuta Monte Carlo y presenta probabilidades condicionadas a los supuestos. Puedes declarar una probabilidad común de cobro solo para esa simulación; Gemini no la estima ni se guarda como hecho confirmado. Revisa las propuestas y sus fuentes; confirma los datos para incorporarlos al historial. Las ventas y utilidades no se suman como caja.
4. Opcionalmente activa **contexto externo vigente**. Gemini usa Google Search para consultar fuentes públicas y entrega enlaces citables; por privacidad, esa búsqueda recibe solo la moneda y un foco genérico, nunca el texto, los nombres o los montos del documento. Puede consumir cuota adicional y un fallo de búsqueda se muestra sin invalidar los cálculos locales.
5. Abre **Predicción avanzada**. El botón **Ejecutar ejemplo completo** carga y calcula datos sintéticos sin una clave de IA. El ejemplo mantiene fechas fijas de marzo a septiembre de 2026; no se importa al libro de tu empresa.
6. Para datos propios, indica comienzo del historial, fecha de pronóstico, saldo y umbral; pulsa **Tomar historial confirmado de mi empresa**. Revisa la agenda propuesta y confirma cobertura completa. Los días sin filas no se consideran automáticamente cero.
7. Selecciona horizonte, simulaciones y modelo; pulsa **Calcular y guardar predicción**. Python genera curvas, probabilidades, recurrencias y comparación de acciones, y guarda una nueva versión en la base.
8. En el copiloto de esa predicción, autoriza el envío del resumen a Google. Pregunta sobre resultados o solicita un horizonte, umbral o retraso de cobro. Gemini propone; **Confirmar y recalcular con Python** crea una nueva versión y actualiza la gráfica. No altera el historial original.
9. Genera un informe con autorización separada. La narrativa usa Gemini; las tablas numéricas del HTML se obtienen del resultado guardado. El informe queda en el historial de informes. Puedes imprimirlo a PDF desde el navegador.

### Revisión de la agenda y acciones

El panel **Agenda, acciones y configuración avanzada** contiene el contrato JSON completo del motor. Puedes revisar o añadir `candidate_actions`, probabilidades de cobro, muestras de retraso y los parámetros de cópula. La interfaz no inventa estas observaciones a partir de textos ni equipara `confidence` del motor viejo con una probabilidad estadística.

Al construir desde historial, los pendientes de contraparte/dirección/categoría coincidentes se proponen como reemplazos (`history_series_key`, `replaces_on`), no como movimientos adicionales. Para una serie sin periodicidad esto excluye toda la serie del modelo de fondo: debes aportar su agenda completa. Revisa esa conciliación antes de calcular; no es conciliación automática de facturas pagadas. Los vencidos anteriores al inicio no se incluyen automáticamente.

El chat admite explícitamente explicación de resultados, horizonte, umbral y retraso total de un cobro identificado. No es un agente general: no ejecuta SQL, no genera código ejecutable, no inventa créditos, no edita historia y no prepara automáticamente todas las combinaciones financieras posibles. Para otras acciones usa el JSON y revisa costos y devolución del principal. Una propuesta estructuralmente válida todavía puede interpretar mal la solicitud; revisa antes de confirmar.

### Compra de mercancía y calendario financiero

Después de abrir o calcular una predicción, el panel **Compra de mercancía** permite capturar hasta 30 artículos. Python calcula posición de inventario, punto de reorden, objetivo de cobertura, pedido mínimo y múltiplo de compra. Las necesidades se priorizan por riesgo de desabasto y margen declarado.

La pantalla explica expresamente que compara la predicción del flujo de caja sin compra contra el flujo recalculado con los pagos de compra. Al analizar, cada producto se crea o actualiza en el catálogo privado de la empresa con nombre, SKU, proveedor e hipótesis operativas. El usuario puede registrar por fecha las unidades solicitadas que faltaron. Un estimador local y auditable pondera más los faltantes recientes, calcula ajuste y fluctuación sobre la demanda base, y utiliza el extremo conservador para la siguiente recomendación. No usa Gemini para inventar demanda.

La recomendación no utiliza el saldo mediano como presupuesto libre. Para cada fecha de pago exige que el costo acumulado, redondeado a centavos, quepa en `qLow - umbral - reserva adicional` durante todos los cierres posteriores del horizonte. Luego incorpora las compras recomendadas como egresos ciertos y vuelve a ejecutar el mismo motor de cash flow para mostrar el riesgo antes y después. **Confirmar y guardar** crea otra versión; no emite órdenes, no paga proveedores y no modifica el historial confirmado. La confirmación reutiliza durante cinco minutos el cálculo exacto de la vista previa; si no está disponible, el servidor lo recalcula. Las compras son incrementales: si el gasto ya está implícito en una recurrencia histórica, debe reconciliarse para no duplicarlo.

El **Calendario financiero** combina movimientos realizados, cobros/pagos pendientes, eventos de la predicción seleccionada y los hitos de ordenar, recibir y pagar una compra. Los eventos proyectados y confirmados permanecen identificados por separado. La empresa configura sus días de venta y cierres particulares; esos días aparecen como **No laborables** y aportan venta esperada cero al cálculo de reposición. Si un plazo de pago queda fuera de la predicción, el algoritmo pide ampliar el horizonte en vez de tratarlo como caja disponible.

Si Gemini falla, aparece un error. No se sustituye por un párrafo local presentado como IA. Un error no revoca ni borra el último cálculo guardado.

## Datos y límites

El motor avanzado conserva su implementación original: recurrencia, media estacional, STL, SARIMA/Holt-Winters, simulación, cuantiles, riesgo y optimización. No se vuelve a desarrollar la matemática en JavaScript. La página distingue probabilidad de terminar bajo el umbral y probabilidad de cruzarlo en algún cierre diario.

La banda es de cuantiles **marginales diarios**: por ejemplo, 5%–95% cubre 90% marginal, no 95% y no toda la trayectoria simultáneamente. La simulación no captura todos los cambios estructurales ni certifica la precisión futura. El riesgo de cero observaciones en simulaciones no significa riesgo real nulo. La recomendación es la elegida entre acciones declaradas, no entre todas las posibles.

Límites del módulo web: 1500 movimientos históricos, hasta dos años de cobertura, 150 eventos pendientes, 8 acciones candidatas y 4 acciones de escenario; 1–365 días, 100–10 000 simulaciones y como máximo 2 millones de celdas (días × simulaciones); hasta dos acciones en una combinación. Un cálculo simultáneo por proceso. Las funciones HTTP de cálculo son síncronas y trabajan fuera del bucle asíncrono de FastAPI; no es una cola distribuida con cancelación o límites duros de tiempo. SARIMA y selección automática pueden tardar más. Usa 1000 simulaciones y STL para la primera prueba.

La etiqueta de procedencia de un análisis refleja el origen declarado de una entrada editable; **no certifica que el JSON sea idéntico al documento**. Las predicciones se guardan como snapshots con entradas y resultados. Los informes no recalculan las predicciones estadísticas al redactarse: conservan el ID y la fecha de la versión fuente.

La extracción documental conserva los límites del piloto anterior: 10 MB; PDF con texto (no escaneado ni imágenes de gráficos), DOCX/TXT y tablas CSV/XLSX. Los archivos originales se guardan en la base. No se ejecutan macros ni fórmulas. La interpretación de documentos puede perder estructura y necesita revisión humana. El puntaje de suficiencia es una heurística de cobertura, no confianza del modelo. Las probabilidades del documento requieren saldo y umbral, y asumen cobros independientes con las confianzas editables declaradas; para series históricas, estacionalidad y simulaciones avanzadas utiliza **Predicción avanzada**.

## Almacenamiento y compatibilidad

Las nuevas predicciones usan `analysis_runs` con `engine_version=predictive-6.0-web`. El catálogo, los faltantes y el calendario laboral usan `product_catalog`, `product_stockout_reports`, `company_work_schedules` y `company_non_working_days`, siempre separados por empresa. Para una base SQL Server existente, respáldala y ejecuta `sql/03_catalogo_demanda_calendario.sql` con un administrador; para una base nueva, `sql/02_esquema_inicial.sql` ya contiene las tablas. Los planes deterministas continúan separados. `init_db()` crea tablas faltantes solo cuando la cuenta de aplicación tiene ese permiso; no sustituye una migración administrada.

Para reutilizar tu base del piloto, respáldala primero, usa una carpeta nueva para el código y configura los mismos datos de conexión. No copies `.venv` o `__pycache__` de una versión anterior. No incluyas tus credenciales en el ZIP. Las cuentas y documentos están en la base, no en el código. Usar otro archivo SQLite o instancia SQL abre una base distinta, no recupera automáticamente el historial.

## Código principal

- `app/engine/predictive_engine.py`: copia del motor avanzado entregado anteriormente.
- `app/engine/demand_engine.py`: estimación ponderada y fluctuación de demanda no atendida por día laborable.
- `app/predictions.py`: validación, puente a la base, ejecución, snapshots, propuestas Gemini, confirmación e informes.
- `app/static/predictions.html`, `css/predictions.css`, `js/predictions.js`: interfaz nueva conectada a las rutas del mismo servidor.
- `app/main.py`: registro de la página y API, autenticación y protecciones existentes.
- `app/document_ai.py`: extracción e informes, transportador Gemini compartido.
- `app/document_analysis.py`: cálculos auditables del modo analista documental, escenarios y Monte Carlo condicionado.
- `app/workspace.py`: documentos/historia/planes antiguos e informes con tabla predictiva.
- `iniciar.py`: instalación local y configuración mediante Bloc de notas.

Rutas nuevas, todas requieren sesión:

```
GET  /predictions
GET  /api/predictions/demo-input
POST /api/predictions/from-history
POST /api/predictions/analyze
GET  /api/predictions
GET  /api/predictions/catalog
POST /api/predictions/catalog/products
POST /api/predictions/catalog/stockouts
PUT  /api/predictions/work-schedule
GET  /api/predictions/{id}
GET  /api/predictions/{id}/download
POST /api/predictions/{id}/purchases/preview
POST /api/predictions/{id}/purchases/apply
POST /api/predictions/{id}/assistant
POST /api/predictions/{id}/apply
POST /api/predictions/{id}/report
GET  /api/calendar?start=AAAA-MM-DD&end=AAAA-MM-DD&predictionId={id}
```

Las escrituras JSON requieren `X-C1-Request: 1`, comprobación de origen cuando corresponde y sesión autenticada. El cliente web ya los envía. El ID de empresa se obtiene de la sesión, no se acepta del navegador. La documentación Swagger es una herramienta de desarrollo; sus llamadas también están sujetas a esos encabezados.

## Validación y límites de entrega

Ver `pruebas/ALCANCE.txt`. La suite automatizada contiene 197 pruebas de Python/API, incluidas las reglas de compra, catálogo, estimación por faltantes, calendario laboral, precisión monetaria, continuidad de la curva y entradas numéricas extremas, además de las comprobaciones DOM y HTTP documentadas. SQLite temporal y Gemini simulado en pruebas; motor estadístico real. No se utilizó una clave real, ni una instancia real de SQL Server. No se validó el iniciador en Windows; las instrucciones y ramas de Windows requieren prueba allí.

La navegación HTTP de Chromium hacia localhost fue bloqueada por la política del entorno. No se desactivó. La prueba DOM cargó HTML/CSS/JS reales en memoria y conectó fetch a TestClient; esa prueba NO equivale a navegación end-to-end real. Se conserva el registro del intento fallido y el script opcional para ejecutarlo en otro entorno.

`C1_PUBLIC_MODE=1` continúa bloqueando la publicación. Antes de datos reales por internet se necesitan auditoría de seguridad, HTTPS, autorizaciones empresariales, backups restaurables, autenticación/recuperación completas, retención, protección de parsers, límites persistentes y evaluación del modelo. No se entregan como resueltos. Usa documentos sintéticos o anonimizados hasta revisar las condiciones de tratamiento de datos de Gemini y la autorización de la empresa.

## Documentación técnica consultada

- Gemini, compatibilidad y salida estructurada: https://ai.google.dev/gemini-api/docs/openai
- Gemini, herramientas y ejecución de funciones: https://ai.google.dev/gemini-api/docs/tools
- Gemini, fundamentación con Google Search: https://ai.google.dev/gemini-api/docs/google-search
- Gemini, límites de las salidas estructuradas: https://ai.google.dev/gemini-api/docs/generate-content/structured-output
- FastAPI, operaciones síncronas y concurrencia: https://fastapi.tiangolo.com/async/
- Gemini, modelos: https://ai.google.dev/gemini-api/docs/models

Las credenciales, la disponibilidad y la cuota de tu proyecto son configuraciones de tu equipo; el código descargado no conecta tu cuenta por sí solo.
