# Configurar Gemini y el estilo académico

La aplicación llama a Gemini desde FastAPI, no desde el navegador. La clave permanece en `.env` y nunca forma parte del HTML ni de la conversación.

## 1. Crear la clave en Google AI Studio

1. Abre [Google AI Studio](https://aistudio.google.com/) e inicia sesión.
2. En el panel, entra a **Dashboard → Projects**. Selecciona un proyecto o usa **Import projects** para incorporar uno existente de Google Cloud.
3. Entra a **API Keys** y crea una clave para ese proyecto. Usa una clave de autorización (**Auth key**), que es el tipo actual creado por AI Studio.
4. Conserva la clave en un gestor de secretos. No la pegues en el navegador, en archivos JavaScript, en GitHub ni en una conversación.
5. En la carpeta de C1 Tesorería ejecuta:

   ```powershell
   python .\iniciar.py --configure
   ```

6. En el `.env` que se abre, completa únicamente el valor secreto:

   ```env
   AI_API_URL=https://generativelanguage.googleapis.com/v1beta/openai/chat/completions
   AI_API_KEY=PEGA_AQUI_LA_CLAVE
   AI_MODEL=gemini-3.8-flash
   AI_TIMEOUT_SECONDS=60
   AI_ASSISTANT_INSTRUCTIONS_FILE=assistant_instructions.txt
   ```

7. Guarda `.env`, inicia la aplicación con `python .\iniciar.py`, inicia sesión y pulsa **Probar Gemini**. La prueba hace una solicitud real y consume cuota.

Cada clave pertenece a un proyecto de Google Cloud; el proyecto controla acceso, cuota y facturación. Si recibes `401` o `403`, revisa la clave y permisos. Para `429`, revisa la cuota del proyecto. Consulta la guía oficial de [claves de Gemini](https://ai.google.dev/gemini-api/docs/api-key) y la guía del [endpoint compatible con OpenAI](https://ai.google.dev/gemini-api/docs/openai).

## 2. Afinar el diálogo en AI Studio

En la Gemini API y AI Studio no hay actualmente un modelo disponible para *fine-tuning* de pesos. Para este caso se debe hacer **ajuste de instrucciones** (*prompt tuning*): probar una instrucción de sistema y copiar la versión elegida a la aplicación. Google documenta esta situación en [Fine-tuning with the Gemini API](https://ai.google.dev/gemini-api/docs/model-tuning/).

1. En AI Studio crea un prompt de tipo **Chat**.
2. Selecciona el mismo modelo indicado por `AI_MODEL`.
3. Abre **System instructions**.
4. Copia allí todo el contenido de `assistant_instructions.txt`.
5. Prueba preguntas representativas, por ejemplo:

   - “Explica la diferencia entre riesgo terminal y riesgo de cruzar el umbral en algún día.”
   - “Define el déficit de liquidez y expresa su cálculo con una ecuación.”
   - “Resume los supuestos, la evidencia y las limitaciones en tres apartados.”

6. Evalúa cada respuesta con criterios concretos: precisión, definición de términos, separación entre dato y supuesto, concisión, unidades, claridad de fórmulas y reconocimiento de límites.
7. Modifica solamente las instrucciones de estilo hasta obtener el registro deseado. No elimines las reglas finales que subordinan el estilo a la seguridad y a la validación financiera.
8. Copia la versión final a `assistant_instructions.txt` y guarda el archivo en UTF-8. La siguiente consulta del chat la usa automáticamente; no es necesario volver a crear la clave.

Guardar un prompt en AI Studio **no sincroniza** esa instrucción con esta aplicación. El paso de copiarla al archivo local es deliberado para que el comportamiento quede versionado y revisable. La guía oficial de [AI Studio](https://ai.google.dev/gemini-api/docs/ai-studio-quickstart) explica cómo probar y modificar instrucciones de sistema.

## 3. Markdown y matemáticas

Las respuestas de Gemini aceptan Markdown: párrafos, títulos, énfasis, listas, citas, tablas, enlaces y bloques de código. El HTML crudo se limpia antes de insertarlo en la página; scripts, formularios, imágenes remotas y atributos peligrosos se descartan.

Para evitar confundir el símbolo monetario `$` con una fórmula, se recomienda pedir estos delimitadores:

```text
En línea: \( E[X] = \sum_i p_i x_i \)

Bloque:
\[
P(L < u) = \frac{1}{N}\sum_{j=1}^{N}\mathbf{1}(L_j < u)
\]
```

El chat también reconoce `$...$` y bloques `$$...$$`, pero `\(...\)` y `\[...\]` son más seguros en una aplicación financiera. El renderizado usa copias locales de Marked, DOMPurify y KaTeX; no depende de una CDN.

## 4. Qué sí cambia el archivo de estilo

`assistant_instructions.txt` controla tono, organización, nivel pedagógico y formato de las interpretaciones. No puede autorizar pagos, modificar el esquema JSON, evitar la confirmación del usuario ni sustituir los cálculos de Python.

En el análisis documental puede activarse **contexto externo vigente**. Esta opción usa la API nativa de Interactions con la herramienta Google Search, además del endpoint compatible con OpenAI usado para las salidas JSON. La búsqueda recibe únicamente la moneda base y un foco genérico (por ejemplo, tesorería, operaciones o impuestos): no recibe el texto, nombres ni montos del archivo. Los enlaces devueltos se muestran como recursos y el resultado fundamentado se entrega a Gemini junto con los cálculos de Python. Esta función puede generar consultas facturables adicionales y depende de que `AI_MODEL` admita Google Search.

Para cambiar de archivo, indica una ruta relativa dentro de la carpeta del proyecto:

```env
AI_ASSISTANT_INSTRUCTIONS_FILE=mis_instrucciones_academicas.txt
```

El archivo debe estar en UTF-8, no estar vacío y medir como máximo 16 KB. Por seguridad, no se aceptan rutas fuera de la carpeta de la aplicación.
