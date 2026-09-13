-- Ampliación segura para una base C1Tesoreria existente.
-- Crea catálogo, reportes de faltantes y calendario laboral; no borra datos.
USE [C1Tesoreria];
GO
IF OBJECT_ID(N'dbo.product_catalog', N'U') IS NULL
BEGIN
CREATE TABLE product_catalog (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    company_id VARCHAR(36) NOT NULL FOREIGN KEY REFERENCES companies(id),
    user_id VARCHAR(36) NOT NULL FOREIGN KEY REFERENCES app_users(id),
    sku NVARCHAR(80) NOT NULL,
    name NVARCHAR(160) NOT NULL,
    supplier NVARCHAR(160) NOT NULL,
    stock_on_hand NUMERIC(19,4) NOT NULL,
    average_daily_demand NUMERIC(19,4) NOT NULL,
    unit_cost NUMERIC(19,4) NOT NULL,
    lead_time_days INTEGER NOT NULL,
    incoming_units NUMERIC(19,4) NOT NULL,
    safety_stock_units NUMERIC(19,4) NOT NULL,
    minimum_order_units NUMERIC(19,4) NOT NULL,
    order_multiple NUMERIC(19,4) NOT NULL,
    unit_price NUMERIC(19,4) NULL,
    payment_terms_days INTEGER NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    CONSTRAINT uq_product_catalog_company_sku UNIQUE(company_id,sku)
);
CREATE INDEX ix_product_catalog_company_id ON product_catalog(company_id);
END;
GO
IF OBJECT_ID(N'dbo.product_stockout_reports', N'U') IS NULL
BEGIN
CREATE TABLE product_stockout_reports (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    company_id VARCHAR(36) NOT NULL FOREIGN KEY REFERENCES companies(id),
    product_id VARCHAR(36) NOT NULL FOREIGN KEY REFERENCES product_catalog(id),
    user_id VARCHAR(36) NOT NULL FOREIGN KEY REFERENCES app_users(id),
    occurred_on DATE NOT NULL,
    missing_units NUMERIC(19,4) NOT NULL,
    note NVARCHAR(500) NOT NULL,
    created_at DATETIME NOT NULL,
    CONSTRAINT ck_stockout_positive CHECK(missing_units>0)
);
CREATE INDEX ix_product_stockout_reports_company_id ON product_stockout_reports(company_id);
CREATE INDEX ix_product_stockout_reports_product_id ON product_stockout_reports(product_id);
CREATE INDEX ix_product_stockout_reports_occurred_on ON product_stockout_reports(occurred_on);
END;
GO
IF OBJECT_ID(N'dbo.company_work_schedules', N'U') IS NULL
BEGIN
CREATE TABLE company_work_schedules (
    company_id VARCHAR(36) NOT NULL PRIMARY KEY FOREIGN KEY REFERENCES companies(id),
    working_weekdays VARCHAR(20) NOT NULL,
    updated_at DATETIME NOT NULL
);
END;
GO
IF OBJECT_ID(N'dbo.company_non_working_days', N'U') IS NULL
BEGIN
CREATE TABLE company_non_working_days (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    company_id VARCHAR(36) NOT NULL FOREIGN KEY REFERENCES companies(id),
    event_date DATE NOT NULL,
    label NVARCHAR(160) NOT NULL,
    created_at DATETIME NOT NULL,
    CONSTRAINT uq_non_working_company_date UNIQUE(company_id,event_date)
);
CREATE INDEX ix_company_non_working_days_company_id ON company_non_working_days(company_id);
CREATE INDEX ix_company_non_working_days_event_date ON company_non_working_days(event_date);
END;
GO
