# -*- coding: utf-8 -*-
"""Contrato canónico de staging para inventario físico de productos.

Derivado de ``models.Producto``, ``ProductosRepository.crear_producto``,
``ui.productos_ui`` y el schema SQLite. No importa ni modifica datos.
Generador, validador y futuro importador deben consumir este módulo.
"""
from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple


HEADER_ROW = 4
DATA_START_ROW = 5
DEFAULT_BLANK_ROWS = 300
INVENTORY_ID_NAMESPACE = uuid.UUID("24cc36c1-5d71-4f1e-a259-f4f9b19d0df5")

CATEGORY_UI_VALUES = (
    "Elementos de Fijación",
    "Herrajes",
    "Pinturas",
    "Varillas/Tubos/Alambres",
    "Líquidos",
    "Productos en Polvo",
    "Herramientas Manuales",
    "Electrodomésticos y Equipos",
    "Materiales de Construcción",
    "Electricidad",
    "Plomería",
)
UNIT_UI_VALUES = ("UNIDAD", "METRO", "KILO", "LITRO", "GALÓN", "SACO")
YES_NO_VALUES = ("NO", "SI")
BARCODE_STATUS_VALUES = ("PENDIENTE", "ESCANEADO")
REGISTRATION_STATUS_VALUES = (
    "INCOMPLETO",
    "LISTO_SIN_BARCODE",
    "LISTO_COMPLETO",
    "REVISAR",
)

# Contrato operacional de captura física (Fase 2D). A diferencia del workbook
# maestro de Fase 2B, este input humano no contiene IDs técnicos ni fórmulas.
# Parser, tests, documentación y UI importan esta única definición.
OPERATIONAL_INVENTORY_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("nombre", "PRODUCTO / NOMBRE"),
    ("categoria", "CATEGORÍA"),
    ("marca", "MARCA"),
    ("precio_compra", "PRECIO DE COMPRA"),
    ("precio_venta", "PRECIO DE VENTA"),
    ("stock_minimo", "STOCK MÍNIMO"),
    ("unidad_base", "UNIDAD DE MEDIDA BASE"),
    ("presentacion_empaque", "PRESENTACIÓN / EMPAQUE"),
    ("cantidad_base_por_empaque", "CANTIDAD DE UNIDAD BASE POR EMPAQUE"),
    ("vende_unidad_base", "¿SE VENDE POR UNIDAD BASE? (SI/NO)"),
    ("vende_medio_empaque", "¿SE VENDE POR MEDIO EMPAQUE? (SI/NO)"),
    ("vende_empaque_completo", "¿SE VENDE POR EMPAQUE COMPLETO? (SI/NO)"),
    ("permite_decimales", "¿PERMITE DECIMALES? (SI/NO)"),
    ("empaques_completos_contados", "EMPAQUES COMPLETOS CONTADOS"),
    ("unidades_sueltas_contadas", "UNIDADES BASE SUELTAS CONTADAS"),
    ("cantidad_total_excel", "CANTIDAD TOTAL CONTADA"),
    ("barcode_primero", "CÓDIGO DE BARRAS - 1er ESCANEO (PENDIENTE)"),
    ("barcode_segundo", "VERIFICACIÓN CÓDIGO DE BARRAS - 2do ESCANEO (PENDIENTE)"),
)
OPERATIONAL_INVENTORY_HEADERS = tuple(label for _, label in OPERATIONAL_INVENTORY_FIELDS)
OPERATIONAL_HEADER_TO_KEY = {label: key for key, label in OPERATIONAL_INVENTORY_FIELDS}
OPERATIONAL_REQUIRED_KEYS = (
    "nombre", "categoria", "precio_compra", "precio_venta", "stock_minimo",
    "unidad_base", "presentacion_empaque", "vende_unidad_base",
    "vende_medio_empaque", "vende_empaque_completo", "permite_decimales",
    "empaques_completos_contados", "unidades_sueltas_contadas",
    "cantidad_total_excel",
)

