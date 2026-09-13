# Despliegue de COMPRIA en Render

`render.yaml` crea el servicio web y una base administrada de PostgreSQL. El plan configurado es persistente y apto para una aplicación con datos; no uses la base gratuita para datos que deban conservarse, ya que caduca a los 30 días.

1. Sube estos cambios al repositorio de GitHub y entra a [Render](https://dashboard.render.com/).
2. Selecciona **New → Blueprint**, conecta el repositorio y acepta `render.yaml`.
3. Durante la creación, Render solicita tres secretos. Configura:
   - `AI_API_KEY`: la clave de Gemini.
   - `INITIAL_ADMIN_EMAIL`: tu correo para iniciar sesión.
   - `INITIAL_ADMIN_PASSWORD`: una contraseña nueva de al menos 12 caracteres.
4. Espera a que el despliegue termine y confirma que `https://<servicio>.onrender.com/health` responde `{"status":"ok",...}`. La primera cuenta se crea una sola vez; el registro público queda cerrado.
5. En el servicio, abre **Settings → Custom Domains**, añade `compria.tech` y después añade `www.compria.tech`. Render redirige una de las dos variantes a la otra y emite el certificado HTTPS automáticamente.
6. En el proveedor DNS del dominio, elimina registros `AAAA`. Para el dominio raíz, apunta `@` al registro que Render indique: usa `ALIAS`/`ANAME` hacia el subdominio `onrender.com` si tu proveedor lo admite, o el registro `A` `216.24.57.1` cuando no lo admita. Para `www`, crea un `CNAME` hacia el subdominio `onrender.com` mostrado por Render.
7. Vuelve a Render y pulsa **Verify**. Cuando el certificado termine de emitirse, entra a `https://compria.tech` e inicia sesión con la cuenta inicial.

Render mantiene el `DATABASE_URL` de PostgreSQL dentro de su red privada. No copies esa cadena ni las claves a GitHub o a archivos `.env` del repositorio.
