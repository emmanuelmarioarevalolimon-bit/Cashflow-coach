# Fuentes técnicas oficiales

Consultadas el 12 de septiembre de 2026. Las decisiones y límites específicos del piloto se documentan en el README; estas fuentes no certifican el código generado.

- SQLAlchemy: dialecto Microsoft SQL Server, pyodbc y tipos SQL.
  https://docs.sqlalchemy.org/en/20/dialects/mssql.html
- Microsoft: ODBC Driver 18 para SQL Server, instalación por separado.
  https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server?view=sql-server-ver17
- Microsoft: Encrypt y TrustServerCertificate.
  https://learn.microsoft.com/en-us/sql/connect/odbc/dsn-connection-string-attribute?view=sql-server-ver17
- Google: compatibilidad con Chat Completions (las solicitudes van al dominio de Google).
  https://ai.google.dev/gemini-api/docs/openai
- Google: modelo configurable Gemini 3.8 Flash.
  https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash
- Google: salida estructurada; JSON válido no garantiza semántica correcta.
  https://ai.google.dev/gemini-api/docs/generate-content/structured-output
- Google: tratamiento de datos y restricciones de servicios gratuitos/pagados.
  https://ai.google.dev/gemini-api/terms
- FastAPI: archivos y UploadFile.
  https://fastapi.tiangolo.com/tutorial/request-files/
- OWASP: carga de archivos. En producción faltan antivirus y aislamiento de parsers.
  https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html
- OWASP: almacenamiento de contraseñas.
  https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html

El motor original proviene del archivo del usuario algoritmo_budget(1).py. Su SHA-256 se conserva en sources/ALGORITMO-ORIGINAL.sha256. Este modelo usa ingresos ponderados por confianza, no intervalos estadísticos; consulta su docstring y el README.
