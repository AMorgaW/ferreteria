# Fase 5 — Pre-inventory stabilization

**Estado final: COMPLETE — FINAL ACCEPTANCE GO.**

FERREPRO queda **READY FOR PRODUCT CATALOG / INVENTORY PREPARATION**. Esto no
significa que productos, Excel o inventario comerciales hayan sido cargados,
ni que exista cutover o deployment comercial.

5A, 5B y 5C son software/operación. No son Fase 6, no tocan `ferreteria.db` comercial y no ejecutan inventario ni caja reales.

**5A:** Caja administrativa (ADMIN/GERENTE) y Caja restringida (VENDEDOR/EMPLEADO). El acceso materializa defensivamente el schema 3D si falta. Ver el contrato de caja en [CASH_OPERATIONS.md](../fase3/CASH_OPERATIONS.md).

**5B:** lifecycle versionado de migraciones SQLite (backup → latest) para cerrar F5-H1/H2. Ver [FASE5B.md](FASE5B.md).

**5C:** hardening del writer LAN legacy (F5-M1) y warning seguro de rehash PBKDF2 (F5-L1). Decisión: **LAN DISABLED** como writer comercial. Ver [FASE5C.md](FASE5C.md).

**5D:** aceptación final de 5A + 5B + 5C e integración dirigida con Fases 1–4. **GO.** Ver [FASE5_FINAL.md](FASE5_FINAL.md).

- [FASE5B.md](FASE5B.md) — migration lifecycle, backup-before-migrate, cutover 010
- [FASE5C.md](FASE5C.md) — LAN disabled, auth rehash warning safe
- [FASE5_FINAL.md](FASE5_FINAL.md) — final pre-inventory acceptance, GO
