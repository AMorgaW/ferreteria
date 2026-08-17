# Fase 5 — Caja, roles y schema de estación

5A, 5B y 5C son software/operación. No son Fase 6, no tocan `ferreteria.db` comercial y no ejecutan inventario ni caja reales.

**5A:** Caja administrativa (ADMIN/GERENTE) y Caja restringida (VENDEDOR/EMPLEADO). El acceso materializa defensivamente el schema 3D si falta. Ver el contrato de caja en [CASH_OPERATIONS.md](../fase3/CASH_OPERATIONS.md).

**5B:** lifecycle versionado de migraciones SQLite (backup → latest) para cerrar F5-H1/H2. Ver [FASE5B.md](FASE5B.md).

**5C:** hardening del writer LAN legacy (F5-M1) y warning seguro de rehash PBKDF2 (F5-L1). Decisión: **LAN DISABLED** como writer comercial. Ver [FASE5C.md](FASE5C.md).

No existe `FASE5_FINAL.md` en 5C.

- [FASE5B.md](FASE5B.md) — migration lifecycle, backup-before-migrate, cutover 010
- [FASE5C.md](FASE5C.md) — LAN disabled, auth rehash warning safe
