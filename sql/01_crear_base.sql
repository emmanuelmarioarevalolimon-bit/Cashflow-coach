-- Ejecutar una sola vez con una cuenta administradora en SQL Server Management Studio.
-- No borra bases, tablas ni datos existentes. Cambia el nombre aquí y en .env si hace falta.
USE master;
GO
IF DB_ID(N'C1Tesoreria') IS NULL
BEGIN
    CREATE DATABASE [C1Tesoreria];
END;
GO
-- Concede permisos a una identidad de aplicación, no a sa.
-- Para instalar el esquema: ejecuta 02_esquema_inicial.sql en C1Tesoreria con un administrador.
-- Para la app, concede SELECT, INSERT, UPDATE, DELETE sobre sus tablas a su usuario.
-- No abras el puerto SQL a internet. SQL Server Management Studio NO es el motor SQL Server.