NO_PACKAGE_VALUE = "SIN EMPAQUE"
PACKAGE_PRESENTATION_VALUES = (
    NO_PACKAGE_VALUE, "UNIDAD", "CAJA", "BULTO", "SACO", "ROLLO",
    "PAQUETE", "BOLSA", "BOTELLA", "TUBO", "GALÓN",
)


@dataclass(frozen=True)
class ProductField:
    key: str
    excel_column: str
    block: str
    db_column: Optional[str]
    data_type: str
    classification: str
    required: bool = False
    user_input: bool = True
    generated_by_system: bool = False
    default: Any = None
    validation: str = ""
    barcode_related: bool = False
    width: float = 14
    number_format: str = "General"
    include_in_products: bool = True
    transformation: str = "Directa"
    observation: str = ""


FIELDS: Tuple[ProductField, ...] = (
    ProductField("registro_inventario_id", "registro_inventario_id", "IDENTIFICACIÓN", None, "UUID/TEXT", "SYSTEM_GENERATED", generated_by_system=True, validation="UUID único de staging", width=38, transformation="UUIDv5 estable", observation="No sustituye productos.local_id; no borrar"),
    ProductField("tipo_registro", "tipo_registro", "IDENTIFICACIÓN", None, "ENUM", "DERIVED/COMPUTED", generated_by_system=True, validation="EXISTENTE o NUEVO", width=13),
    ProductField("activo_sistema", "activo_sistema", "IDENTIFICACIÓN", "activo", "ENUM", "SYSTEM_GENERATED", user_input=False, generated_by_system=True, default="ACTIVO", validation="ACTIVO/INACTIVO", width=16, transformation="activo=1 → ACTIVO"),
    ProductField("producto_id_sistema", "producto_id_sistema", "IDENTIFICACIÓN", "id", "INTEGER", "SYSTEM_GENERATED", user_input=False, generated_by_system=True, width=18, observation="Solo filas existentes"),
    ProductField("producto_local_id", "producto_local_id", "IDENTIFICACIÓN", "local_id", "UUID/TEXT", "SYSTEM_GENERATED", user_input=False, generated_by_system=True, width=38, observation="Existente se preserva; nuevo se genera al importar"),
    ProductField("codigo_sistema_actual", "codigo_sistema_actual", "IDENTIFICACIÓN", "codigo_barras", "TEXT", "LEGACY_ONLY", user_input=False, generated_by_system=True, width=25, observation="SKU/código legacy; no se presume barcode físico"),
    ProductField("nombre", "nombre", "IDENTIFICACIÓN", "nombre", "TEXT", "REQUIRED_FOR_NEW_PRODUCT", required=True, validation="No vacío; máximo 150 caracteres", width=32),
    ProductField("categoria", "categoria", "IDENTIFICACIÓN", "categoria", "TEXT", "REQUIRED_FOR_NEW_PRODUCT", required=True, validation="Debe existir en CATALOGOS", width=25, observation="La UI la marca obligatoria"),
    ProductField("marca", "marca", "IDENTIFICACIÓN", "marca", "TEXT", "OPTIONAL_PRODUCT_DATA", width=22, observation="Catálogo abierto; admite marca nueva"),
    ProductField("presentacion", "presentacion", "IDENTIFICACIÓN", "presentacion", "TEXT", "OPTIONAL_PRODUCT_DATA", width=24, observation="Tamaño/medida/color que distingue variantes"),
    ProductField("proveedor", "proveedor", "IDENTIFICACIÓN", "proveedor_id", "TEXT", "OPTIONAL_PRODUCT_DATA", validation="Vacío o proveedor catalogado", width=28, transformation="Resolver nombre a proveedor_id"),
    ProductField("proveedor_id", "proveedor_id", "IDENTIFICACIÓN", "proveedor_id", "INTEGER", "SYSTEM_GENERATED", user_input=False, generated_by_system=True, width=14, observation="ID técnico de proveedor existente"),
    ProductField("precio_compra", "precio_compra", "INFORMACIÓN COMERCIAL", "precio_compra", "DECIMAL", "REQUIRED_FOR_NEW_PRODUCT", required=True, validation="Número >= 0", width=17, number_format='"$"#,##0.00'),
    ProductField("precio_venta", "precio_venta", "INFORMACIÓN COMERCIAL", "precio_venta", "DECIMAL", "REQUIRED_FOR_NEW_PRODUCT", required=True, validation="Número > 0 y >= precio_compra", width=17, number_format='"$"#,##0.00'),
    ProductField("stock_minimo", "stock_minimo", "INFORMACIÓN COMERCIAL", "stock_minimo", "INTEGER", "REQUIRED_FOR_NEW_PRODUCT", required=True, default=10, validation="Entero >= 0", width=14, number_format="0"),
    ProductField("unidad_medida", "unidad_medida", "INFORMACIÓN COMERCIAL", "unidad_medida", "ENUM", "REQUIRED_FOR_NEW_PRODUCT", required=True, default="UNIDAD", validation="Debe existir en CATALOGOS", width=18),
    ProductField("permite_decimales", "permite_decimales", "INFORMACIÓN COMERCIAL", "permite_decimales", "BOOLEAN", "OPTIONAL_PRODUCT_DATA", default="NO", validation="SI/NO", width=19, transformation="SI=1, NO=0"),
    ProductField("viene_en_caja", "viene_en_caja", "INFORMACIÓN COMERCIAL", "viene_en_caja", "BOOLEAN", "OPTIONAL_PRODUCT_DATA", default="NO", validation="SI/NO", width=16, transformation="SI=1, NO=0"),
    ProductField("unidades_por_caja", "unidades_por_caja", "INFORMACIÓN COMERCIAL", "unidades_por_caja", "INTEGER", "OPTIONAL_PRODUCT_DATA", default=1, validation="Entero >= 1 si viene_en_caja=SI", width=19, number_format="0"),
    ProductField("vende_por_empaque", "vende_por_empaque", "INFORMACIÓN COMERCIAL", "vende_por_empaque", "BOOLEAN", "OPTIONAL_PRODUCT_DATA", default="NO", validation="SI/NO", width=19, transformation="SI=1, NO=0"),
    ProductField("ubicacion", "ubicacion", "INVENTARIO FÍSICO", "ubicacion", "TEXT", "OPTIONAL_PRODUCT_DATA", width=20),
    ProductField("descripcion", "descripcion", "INVENTARIO FÍSICO", "descripcion", "TEXT", "OPTIONAL_PRODUCT_DATA", width=30),
    ProductField("stock_sistema_actual", "stock_sistema_actual", "INVENTARIO FÍSICO", "stock", "DECIMAL", "LEGACY_ONLY", user_input=False, generated_by_system=True, width=20, number_format="0.000", observation="Referencia/cache; nunca prellena cantidad_contada"),
    ProductField("cantidad_contada", "cantidad_contada", "INVENTARIO FÍSICO", None, "DECIMAL", "INVENTORY_COUNT_DATA", required=True, validation="Número >= 0, máximo 3 decimales; entero si permite_decimales=NO", width=19, number_format="0.000"),
    ProductField("pasillo", "pasillo", "INVENTARIO FÍSICO", None, "TEXT", "INVENTORY_COUNT_DATA", width=14),
    ProductField("estante", "estante", "INVENTARIO FÍSICO", None, "TEXT", "INVENTORY_COUNT_DATA", width=14),
    ProductField("diferencia_unidades", "diferencia_unidades", "CÁLCULOS", None, "FORMULA", "DERIVED/COMPUTED", user_input=False, generated_by_system=True, width=19, number_format="0.000", transformation="cantidad_contada - stock_sistema_actual"),
    ProductField("valor_inventario_costo", "valor_inventario_costo", "CÁLCULOS", None, "FORMULA", "DERIVED/COMPUTED", user_input=False, generated_by_system=True, width=23, number_format='"$"#,##0.00'),
    ProductField("valor_potencial_venta", "valor_potencial_venta", "CÁLCULOS", None, "FORMULA", "DERIVED/COMPUTED", user_input=False, generated_by_system=True, width=23, number_format='"$"#,##0.00'),
    ProductField("margen_unitario", "margen_unitario", "CÁLCULOS", None, "FORMULA", "DERIVED/COMPUTED", user_input=False, generated_by_system=True, width=18, number_format='"$"#,##0.00'),
    ProductField("margen_porcentaje", "margen_porcentaje", "CÁLCULOS", None, "FORMULA", "DERIVED/COMPUTED", user_input=False, generated_by_system=True, width=20, number_format="0.0%"),
    ProductField("codigo_barras", "codigo_barras", "BARCODE", "codigo_barras", "TEXT", "BARCODE_PENDING", barcode_related=True, width=24, observation="Vacío hasta scan físico; no generar FRP/EAN"),
    ProductField("estado_barcode", "estado_barcode", "BARCODE", None, "ENUM", "BARCODE_PENDING", default="PENDIENTE", validation="PENDIENTE o ESCANEADO", barcode_related=True, width=18),
    ProductField("estado_registro", "estado_registro", "CONTROL", None, "FORMULA", "DERIVED/COMPUTED", user_input=False, generated_by_system=True, width=22),
    ProductField("errores_validacion", "errores_validacion", "CONTROL", None, "FORMULA", "DERIVED/COMPUTED", user_input=False, generated_by_system=True, width=45),
    ProductField("observaciones_inventario", "observaciones_inventario", "CONTROL", None, "TEXT", "INVENTORY_COUNT_DATA", width=38),
    ProductField("posible_duplicado", "posible_duplicado", "CONTROL", None, "FORMULA", "DERIVED/COMPUTED", user_input=False, generated_by_system=True, width=30),
    # Campos descubiertos que no son captura del workbook.
    ProductField("unidades_por_media_caja", "", "NO CAPTURADO", "unidades_por_media_caja", "INTEGER", "DERIVED/COMPUTED", include_in_products=False, user_input=False, generated_by_system=True, default=1, transformation="max(1, unidades_por_caja // 2)"),
    ProductField("iva", "", "NO CAPTURADO", "iva", "DECIMAL", "SYSTEM_GENERATED", include_in_products=False, user_input=False, generated_by_system=True, default=0, observation="La UI declara IVA eliminado"),
    ProductField("fecha_registro", "", "NO CAPTURADO", "fecha_registro", "TIMESTAMP", "SYSTEM_GENERATED", include_in_products=False, user_input=False, generated_by_system=True, default="CURRENT_TIMESTAMP"),
    ProductField("precio_mayorista", "", "NO CAPTURADO", "precio_mayorista", "REAL", "LEGACY_ONLY", include_in_products=False, user_input=False, observation="Sin input/caller en Producto/ProductosUI actuales"),
    ProductField("stock_maximo", "", "NO CAPTURADO", "stock_maximo", "INTEGER", "LEGACY_ONLY", include_in_products=False, user_input=False, observation="Sin input/caller moderno"),
    ProductField("usar_unidades_categoria", "", "NO CAPTURADO", "usar_unidades_categoria", "INTEGER", "LEGACY_ONLY", include_in_products=False, user_input=False, default=1),
    ProductField("unidades_venta_custom", "", "NO CAPTURADO", "unidades_venta_custom", "TEXT/JSON", "LEGACY_ONLY", include_in_products=False, user_input=False),
    ProductField("unidad_base_producto", "", "NO CAPTURADO", "unidad_base_producto", "TEXT", "LEGACY_ONLY", include_in_products=False, user_input=False),
    ProductField("sync_metadata", "", "NO CAPTURADO", "remote_id/updated_at/deleted_at/is_deleted/sync_status/last_synced_at/version/device_id/created_by/updated_by", "SYNC", "SYSTEM_GENERATED", include_in_products=False, user_input=False, generated_by_system=True),
)

