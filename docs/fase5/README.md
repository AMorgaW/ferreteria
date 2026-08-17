# Fase 5 — Caja, roles y schema de estación

5A y 5B son software/operación. No son Fase 6, no tocan `ferreteria.db` comercial y no ejecutan inventario ni caja reales.

**5A:** Caja administrativa (ADMIN/GERENTE) y Caja restringida (VENDEDOR/EMPLEADO). El acceso materializa defensivamente el schema 3D si falta. Ver el contrato de caja en [CASH_OPERATIONS.md](../fase3/CASH_OPERATIONS.md).

**5B:** lifecycle versionado de migraciones SQLite (backup → latest) para cerrar F5-H1/H2. Ver [FASE5B.md](FASE5B.md).

No existe `FASE5_FINAL.md` en 5B.

- [FASE5B.md](FASE5B.md) — migration lifecycle, backup-before-migrate, cutover 010
