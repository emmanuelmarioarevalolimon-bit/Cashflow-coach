# Hospedar COMPRIA desde esta laptop

COMPRIA usa SQLite en `local-demo.db`, escucha solamente en `127.0.0.1:8765` y se publica mediante Cloudflare Tunnel. No es necesario abrir puertos en el router.

## Probar ahora con una dirección temporal

Desde la carpeta del proyecto:

```bash
./HOST_COMPRIA.sh --quick
```

Cloudflare imprimirá una dirección temporal `https://...trycloudflare.com`. La dirección deja de funcionar al cerrar el proceso.

## Conectar compria.tech de forma permanente

1. Añade `compria.tech` a Cloudflare y cambia en el registrador los servidores DNS por los que Cloudflare indique.
2. En el panel de Cloudflare abre **Networking → Tunnels**, crea un túnel llamado `compria-laptop` y elige la opción administrada desde Cloudflare.
3. En el túnel añade una aplicación publicada con hostname `compria.tech` y servicio `http://localhost:8765`.
4. Copia solamente el token del comando de instalación y guárdalo en `.cloudflare-tunnel-token`, en una sola línea. Este archivo está excluido de Git.
5. Ejecuta `chmod 600 .cloudflare-tunnel-token` y después `./HOST_COMPRIA.sh`.

La laptop debe permanecer encendida, despierta y conectada. Conserva copias de seguridad de `local-demo.db`; ahí están las cuentas, documentos y cálculos. `COOKIE_SECURE=1` y `ALLOW_REGISTRATION=0` ya están configurados en el archivo privado `.env` para el acceso público por HTTPS.