PRODUCT_FIELDS = tuple(field for field in FIELDS if field.include_in_products)
PRODUCT_HEADERS = tuple(field.excel_column for field in PRODUCT_FIELDS)
FIELD_BY_KEY = {field.key: field for field in FIELDS}
HEADER_TO_KEY = {field.excel_column: field.key for field in PRODUCT_FIELDS}
REQUIRED_READY_KEYS = tuple(field.key for field in PRODUCT_FIELDS if field.required)


@dataclass(frozen=True)
class ValidationIssue:
    row: int
    code: str
    field: str
    message: str
    kind: str = "ERROR"  # MISSING, ERROR o WARNING


def stable_inventory_id(identity: str) -> str:
    return str(uuid.uuid5(INVENTORY_ID_NAMESPACE, str(identity)))


def normalized_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    return re.sub(r"\s+", " ", text)


def parse_decimal(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise InvalidOperation("boolean no es número")
    if not isinstance(value, (int, float, Decimal)):
        raise InvalidOperation("el valor debe ser una celda numérica")
    result = Decimal(str(value))
    if not result.is_finite():
        raise InvalidOperation("número no finito")
    return result


def has_max_three_decimals(value: Decimal) -> bool:
    return value * 1000 == (value * 1000).to_integral_value()


def is_active_record(record: Mapping[str, Any]) -> bool:
    if str(record.get("tipo_registro") or "").strip().upper() == "EXISTENTE":
        return True
    activity_keys = (
        "nombre", "categoria", "marca", "presentacion", "proveedor",
        "precio_compra", "precio_venta", "ubicacion", "descripcion",
        "cantidad_contada", "pasillo", "estante", "codigo_barras",
        "observaciones_inventario",
    )
    return any(record.get(key) not in (None, "") for key in activity_keys)


def validate_record(
    record: Mapping[str, Any], *, row: int,
    categories: Iterable[str], units: Iterable[str], providers: Iterable[str],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not is_active_record(record):
        return issues

    def missing(key: str, label: str) -> None:
        if record.get(key) in (None, ""):
            issues.append(ValidationIssue(row, "REQUIRED_MISSING", key, f"Falta {label}", "MISSING"))

    for key in REQUIRED_READY_KEYS:
        missing(key, FIELD_BY_KEY[key].excel_column)

    name = str(record.get("nombre") or "").strip()
    if len(name) > 150:
        issues.append(ValidationIssue(row, "NAME_TOO_LONG", "nombre", "Nombre supera 150 caracteres"))

    category = normalized_text(record.get("categoria"))
    allowed_categories = {normalized_text(item) for item in categories if str(item).strip()}
    if category and category not in allowed_categories:
        issues.append(ValidationIssue(row, "CATEGORY_UNKNOWN", "categoria", "Categoría no existe en CATALOGOS"))

    unit = normalized_text(record.get("unidad_medida"))
    allowed_units = {normalized_text(item) for item in units if str(item).strip()}
    if unit and unit not in allowed_units:
        issues.append(ValidationIssue(row, "UNIT_UNKNOWN", "unidad_medida", "Unidad no existe en CATALOGOS"))

    provider = normalized_text(record.get("proveedor"))
    allowed_providers = {normalized_text(item) for item in providers if str(item).strip()}
    if provider and provider not in allowed_providers:
        issues.append(ValidationIssue(row, "PROVIDER_UNKNOWN", "proveedor", "Proveedor no catalogado", "WARNING"))

    numeric: dict[str, Optional[Decimal]] = {}
    for key in ("precio_compra", "precio_venta", "cantidad_contada"):
        try:
            numeric[key] = parse_decimal(record.get(key))
        except InvalidOperation:
            numeric[key] = None
            issues.append(ValidationIssue(row, "INVALID_NUMBER", key, f"{key} debe ser número"))
    cost, sale, quantity = numeric["precio_compra"], numeric["precio_venta"], numeric["cantidad_contada"]
    if cost is not None and cost < 0:
        issues.append(ValidationIssue(row, "INVALID_PRICE", "precio_compra", "Precio de compra no puede ser negativo"))
    if sale is not None and sale <= 0:
        issues.append(ValidationIssue(row, "INVALID_PRICE", "precio_venta", "Precio de venta debe ser mayor a 0"))
    if cost is not None and sale is not None and sale < cost:
        issues.append(ValidationIssue(row, "SALE_BELOW_COST", "precio_venta", "Precio de venta menor al costo"))
    if quantity is not None:
        if quantity < 0:
            issues.append(ValidationIssue(row, "INVALID_QUANTITY", "cantidad_contada", "Cantidad no puede ser negativa"))
        if not has_max_three_decimals(quantity):
            issues.append(ValidationIssue(row, "QUANTITY_SCALE", "cantidad_contada", "Cantidad excede 3 decimales"))
        if str(record.get("permite_decimales") or "NO").strip().upper() != "SI" and quantity != quantity.to_integral_value():
            issues.append(ValidationIssue(row, "FRACTION_NOT_ALLOWED", "cantidad_contada", "Producto no permite cantidad fraccionaria"))

    try:
        stock_min = parse_decimal(record.get("stock_minimo"))
        if stock_min is not None and (stock_min < 0 or stock_min != stock_min.to_integral_value()):
            raise InvalidOperation
    except InvalidOperation:
        issues.append(ValidationIssue(row, "INVALID_STOCK_MIN", "stock_minimo", "Stock mínimo debe ser entero >= 0"))

    for key in ("permite_decimales", "viene_en_caja", "vende_por_empaque"):
        if str(record.get(key) or "").strip().upper() not in YES_NO_VALUES:
            issues.append(ValidationIssue(row, "INVALID_BOOLEAN", key, f"{key} debe ser SI o NO"))
    if str(record.get("viene_en_caja") or "NO").strip().upper() == "SI":
        try:
            units_box = parse_decimal(record.get("unidades_por_caja"))
            if units_box is None or units_box < 1 or units_box != units_box.to_integral_value():
                raise InvalidOperation
        except InvalidOperation:
            issues.append(ValidationIssue(row, "INVALID_PACKAGE", "unidades_por_caja", "Unidades por caja debe ser entero >= 1"))

    barcode = str(record.get("codigo_barras") or "").strip()
    barcode_status = str(record.get("estado_barcode") or "").strip().upper()
    if barcode_status not in BARCODE_STATUS_VALUES:
        issues.append(ValidationIssue(row, "INVALID_BARCODE_STATUS", "estado_barcode", "Estado barcode inválido"))
    elif barcode and barcode_status != "ESCANEADO":
        issues.append(ValidationIssue(row, "BARCODE_STATE_MISMATCH", "estado_barcode", "Barcode lleno debe estar ESCANEADO"))
    elif not barcode and barcode_status == "ESCANEADO":
        issues.append(ValidationIssue(row, "BARCODE_STATE_MISMATCH", "codigo_barras", "ESCANEADO requiere barcode"))

    local_id = str(record.get("producto_local_id") or "").strip()
    if local_id:
        try:
            uuid.UUID(local_id)
        except (ValueError, AttributeError):
            issues.append(ValidationIssue(row, "INVALID_LOCAL_ID", "producto_local_id", "producto_local_id no es UUID"))
    if str(record.get("tipo_registro") or "").strip().upper() == "EXISTENTE" and not local_id:
        issues.append(ValidationIssue(row, "EXISTING_WITHOUT_LOCAL_ID", "producto_local_id", "Producto existente sin local_id"))
    return issues


def status_from_issues(record: Mapping[str, Any], issues: Sequence[ValidationIssue]) -> str:
    if not is_active_record(record):
        return ""
    if any(issue.kind in ("ERROR", "WARNING") for issue in issues):
        return "REVISAR"
    if any(issue.kind == "MISSING" for issue in issues):
        return "INCOMPLETO"
    barcode = str(record.get("codigo_barras") or "").strip()
    state = str(record.get("estado_barcode") or "").strip().upper()
    return "LISTO_COMPLETO" if barcode and state == "ESCANEADO" else "LISTO_SIN_BARCODE"


def mapping_rows() -> list[tuple[Any, ...]]:
    return [
        (
            field.excel_column or "(no capturado)",
            field.key,
            "productos" if field.db_column else "staging_excel",
            field.db_column or "—",
            "SI" if field.required else "NO",
            field.data_type,
            "" if field.default is None else field.default,
            field.transformation,
            f"{field.classification}. {field.observation}".strip(),
        )
        for field in FIELDS
    ]
