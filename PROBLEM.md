# PROBLEM.md: Reto Cierre Kalmora (Talky Labs)

Definición completa del problema que resolvemos en el hackathon de Talky Labs **«Reto Cierre Kalmora»**. Es la fuente única de verdad para el equipo de backend (Python), el de frontend (React) y los agentes de código. Lee esto antes de construir nada.

> **Alcance.** Este documento describe **el problema**: qué entra, qué debe salir, cómo se puntúa, las reglas y el vocabulario. No describe nuestra solución.

> **Fuentes.** Todo sale del paquete oficial de los organizadores (`README.md`, `POLITICAS_CONTABLES.md`, `FORMATO_ENTREGA.md`, `score.py`, `phase_dev/` y `phase_test/`) y de la web del reto (`https://usetalky.com/hackathon/kalmora`). Los recuentos y nombres de campo se han calculado sobre los ficheros. Si este documento contradice al paquete oficial, manda el paquete.

> **Rutas.** Son relativas al paquete del participante: `phase_dev/…` (julio) y `phase_test/…` (septiembre). `score.py` y los tres `.md` oficiales están en la raíz del paquete de dev.

---

## Índice

1. [Resumen ejecutivo](#1-resumen-ejecutivo)
2. [Contexto: Grupo Kalmora](#2-contexto-grupo-kalmora)
   - [2.1 Sociedades](#21-sociedades)
   - [2.2 Plan de cuentas](#22-plan-de-cuentas)
   - [2.3 Objetos de coste](#23-objetos-de-coste)
   - [2.4 Convenciones de datos](#24-convenciones-de-datos)
3. [Fases y calendario](#3-fases-y-calendario)
4. [Entradas: diccionario de datos](#4-entradas-diccionario-de-datos)
   - [4.1 Árbol de una fase y recuentos](#41-árbol-de-una-fase-y-recuentos)
   - [4.2 `erp/`](#42-erp)
   - [4.3 `inbox/ap/`](#43-inboxap)
   - [4.4 `inbox/ar/`](#44-inboxar)
   - [4.5 `bank/`](#45-bank)
   - [4.6 `tasks/`](#46-tasks)
   - [4.7 `golden/` (solo dev)](#47-golden-solo-dev)
5. [Las seis tareas y el balance](#5-las-seis-tareas-y-el-balance)
   - [5.0 Mapa de entradas por tarea](#50-mapa-de-entradas-por-tarea)
   - [5.1 AP: bandeja de proveedores (30 %)](#51-ap-bandeja-de-proveedores-30-)
   - [5.2 AR: facturación del mes (10 %)](#52-ar-facturación-del-mes-10-)
   - [5.3 AR: aplicación de cobros (15 %)](#53-ar-aplicación-de-cobros-15-)
   - [5.4 Conciliación bancaria (20 %)](#54-conciliación-bancaria-20-)
   - [5.5 Conciliación intragrupo (5 %)](#55-conciliación-intragrupo-5-)
   - [5.6 Cierre (10 %)](#56-cierre-10-)
   - [5.7 Balance de sumas y saldos (10 %)](#57-balance-de-sumas-y-saldos-10-)
6. [Salidas: formato de entrega](#6-salidas-formato-de-entrega)
7. [Evaluación: el scorer exacto](#7-evaluación-el-scorer-exacto)
8. [Reglas del reto y entrega](#8-reglas-del-reto-y-entrega)
9. [Dependencias entre tareas](#9-dependencias-entre-tareas)
10. [Glosario](#10-glosario)
11. [Definición de terminado y ambigüedades abiertas](#11-definición-de-terminado-y-ambigüedades-abiertas)

---

## 1. Resumen ejecutivo

Grupo Kalmora es un grupo sintético de infraestructuras y servicios del tamaño de una empresa del IBEX 35: siete sociedades en España, Portugal y México. Llega a fin de mes con la bandeja de proveedores llena, los cobros sin aplicar y los bancos sin conciliar. Hay que construir un **agente que haga el cierre mensual del centro de servicios compartidos**. Para cada fase, el agente recibe:

- una foto del ERP tal como estaba contabilizado, sin nuestro trabajo;
- los documentos recibidos en el mes;
- los extractos bancarios;
- la lista exacta de tareas.

Con eso entrega **seis ficheros JSONL**: AP, facturación AR, aplicación de cobros, conciliación bancaria, intragrupo y cierre. Cada uno lleva decisiones y **asientos contables**. El `score.py` oficial puntúa cada fichero contra un golden y, además, suma **todos** nuestros asientos al diario registrado para comparar el balance resultante, cuenta a cuenta, con el correcto. El total va de 0 a 100: seis tareas ponderadas más el balance (10 %).

Hay dos fases:

- **Julio 2026 (`phase_dev`):** trae golden, sirve para aprender y autoevaluarse.
- **Septiembre 2026 (`phase_test`):** sin golden. Es la que decide y **se entrega una sola vez**.

El lema de la web: «Gana quien deje el balance más cerca del correcto».

---

## 2. Contexto: Grupo Kalmora

### 2.1 Sociedades

Datos de `erp/companies.json`, idénticos en dev y test, completados con el README y la web.

| Código | Nombre | País | Moneda local | `role` | Actividad | Particularidades contables |
|---|---|---|---|---|---|---|
| `1000` | Kalmora Infraestructuras y Servicios, S.A. | ES | EUR | `holding` | Holding, servicios corporativos | Cabecera del **cash pooling** (`BIN-1000`, saldo cero diario con `BIN-1100` y `BIN-1200`). **Préstamo sindicado** (17000000). Factura **management fees** mensuales a 1100, 1200, 1300, 2100 y 3100 (`intercompany_agreements.json`, +4 % en 2026). Proveedores **SaaS facturados en USD** (servicios de no establecidos, `SIS`). **Prestamista** del préstamo intragrupo `KMI-2025-01` a 3100. |
| `1100` | Kalmora Construcción, S.A.U. | ES | EUR | `construction` | Obras públicas y privadas | Imputa a **PEP/WBS** de obra. **Subcontratas** con ISP (`SISP`) y **retención de garantía del 5 %** (40000900). **Factoring** con Banco Atlántico (55300000, socio `FACTOR-BAE`). **Confirming** a proveedores. **Pagarés** de clientes (43100000). Avales. Socio al 50 % de la UTE 1910. |
| `1200` | Kalmora Servicios Urbanos, S.L.U. | ES | EUR | `urban_services` | Limpieza viaria, residuos, jardines, alumbrado | **Contratos municipales** con canon mensual, **penalidades** y **revisión de precios** por decreto. **Recibos SEPA** a comunidades de propietarios (`CMA-1200`). IVA al 10 % (R10) en limpieza viaria y residuos. |
| `1300` | Kalmora Energía Renovable, S.L.U. | ES | EUR | `energy` | 3 plantas solares (CC-1300-PSF1/2/3) | Venta por **PPA** (C200079: 70 % de la producción de PSF1 y PSF2 a 41,50 €/MWh) y en **mercado** mediante representante (C200080), con **compensación (netting)** de los honorarios del representante. Hay cuentas de IVPEE (63110000, 47530000). |
| `1910` | UTE Kalmora Construcción – Hidrocon (Línea 9) | ES | EUR | `ute` | Unión temporal de empresas, obra OB-1910-2501 | Socios: 1100 (50 %) y `EXT-HIDROCON` (Hidrocon Obras, S.A., 50 %). **Llamadas de fondos** a los socios: 55210000 en el socio y 55220000 en la UTE. Los proveedores de la UTE deben facturar a 1910 y no a 1100. |
| `2100` | Kalmora Portugal – Construção e Serviços, Lda. | PT | EUR | `construction` | Obras en Portugal | IVA 23 %/13 %/6 % (`P23`/`P13`/`P06`; emitido `PR23`/`PR06`). **Autoliquidação** en construcción (`PAUT`) y en servicios de no residentes (`PSIS`); en ventas, `PRAUT`. Retención IRS 25 %. La web menciona el **ATCUD**, que no aparece en los documentos del paquete. Su banco (`BLC-2100`) reporta en **CAMT.053**. |
| `3100` | Kalmora México Infraestructura, S.A. de C.V. | MX | **MXN** | `construction` | Obra pública en México | **CFDI 4.0**. **Anticipo del 30 %** amortizado en cada estimación (43800000). **5 al millar** (0,5 %, 63100000). **Préstamo intragrupo en EUR** recibido de 1000 (16330000, intereses en 55200000), que se valora en divisa. **Cuenta bancaria en USD** (`BANH-3100-USD`). Retenciones ISR 10 %, IVA retenido 10,67 % y fletes 4 %. IVA 16 % (`M16`/`MR16`). |

Acuerdos intragrupo (`erp/intercompany_agreements.json`):

- **`management_fees`:** fee mensual por sociedad receptora en céntimos, con `monthly_eur_2025` y `monthly_eur_2026`. Emisor: 1000. Base: «Contrato de servicios corporativos 2023, revisión +4 % en 2026».
- **`loan`:**
  - `KMI-2025-01`, principal 500000000 (5.000.000,00 EUR), `rate_bp` 600 (6 %), base `act/360`, inicio 2025-02-03;
  - prestamista 1000, prestatario 3100;
  - «Intereses devengados mensualmente por ambas partes con base act/360; pago anual en diciembre».
- **`cash_pooling`:**
  - cabecera `BIN-1000`; participantes `BIN-1100` y `BIN-1200`;
  - «Zero balancing diario»;
  - interés «EURIBOR 1M sintético (2,35 %) + 0,50 %, act/360, liquidación mensual».
- **`ute`:** sociedad 1910; socios `[["1100", 5000], ["EXT-HIDROCON", 5000]]` (en puntos básicos).

### 2.2 Plan de cuentas

Plan único para el grupo, basado en el PGC: `erp/chart_of_accounts.jsonl`, con 97 cuentas de 8 dígitos, idéntico en dev y test. Campos:

- `account`
- `description`
- `type`: `BS` balance o `PL` resultados.
- `open_items`: la cuenta se gestiona por partidas abiertas.

**Socio (`partner`) según las políticas, §1:**

| Cuentas | Socio |
|---|---|
| 400/410/403/407/40000900/40090000 | id del proveedor |
| 430/431/436/438/43000900/43090000/49000000 | id del cliente |
| Intragrupo 5520/5521/5522/2423/1633 | código de sociedad |
| 55300000 | `FACTOR-BAE` |

En el diario se observa además:

- 43300000 lleva como socio el código de sociedad (`"1100"`);
- 40300000 lleva el proveedor intragrupo (`V-IC1000`);
- en 55220000 de la UTE los socios son `1100` y `EXT-HIDROCON`.

Leyenda: OI = `open_items: true`.

**Balance**

| Cuenta | Descripción | OI | Uso en las políticas y en los datos |
|---|---|---|---|
| 10000000 | Capital social | | |
| 11300000 | Reservas voluntarias | | |
| 12900000 | Resultado del ejercicio | | |
| 16330000 | Deudas a l/p con empresas del grupo | | Préstamo `KMI-2025-01` en 3100 (socio `1000`). Cierre: `FX_REVAL` `GL:16330000`. Debe cuadrar con 24230000 (§6). |
| 17000000 | Deudas a l/p con entidades de crédito | | Préstamo sindicado y préstamos bancarios |
| 21300000 | Maquinaria | | Inmovilizado; lleva objeto de coste (p. ej. pedidos `capex`) |
| 21700000 | Equipos para procesos de información | | Inmovilizado |
| 21800000 | Elementos de transporte | | Inmovilizado |
| 23100000 | Construcciones en curso | | Inmovilizado |
| 24230000 | Créditos a l/p a empresas del grupo | | Préstamo `KMI-2025-01` en 1000 (socio `3100`) |
| 28130000 | Amortización acumulada de maquinaria | | |
| 40000000 | Proveedores | OI | Acreedor de bienes y subcontratas (`reconciliation_account`) |
| 40000900 | Proveedores, retenciones por garantía (obra) | OI | Retención de garantía del 5 % (Cr), socio proveedor |
| 40090000 | Proveedores, facturas pendientes de recibir | | **Cuenta puente GR/IR**: las entradas la abonan y la factura la carga. También periodificaciones `ACCRUAL` (Cr) y facturas IC en tránsito (Cr, socio = sociedad emisora). Sale en `open_items` con asignación `<pedido>/<posición>`. |
| 40300000 | Proveedores, empresas del grupo | OI | Acreedor intragrupo. Debe cuadrar con 43300000 (§6). |
| 40700000 | Anticipos a proveedores | OI | `DOWN_PAYMENT_REQUEST` (Dr). Los anticipos se aplican al tipo histórico (Cr). |
| 41000000 | Acreedores por prestaciones de servicios | OI | Acreedor de servicios |
| 43000000 | Clientes | OI | Socio cliente, asignación = nº de factura |
| 43000900 | Clientes, retenciones por garantía | OI | Garantía retenida por el cliente (Dr en la factura) |
| 43090000 | Clientes, obra ejecutada pendiente de certificar | | `WIP_REVENUE` (Dr) |
| 43100000 | Clientes, efectos comerciales en cartera (pagarés) | OI | Pagarés; asignación `PAG<número>` |
| 43300000 | Clientes, empresas del grupo | OI | Cliente intragrupo |
| 43600000 | Clientes de dudoso cobro | OI | `DOUBTFUL_RECLASS` |
| 43800000 | Anticipos de clientes | OI | Anticipo de obra en México (amortización Dr). Cobro duplicado `OVERPAYMENT_DUPLICATE` (Cr). |
| 44000000 | Deudores varios | OI | |
| 46500000 | Remuneraciones pendientes de pago | | Nóminas |
| 47000000 | Hacienda Pública, deudora por IVA | | Devolución de IVA cobrada (`NON_CUSTOMER`) |
| 47200000 | HP, IVA soportado | | IVA deducible (Dr) e IVA de importación del DUA (Dr) |
| 47210000 | HP, IVA soportado ISP/intracomunitario/importación (autorrepercutido) | | Dr por la cuota autorrepercutida (`SISP`, `SIC`, `SIS`, `PAUT`, `PSIS`) |
| 47300000 | HP, retenciones y pagos a cuenta | | Retención del 19 % sobre intereses bancarios (Dr) |
| 47400000 | Activos por impuesto diferido | | |
| 47500000 | HP, acreedora por IVA | | Liquidaciones de IVA |
| 47510000 | HP, acreedora por retenciones practicadas | | IRPF, ISR, IVA retenido MX, IRS PT (Cr) |
| 47520000 | HP, acreedora por impuesto sobre sociedades | | |
| 47530000 | HP, acreedora por IVPEE | | |
| 47600000 | Organismos de la Seguridad Social, acreedores | | |
| 47700000 | HP, IVA repercutido | | IVA de las facturas emitidas (Cr) |
| 47710000 | HP, IVA repercutido autorrepercutido | | Cr por la cuota autorrepercutida |
| 48000000 | Gastos anticipados | | `PREPAID` |
| 48500000 | Ingresos anticipados | | |
| 49000000 | Deterioro de valor de créditos por operaciones comerciales | | `BAD_DEBT`, socio cliente |
| 52000000 | Deudas a c/p con entidades de crédito | | |
| 52080000 | Deudas por efectos descontados / anticipos de factoring | | |
| 55200000 | Cuenta corriente con empresas del grupo (cash pooling) | OI | Barridos de pooling, sus intereses, financiación intragrupo e intereses del préstamo KMI (socio = sociedad). Debe cuadrar entre sociedades (§6). |
| 55210000 | Cuenta corriente con UTE | OI | En 1100, socio `1910` |
| 55220000 | Cuenta corriente con socios de UTE | OI | En 1910, socios `1100` y `EXT-HIDROCON`. 55210000 y 55220000 deben cuadrar (§6). |
| 55300000 | Cuenta corriente con entidad de factoring | OI | Socio `FACTOR-BAE`. Recibe `FACTORED_MISDIRECTED` (Cr) y `FACTORING_CHARGES_NOT_BOOKED` (Cr). |
| 55500000 | Partidas pendientes de aplicación (cobros sin identificar) | OI | Los abonos del N43 entran aquí (Cr). La aplicación de cobros la carga (Dr). |
| 55510000 | Partidas pendientes de aplicación (reclamaciones a bancos) | OI | |
| 56500000 | Fianzas constituidas a c/p | | Devolución de fianza (`NON_CUSTOMER`) |
| 57200001 | Bancos c/c – Banco Ibérico del Norte | | `BIN-1000`, `BIN-1100`, `BIN-1200` |
| 57200002 | Bancos c/c – Caja Mediterránea | | `CMA-1000`, `CMA-1100`, `CMA-1200`, `CMA-1910` |
| 57200003 | Bancos c/c – Banco Atlántico Empresas | | `BAE-1100`, `BAE-1300` |
| 57200004 | Bancos c/c – Banco Lusitano | | `BLC-2100` |
| 57200005 | Bancos c/c MXN – Banco del Anáhuac | | `BANH-3100-MXN` |
| 57200006 | Bancos c/c USD – Banco del Anáhuac | | `BANH-3100-USD` (saldo valorado en MXN; `FX_REVAL` `BANK:BANH-3100-USD`) |

**Resultados** (llevan objeto de coste, §2.3)

| Cuenta | Descripción | Uso en las políticas y en los datos |
|---|---|---|
| 60000000 | Compras de materiales | Gasto por defecto de suministradores de materiales |
| 60700000 | Trabajos realizados por otras empresas (subcontratas) | Subcontratas de obra |
| 62100000 | Arrendamientos y cánones | Alquileres de oficina y arrendamientos rústicos |
| 62110000 | Alquiler de maquinaria | |
| 62200000 | Reparaciones y conservación | |
| 62300000 | Servicios de profesionales independientes | |
| 62400000 | Transportes | |
| 62500000 | Primas de seguros | Seguros, típico `PREPAID` |
| 62600000 | Servicios bancarios y similares | `BANK_FEE_NOT_BOOKED`; comisión de recibo devuelto |
| 62700000 | Publicidad, propaganda y relaciones públicas | |
| 62800000 | Suministros | Electricidad, agua y telecomunicaciones |
| 62810000 | Combustibles | |
| 62900000 | Otros servicios | |
| 62910000 | Viajes y desplazamientos | `CARD_SETTLEMENT_NOT_BOOKED` (CC-1000-DIR) |
| 62920000 | Servicios informáticos y licencias | SaaS |
| 62930000 | Gestión de residuos | Vertedero |
| 62940000 | Servicios intragrupo recibidos | Management fees recibidos |
| 63100000 | Otros tributos | 5 al millar en México (Dr) |
| 63110000 | Impuesto sobre el valor de la producción de energía eléctrica (IVPEE) | |
| 63400000 | Ajustes negativos en la imposición indirecta (IVA no deducible) | |
| 64000000 | Sueldos y salarios | |
| 64200000 | Seguridad Social a cargo de la empresa | |
| 66200000 | Intereses de deudas | `LOAN_INTEREST_NOT_BOOKED` |
| 66210000 | Intereses de deudas con empresas del grupo | Intereses KMI en 3100 e intereses de pooling |
| 66500000 | Gastos financieros por factoring y descuento | `FACTORING_CHARGES_NOT_BOOKED` |
| 66800000 | Diferencias negativas de cambio | `FX_RATE_DIFFERENCE`, `FX_REVAL` |
| 66900000 | Otros gastos financieros (comisiones de avales) | Comisiones de aval |
| 69400000 | Pérdidas por deterioro de créditos comerciales | `BAD_DEBT` (dotación) |
| 70000000 | Ventas | |
| 70500000 | Prestaciones de servicios | Ingreso de servicios |
| 70510000 | Obra certificada | Ingreso de obra |
| 70520000 | Ingresos por revisión de precios | Atrasos de revisión, una línea por mes |
| 70530000 | Venta de energía | PPA y mercado |
| 70540000 | Servicios intragrupo prestados | Management fees emitidos por 1000 |
| 70590000 | Penalizaciones contractuales (menor ingreso) | `PENALTY` (Dr) |
| 71300000 | Variación de obra ejecutada pendiente de certificar | `WIP_REVENUE` (Cr) |
| 75900000 | Ingresos por servicios diversos | Indemnización de seguro (`NON_CUSTOMER`) |
| 76200000 | Ingresos de créditos | Intereses bancarios cobrados |
| 76210000 | Ingresos de créditos con empresas del grupo | Intereses KMI en 1000 |
| 76800000 | Diferencias positivas de cambio | `FX_RATE_DIFFERENCE`, `FX_REVAL` |
| 79400000 | Reversión del deterioro de créditos comerciales | `BAD_DEBT` (reversión) |

### 2.3 Objetos de coste

Regla de las políticas, §1: las cuentas de gasto, ingreso e inmovilizado llevan `cost_center` **o** `wbs`, nunca los dos.

- **Obra:** se imputa al PEP.
- **Estructura y servicios:** se imputan al centro de coste.

**Centros de coste** (`erp/cost_centers.jsonl`, 25, idéntico en dev y test; campos `id`, `company`, `desc`):

| Sociedad | Centros de coste |
|---|---|
| 1000 | `CC-1000-DIR` (Dirección general), `CC-1000-FIN` (Dirección financiera y tesorería), `CC-1000-IT`, `CC-1000-RRHH`, `CC-1000-LEG`, `CC-1000-COM` |
| 1100 | `CC-1100-ADM` (estructura, sede Madrid), `CC-1100-MAQ` (parque de maquinaria) |
| 1200 | `CC-1200-ADM`, `CC-1200-TALLER`. Uno por contrato municipal: `CC-1200-LV01`, `-RR01`, `-LV02`, `-PJ01`, `-AL01`, `-RR02`, `-LV03`, `-PJ02`. |
| 1300 | `CC-1300-ADM`. Plantas: `CC-1300-PSF1` (Campollano I, 49,9 MWp), `CC-1300-PSF2` (Lomaseca, 32,4 MWp), `CC-1300-PSF3` (Vegalta Solar, 21,0 MWp). |
| 1910 / 2100 / 3100 | `CC-1910-ADM`, `CC-2100-ADM`, `CC-3100-ADM` |

**Proyectos y PEP** (`erp/projects.jsonl`, 20, idéntico en dev y test):

- **Campos:** `id`, `company`, `name`, `town`, `kind` (`civil` / `building` / `civil_building`), `public_works` (bool), `start`, `planned_end`, `budget_cost` (céntimos) y `wbs[]` (`{id, desc, sub}`).
- **PEP:** cada proyecto tiene cinco, `<proyecto>.01` a `.05`. El campo `sub` indica el arquetipo de subcontrata asociado.

| PEP | Descripción | `sub` |
|---|---|---|
| `.01` | Movimiento de tierras y demoliciones | `SUB_EARTH` |
| `.02` | Cimentación y estructura | `SUB_STRUCT` |
| `.03` | Instalaciones | `SUB_MEP` |
| `.04` | Acabados, urbanización y señalización | `SUB_FINISH` |
| `.05` | Costes indirectos de obra | `null` |

| Sociedad | Proyectos (`public_works` = obra pública) |
|---|---|
| 1100 (14) | OB-1100-2511, -2512, -2513, -2414, -2416, -2518, -2520, -2521, -2323 y -2524 son obra pública. OB-1100-2515, -2617, -2419 y -2522 son edificación privada. |
| 1910 (1) | OB-1910-2501 (Línea 9, obra pública) |
| 2100 (3) | OB-2100-2501 y -2502 son obra pública. OB-2100-2503 es privada. |
| 3100 (2) | OB-3100-2501 y -2502, obra pública |

### 2.4 Convenciones de datos

**Importes**

- Todos los importes van en **céntimos enteros**. En los asientos, `debit` y `credit` son enteros ≥ 0. En saldos (`open_items.balance`, balances de sumas y saldos), positivo = deudor y negativo = acreedor.
- Se entrega en la **moneda local** de la sociedad: EUR, o MXN en 3100.
- Una línea en moneda extranjera se convierte al tipo **SYN-BCE** de la **fecha de la factura**, o al último publicado si ese día no hay.
- El redondeo se hace **por línea**. La diferencia la absorbe la línea del proveedor o del cliente.

**Tipos de cambio** (`erp/fx_rates.jsonl`)

- `base` siempre `EUR`.
- `rate` son unidades de divisa por 1 EUR. Ejemplo a 2026-07-31: USD 1,2487; GBP 0,9016; MXN 18,9004; CNY 7,5457; CHF 1,0099.
- Solo hay días laborables, de lunes a viernes.
- `source` = «SYN-BCE (sintético)».

**Cantidades y porcentajes**

- `quantity_milli` y `mwh_milli` van en milésimas.
- `unit_price` va en céntimos por unidad. Valor de una entrada = `quantity_milli × unit_price / 1000` (comprobado en `goods_receipts`).
- Porcentajes y tipos en puntos básicos: `rate` 2100 = 21 %, `retention_bp` 500 = 5 %, `share_bp` 7000 = 70 %, `advance_bp` 3000 = 30 %.

**Fechas e identificadores**

- Fechas en `YYYY-MM-DD`. En `message.json`, `received_at` es fecha y hora ISO.
- NIF y NIPC son sintéticos y los españoles llevan el **dígito de control incorrecto a propósito**. IBAN, empresas y personas son inventados.
- Todos los documentos llevan el pie «Synthetic test document – no legal or fiscal validity».

| Objeto | Formato | Ejemplo |
|---|---|---|
| Documento de AP | `API` + 6 dígitos | `API004093` |
| Asiento | `<sociedad>-<año>-<10 dígitos>`, con prefijo numérico por clase | `1100-2026-5100000753` |
| Línea de asiento (`book_line`) | `<id asiento>#<line>`, donde `line` es el campo `line` de 1 a n | `1100-2026-1600000190#2` |
| Línea de extracto (`bank_line`) | `BL` + 7 dígitos | `BL0004502` |
| Partida de facturación | `BILL-<contrato>-<YYYYMM>`; revisión de precios `BILL-<contrato>-REV<año>` | `BILL-CV-OB-1100-2511-202607`, `BILL-CT-1200-LV01-REV2026` |
| Proveedor / proveedor IC | `V1xxxxx` / `V-IC<sociedad>` | `V100045`, `V-IC1000` |
| Cliente / cliente IC | `C2xxxxx` / `C-IC<sociedad>` | `C200001`, `C-IC1000` |
| Pedido / entrada | `45000xxxxx` / `50000xxxxx` (GR), `10000xxxxx` (SES) | `4500019036` |
| Facturas emitidas | 1200 `SUyy-nnnnn` (servicios) y `RCyy-nnnnn` (recibos SEPA); 1100 `OByy-nnnnn`; 2100 `FT OByy-nnnnn` (con espacio); 1300 `ENyy-nnnnn`; 3100 `EST-yyyy-nnnnn` (estimaciones) y `ANT-yyyy-nnnnn` (anticipos); 1910 `UL9-yy-nnnnn` | `SU26-00107` |

**Clases de asiento** (`doc_type`, estilo SAP) y orígenes (`source`) en `erp/journal_entries.jsonl`:

| `doc_type` | Prefijo del id | `source` observados | Qué es |
|---|---|---|---|
| `WE` | 50 | `MM` | Entrada de mercancía o hoja de servicios (Dr gasto / Cr 40090000) |
| `KR` | 51 | `AP` | Factura de proveedor |
| `KG` | 52 | `AP` | Abono de proveedor |
| `ZP` | 16 | `F110` (propuesta de pago), `DD` (adeudo domiciliado), `CONFIRMING`, `SWIFT`, `LOAN`, `PAYROLL`, `SS`, `VAT`, `WHT`, `MANUAL_PAYMENT`, `UTE` | Pagos |
| `SA` | 10 | `OPENING`, `CLOSE_ACCRUAL`, `CLOSE_PREPAID`, `CLOSE_FX`, `CLOSE_WIP`, `CLOSE_BADDEBT`, `CLOSE_DOUBTFUL`, `TREASURY`, `PAYROLL`, `VAT`, `FACTORING`, `IC_ACCRUAL` (solo en test); las retrocesiones llevan el sufijo `:reversal` | Asientos generales y de cierre |
| `DR` | 18 | `SD`, `IC_BILLING` | Factura emitida |
| `DZ` | 14 | `CASHAPP` (cobro aplicado), `N43AUTO` (cobro importado a 55500000), `SEPA`, `SEPA_RETURN`, `PAGARE` | Cobros |
| `SB` | 11 | `BANKFEE`, `BANKINT`, `CARD` | Gastos e ingresos bancarios |
| `ZB` | 17 | `FACTORING`, `UTE`, `VAT_REFUND` | Movimientos bancarios varios |
| `IC` | 30 | `POOL`, `POOL_INT`, `IC_LOAN`, `IC_FUNDING` | Intragrupo |

---

## 3. Fases y calendario

| Fase | Carpeta | Mes a cerrar | Histórico del diario | Golden | Para qué |
|---|---|---|---|---|---|
| Desarrollo | `phase_dev` | **julio 2026** | Desde 01/10/2024 (apertura) hasta 31/07/2026: 22 meses | **Sí** (`phase_dev/golden/`) | Desarrollar e iterar con `score.py`. «Julio para aprender». |
| Evaluación | `phase_test` | **septiembre 2026** | Desde 01/10/2024 hasta 30/09/2026: 24 meses | **No** | Evaluación final. «Septiembre para ganar»: **se entrega una sola vez** y no hay leaderboard de test. |

- El enlace de descarga de dev caduca el **9 de octubre de 2026**. Los materiales no dan una fecha límite de entrega de septiembre.
- La web resume la escala del mes de evaluación así: **297 documentos de AP**, **12 cuentas bancarias en tres formatos y cuatro divisas**, **7 sociedades** (ES/PT/MX) y **24 meses de histórico** del diario.
  - Las cuentas son EUR, MXN y USD.
  - Los extractos traen además movimientos SWIFT en GBP.

**Qué representa cada fase.** Cada fase es una foto del ERP **tal como estaba contabilizado** al cierre del mes, **sin nuestro trabajo**. Según el README:

- Las facturas del mes están en la bandeja (`inbox/ap/`) y **no están contabilizadas**.
- Los cobros entraron automáticamente desde el N43 a la cuenta **55500000** (pendientes de aplicar): asientos `source = N43AUTO`, Dr 572 / Cr 55500000.
- Tesorería **no ha registrado las comisiones** del banco.
- **Faltan las periodificaciones de cierre.** En el diario del mes solo están las retrocesiones del día 1 del cierre anterior.
- Hay **errores humanos** que hay que encontrar.

La web lo resume así: «Vuestros asientos se suman al diario y el balance resultante se compara, cuenta a cuenta, con el correcto. Lo que dejéis sin contabilizar también cuenta».

---

## 4. Entradas: diccionario de datos

### 4.1 Árbol de una fase y recuentos

```
phase_x/
├── erp/        ← ERP a la fecha de cierre (solo lo registrado): 24 ficheros
├── inbox/
│   ├── ap/<doc_id>/       ← cada documento recibido en el mes: message.json + PDF / Facturae XML / CFDI XML / DUA
│   └── ar/
│       ├── billing/<item>/    ← item.json + documento.pdf (certificación, parte de servicio, decreto, producción PPA, liquidación de mercado)
│       ├── remittances/       ← avisos de pago (JSON + PDF) y exportaciones del portal FACe (CSV)
│       └── notices/           ← penalidades notificadas en el mes (solo existe en test)
├── bank/<cuenta>/<YYYY-MM>.n43 | .camt053.xml | .csv  y  <YYYY-MM>.lines.jsonl   ← 4 últimos meses
├── tasks/      ← lista exacta de lo que hay que resolver (6 ficheros)
└── golden/     ← solo en phase_dev
```

| Elemento | Dev (julio) | Test (septiembre) |
|---|---|---|
| Documentos en `inbox/ap/` (= `tasks/ap_documents.json`) | 305 | 297 |
| Partidas en `inbox/ar/billing/` (= `tasks/ar_billing_items.json`) | 26 | 25 |
| Cobros a aplicar (`tasks/ar_receipts.json`) | 32 | 34 |
| Avisos de pago / CSV FACe en `inbox/ar/remittances/` | 6 / 2 | 7 / 3 |
| PDFs de penalidad en `inbox/ar/notices/` | (no hay carpeta) | 2 |
| Cuentas bancarias (`tasks/bank_accounts.json`) | 12 | 12 |
| Meses de extracto | 2026-04 a 2026-07 | 2026-06 a 2026-09 |
| Líneas de extracto del mes a cerrar | 286 | 279 |
| Asientos en el diario | 36.743 | 40.542 |

### 4.2 `erp/`

Número de filas: líneas JSONL, o elementos en los `.json`.

| Fichero | Dev | Test | Contenido |
|---|---|---|---|
| `companies.json` | 7 | 7 (idéntico) | Sociedades |
| `chart_of_accounts.jsonl` | 97 | 97 (idéntico) | Plan de cuentas |
| `tax_codes.json` | 3 bloques | idéntico | Códigos de IVA, retenciones y deducciones de cliente |
| `cost_centers.jsonl` | 25 | 25 (idéntico) | Centros de coste |
| `projects.jsonl` | 20 | 20 (idéntico) | Obras con sus PEP |
| `vendors.jsonl` | 225 | 227 | Maestro de proveedores |
| `contractor_certificates.jsonl` | 97 | 101 | Certificados del art. 43 LGT registrados |
| `customers.jsonl` | 87 | 87 (idéntico) | Maestro de clientes |
| `sales_contracts.jsonl` | 83 | 83 (idéntico) | Contratos de venta |
| `purchase_orders.jsonl` | 655 | 676 | Pedidos de compra |
| `goods_receipts.jsonl` | 21.699 | 23.870 | Entradas de mercancía (GR) y hojas de entrada de servicios (SES) |
| `journal_entries.jsonl` | 36.743 | 40.542 | Libro diario completo desde 01/10/2024 |
| `open_items.jsonl` | 1.626 | 1.755 | Partidas abiertas por socio y asignación al cierre |
| `ap_invoices.jsonl` | 4.207 | 4.694 | Facturas de proveedor contabilizadas (histórico) |
| `ap_document_log.jsonl` | 4.459 | 5.002 | Qué se hizo con cada documento de AP recibido antes |
| `ar_invoices.jsonl` | 1.410 | 1.564 | Facturas emitidas (histórico) |
| `billing_history.jsonl` | 487 | 537 | Partidas de facturación de meses anteriores, con sus datos |
| `promissory_notes.jsonl` | 8 | 10 | Pagarés recibidos de clientes |
| `factoring_assignments.jsonl` | 42 | 48 | Facturas cedidas al factor |
| `sepa_remittances.jsonl` | 22 | 24 | Remesas de recibos SEPA |
| `penalty_notices.jsonl` | 10 | 10 (idéntico) | Penalidades notificadas (histórico) |
| `intercompany_agreements.json` | 4 bloques | idéntico | Fees, préstamo, pooling y UTE (§2.1) |
| `fx_rates.jsonl` | 2.365 | 2.580 | Tipos SYN-BCE de 5 divisas, del 2024-09-23 al fin de mes |
| `bank_accounts.jsonl` | 12 | 12 (idéntico) | Cuentas bancarias |

#### `tax_codes.json`

Tiene tres bloques: `tax_codes`, `withholdings` y `customer_deductions`.

**`tax_codes`**: `{código: {country, kind, rate (pb), desc}}`.

| Código | País | `kind` | Tipo | Qué es |
|---|---|---|---|---|
| `S21` / `S10` / `S04` | ES | input | 21/10/4 % | IVA soportado deducible |
| `SEX` | ES | exempt | 0 | Exento o no sujeto: seguros, financieros, arrendamiento rústico, tasas |
| `SISP` | ES | reverse | 21 % | ISP en ejecuciones de obra, art. 84.Uno.2º f) LIVA: autorrepercusión |
| `SIC` | ES | reverse | 21 % | Adquisición intracomunitaria de bienes |
| `SIS` | ES | reverse | 21 % | Servicios de no establecidos (art. 69/84.Uno.2º a) |
| `SIMP` | ES | import | 21 % | IVA a la importación liquidado en DUA, suplido por el transitario |
| `SND` | ES | nondeductible | 21 % | IVA soportado no deducible (mayor gasto) |
| `SREAV` | ES | exempt | 0 | Régimen especial de agencias de viajes |
| `R21` / `R10` | ES | output | 21/10 % | IVA repercutido. R10: limpieza viaria, recogida y tratamiento de residuos. |
| `RISP` | ES | output_reverse | 0 | Sin IVA: ISP art. 84.Uno.2º f), cliente empresario o promotor |
| `REX` | ES | output | 0 | Exento o no sujeto |
| `P23` / `P13` / `P06` | PT | input | 23/13/6 % | IVA dedutível |
| `PSIS` | PT | reverse | 23 % | Autoliquidação en servicios de no residente (art. 2.º n.º 1 i) CIVA) |
| `PAUT` | PT | reverse | 23 % | Autoliquidação en construcción civil (art. 2.º n.º 1 j) CIVA) |
| `PR23` / `PR06` | PT | output | 23/6 % | IVA liquidado. PR06: empreitadas de reabilitação y obras públicas municipales. |
| `PRAUT` | PT | output_reverse | 0 | Autoliquidação por el adquirente, sin IVA en la factura |
| `M16` / `M00` | MX | input / exempt | 16/0 % | IVA acreditable / tasa 0 % |
| `MR16` | MX | output | 16 % | IVA trasladado |

**`withholdings`**: todas van a la cuenta 47510000.

| Código | Tipo | Qué es | Modelo |
|---|---|---|---|
| `IRPF15` | 1500 pb | Actividades profesionales, 15 % | 111 |
| `IRPF7` | 700 pb | Nuevos profesionales, 7 % | 111 |
| `IRPF19` | 1900 pb | Arrendamiento de inmueble urbano, 19 % | 115 |
| `MXISR10` | 1000 pb | ISR de honorarios de persona física, 10 % | MX-DIOT |
| `MXIVAR` | 1067 pb | IVA retenido, 2/3 de honorarios de persona física (10,6667 %) | MX-DIOT |
| `MXFLETE` | 400 pb | IVA retenido de autotransporte de carga, 4 % | MX-DIOT |
| `PTIRS25` | 2500 pb | Retenção na fonte IRS categoría B, 25 % | PT-DMR |

**`customer_deductions`**:

| Código | Tipo | Cuenta | Qué es |
|---|---|---|---|
| `RET_GAR5` | 500 pb | 43000900 | Retención de garantía del 5 % (cliente privado) |
| `MX5MILL` | 50 pb | 63100000 | Derecho de inspección y vigilancia de obra pública, 5 al millar |

#### `vendors.jsonl`

Maestro de proveedores: 225 en dev y 227 en test.

| Campo | Significado |
|---|---|
| `id` | `V1xxxxx` o `V-IC<sociedad>` (7 proveedores intragrupo, uno por sociedad) |
| `name`, `tax_id`, `vat_id`, `country`, `currency`, `language` (`es`/`pt`/`en`), `address{}` | Identificación. Países: ES 176, PT 24, MX 15, US 4, DE 2, IE 2, CN 1, GB 1 (dev). |
| `email` | Dominio habitual de facturación; se compara con el remitente para detectar fraude |
| `natural_person` | Persona física (relevante para retenciones) |
| `archetype` | Tipo de proveedor, 51 valores (abajo) |
| `reconciliation_account` | Cuenta de acreedor: 40000000 bienes y subcontratas, 41000000 servicios, 40300000 grupo |
| `default_tax_code`, `default_gl_account` | IVA y cuenta de gasto por defecto. «La ficha manda salvo que el documento o el pedido digan otra cosa». |
| `withholding` | `null`, `IRPF15`, `IRPF7`, `IRPF19`, `PTIRS25`, `MXFLETE` o `MXISR10+MXIVAR` |
| `payment_method` | `SEPA`, `CONF` (confirming), `DD` (domiciliación), `SPEI`, `IC`, `SWIFT`, `NET` (compensación) |
| `payment_terms_days` | 0, 5, 10, 15, 30, 45 o 60 |
| `bank{iban}` (o `{clabe, iban:null}` en MX) | IBAN vigente de la ficha |
| `bank_history[]` | IBAN anteriores `{iban, valid_to}` |
| `companies[]` | Sociedades a las que suministra |
| `po_required` | Si exige pedido |
| `created_on` | Fecha de alta |
| `intercompany` | Código de sociedad si es proveedor del grupo |
| `guarantee_retention_bp` | 500 en subcontratas con retención de garantía (54 en dev) |
| `alternative_payee` | Cesión a un factor: `{type:"FACTOR", name, iban, from_date}` (3 en dev) |
| `garnishments[]` | Embargos AEAT: `{ref, amount (límite), from_date}` (1 en dev) |

**Arquetipos y valores por defecto** (país, IVA, cuenta de gasto, cuenta de acreedor):

| Grupo | Arquetipos |
|---|---|
| Subcontratas de obra | `SUB_EARTH`, `SUB_STRUCT`, `SUB_MEP` y `SUB_FINISH` (ES, `SISP`, 60700000, 40000000). `PT_SUB` (PT, `PAUT`, 60700000). `MX_SUB` (MX, `M16`, 60700000). |
| Materiales | `ARIDOS`, `HORMIGON`, `FERRETERIA`, `ACERO`, `PREFAB`, `CONSUMIBLES` y `EPI` (S21, 60000000). `PT_MAT` (P23). `MX_MAT` (M16). `IMPORT_CN` (CN, `SEX`, 60000000). |
| Maquinaria e inmovilizado | `MAQUINARIA` (62110000). `EQUIP_DE` (DE, `SIC`, 21300000). `TALLER` (62200000). `PT_RENT` (P23, 62110000). `MX_RENT_USD` (US, `M00`, 62110000). |
| Suministros | `ELEC` y `TELECOM` (S21, 62800000). `WATER` (S10, 62800000). `FUEL` (62810000). `PT_UTIL`. `MX_UTIL`. |
| Residuos | `RESIDUOS` (S10, 62930000, 40000000). `LANDFILL` (S10, 62930000, 41000000). |
| Profesionales | `PROF_CORP`, `PROF_IND`, `LAB_OCA` y `MARKET_REP_FEE` (S21, 62300000). `PT_PROF`. `MX_PROF`. `RATING_GB` (GB, `SIS`). |
| Alquileres | `RENT_OFFICE` y `RENTING` (S21, 62100000). `RENT_RUSTIC` (`SEX`, 62100000). |
| Otros servicios | `SITE_SERV`, `OFFICE` y `COURIER` (62900000). `OM` (62200000). `TRAVEL` (`SREAV`, 62910000). `INSURANCE` (`SEX`, 62500000). `FORWARDER` (`SEX`, 62400000). `MX_FLETE` (M16, 62400000). |
| SaaS | `SAAS_ES` (S21). `SAAS_US` y `SAAS_IE` (`SIS`, 62920000). |
| Grupo | `INTERCOMPANY` (S21, 62940000, 40300000) |

Ejemplo (recortado):

```json
{"id": "V100132", "name": "Torre Castellana Norte Patrimonial Socimi, S.A.", "tax_id": "A64531697", "country": "ES", "currency": "EUR", "email": "facturacion@torrecastellananor.es", "natural_person": false, "archetype": "RENT_OFFICE", "reconciliation_account": "41000000", "default_tax_code": "S21", "default_gl_account": "62100000", "withholding": "IRPF19", "payment_method": "SEPA", "payment_terms_days": 5, "bank": {"iban": "ES7734078873791207916424"}, "bank_history": [], "companies": ["1000"], "po_required": false, "intercompany": null}
```

#### `contractor_certificates.jsonl`

Certificados de estar al corriente del art. 43.1.f LGT ya registrados. Campos: `vendor`, `issued_on`, `valid_until` (12 meses desde la emisión) y `reference` (`CERT-43-…`).

```json
{"vendor": "V100003", "issued_on": "2024-07-01", "valid_until": "2025-07-01", "reference": "CERT-43-15195852"}
```

#### `customers.jsonl`

87 clientes.

| Campo | Significado |
|---|---|
| `id` | `C2xxxxx` o `C-IC<sociedad>` |
| `name`, `tax_id`, `country`, `address{}`, `currency`, `iban` | Identificación |
| `kind` | `community` (44, comunidades de propietarios, recibos SEPA), `public` (20: 16 ES con DIR3, 2 PT, 2 MX), `private` (16), `group` (7) |
| `dir3` | `{oficina_contable, organo_gestor, unidad_tramitadora}`. Solo los 16 clientes públicos españoles; se usa para FACe. |
| `mandate` | Mandato SEPA (`KSU-000nn`), solo las comunidades |
| `insolvency` | `{declared_on, court, proceeding}`. Un cliente: `C200004`, concurso declarado el 2026-06-18. |
| `group` | Código de sociedad si es cliente intragrupo |

```json
{"id": "C200001", "name": "Ayuntamiento de Puerto Alcor", "tax_id": "P47686273", "country": "ES", "kind": "public", "currency": "EUR", "iban": "ES5538993139363339128644", "dir3": {"oficina_contable": "L07961094", "organo_gestor": "L07553049", "unidad_tramitadora": "L06219597"}}
```

#### `sales_contracts.jsonl`

83 contratos. Los campos dependen de `kind`:

| `kind` | N.º | Campos específicos |
|---|---|---|
| `obra_cert` (`CV-OB-…`) | 20 | `project`, `value` (céntimos), `tax` (`R21` en 11, `RISP` en 4, `PR06` en 2, `PRAUT` en 1, `MR16` en 2), `retention_bp` (0 o 500), `terms_days`, `factoring` (bool; 1100 tiene 5 en `true`). 3100: `mx5mill: true`, `advance_bp: 3000`. |
| `service_monthly` (`CT-1200-…`) | 17 | 8 contratos municipales (`CT-1200-LV01`…`-PJ02`, cada uno con su CC) y 9 industriales privados (`CT-1200-IND01`…`-IND09`, CC-1200-ADM). Campos: `cc`, `name`, `fee` (canon mensual), `tax` y `terms_days`; los municipales llevan además `price_revision` (bool) y `penalty_prob` (parámetro sintético). |
| `sepa_recibo` (`CT-1200-PRVnnn`) | 44 | `cc`, `name`, `fee`, `tax`, `terms_days` 0 |
| `ppa` (`PPA-1300-01`) | 1 | `plants[]`, `share_bp` 7000, `price_mwh` 4150 (céntimos/MWh) |
| `market` (`MKT-1300-01`) | 1 | `plants[]` (3 plantas) |

Campos comunes: `id`, `company`, `customer`, `start`, `end`, `tax` y `terms_days`.

```json
{"id": "CT-1200-LV01", "company": "1200", "customer": "C200001", "kind": "service_monthly", "cc": "CC-1200-LV01", "name": "Limpieza viaria de Puerto Alcor", "fee": 41200000, "tax": "R10", "terms_days": 30, "start": "2023-01-01", "end": "2028-12-31", "price_revision": true, "penalty_prob": 0.12}
```

#### `purchase_orders.jsonl`

| Campo | Significado |
|---|---|
| `id` | Número de pedido (`45000xxxxx`) |
| `company`, `vendor`, `created_on`, `currency` (EUR, MXN, USD) | Cabecera |
| `type` | `framework` 310, `standard` 263, `subcontract` 72, `capex` 6, `import` 4 (dev) |
| `project`, `purchasing_group` (`P01`…`P20`), `requester`, `text` | Datos de gestión |
| `items[]` | `{item (10, 20…), material, description, uom, quantity_milli, unit_price (céntimos/ud), gl_account, wbs, cost_center, tax_code, asset}`. `asset` es el id de inmovilizado en `capex`. |

```json
{"id": "4500016102", "company": "1100", "vendor": "V100020", "created_on": "2025-07-23", "type": "standard", "currency": "EUR", "project": "OB-1100-2513", "items": [{"item": 10, "material": "SERV", "description": "Levantamiento topográfico y replanteo", "uom": "ud", "quantity_milli": 1000, "unit_price": 664080, "gl_account": "62300000", "wbs": "OB-1100-2513.05", "cost_center": null, "tax_code": "S21", "asset": null}]}
```

#### `goods_receipts.jsonl`

Entradas de mercancía (`GR`, 18.308 en dev) y hojas de entrada de servicios (`SES`, 3.391 en dev).

| Campo | Significado |
|---|---|
| `id` | Número de entrada |
| `type` | `GR` o `SES` |
| `company`, `po`, `po_item`, `vendor`, `posting_date` | Referencias |
| `quantity_milli`, `amount` | Cantidad recibida; `amount` = valor a precio de pedido |
| `reference` | Albarán (`AL-nnnnnn`) o `SES-YYYYMM` |
| `journal_entry` | Asiento `WE`: Dr gasto o inmovilizado / Cr 40090000 |

```json
{"id": "5000020001", "type": "GR", "company": "1100", "po": "4500010082", "po_item": 10, "vendor": "V100060", "posting_date": "2024-10-04", "quantity_milli": 31500, "amount": 232754, "reference": "AL-051274", "journal_entry": "1100-2024-5000000007"}
```

#### `journal_entries.jsonl`

Libro diario completo desde la apertura (`OPENING`, 01/10/2024).

| Campo | Significado |
|---|---|
| `id` | Id del asiento (§2.4) |
| `company`, `doc_type`, `posting_date`, `document_date`, `reference`, `header_text`, `source`, `currency` | Cabecera. Las clases y orígenes están en §2.4. |
| `lines[]` | `{line, account, debit, credit, currency, amount_doc, partner, cost_center, wbs, tax_code, assignment, text}`. `debit` y `credit` en céntimos de moneda local; `amount_doc` en céntimos de la moneda de la línea; `assignment` = asignación de partida abierta (nº de factura, `pedido/posición`, `PAG<n>`…). |

```json
{"id": "1100-2026-1400000019", "company": "1100", "doc_type": "DZ", "posting_date": "2026-07-06", "document_date": "2026-07-06", "reference": "RCPT-000486", "header_text": "Cobro pendiente de aplicar (importación automática N43)", "source": "N43AUTO", "currency": "EUR",
 "lines": [{"line": 1, "account": "57200001", "debit": 44994059, "credit": 0, "currency": "EUR", "amount_doc": 44994059, "partner": null, "cost_center": null, "wbs": null, "tax_code": null, "assignment": null, "text": "Abono N43 pendiente de aplicar"},
           {"line": 2, "account": "55500000", "debit": 0, "credit": 44994059, "currency": "EUR", "amount_doc": 44994059, "partner": null, "cost_center": null, "wbs": null, "tax_code": null, "assignment": null, "text": "ORDEN DE PAGO 2026/094993"}]}
```

#### `open_items.jsonl`

Partidas abiertas al cierre: `{company, account, partner, assignment, balance}`, con balance en céntimos y signo (negativo = acreedor). En dev hay 13 cuentas: 40000900, 40090000, 43000000, 43300000, 40000000, 41000000, 43000900, 55300000, 43800000, 40700000, 43600000, 40300000 y 43100000.

```json
{"company": "1000", "account": "40090000", "partner": "V100123", "assignment": "4500022284/10", "balance": -2790000}
```

#### `ap_invoices.jsonl`

Facturas de proveedor ya contabilizadas.

| Campo | Significado |
|---|---|
| `doc_id`, `company`, `vendor`, `kind` (`invoice` / `credit_note`), `number`, `issue_date`, `received_on`, `posted_on`, `journal_entry` | Identificación |
| `currency` (EUR, MXN, USD, GBP), `net`, `tax`, `gross`, `withholding`, `retention`, `payable`, `due_date` | Importes en céntimos de la moneda del documento |
| `po_refs[]` | Pedidos referenciados |
| `decision` | `POST` o `HOLD` (decisión inicial) |
| `payee` | `null`, `{type:"FACTOR", name, iban}` o `{type:"AEAT_EMBARGO", name, ref, limit}` |
| `cases[]` | Etiquetas de la casuística del documento: `PO_REF_MISSING`, `PO_REF_TYPO`, `PO_REF_STALE`, `MULTI_PO`, `PRICE_SMALL`, `PRICE_OVER`, `QTY_NO_GR`, `CORRECTED_REISSUE`, `CREDIT_NOTE`, `FACTORING_CESSION`, `NEW_VENDOR`, `EMBARGO`… |

```json
{"doc_id": "API000073", "company": "1000", "vendor": "V100129", "kind": "invoice", "number": "2024/313", "issue_date": "2024-10-15", "received_on": "2024-10-23", "posted_on": "2024-10-24", "journal_entry": "1000-2024-5100000010", "currency": "EUR", "net": 531381, "tax": 111590, "gross": 642971, "withholding": 79707, "retention": 0, "payable": 563264, "due_date": "2024-11-14", "po_refs": [], "decision": "POST", "payee": null, "cases": []}
```

#### `ap_document_log.jsonl`

Registro de **todos** los documentos de AP recibidos antes del mes, facturas o no.

| Campo | Significado |
|---|---|
| `doc_id`, `received_on`, `company`, `vendor`, `number` | Identificación |
| `kind` | `invoice`, `credit_note`, `certificate_art43`, `statement`, `proforma`, `letter_cession`, `letter_bank_change` o `letter_embargo` |
| `decision` | `POST`, `NOT_INVOICE`, `REJECT`, `DUPLICATE` o `HOLD` |
| `reasons[]` | Códigos de §2.2 de las políticas; `["DUPLICATE"]` en duplicados |
| `duplicate_of` | Documento original, si es duplicado |
| `corrected_by` | Documento que sustituyó a uno rechazado |
| `journal_entry` | Asiento, si se contabilizó |
| `resolved_on` | Fecha de resolución de un `HOLD` |

```json
{"doc_id": "API005268", "received_on": "2024-11-26", "kind": "invoice", "vendor": "V100162", "company": "1200", "number": "2024-024437", "decision": "DUPLICATE", "reasons": ["DUPLICATE"], "duplicate_of": "API000118", "corrected_by": null, "journal_entry": null, "resolved_on": null}
```

#### `ar_invoices.jsonl`

Facturas emitidas.

| Campo | Significado |
|---|---|
| `id` | Número de factura (§2.4) |
| `company`, `customer`, `contract`, `kind` (`invoice` / `advance`) | Identificación |
| `date`, `due_date` | Fecha de factura y de vencimiento |
| `tax_code`, `net`, `tax`, `gross`, `retention` | Importes en céntimos |
| `deductions[]` | `{code: MX5MILL / ADV_AMORT, amount, account}` |
| `payable`, `currency` | Importe a cobrar y moneda |
| `factored` | Cedida al factor (bool) |
| `journal_entry` | Asiento de la factura |
| `face` | `{oficina_contable, organo_gestor, unidad_tramitadora, registry}` o `null` |
| `certification` | Id de la certificación, en facturas de obra |

```json
{"id": "OB26-00039", "company": "1100", "customer": "C200001", "contract": "CV-OB-1100-2511", "kind": "invoice", "date": "2026-05-31", "due_date": "2026-06-30", "tax_code": "R21", "net": 119706276, "tax": 25138318, "gross": 144844594, "retention": 0, "deductions": [], "payable": 144844594, "currency": "EUR", "factored": true, "journal_entry": "1100-2026-1800000048", "face": {"oficina_contable": "L07961094", "organo_gestor": "L07553049", "unidad_tramitadora": "L06219597", "registry": "REGAGE26e76096177"}, "certification": "CERT-OB-1100-2511-09"}
```

#### `billing_history.jsonl`

Partidas de facturación de meses anteriores. Comunes: `id`, `type`, `company`, `contract`, `customer` y `month`. Según `type`:

| `type` | N.º en dev | Bloque de datos |
|---|---|---|
| `OBRA_CERTIFICATION` | 267 | `cert{id, contract, project, number, month, cumulative (a origen), previous (anterior), current (esta certificación), approved, approved_on, approver, lines[{desc, amount, account, wbs}]}` |
| `SERVICE_MONTHLY` | 168 | `fee` (canon) y `extra_services[{order, desc, amount, approved}]` |
| `PPA` | 20 | `production{period, plants[{plant, name, mwh_milli}], share_bp, price_eur_mwh}` |
| `MARKET_SETTLEMENT` | 20 | `settlement{period, plants[{plant, name, mwh_milli, amount}], avg_price, deviations}` |
| `PRICE_REVISION` | 12 | `revision{old_fee, new_fee, effective, approved_on, months[], decree}` |

```json
{"id": "BILL-CT-1200-RR01-REV2025", "type": "PRICE_REVISION", "company": "1200", "contract": "CT-1200-RR01", "customer": "C200020", "month": "2025-03", "revision": {"old_fee": 68850000, "new_fee": 70882764, "effective": "2025-01-01", "approved_on": "2025-03-01", "months": ["2025-01", "2025-02"], "decree": "Decreto de Alcaldía 2025/4309"}}
```

#### `promissory_notes.jsonl`, `factoring_assignments.jsonl`, `sepa_remittances.jsonl` y `penalty_notices.jsonl`

| Fichero | Campos | Ejemplo |
|---|---|---|
| `promissory_notes.jsonl` | `number`, `customer`, `company`, `received_on`, `maturity`, `amount`, `bank`, `applications[{invoice, amount}]`, `journal_entry` | `{"number": "9784062", "customer": "C200008", "company": "1100", "received_on": "2025-03-20", "maturity": "2025-07-18", "amount": 45079746, "bank": "Caixa Mediterrània", "applications": [{"invoice": "OB24-00011", "amount": 45079746}], "journal_entry": "1100-2025-1400000011"}` |
| `factoring_assignments.jsonl` | `invoice`, `remittance` (`FAC…`), `date`, `advance`, `interest`, `fee`, `customer`. Clientes en dev: C200002, C200013, C200005, C200001. | `{"invoice": "OB24-00002", "remittance": "FAC24110850", "date": "2024-11-08", "advance": 184028319, "interest": 2046803, "fee": 511190, "customer": "C200005"}` |
| `sepa_remittances.jsonl` | `id` (`SDDyyyymm1200`), `date`, `invoices[]` (recibos `RC…`), `total` | `{"id": "SDD2026071200", "date": "2026-07-06", …}` |
| `penalty_notices.jsonl` | `invoice`, `contract`, `customer`, `amount`, `notified_on`, `resolution` | `{"invoice": "SU26-00056", "contract": "CT-1200-LV01", "customer": "C200001", "amount": 212795, "notified_on": "2026-05-25", "resolution": "Resolución 2026/940 – …"}` |

#### `bank_accounts.jsonl`

Cada cuenta tiene `id`, `company`, `bank`, `bic`, `iban` (o `clabe` en México), `gl_account`, `currency`, `statement_format` y `roles`. Todas se listan en §4.5.

### 4.3 `inbox/ap/`

Hay una carpeta por documento recibido en el mes, `inbox/ap/<doc_id>/`, con `message.json` y uno o dos adjuntos. `message.json` **no** trae campos de sociedad destinataria ni de proveedor: hay que deducirlos del documento (NIF del emisor y del receptor, razón social, pedido) y del canal (remitente, asunto).

**`message.json`**

| Campo | Cuándo | Significado |
|---|---|---|
| `doc_id` | siempre | Id de la tarea |
| `channel` | siempre | `email`, `facturae`, `portal`, `cfdi` o `paper` |
| `received_at` | siempre | Fecha y hora de recepción, dentro del mes |
| `mailbox` | siempre | `facturas.proveedores@kalmora.example` |
| `attachments[]` | siempre | Nombres de los ficheros adjuntos |
| `from`, `to`, `subject`, `body` | `email`, `cfdi` | Correo de envío. `from` es el dominio a comparar con la ficha. |
| `source` | `facturae`, `portal`, `paper` | «Buzón de factura electrónica (Facturae 3.2.2)», «Portal de proveedores (descarga)», «Registro de entrada en papel (escaneado en recepción)» |
| `uploaded_by` | `portal` | Cuenta que subió el documento al portal |

**Canales y adjuntos**

| Canal | Dev | Test | Adjuntos |
|---|---|---|---|
| `email` | 211 | 217 | Un PDF: `factura_<nº>.pdf`, `invoice_<nº>.pdf`, `letter_cession_<doc>.pdf`, `letter_bank_change_<doc>.pdf`, `letter_embargo_<doc>.pdf`, `certificate_art43_<doc>.pdf`, `proforma_<doc>.pdf` o `statement_<doc>.pdf`. En test, un correo trae dos PDFs: `factura_…pdf` y `DUA_<MRN>.pdf`. |
| `facturae` | 43 | 34 | `facturae_<nº>.xml` (Facturae 3.2.2). En test, uno trae un PDF en su lugar. |
| `portal` | 30 | 26 | Un PDF |
| `cfdi` | 15 | 15 | `factura_<nº>.pdf` + `<UUID>.xml` (CFDI 4.0) |
| `paper` | 6 | 5 | Un PDF escaneado |

| Tipo de adjunto (prefijo) | Dev | Test |
|---|---|---|
| `factura_*.pdf` (incluye los PDF de CFDI) | 225 | 227 |
| `invoice_*.pdf` (inglés) | 25 | 22 |
| `facturae_*.xml` | 43 | 33 |
| `<UUID>.xml` (CFDI) | 15 | 15 |
| `certificate_art43_*.pdf` | 4 | 6 |
| `proforma_*.pdf` / `statement_*.pdf` | 3 / 3 | 3 / 3 |
| `letter_*.pdf` | 2 (cesión, cambio de cuenta) | 3 (cesión, embargo, cambio de cuenta) |
| `DUA_*.pdf` | 0 | 1 |

**Formatos de documento**

- **PDF de factura:** en español, portugués o inglés, de una a tres páginas. Contenido típico:
  - emisor con NIF; destinatario («FACTURAR A», con NIF);
  - nº de factura, fecha y periodo; «Su pedido» o «Pedido cliente»;
  - líneas con albaranes `AL-…` y fecha, cantidad, unidad, precio e importe;
  - base, IVA (o «IVA ISP (0%)», «IVA autoliquidação (0%)», «Reverse charge»);
  - retenciones («Retención IRPF 15%», «Retención garantía 5 %», «Retenção 5 %», «Retención ISR/IVA 4%»), total y total a pagar;
  - forma de pago e **IBAN de domiciliación**.

  Las certificaciones de subcontrata muestran «Certificado a origen», «Certificado anterior» e «Importe de esta certificación».

  La mayoría de los PDF llevan capa de texto. **Algunos son imagen sin texto** (3 en dev, 4 en test) y requieren OCR.
- **Facturae 3.2.2** (namespace `fe:`):
  - `FileHeader/Batch`;
  - `Parties/SellerParty|BuyerParty/TaxIdentification/TaxIdentificationNumber`;
  - `Invoices/Invoice/InvoiceHeader/InvoiceNumber`;
  - `InvoiceIssueData/IssueDate`, con `InvoicingPeriod`;
  - `TaxesOutputs/Tax{TaxRate, TaxableBase, TaxAmount}`;
  - `InvoiceTotals{TotalGrossAmount, TotalTaxOutputs, TotalTaxesWithheld, InvoiceTotal, TotalExecutableAmount}`;
  - `Items/InvoiceLine{ItemDescription, Quantity, UnitPriceWithoutTax, TotalCost}`.

  Los importes vienen en euros con decimales.
- **CFDI 4.0:**
  - `cfdi:Comprobante@{Serie, Folio, Fecha, SubTotal, Moneda, Total, TipoDeComprobante, MetodoPago, FormaPago}`;
  - `cfdi:Emisor@{Rfc, Nombre}`;
  - `cfdi:Receptor@{Rfc (KMI91110719K = 3100), UsoCFDI}`;
  - `cfdi:Conceptos/cfdi:Concepto@{Cantidad, ValorUnitario, Importe, Descripcion}`;
  - `cfdi:Impuestos/Traslados`;
  - `tfd:TimbreFiscalDigital@UUID`.

  Siempre llega acompañado de su PDF; ambos deben coincidir (`CFDI_MISMATCH`).
- **DUA** (test): documento de importación con MRN, aduana, fecha de levante, importador, representante aduanero (representación indirecta), pedido, origen, valor estadístico en EUR, tipo de cambio USD/EUR aplicado, aranceles e **IVA a la importación** liquidado por el representante.
- **Documentos que no son factura:**
  - carta de **cesión de créditos** (factor, IBAN del factor, fecha de efectos);
  - carta de **cambio de cuenta** (IBAN nuevo y anterior, fecha, «certificado de titularidad» adjunto);
  - **diligencia de embargo** de la AEAT;
  - **certificado art. 43.1.f LGT** (referencia `CERT-43-…`, emisión y validez de 12 meses);
  - **proforma** («Documento sin validez fiscal»);
  - **extracto o recordatorio** de deuda del proveedor.

### 4.4 `inbox/ar/`

**`billing/<billing_item>/`:** `item.json` + `documento.pdf`. Los importes y el estado de aprobación **solo están en el PDF**.

```json
{"billing_item": "BILL-CV-OB-1100-2511-202607", "type": "OBRA_CERTIFICATION", "company": "1100", "contract": "CV-OB-1100-2511", "customer": "C200001", "month": "2026-07", "documents": ["documento.pdf"]}
```

| `type` | Dev | Test | Qué contiene `documento.pdf` |
|---|---|---|---|
| `OBRA_CERTIFICATION` | 14 | 13 | «Certificación de obra nº N»: obra, contrato, cliente, mes certificado, importe del mes por capítulo, **certificado a origen, anterior e importe de la presente certificación**, y la aprobación (o no) de la Dirección Facultativa |
| `SERVICE_MONTHLY` | 8 | 8 | «Parte mensual de servicio – conformidad municipal»: canon mensual y servicios extraordinarios, con orden, importe y estado (conforme o pendiente) |
| `PRICE_REVISION` | 2 | 2 | Decreto de Alcaldía: nuevo canon, canon anterior, **fecha de efectos**, meses facturables y fecha de aprobación |
| `PPA` | 1 | 1 | Informe mensual de producción, medida fiscal: MWh netos por planta, % del PPA y precio fijo. El periodo es el mes anterior: el item `…-202606` se factura en julio. |
| `MARKET_SETTLEMENT` | 1 | 1 | Liquidación del representante (Ibermarket): MWh e importe por planta, precio medio, **coste de desvíos**. Los honorarios del representante se facturan aparte y se compensan en el pago. |

Partidas de dev: 14 certificaciones (1100 ×9, 1910, 2100 ×2, 3100 ×2), los 8 contratos de servicios de 1200, `REV2026` de `CT-1200-LV01` y `CT-1200-LV02`, `BILL-PPA-1300-01-202606` y `BILL-MKT-1300-01-202606`.

En test hay 13 certificaciones (OB-1100-2520 ya no aparece), los 8 de servicios, `REV2026` de `CT-1200-AL01` y `CT-1200-PJ01`, y PPA y MKT `-202608`.

**`remittances/`**

- **`aviso_pago_<RCPT-nnnnnn>.json`** + **`.pdf`:** el JSON trae `{file, channel ("pdf" / "email"), from_ (pagador), received_at}`. El PDF («Comunicación de pago / Remittance advice») trae beneficiario, fecha valor, referencia de la orden, facturas pagadas con importe y total transferido.
- **`FACe_estado_facturas_<cliente>_<YYYYMM>.csv`:** exportación del portal FACe.
  - Separador `;`, decimales con coma, fechas `DD/MM/YYYY`.
  - Columnas: `numero_registro;numero_factura;fecha_factura;importe;estado;fecha_estado;importe_pagado`.
  - Ejemplo: `REGAGE26e21895867;OB26-00035;30/04/2026;449940,59;PAGADA;06/07/2026;449940,59`.

**`notices/`** (solo en test): `penalidad_<factura>.pdf`. Es una resolución municipal con contrato, factura, importe de la penalidad y la frase «Su importe se deducirá del próximo pago (art. 194 LCSP)».

### 4.5 `bank/`

Hay 12 cuentas y en cada una 4 meses de extracto (dev: 2026-04 a 2026-07; test: 2026-06 a 2026-09). Cada mes trae el fichero bruto y `<YYYY-MM>.lines.jsonl`.

| Cuenta | Sociedad | Banco | `gl_account` | Divisa | Formato | `roles` | Líneas del mes (dev / test) |
|---|---|---|---|---|---|---|---|
| `BIN-1000` | 1000 | Banco Ibérico del Norte | 57200001 | EUR | `n43` | pool_header, payments, loans | 42 / 39 |
| `CMA-1000` | 1000 | Caja Mediterránea de Ahorros | 57200002 | EUR | `n43` | direct_debits | 16 / 11 |
| `BIN-1100` | 1100 | Banco Ibérico del Norte | 57200001 | EUR | `n43` | pool_participant, payments, receipts | 37 / 34 |
| `BAE-1100` | 1100 | Banco Atlántico Empresas | 57200003 | EUR | `n43` | confirming, factoring, avales, receipts | 13 / 13 |
| `CMA-1100` | 1100 | Caja Mediterránea de Ahorros | 57200002 | EUR | `n43` | direct_debits, receipts, loans | 38 / 29 |
| `BIN-1200` | 1200 | Banco Ibérico del Norte | 57200001 | EUR | `n43` | pool_participant, payments, receipts | 30 / 45 |
| `CMA-1200` | 1200 | Caja Mediterránea de Ahorros | 57200002 | EUR | `n43` | sepa_collections, direct_debits | 24 / 26 |
| `BAE-1300` | 1300 | Banco Atlántico Empresas | 57200003 | EUR | `n43` | payments, receipts, direct_debits | 16 / 15 |
| `CMA-1910` | 1910 | Caja Mediterránea de Ahorros | 57200002 | EUR | `n43` | payments, receipts, direct_debits | 23 / 24 |
| `BLC-2100` | 2100 | Banco Lusitano Comercial | 57200004 | EUR | `camt053` | payments, receipts, direct_debits | 21 / 18 |
| `BANH-3100-MXN` | 3100 | Banco del Anáhuac | 57200005 | MXN | `csv_mx` | payments, receipts, direct_debits | 22 / 21 |
| `BANH-3100-USD` | 3100 | Banco del Anáhuac | 57200006 | USD | `csv_mx` | usd | 4 / 4 |

La pareja `(company, gl_account)` identifica la cuenta bancaria en el diario.

**`<YYYY-MM>.lines.jsonl`**

Tiene una fila por movimiento, en el mismo orden que el fichero bruto: `{bank_line, booking_date, value_date, amount (céntimos con signo: + abono, − cargo, en la divisa de la cuenta), currency, text}`.

- `text` es el primer concepto, truncado.
- Las referencias, los conceptos complementarios y el importe en divisa original solo están en el fichero bruto.

```json
{"bank_line": "BL0000581", "booking_date": "2026-07-06", "value_date": "2026-07-06", "amount": 44994059, "currency": "EUR", "text": "TRANSFERENCIA DE TESORERIA AYUNTAMIENTO DE ALCA"}
```

**Norma 43 (AEB/CSB 43), `.n43`:**

- Registros de 80 caracteres, codificación **ISO-8859-1 (latin-1)**, fin de línea CRLF.
- Importes de 14 dígitos con 2 decimales implícitos.
- Clave debe/haber: `1` = debe (cargo), `2` = haber (abono).
- El `bank_line` **no** está en el fichero: se une por posición con `lines.jsonl`.

| Registro | Campo (posiciones 1-based) |
|---|---|
| `11` cabecera de cuenta | banco 3-6, oficina 7-10, cuenta 11-20, fecha inicial AAMMDD 21-26, fecha final 27-32, clave D/H del saldo 33, saldo inicial 34-47, divisa 48-50 (978 = EUR), modalidad 51, titular 52-77 |
| `22` movimiento | oficina 7-10, fecha de operación 11-16, fecha valor 17-22, concepto común 23-24, concepto propio 25-27, clave D/H 28, importe 29-42, nº de documento 43-52, referencia 1 53-64, referencia 2 65-80 |
| `23` concepto complementario | código 01-05 en 3-4, concepto 5-42, concepto 43-80 (hasta 5 por movimiento) |
| `24` equivalencia de divisa | código de dato 3-4, divisa origen ISO numérica 5-7 (840 USD, 826 GBP), importe en divisa 8-21. Aparece en transferencias SWIFT de `BIN-1000` y `BIN-1100`. |
| `33` final de cuenta | nº de apuntes debe 21-25, total debe 26-39, nº de apuntes haber 40-44, total haber 45-58, clave D/H 59, saldo final 60-73, divisa 74-76 |
| `88` fin de fichero | nueves 3-20, nº total de registros 21-26 |

Conceptos comunes observados en `22`, con su significado AEB: 02 abonarés e ingresos (transferencias recibidas), 03 domiciliados y recibos, 04 transferencias y traspasos, 05 amortización de préstamos, 06 remesas de efectos, 12 tarjetas, 13 operaciones con el extranjero, 14 devoluciones e impagados, 15 nóminas y seguros sociales, 17 intereses, comisiones y gastos. En los ficheros de test aparece además 98 (anulaciones y correcciones).

Ejemplo:

```
119101293828481422432607012607312000000000000009783KALMORA CONSTRUCCION
22    2938260703260703040121000000048850003365553690            APORT 07/2026
2301TRANSFERENCIA A UTE KALMORA HIDROCON L
```

**CAMT.053** (`BLC-2100`, `.camt053.xml`):

- Namespace `urn:iso:std:iso:20022:tech:xsd:camt.053.001.08`.
- Saldos `Bal/Tp/CdOrPrtry/Cd` = `OPBD` (apertura) y `CLBD` (cierre), con `CdtDbtInd`.
- Cada `Ntry` trae:
  - `NtryRef` (**= `bank_line`**), `Amt@Ccy`, `CdtDbtInd` (`CRDT` / `DBIT`), `Sts`, `BookgDt`, `ValDt`;
  - `BkTxCd/Prtry/Cd` (5 dígitos: concepto común + propio, como en N43);
  - `EndToEndId`, `RltdPties/Dbtr|Cdtr/Nm`, `RmtInf/Ustrd`.

**CSV mexicano** (`BANH-3100-MXN` y `BANH-3100-USD`, `.csv`, UTF-8):

- Línea 1: `Cuenta,<CLABE>,Moneda,MXN|USD,Periodo,01/07/2026 al 31/07/2026,Saldo inicial,<decimal>`.
- Línea 2: `Fecha,Concepto,Referencia,Clave de rastreo,Cargo,Abono,Saldo`.
- Después, una fila por movimiento, con fecha `DD/MM/YYYY` e importes decimales con punto. Dentro de los nombres, las comas se sustituyen por espacios.
- La cuenta USD está en USD; 3100 lleva su contabilidad en MXN.

```
06/07/2026,TRANSFERENCIA DE INSTITUTO DE SALUD DEL ESTADO  ORDEN DE PAGO 2026/035614 ORDENANTE INSTITUTO DE SALUD DEL ESTAD,ORDEN DE PAGO 20,202607063719685188,0.00,35941519.16,435891305.15
```

### 4.6 `tasks/`

| Fichero | Forma | Dev | Test | Qué se entrega |
|---|---|---|---|---|
| `ap_documents.json` | lista de `doc_id` | 305 | 297 | Una fila de `ap.jsonl` por `doc_id` |
| `ar_billing_items.json` | lista de `billing_item` | 26 | 25 | Una fila de `ar_billing.jsonl` por partida |
| `ar_receipts.json` | lista de `bank_line` | 32 | 34 | Una fila de `ar_cash.jsonl` por línea. Todas son abonos del mes. Dev: BIN-1200 13, BIN-1100 11, BLC-2100 4, BAE-1300 2, BANH-3100-MXN 2. Test: BIN-1200 21, BIN-1100 5, BLC-2100 3, BAE-1300 2, BANH-3100-MXN 2, CMA-1910 1. |
| `bank_accounts.json` | lista de cuentas | 12 | 12 | Una fila de `bank_rec.jsonl` por cuenta |
| `intercompany.json` | `{pairs, accounts}` | 7 pares | igual | `pairs`: `["1000","1100"]`, `["1000","1200"]`, `["1000","1300"]`, `["1000","2100"]`, `["1000","3100"]`, `["1100","1200"]`, `["1100","1910"]`. `accounts`: 43300000, 40300000, 55200000, 55210000, 55220000, 24230000, 16330000, 40090000. |
| `close.json` | `{month, steps}` | `2026-07` | `2026-09` | `steps`: `ACCRUAL`, `PREPAID`, `WIP_REVENUE`, `FX_REVAL`, `BAD_DEBT`, `DOUBTFUL_RECLASS` |

### 4.7 `golden/` (solo dev)

Son las respuestas correctas de julio, que usa `score.py`. Los ficheros llevan más campos que los que pide `FORMATO_ENTREGA.md`; el scorer ignora los que no lee (§7).

| Fichero | Filas | Campos (los que no puntúan, entre corchetes) |
|---|---|---|
| `ap.jsonl` | 305 | `doc_id`, `document_type`, `decision`, `reasons`, [`cases`], `company`, `vendor_id`, `invoice_number`, `invoice_date`, `currency`, `net`, `tax`, `gross`, `withholding`, `retention`, `payable`, [`due_date`], `duplicate_of`, [`credit_note_of`], `payee` (con [`name`, `iban`]), `payment_block`, `lines[{amount, account, cost_center, wbs, tax_code, po, po_item, [goods_receipts]}]`, `journal_entry` (asiento completo con id, cabecera y líneas), `action`, [`action_data`]. Los `NOT_INVOICE` no llevan importes, líneas ni asiento. |
| `ar_billing.jsonl` | 26 | `billing_item`, [`type`], `company`, [`customer`, `contract`], `expected`, `invoice{date, due_date, tax_code, net, tax, gross, retention, deductions[{code, amount, account}], payable, currency, face, lines[{description, amount, account, cost_center, wbs}]}`, `journal_entry` |
| `ar_cash.jsonl` | 32 | `bank_line`, [`account`], `company`, [`date`, `amount`, `kind`], `customer`, `applications[{invoice, amount}]`, `residuals[{type, [invoice], amount, [account]}]`, `adjustment[{company, account, debit, credit, partner, [assignment], cost_center, wbs}]` |
| `bank_rec.jsonl` | 12 | `account`, `company`, [`gl_account`, `currency`, `statement_opening`, `statement_closing`], `matches[{bank_lines, book_lines, [category]}]`, `unmatched_bank[{bank_line, category, [amount]}]`, `unmatched_book[{book_line, category, [amount]}]`, `adjustments[{[ref], category, lines}]`. En `matches[].category` aparece `MATCH` o una categoría «de diferencia». |
| `ic.jsonl` | 5 | `pair`, [`account`], `cause`, [`detail`], `amount`, `responsible`, `adjustment`, [`note`]. `POOLING_NOT_BOOKED` lleva `adjustment: []`. |
| `close.jsonl` | 76 | `type`, `company`, la clave (`vendor` / `invoice` / `item` / `customer` / `billing_item`), `amount`, [`je`], `journal_entry`. Extras: `ACCRUAL` [`invoice`, `period`, `estimate`]; `FX_REVAL` [`currency`, `foreign`, `rate`]; `BAD_DEBT` [`target`, `previous`]. |
| `trial_balance_recorded.jsonl` | 244 | `{company, account, balance}`. `balance` = Σ(debit − credit) del diario registrado (`erp/journal_entries.jsonl`) por sociedad y cuenta, en moneda local. |
| `trial_balance_truth.jsonl` | 259 | `{company, account, balance}`: el balance correcto al cierre del mes |
| `summary.json` | — | `{phase: "dev", month: "2026-07", ap_documents: 305, ar_billing_items: 26, ar_receipts: 32, bank_accounts: 12, ic_differences: 5, close_entries: 76, tagged: {IC: 3, AP: 242, BANK: 54, AR_BILL: 25, AR_CASH: 32, CLOSE: 76}}` |

**Observaciones de formato en el golden de dev.**

- En los documentos AP en USD, los importes de cabecera y de `lines` van en la **moneda del documento** (`currency`). El `journal_entry` va en moneda local, con `currency` y `amount_doc` por línea.
- Los `DUPLICATE` llevan `reasons: ["DUPLICATE"]`.

**Distribución de valores en el golden de dev** (julio):

| Dimensión | Valores |
|---|---|
| AP `decision` | POST 242, HOLD 19, REJECT 18, DUPLICATE 14, NOT_INVOICE 12 (ningún `POST_PAYMENT_BLOCK`) |
| AP `document_type` | INVOICE 283, CREDIT_NOTE 9, CONTRACTOR_TAX_CERTIFICATE 4, PROFORMA 3, VENDOR_STATEMENT 3, DOWN_PAYMENT_REQUEST 1, FACTORING_NOTICE 1, BANK_DETAILS_CHANGE 1 (ningún `TAX_GARNISHMENT_ORDER`) |
| AP `reasons` (HOLD/REJECT) | QTY_NOT_RECEIVED 9, PRICE_VARIANCE 6, WRONG_ADDRESSEE 3, ISP_NOT_APPLIED 3, VAT_RATE_INCORRECT 3, BANK_DETAILS_CHANGED 2, MANDATORY_FIELD_MISSING 2, CERTIFICATION_CUMULATIVE_BILLED 2, WITHHOLDING_MISSING 2, VENDOR_NOT_IN_MASTER 2, ARITHMETIC_ERROR 2, CFDI_MISMATCH 1 |
| AP `payee` | FACTOR 1 (ningún `AEAT_EMBARGO`) |
| AR billing `expected` | INVOICE 25, SKIP_PENDING_APPROVAL 1 |
| AR cash `residuals[].type` | FACTORED_MISDIRECTED 2, NON_CUSTOMER 2, PENALTY 1, NETTING_AP 1, OVERPAYMENT_DUPLICATE 1. Hay 2 cobros con `customer: null`. |
| Banco `unmatched_bank` | BANK_FEE_NOT_BOOKED 31, DIRECT_DEBIT_NOT_BOOKED 17, INTEREST_NOT_BOOKED 4, RETURNED_DIRECT_DEBIT 4, CARD_SETTLEMENT_NOT_BOOKED 1, BANK_ERROR 1, UNRECORDED_RECEIPT 1, WRONG_BANK_ACCOUNT 1, POOLING_NOT_BOOKED 1 |
| Banco `unmatched_book` | PRIOR_PERIOD_BANK_ITEM 4, OUTSTANDING_PAYMENT 1, TRANSFER_IN_TRANSIT 1, BOOK_DUPLICATE 1, WRONG_BANK_ACCOUNT 1, FX_REVALUATION 1 |
| Banco `adjustments[].category` | BANK_FEE_NOT_BOOKED 25, DIRECT_DEBIT_NOT_BOOKED 14, FX_RATE_DIFFERENCE 5, INTEREST_NOT_BOOKED 2, FACTORING_CHARGES_NOT_BOOKED 2, RETURNED_DIRECT_DEBIT 2, y 1 de cada una: CARD_SETTLEMENT_NOT_BOOKED, WRONG_BANK_ACCOUNT, UNRECORDED_RECEIPT, BOOK_DUPLICATE, LOAN_INTEREST_NOT_BOOKED, POOLING_NOT_BOOKED |
| IC `cause` | INTEREST_DAY_COUNT, INVOICE_IN_TRANSIT, WRONG_TRADING_PARTNER, DUPLICATE_POSTING, POOLING_NOT_BOOKED (1 de cada) |
| Cierre `type` | ACCRUAL 57, PREPAID 9, FX_REVAL 8, WIP_REVENUE 1, BAD_DEBT 1 (ningún `DOUBTFUL_RECLASS`) |

---

## 5. Las seis tareas y el balance

Las reglas de decisión salen de `POLITICAS_CONTABLES.md`. Lo que no está en las políticas «se deduce del histórico: el diario y los documentos ya procesados muestran cómo se ha hecho siempre».

### 5.0 Mapa de entradas por tarea

| Tarea | Unidad de trabajo | Entradas principales |
|---|---|---|
| AP | `doc_id` | `inbox/ap/<doc_id>/*`; `vendors`, `contractor_certificates`, `purchase_orders`, `goods_receipts`, `open_items` (40090000), `ap_invoices`, `ap_document_log`, `journal_entries` (histórico de imputación), `tax_codes`, `fx_rates`, `companies`, `projects`, `cost_centers` |
| AR billing | `billing_item` | `inbox/ar/billing/<item>/*`; `sales_contracts`, `customers` (DIR3), `billing_history`, `ar_invoices`, `open_items` (43800000 anticipo), `projects`, `tax_codes` |
| AR cash | `bank_line` | `bank/<cuenta>/<mes>.*`; `inbox/ar/remittances/*`, `inbox/ar/notices/*`; `open_items`, `ar_invoices`, `customers`, `promissory_notes`, `factoring_assignments`, `penalty_notices`, `vendors` (netting), `journal_entries` (asientos `N43AUTO`) |
| Bancos | cuenta bancaria | `bank/<cuenta>/*` (mes y anteriores), `bank_accounts`, `journal_entries` (líneas 572), `vendors`, `customers`, `fx_rates`, `intercompany_agreements`, `factoring_assignments`, `sepa_remittances` |
| Intragrupo | diferencia por pareja | `journal_entries`, `open_items`, `intercompany_agreements`, `tasks/intercompany.json`, documentos IC en `inbox/ap` |
| Cierre | partida de cierre | `journal_entries`, `ap_invoices` (histórico por proveedor), `open_items`, `fx_rates`, `customers` (`insolvency`), `ar_invoices`, `billing_history` y la certificación pendiente de `inbox/ar/billing` |
| Balance | — | Se calcula solo a partir de todos los asientos entregados |

### 5.1 AP: bandeja de proveedores (30 %)

**Objetivo.** Para cada documento de `tasks/ap_documents.json`:

- clasificar el tipo;
- decidir (contabilizar, retener, rechazar, duplicado o no factura) con su motivo;
- extraer la cabecera;
- imputar cada línea (cuenta, objeto de coste, IVA, pedido y posición);
- determinar el beneficiario del pago;
- si se contabiliza, construir el **asiento**.

**Paso 1. Tipo de documento** (§2.1):

| `document_type` | Qué es | Decisión y acción |
|---|---|---|
| `INVOICE` | Factura ordinaria (PDF, Facturae XML o CFDI) | Según el paso 2 |
| `CREDIT_NOTE` | Factura rectificativa o abono | `POST`: asiento inverso imputado a la misma cuenta y objeto de coste |
| `DOWN_PAYMENT_REQUEST` | Solicitud de anticipo de un proveedor extranjero con pedido aprobado | `POST`: Dr 40700000 / Cr 40000000 |
| `PROFORMA` | Proforma u oferta | `NOT_INVOICE`, `action: NONE` |
| `VENDOR_STATEMENT` | Extracto o recordatorio de deuda | `NOT_INVOICE`, `action: NONE` |
| `FACTORING_NOTICE` | Notificación de cesión de créditos | `NOT_INVOICE`, `action: REGISTER_ALTERNATIVE_PAYEE` |
| `TAX_GARNISHMENT_ORDER` | Diligencia de embargo de la AEAT | `NOT_INVOICE`, `action: REGISTER_EMBARGO` |
| `BANK_DETAILS_CHANGE` | Carta firmada de cambio de cuenta con certificado bancario | `NOT_INVOICE`, `action: UPDATE_BANK_DETAILS` |
| `CONTRACTOR_TAX_CERTIFICATE` | Certificado de estar al corriente (art. 43.1.f LGT) | `NOT_INVOICE`, `action: UPDATE_CONTRACTOR_CERTIFICATE` |

**Paso 2. Decisión sobre una factura** (§2.2). Se comprueba **en este orden** y **gana la primera que falle**:

| Orden | Decisión | Código (`reasons`) | Condición |
|---|---|---|---|
| 1 | `DUPLICATE` | `duplicate_of` = `doc_id` del primero | Mismo proveedor, mismo número de factura e importe, ya recibido en el histórico o antes en el mes. El número se normaliza sin guiones, barras ni prefijos. Puede llegar como reenvío, escaneo, por otro canal o con el número escrito de otra forma. **Dos alquileres del mismo importe en meses distintos no son duplicados.** |
| 2 | `REJECT` (hay que pedir una factura nueva) | `MANDATORY_FIELD_MISSING` | Falta el NIF del destinatario |
| 2 | `REJECT` | `WRONG_ADDRESSEE` | Va dirigida a otra sociedad del grupo distinta de la que hizo el pedido, o a 1100 en vez de a la UTE 1910 |
| 2 | `REJECT` | `ISP_NOT_APPLIED` | Un subcontratista de obra repercute IVA cuando procede inversión del sujeto pasivo |
| 2 | `REJECT` | `VAT_RATE_INCORRECT` | Tipo de IVA distinto del aplicable. Recogida y tratamiento de residuos, limpieza viaria y agua llevan **10 %**; el resto, **21 %**. |
| 2 | `REJECT` | `WITHHOLDING_MISSING` | Un profesional persona física o un arrendador urbano no practica la retención |
| 2 | `REJECT` | `ARITHMETIC_ERROR` | El total no es la base más las cuotas |
| 2 | `REJECT` | `CERTIFICATION_CUMULATIVE_BILLED` | La subcontrata factura el importe **a origen** en vez del de **esta certificación** |
| 2 | `REJECT` | `CFDI_MISMATCH` | El XML del CFDI no coincide con el PDF |
| 3 | `HOLD` (no se contabiliza todavía) | `VENDOR_NOT_IN_MASTER` | El proveedor no está dado de alta. `vendor_id` = `null`. |
| 3 | `HOLD` | `BANK_DETAILS_CHANGED` | El IBAN de la factura difiere del de la ficha y no lo respalda ni una carta de cambio firmada (registrada o recibida en el mes) ni una cesión de créditos a un factor. También cuando el correo viene de un dominio parecido al habitual. Se trata como **posible fraude**. |
| 3 | `HOLD` | `QTY_NOT_RECEIVED` | Algún albarán facturado no tiene entrada de mercancía |
| 3 | `HOLD` | `PRICE_VARIANCE` | El precio unitario supera el del pedido en **más del 2 %** o en **más de 150 €** por línea |
| 4 | `POST_PAYMENT_BLOCK` | `payment_block = "CONTRACTOR_CERTIFICATE_EXPIRED"` | El subcontratista de obra no tiene certificado del art. 43 vigente a la fecha de la factura |
| 5 | `POST` | `[]` | Una diferencia de precio dentro de la tolerancia se imputa al mismo gasto u objeto de coste que la línea |

**Beneficiario del pago (`payee`):**

- Si hay **cesión de créditos vigente a la fecha de la factura**, el pago va al factor: `{"type": "FACTOR"}`.
- Si hay **diligencia de embargo de la AEAT recibida antes que la factura**, va a la AEAT: `{"type": "AEAT_EMBARGO"}`.
- En cualquier otro caso, `null`.

En los datos, las cesiones registradas están en `vendors.alternative_payee` (con `from_date`) y los embargos en `vendors.garnishments`. Las nuevas llegan como cartas en la bandeja.

**Paso 3. Asiento de una factura de proveedor** (§2.3 y §1):

| Concepto | Asiento |
|---|---|
| Líneas con pedido y entrada | Dr **40090000** (puente GR/IR) por el **valor de las entradas** (cantidad × precio del pedido), socio = proveedor. La diferencia de precio va al Dr de la cuenta de gasto de la línea, con su objeto de coste. |
| Líneas sin pedido | Dr a la cuenta de gasto o inmovilizado, con su objeto de coste |
| IVA soportado deducible | Dr 47200000 |
| ISP de obra (`SISP`), intracomunitario (`SIC`), servicios de no establecidos (`SIS`), autoliquidação PT (`PAUT`/`PSIS`) | Dr **47210000** y Cr **47710000** por la cuota autorrepercutida |
| IVA de importación del DUA, suplido por el transitario | Dr 47200000 |
| Exento o no sujeto (seguros, arrendamiento rústico, tasas, REAV) | Sin cuota |
| Retenciones (IRPF y equivalentes) | Cr **47510000**. Tipos: IRPF 15 % profesional, 7 % nuevo profesional, 19 % arrendamiento urbano. México: ISR 10 %, IVA retenido 10,67 %, fletes 4 %. Portugal: IRS 25 %. |
| Retención de garantía de obra (5 % sobre la base) | Cr **40000900**, socio = proveedor |
| Cuenta del proveedor (`reconciliation_account`) | Cr por el **importe a pagar** = total − retenciones − garantía − anticipos aplicados |
| Anticipos aplicados | Cr 40700000 al **tipo de cambio histórico** del anticipo |
| Moneda extranjera | Cada línea al tipo SYN-BCE de la fecha de factura (o el último publicado), redondeo por línea. La diferencia la absorbe la línea del proveedor. |
| Socio y objeto de coste | Según §2.2 y §2.3 de este documento |

**Salida (`ap.jsonl`, una fila por `doc_id`):**

| Campo | Tipo y valores | Notas |
|---|---|---|
| `doc_id` | string | Clave |
| `document_type` | `INVOICE`, `CREDIT_NOTE`, `DOWN_PAYMENT_REQUEST`, `PROFORMA`, `VENDOR_STATEMENT`, `FACTORING_NOTICE`, `TAX_GARNISHMENT_ORDER`, `BANK_DETAILS_CHANGE`, `CONTRACTOR_TAX_CERTIFICATE` | |
| `decision` | `POST`, `POST_PAYMENT_BLOCK`, `HOLD`, `REJECT`, `DUPLICATE`, `NOT_INVOICE` | |
| `reasons` | lista de códigos de la tabla anterior | `[]` si `POST` |
| `company` | código de sociedad | Sociedad destinataria |
| `vendor_id` | id o `null` | `null` si el proveedor no existe en el maestro |
| `invoice_number` | string | Tal como figura en el documento |
| `invoice_date` | `YYYY-MM-DD` | |
| `currency` | ISO | Moneda del documento |
| `net`, `tax`, `gross`, `withholding`, `retention`, `payable` | enteros en céntimos | Base, cuota de IVA facturada, total, retenciones fiscales, retención de garantía, importe a pagar |
| `duplicate_of` | `doc_id` o `null` | Obligatorio en `DUPLICATE` |
| `payee` | `null`, `{"type": "FACTOR"}` o `{"type": "AEAT_EMBARGO"}` | |
| `payment_block` | `null` o `"CONTRACTOR_CERTIFICATE_EXPIRED"` | |
| `action` | `NONE`, `REGISTER_ALTERNATIVE_PAYEE`, `REGISTER_EMBARGO`, `UPDATE_BANK_DETAILS`, `UPDATE_CONTRACTOR_CERTIFICATE` | Solo en `NOT_INVOICE` |
| `lines[]` | `{amount, account, cost_center, wbs, tax_code, po, po_item}` | Imputación por línea; `po` y `po_item` si hay pedido |
| `journal_entry` | `{company, lines:[…]}` | **Solo** con `POST` y `POST_PAYMENT_BLOCK` |

**Casos que señalan los organizadores** (web y README):

- Duplicados disfrazados: reenvío, escaneo, portal más correo, número con otro formato.
- Cartas que no son facturas.
- Alquileres del mismo importe todos los meses, que no son duplicados.
- ISP, IVA y retenciones mal aplicados.
- Entradas pendientes y diferencias de precio.
- IBAN sospechoso: un IBAN distinto del de la ficha **sin** carta de cambio verificada es una alerta.
- Factoring y embargos.
- Las facturas de obra de subcontratas llevan ISP y retención de garantía: hay que mirar bien «a origen» frente a «esta certificación».

### 5.2 AR: facturación del mes (10 %)

**Objetivo.** Para cada partida de `tasks/ar_billing_items.json`:

- decidir si se factura (`INVOICE`) o no (`SKIP_PENDING_APPROVAL`);
- si se factura, calcular importes, impuestos, retenciones y deducciones, DIR3 y líneas;
- construir el **asiento**.

**Reglas** (§3.1):

- **Certificaciones de obra:**
  - Se factura **solo** la certificación **aprobada por la Dirección Facultativa**, por el importe de **esta certificación** (a origen − anterior).
  - Fecha de factura: **último día del mes certificado**. Vencimiento: fecha + días del contrato (`terms_days`).
  - Si está pendiente de aprobación: `SKIP_PENDING_APPROVAL`. En el cierre se registra entonces la obra ejecutada pendiente de certificar (`WIP_REVENUE`, §5.6).
- **Impuestos y deducciones según el contrato** (`sales_contracts.tax`):

  | Código | Cuándo |
  |---|---|
  | `R21` | IVA 21 % |
  | `RISP` | Obra de edificación para un promotor empresario: sin IVA y con la leyenda del art. 84.Uno.2º f |
  | `R10` | 10 %: limpieza viaria y residuos |
  | `PR06` / `PR23` / `PRAUT` | Portugal |
  | `MR16` | México |

  - **Retención de garantía** del contrato: 5 % de la base en obra privada (`retention_bp`).
  - **México:**
    - **5 al millar**: 0,5 % de la base, gasto 63100000;
    - **amortización del anticipo**: 30 % del total con IVA de cada estimación, hasta agotar el anticipo, contra 43800000.
- **Clientes públicos españoles:** factura electrónica por **FACe** con los tres códigos **DIR3** del maestro de clientes (`oficina_contable`, `organo_gestor`, `unidad_tramitadora`).
- **Servicios municipales:** canon mensual vigente más los servicios extraordinarios **con conformidad** del técnico municipal. Los pendientes de conformidad no se facturan.
- **Revisión de precios:** cuando se aprueba el decreto, se factura la diferencia (canon nuevo − antiguo) de **cada** mes desde la fecha de efectos. Una línea por mes, cuenta 70520000.
- **PPA:** MWh medidos × porcentaje del PPA × precio fijo, con el importe **truncado** al céntimo.
- **Mercado:** la liquidación del representante, por planta, menos los desvíos.
- **Asiento:**
  - Dr **43000000** por el importe a cobrar (socio cliente, asignación = número de factura).
  - Dr **43000900** por la garantía, Dr **43800000** por la amortización del anticipo y Dr **63100000** por el 5 al millar.
  - Cr a la cuenta de ingresos con PEP o centro de coste: **70510000** obra, **70500000** servicios, **70520000** revisión, **70530000** energía.
  - Cr **47700000** por el IVA.

**Salida (`ar_billing.jsonl`, una fila por `billing_item`):**

| Campo | Tipo y valores | Notas |
|---|---|---|
| `billing_item` | string | Clave |
| `expected` | `INVOICE` o `SKIP_PENDING_APPROVAL` | |
| `invoice.date`, `invoice.due_date` | `YYYY-MM-DD` | |
| `invoice.tax_code` | `R21`, `R10`, `RISP`, `PR06`, `PR23`, `PRAUT`, `MR16`, … | |
| `invoice.net`, `invoice.tax`, `invoice.retention`, `invoice.payable` | céntimos | `payable` = total con IVA − retención − deducciones |
| `invoice.deductions[]` | `{code, amount, account}` | Códigos del histórico: `MX5MILL` (63100000), `ADV_AMORT` (43800000) |
| `invoice.face` | `{oficina_contable, organo_gestor, unidad_tramitadora}` o `null` | Solo para clientes públicos españoles |
| `invoice.lines[]` | `{description, amount, account, wbs}`, o `cost_center` en servicios y energía | |
| `journal_entry` | `{company, lines}` | Solo si `INVOICE` |

**Casos que señalan los organizadores:**

- Certificaciones a origen y sin aprobar.
- DIR3 para FACe.
- ISP a promotor.
- Revisión de precios con atrasos.
- Anticipo y 5 al millar en México.

### 5.3 AR: aplicación de cobros (15 %)

**Objetivo.** Para cada línea de abono de `tasks/ar_receipts.json`:

- identificar el cliente (o `null` si no es un cliente);
- decidir a qué facturas o pagarés se aplica y por qué importe;
- clasificar las diferencias;
- entregar el **asiento de ajuste** que vacía 55500000.

**Punto de partida** (§3.2): «Los abonos del extracto ya entraron en Dr 572 / Cr 55500000» (asientos `N43AUTO`).

**Reglas:**

- **Aplicaciones:** factura (o pagaré) e importe.
- **Diferencias (`residuals[].type`):**

  | Tipo | Qué es | Contrapartida |
  |---|---|---|
  | `PENALTY` | Penalidad descontada por la administración | Dr 70590000 |
  | `NETTING_AP` | Compensación con una factura de honorarios del propio cliente, por ejemplo el representante de mercado | Dr a la cuenta del proveedor |
  | `OVERPAYMENT_DUPLICATE` | El cliente pagó dos veces | Cr 43800000 (a devolver o compensar) |
  | `FACTORED_MISDIRECTED` | El cliente pagó a Kalmora una factura cedida al factor | Cr 55300000 `FACTOR-BAE` |
  | `NON_CUSTOMER` | No es un cliente | Indemnización de seguro 75900000; devolución de fianza 56500000; devolución de IVA 47000000 |

- **Asiento de ajuste:** Dr 55500000 / Cr 430 (o 431, o la cuenta de la diferencia).
- **Pagos de menos sin causa conocida:** se aplica **parcialmente** a la factura y el resto queda abierto.
- **Pagarés al vencimiento:** se aplican a **43100000** (asignación `PAG<número>`) con `{"pagare": "<número>", "amount": …}`.

**Salida (`ar_cash.jsonl`, una fila por `bank_line`):**

| Campo | Tipo y valores | Notas |
|---|---|---|
| `bank_line` | string | Clave |
| `customer` | id de cliente o `null` | `null` si el cobro no viene de un cliente |
| `applications[]` | `{invoice, amount}` o `{pagare, amount}` | `invoice` = id literal de `ar_invoices` (p. ej. `"FT OB26-00004"`, con espacio) |
| `residuals[]` | `{type, invoice?, amount}` | `type` ∈ `PENALTY`, `NETTING_AP`, `OVERPAYMENT_DUPLICATE`, `FACTORED_MISDIRECTED`, `NON_CUSTOMER` |
| `adjustment[]` | lista de líneas `{company, account, debit, credit, partner?, cost_center?, wbs?}` | **Cada línea lleva `company`**: la fila no tiene sociedad (§7.8) |

**Casos que señalan los organizadores:**

- Pagos agrupados sin referencia.
- Parciales, pagarés y penalidades.
- Compensaciones y pagos duplicados.
- Facturas cedidas cobradas por error.

### 5.4 Conciliación bancaria (20 %)

**Objetivo.** Para cada una de las 12 cuentas de `tasks/bank_accounts.json`:

- casar las líneas del extracto del mes con las líneas del diario en la cuenta 572 correspondiente;
- clasificar lo que queda sin casar en cada lado;
- entregar los **asientos de ajuste** que procedan.

**Casación** (§4): las líneas del extracto (`bank_line`) se casan con las líneas del diario en la cuenta 572 de esa cuenta bancaria (`<id asiento>#<línea>`). Puede ser:

- **1:1**;
- **N:1**: una remesa contra varios pagos, una nómina en dos lotes;
- **1:N**.

**Categorías de lo que queda sin casar** (tabla completa de §4):

| Categoría | Lado | ¿Ajuste? | Asiento |
|---|---|---|---|
| `BANK_FEE_NOT_BOOKED` | banco | sí | Dr 62600000 (comisiones de aval: 66900000) / Cr 572 |
| `INTEREST_NOT_BOOKED` | banco | sí | Dr 572 / Cr 76200000. Retención del 19 %: Dr 47300000 / Cr 572. |
| `LOAN_INTEREST_NOT_BOOKED` | banco o diferencia | sí | Dr 66200000 / Cr 572 |
| `CARD_SETTLEMENT_NOT_BOOKED` | banco | sí | Dr 62910000 (CC-1000-DIR) / Cr 572 |
| `DIRECT_DEBIT_NOT_BOOKED` | banco | sí | Dr cuenta del proveedor (asignación = nº de factura) / Cr 572 |
| `RETURNED_DIRECT_DEBIT` | banco | sí | Dr 43000000 cliente (asignación = recibo) / Cr 572; comisión a 62600000 |
| `FX_RATE_DIFFERENCE` | diferencia | sí | Diferencia entre el cambio del banco y el de referencia: 66800000/76800000 |
| `FACTORING_CHARGES_NOT_BOOKED` | diferencia | sí | Dr 66500000 / Cr 55300000 |
| `POOLING_NOT_BOOKED` | banco | sí | Barrido de cash pooling contra 55200000 (socio 1000) |
| `UNRECORDED_RECEIPT` | banco | sí | No se importó el N43 de ese día: Dr 572 / Cr 55500000 |
| `BOOK_AMOUNT_ERROR` | libro | sí | Corregir la diferencia contra la cuenta del proveedor |
| `WRONG_BANK_ACCOUNT` | libro y banco | sí | Reclasificar entre cuentas 572 |
| `BOOK_DUPLICATE` | libro | sí | Anular el asiento duplicado |
| `BANK_ERROR` | banco | no | Reclamar al banco (cargo duplicado) |
| `OUTSTANDING_PAYMENT` | libro | no | Pago registrado que el banco ejecuta el mes siguiente |
| `TRANSFER_IN_TRANSIT` | libro | no | Traspaso entre cuentas propias pendiente de abono |
| `PRIOR_PERIOD_BANK_ITEM` | libro | no | Registro de un cargo que salió en el extracto del mes anterior |
| `FX_REVALUATION` | libro | no | Valoración o retrocesión de saldos en divisa (no es un movimiento) |

**Salida (`bank_rec.jsonl`, una fila por cuenta):**

| Campo | Tipo y valores | Notas |
|---|---|---|
| `account` | id de cuenta (`BIN-1100`…) | Clave |
| `company` | código de sociedad | Se usa como sociedad por defecto de las líneas de ajuste |
| `matches[]` | `{bank_lines: [bank_line…], book_lines: ["<je_id>#<line>"…]}` | `bank_line` de `bank/<cuenta>/<mes>.lines.jsonl`; `book_line` de `erp/journal_entries.jsonl` |
| `unmatched_bank[]` | `{bank_line, category}` | Categorías de la tabla |
| `unmatched_book[]` | `{book_line, category}` | Categorías de la tabla |
| `adjustments[]` | `{category, lines:[{company, account, debit, credit, partner?, …}]}` | Asientos de ajuste |

**Casos que señalan los organizadores:**

- Remesas contra muchos pagos.
- Comisiones, intereses y cambio SWIFT.
- Errores de importe y de cuenta.
- Partidas en tránsito y errores del banco.

### 5.5 Conciliación intragrupo (5 %)

**Objetivo.** Encontrar las **diferencias** entre los saldos recíprocos de las parejas de sociedades de `tasks/intercompany.json`, asignarles una causa y entregar el **asiento corrector**.

**Reglas** (§6):

- Saldos que deben cuadrar:
  - 43300000 ↔ 40300000 (facturas);
  - 55200000 (pooling, préstamo e intereses);
  - 24230000 ↔ 16330000 (préstamo 1000 → 3100);
  - 55210000 ↔ 55220000 (UTE).
- **Facturas en tránsito:** si una factura intragrupo se emitió y no se había recibido al cierre, el receptor la registra como pendiente de recibir: Dr gasto / Cr **40090000**, socio = sociedad emisora.
- **Intereses del préstamo `KMI-2025-01`:** 6 % con base **act/360** (días reales del mes / 360). Ambas partes devengan lo mismo en EUR.
- **Causas de diferencia:**

  | Causa | Qué pasó |
  |---|---|
  | `INVOICE_IN_TRANSIT` | Factura emitida y no recibida al cierre |
  | `INTEREST_DAY_COUNT` | Los intereses se calcularon con otra base |
  | `WRONG_TRADING_PARTNER` | Asiento con otro socio intragrupo |
  | `DUPLICATE_POSTING` | Asiento duplicado |
  | `POOLING_NOT_BOOKED` | Barrido sin registrar. **Se corrige en la conciliación bancaria; aquí va sin ajuste.** |

**Salida (`ic.jsonl`, una línea por diferencia encontrada):**

| Campo | Tipo y valores | Notas |
|---|---|---|
| `pair` | `["<sociedad>", "<sociedad>"]` | El scorer ordena la pareja |
| `cause` | una de las cinco causas | |
| `amount` | céntimos | Importe de la diferencia (no puntúa) |
| `responsible` | código de sociedad | Sociedad que debe corregir (no puntúa) |
| `adjustment[]` | líneas `{company, account, debit, credit, partner?, cost_center?, wbs?}` | **Cada línea lleva `company`**. `[]` para `POOLING_NOT_BOOKED`. |

Ejemplo de `FORMATO_ENTREGA.md`:

```json
{"pair": ["1000", "3100"], "cause": "INTEREST_DAY_COUNT", "amount": 1666700, "responsible": "3100", "adjustment": [{"company": "3100", "account": "66210000", "debit": 32051, "credit": 0}, {"company": "3100", "account": "55200000", "debit": 0, "credit": 32051, "partner": "1000"}]}
```

**Casos que señalan los organizadores:**

- Facturas en tránsito.
- Intereses con otra base de días.
- Socio equivocado.
- Duplicados.

### 5.6 Cierre (10 %)

**Objetivo.** Generar las partidas de cierre del mes (`tasks/close.json` → `steps`), cada una con su importe y su asiento, fechado el **último día del mes**. Sus retrocesiones del día 1 **no** se entregan.

**Reglas** (§5):

| `type` | Qué | Importe (`amount`) | Asiento |
|---|---|---|---|
| `ACCRUAL` | Servicios **sin pedido** consumidos y no facturados al cierre: electricidad, agua, telecomunicaciones, combustible, viajes, mensajería, material de oficina, vertedero, consultores y profesionales sin pedido. **No** se periodifica lo que tiene pedido (ya está en GR/IR). | Se estima con el histórico de cada proveedor (los periodos de facturación no coinciden con el mes natural). Tolerancia ±15 %. | Dr gasto con su objeto de coste / Cr 40090000, socio = proveedor. Se revierte automáticamente el día 1. |
| `PREPAID` | Primas de seguro, arrendamientos rústicos semestrales y cuotas anuales, repartidos linealmente entre los meses de cobertura. En el mes de la factura se difiere a 48000000 la parte no devengada; cada mes siguiente se imputa una mensualidad. | Variación del saldo de 48000000: **positiva** cuando se difiere, **negativa** cuando se imputa | Dr 48000000 / Cr gasto (diferimiento); Dr gasto / Cr 48000000 (imputación) |
| `WIP_REVENUE` | Obra ejecutada pendiente de certificar (certificación no aprobada) | Importe de la certificación pendiente | Dr 43090000 / Cr 71300000. Se revierte el día 1. |
| `FX_REVAL` | Partidas abiertas en moneda distinta de la local, al tipo SYN-BCE del último día del mes: facturas de proveedor en USD/GBP; en 3100, el préstamo y los intereses en EUR y la cuenta en USD | Valor a tipo de cierre − valor contable, en moneda local. **Positivo si aumenta el valor de la partida.** | Contra 66800000 o 76800000. Se revierte el día 1. |
| `BAD_DEBT` | Saldo pendiente de clientes privados y comunidades (las administraciones públicas y el grupo no se deterioran). Vencido más de 180 días: 50 %; más de 365 días: 100 %. Cliente en **concurso**: 100 % de todo su saldo, garantías incluidas. | Provisión necesaria − provisión anterior | Se ajusta 49000000 (por cliente) contra 69400000 o 79400000 |
| `DOUBTFUL_RECLASS` | En el mes en que se declara el concurso, el saldo pasa de 43000000 a 43600000 factura a factura | — | Dr 43600000 / Cr 43000000 por factura |

**Salida (`close.jsonl`, una línea por partida):**

| `type` | Campo clave | Otros campos |
|---|---|---|
| `ACCRUAL` | `vendor` | `company`, `amount`, `journal_entry` |
| `PREPAID` | `invoice` (`doc_id` de AP, p. ej. `API003311`) | ídem |
| `FX_REVAL` | `item`: `AP:<doc_id>` (factura de proveedor), `GL:16330000` o `GL:55200000` (préstamo intragrupo de 3100) o `BANK:BANH-3100-USD` | ídem |
| `BAD_DEBT` | `customer` | ídem |
| `WIP_REVENUE` | `billing_item` | ídem |
| `DOUBTFUL_RECLASS` | `customer` | ídem |

**Casos que señalan los organizadores:**

- Periodificaciones sin factura (±15 %).
- Gastos anticipados y obra sin certificar.
- Valoración en divisa.
- Deterioro de clientes, uno en concurso. En el maestro, `C200004` tiene `insolvency.declared_on` = 2026-06-18.

### 5.7 Balance de sumas y saldos (10 %)

No hay fichero que entregar: se calcula. El scorer toma el **diario registrado** de la fase y le suma **todas** las líneas de **todos** nuestros asientos, de cualquiera de los seis ficheros:

- `ap.jsonl`: `journal_entry`, sea cual sea la `decision`;
- `ar_billing.jsonl`: `journal_entry`;
- `ar_cash.jsonl`: `adjustment`;
- `bank_rec.jsonl`: `adjustments[].lines`;
- `ic.jsonl`: `adjustment`;
- `close.jsonl`: `journal_entry`.

El balance resultante se compara, cuenta a cuenta (sociedad, cuenta, en moneda local), con el balance correcto. Lo que dejemos sin contabilizar cuenta como diferencia, y un asiento sobrante o duplicado también. La fórmula está en §7.8.

---

## 6. Salidas: formato de entrega

**Una carpeta por fase** con hasta seis ficheros JSON Lines (un objeto por línea, UTF-8). Todos son opcionales: según `FORMATO_ENTREGA.md`, lo que falte puntúa 0 en su tarea.

```
entrega/
├── ap.jsonl          ← uno por doc_id de tasks/ap_documents.json
├── ar_billing.jsonl  ← uno por billing_item de tasks/ar_billing_items.json
├── ar_cash.jsonl     ← uno por bank_line de tasks/ar_receipts.json
├── bank_rec.jsonl    ← uno por cuenta de tasks/bank_accounts.json
├── ic.jsonl          ← una línea por diferencia intragrupo encontrada
└── close.jsonl       ← una línea por partida de cierre
```

**Reglas comunes:**

- **Importes:** **céntimos enteros** en la **moneda local** de la sociedad (EUR; MXN en 3100). Se recoge la excepción observada en el golden de AP (§4.7).
- **Fechas:** `YYYY-MM-DD`.
- **Forma de un asiento.** Es el campo `journal_entry`, o `adjustment` / `adjustments[].lines` en los ajustes:
  - `journal_entry` = `{"company": "<código>", "lines": [ … ]}`;
  - `adjustment` = lista de líneas;
  - cada línea = `{"account": "<8 dígitos>", "debit": <int ≥ 0>, "credit": <int ≥ 0>, "partner": <string|null>, "cost_center": <string|null>, "wbs": <string|null>}`, con `"company"` opcional en asientos con cabecera y **necesario** en `adjustment` de `ar_cash` e `ic`.
- **Cómo se comparan las líneas:** por cuenta, socio, objeto de coste e importe neto (debe − haber), con **±2 céntimos**.
  - El socio solo cuenta en las cuentas de partidas abiertas: prefijos `40`, `41`, `43`, `44`, `49`, `55`, `24`, `16`.
  - El objeto de coste solo cuenta en gastos, ingresos e inmovilizado: prefijos `6`, `7`, `2`.
- **Todos** los asientos se suman al diario registrado para calcular el balance. Cada asiento debe cuadrar (Σ debe = Σ haber por sociedad).
- Códigos de sociedad y de cuenta como **strings**.
- Los campos extra (fechas, textos, asignaciones, ids) se permiten y el scorer los ignora.

**Ejemplos completos.** Los importes y algunos ids son ilustrativos; la forma es la exigida.

`ap.jsonl`: subcontrata de obra con pedido y entrada, ISP y retención de garantía del 5 %.

```json
{"doc_id": "API005263", "document_type": "INVOICE", "decision": "POST", "reasons": [],
 "company": "1100", "vendor_id": "V100045", "invoice_number": "2026-032361", "invoice_date": "2026-08-31", "currency": "EUR",
 "net": 1000000, "tax": 0, "gross": 1000000, "withholding": 0, "retention": 50000, "payable": 950000,
 "duplicate_of": null, "payee": null, "payment_block": null, "action": null,
 "lines": [{"amount": 1000000, "account": "60700000", "cost_center": null, "wbs": "OB-1100-2521.04", "tax_code": "SISP", "po": "4500019036", "po_item": 10}],
 "journal_entry": {"company": "1100", "lines": [
   {"account": "40090000", "debit": 1000000, "credit": 0, "partner": "V100045", "cost_center": null, "wbs": null},
   {"account": "47210000", "debit": 210000, "credit": 0, "partner": null, "cost_center": null, "wbs": null},
   {"account": "47710000", "debit": 0, "credit": 210000, "partner": null, "cost_center": null, "wbs": null},
   {"account": "40000900", "debit": 0, "credit": 50000, "partner": "V100045", "cost_center": null, "wbs": null},
   {"account": "40000000", "debit": 0, "credit": 950000, "partner": "V100045", "cost_center": null, "wbs": null}]}}
```

Documento que no es factura:

```json
{"doc_id": "API005577", "document_type": "CONTRACTOR_TAX_CERTIFICATE", "decision": "NOT_INVOICE", "reasons": [], "company": "1100", "vendor_id": "V100056", "action": "UPDATE_CONTRACTOR_CERTIFICATE", "journal_entry": null}
```

`ar_billing.jsonl`: certificación aprobada de un cliente público español con IVA 21 % y FACe.

```json
{"billing_item": "BILL-CV-OB-1100-2511-202607", "expected": "INVOICE",
 "invoice": {"date": "2026-07-31", "due_date": "2026-08-30", "tax_code": "R21", "net": 10000000, "tax": 2100000, "retention": 0,
             "deductions": [], "payable": 12100000,
             "face": {"oficina_contable": "L07961094", "organo_gestor": "L07553049", "unidad_tramitadora": "L06219597"},
             "lines": [{"description": "Capítulo 01 – Movimiento de tierras y demoliciones", "amount": 6000000, "account": "70510000", "wbs": "OB-1100-2511.01"},
                       {"description": "Capítulo 02 – Cimentación y estructura", "amount": 4000000, "account": "70510000", "wbs": "OB-1100-2511.02"}]},
 "journal_entry": {"company": "1100", "lines": [
   {"account": "43000000", "debit": 12100000, "credit": 0, "partner": "C200001", "cost_center": null, "wbs": null},
   {"account": "70510000", "debit": 0, "credit": 6000000, "partner": null, "cost_center": null, "wbs": "OB-1100-2511.01"},
   {"account": "70510000", "debit": 0, "credit": 4000000, "partner": null, "cost_center": null, "wbs": "OB-1100-2511.02"},
   {"account": "47700000", "debit": 0, "credit": 2100000, "partner": null, "cost_center": null, "wbs": null}]}}
```

Partida no facturada:

```json
{"billing_item": "BILL-CV-OB-2100-2503-202607", "expected": "SKIP_PENDING_APPROVAL"}
```

`ar_cash.jsonl`: cobro con penalidad descontada (ejemplo de `FORMATO_ENTREGA.md`).

```json
{"bank_line": "BL0005123", "customer": "C200014",
 "applications": [{"invoice": "SU26-00412", "amount": 45320000}],
 "residuals": [{"type": "PENALTY", "invoice": "SU26-00412", "amount": 90640}],
 "adjustment": [{"company": "1200", "account": "55500000", "debit": 45229360, "credit": 0, "partner": null},
                {"company": "1200", "account": "70590000", "debit": 90640, "credit": 0, "partner": null, "cost_center": null, "wbs": null},
                {"company": "1200", "account": "43000000", "debit": 0, "credit": 45320000, "partner": "C200014"}]}
```

Cobro de pagaré al vencimiento:

```json
{"bank_line": "BL0000000", "customer": "C200008", "applications": [{"pagare": "1964711", "amount": 25378568}], "residuals": [],
 "adjustment": [{"company": "1100", "account": "55500000", "debit": 25378568, "credit": 0, "partner": null},
                {"company": "1100", "account": "43100000", "debit": 0, "credit": 25378568, "partner": "C200008"}]}
```

`bank_rec.jsonl`:

```json
{"account": "BIN-1100", "company": "1100",
 "matches": [{"bank_lines": ["BL0004410"], "book_lines": ["1100-2026-1600000123#3", "1100-2026-1600000124#2"]}],
 "unmatched_bank": [{"bank_line": "BL0004502", "category": "BANK_FEE_NOT_BOOKED"}],
 "unmatched_book": [{"book_line": "1100-2026-1600000190#2", "category": "OUTSTANDING_PAYMENT"}],
 "adjustments": [{"category": "BANK_FEE_NOT_BOOKED", "lines": [
   {"company": "1100", "account": "62600000", "debit": 3000, "credit": 0, "partner": null, "cost_center": null, "wbs": null},
   {"company": "1100", "account": "57200001", "debit": 0, "credit": 3000, "partner": null, "cost_center": null, "wbs": null}]}]}
```

`ic.jsonl`: diferencia con ajuste, y barrido sin registrar, cuyo ajuste va en bancos.

```json
{"pair": ["1000", "3100"], "cause": "INTEREST_DAY_COUNT", "amount": 1666700, "responsible": "3100",
 "adjustment": [{"company": "3100", "account": "66210000", "debit": 32051, "credit": 0, "partner": null, "cost_center": null, "wbs": null},
                {"company": "3100", "account": "55200000", "debit": 0, "credit": 32051, "partner": "1000", "cost_center": null, "wbs": null}]}
{"pair": ["1000", "1200"], "cause": "POOLING_NOT_BOOKED", "amount": 25000000, "responsible": "1200", "adjustment": []}
```

`close.jsonl`: una línea de cada tipo.

```json
{"type": "ACCRUAL", "company": "1100", "vendor": "V100012", "amount": 182340, "journal_entry": {"company": "1100", "lines": [
  {"account": "62800000", "debit": 182340, "credit": 0, "partner": null, "cost_center": "CC-1100-ADM", "wbs": null},
  {"account": "40090000", "debit": 0, "credit": 182340, "partner": "V100012", "cost_center": null, "wbs": null}]}}
{"type": "PREPAID", "company": "1000", "invoice": "API003311", "amount": -700000, "journal_entry": {"company": "1000", "lines": [
  {"account": "62500000", "debit": 700000, "credit": 0, "partner": null, "cost_center": "CC-1000-FIN", "wbs": null},
  {"account": "48000000", "debit": 0, "credit": 700000, "partner": null, "cost_center": null, "wbs": null}]}}
{"type": "FX_REVAL", "company": "3100", "item": "GL:16330000", "amount": 1520000, "journal_entry": {"company": "3100", "lines": [
  {"account": "66800000", "debit": 1520000, "credit": 0, "partner": null, "cost_center": null, "wbs": null},
  {"account": "16330000", "debit": 0, "credit": 1520000, "partner": "1000", "cost_center": null, "wbs": null}]}}
{"type": "BAD_DEBT", "company": "1100", "customer": "C200007", "amount": 2500000, "journal_entry": {"company": "1100", "lines": [
  {"account": "69400000", "debit": 2500000, "credit": 0, "partner": null, "cost_center": null, "wbs": null},
  {"account": "49000000", "debit": 0, "credit": 2500000, "partner": "C200007", "cost_center": null, "wbs": null}]}}
{"type": "WIP_REVENUE", "company": "2100", "billing_item": "BILL-CV-OB-2100-2503-202607", "amount": 30000000, "journal_entry": {"company": "2100", "lines": [
  {"account": "43090000", "debit": 30000000, "credit": 0, "partner": "C200017", "cost_center": null, "wbs": null},
  {"account": "71300000", "debit": 0, "credit": 30000000, "partner": null, "cost_center": null, "wbs": "OB-2100-2503.02"}]}}
{"type": "DOUBTFUL_RECLASS", "company": "1100", "customer": "C200007", "amount": 1500000, "journal_entry": {"company": "1100", "lines": [
  {"account": "43600000", "debit": 1500000, "credit": 0, "partner": "C200007", "cost_center": null, "wbs": null},
  {"account": "43000000", "debit": 0, "credit": 1500000, "partner": "C200007", "cost_center": null, "wbs": null}]}}
```

---

## 7. Evaluación: el scorer exacto

`score.py` usa solo la biblioteca estándar de Python 3.

### 7.1 Ejecución

```bash
python score.py <evaluator_phase_dir> <participant_phase_dir> <submission_dir> [--json out.json]
python score.py phase_dev phase_dev mi_entrega_dev/      # dev: lee phase_dev/golden/
```

- Lee `<evaluator_phase_dir>/golden/{ap,ar_billing,ar_cash,bank_rec,ic,close}.jsonl` y `trial_balance_{truth,recorded}.jsonl`.
- `<participant_phase_dir>` se recibe pero no se usa.
- Lee de `<submission_dir>` los ficheros que existan; un fichero ausente equivale a lista vacía.
- Imprime un JSON con `score` y detalles por tarea, y `total`. `--json` lo guarda además en un fichero.
- Entregar algo parcial es válido: cada fichero puntúa por separado.

### 7.2 Pesos y total

| Tarea | Clave | Peso |
|---|---|---|
| AP | `ap` | 0,30 |
| AR facturación | `ar_billing` | 0,10 |
| AR cobros | `ar_cash` | 0,15 |
| Bancos | `bank_rec` | 0,20 |
| Intragrupo | `ic` | 0,05 |
| Cierre | `close` | 0,10 |
| Balance | `trial_balance` | 0,10 |

`total = round(100 × Σ peso × score_tarea, 2)`. Cada `score_tarea` se redondea a 4 decimales.

### 7.3 Funciones auxiliares

- **`f1(tp, fp, fn)`:** p = tp/(tp+fp), o 1,0 si tp+fp = 0; r = tp/(tp+fn), o 1,0 si tp+fn = 0. Devuelve 2pr/(p+r), o 0 si p+r = 0.
- **`amount_ok(a, b)`:** |int(a) − int(b)| ≤ **1** céntimo. Es falso si alguno no es convertible, por ejemplo `None`.
- **`norm_num(s)`:** pasa a mayúsculas, elimina todo lo que no sea `[0-9A-Z]` y quita los ceros a la izquierda. Se usa para comparar `invoice_number`.
- **Media de una lista vacía:** 1,0.
- **`je_lines(je, company)`:**
  - acepta `{"lines": [...]}` o una lista de líneas;
  - por línea, importe = int(debit or 0) − int(credit or 0), y se descartan las de importe 0;
  - sociedad = `line.company` o, si falta, el `company` pasado o, si falta, `je.company`;
  - `cost_center` y `wbs` vacíos pasan a `None`; `partner` se toma tal cual (`""` ≠ `null`).
- **`norm_line`:**
  - conserva `partner` solo si la cuenta empieza por `40`, `41`, `43`, `44`, `49`, `55`, `24` o `16`;
  - conserva `cost_center` y `wbs` solo si empieza por `6`, `7` o `2`;
  - en el resto, `None`.
- **`je_match(gold, sub, tol=2)`:**
  1. Normaliza las líneas de ambos lados. La sociedad **no** se compara.
  2. Agrupa las líneas del participante por clave `(cuenta, partner, cost_center, wbs)`, con su lista de importes con signo.
  3. Para cada línea del golden, busca en su clave el importe más cercano. Si |diferencia| ≤ **2 céntimos**, es acierto y ese importe se consume.
  4. Resultado = aciertos / **max(nº líneas golden, nº líneas participante)**, o 1,0 si ambos están vacíos.

  Debe y haber importan por el signo.

### 7.4 AP (`score_ap`)

Recorre las filas del golden y busca la entrega por `doc_id`.

- **Decisión, F1 macro:**
  - Clases = decisiones del golden ∪ decisiones presentes en **cualquier** fila entregada.
  - Por documento del golden: si la decisión coincide, tp de esa clase. Si no, fn de la clase del golden y, si se entregó decisión, fp de la clase entregada.
  - Macro = media de `f1` por clase.
- **`reasons`** (media de una lista):
  - si el golden es `HOLD`, `REJECT` o `POST_PAYMENT_BLOCK` con `reasons` no vacío: 1 si la intersección con las `reasons` entregadas es no vacía, 0 si no;
  - si el golden es `DUPLICATE`: 1 si `duplicate_of` coincide.
- **Solo para documentos con golden `POST` o `POST_PAYMENT_BLOCK`**, sea cual sea la decisión entregada:
  - **`header`:** media de 10 comprobaciones. Igualdad exacta en `company`, `vendor_id` e `invoice_date`; `norm_num` en `invoice_number`; `amount_ok` (±1) en `net`, `tax`, `gross`, `withholding`, `retention` y `payable`. `currency` y `due_date` no puntúan.
  - **`coding`:**
    - Clave de línea = `(account, cost_center, wbs, tax_code)`. Se suman los `amount` entregados por clave.
    - Por cada línea del golden se toma min(|importe golden|, |importe entregado restante en esa clave|) y se descuenta.
    - coding = Σ tomado / Σ |importes golden|. Es una medida tipo *recall* ponderada por importe.
  - **`po_match`:** solo si el golden tiene líneas con `po`. Es Σ |importe| de las líneas del golden cuyo `(po, po_item)` aparece en alguna línea entregada, dividido por Σ |importe| de las líneas del golden con `po`.
  - **`journal_entry`:** `je_match(golden.journal_entry, entrega.journal_entry)`, si el golden tiene asiento.
  - **`payee_and_block`:** solo si el golden tiene `payee` o `payment_block`. Vale 1 si coincide `payee.type` (cuando el golden tiene `payee`) y `payment_block` (cuando el golden lo tiene).
- **Fórmula:**

```
S_AP = 0,30·F1_macro + 0,15·header + 0,15·coding + 0,10·po_match + 0,20·journal_entry + 0,05·reasons + 0,05·payee_and_block
```

Cada componente es la media de su lista (1,0 si está vacía). Además informa `per_decision_f1`, `documents` y `answered`.

### 7.5 AR facturación (`score_ar_billing`)

Por cada partida del golden:

- Si `expected` no coincide, 0.
- Si coincide y no es `INVOICE`, 1.
- Si es `INVOICE`:
  - `head` = media de: `tax_code` igual, `due_date` igual, `amount_ok` (±1) en `net`, `tax`, `retention` y `payable`, y, si el golden tiene `face`, los tres códigos DIR3 iguales (una sola comprobación);
  - puntuación = **0,6 · head + 0,4 · je_match(journal_entry)**.
  - No puntúan `date`, `gross`, `deductions` ni `lines`, salvo a través del asiento.

`S_ARB` = media sobre las partidas del golden (1,0 si no hay ninguna).

### 7.6 AR cobros (`score_ar_cash`)

Por cada `bank_line` del golden:

- **`cust`:** 1 si `customer` es exactamente igual, `null` incluido.
- **`app`:**
  - multiconjuntos de `(invoice or pagare, amount)`; 1 si son iguales;
  - si no, |intersección| / max(|golden|, |entrega|); 1 si ambos están vacíos.
- **`res`:** igual que `app`, sobre multiconjuntos de `(type, amount)` de `residuals`. La `invoice` del residual no cuenta.
- **`adj`:** `je_match(golden.adjustment, entrega.adjustment)`.
- **Puntuación:** **0,15 · cust + 0,45 · app + 0,20 · res + 0,20 · adj**.

`S_ARC` = media. Informa `fully_correct` (cobros con 1,0).

### 7.7 Bancos (`score_bank`)

Por cada cuenta del golden:

- **`mf`:** F1 sobre pares `(bank_line, book_line)`. Cada grupo de `matches` se expande al producto cartesiano de sus `bank_lines` × `book_lines`.
- **`uf`:**
  - Conjunto de no casadas: `("B", bank_line)` de `unmatched_bank` y `("L", book_line)` de `unmatched_book`.
  - found = claves del golden presentes en la entrega.
  - uf = f1(found, |entrega − golden|, |golden| − found). La categoría no influye aquí.
- **`catacc`:** claves del golden con la **misma categoría** en la entrega / |golden|; 1,0 si el golden no tiene no casadas.
- **`adj`:** `je_match` de **todas** las líneas de todos los `adjustments` aplanadas, golden contra entrega. La `category` del ajuste no se compara.
- **Puntuación:** **0,45 · mf + 0,20 · uf + 0,15 · catacc + 0,20 · adj**.

`S_BANK` = media sobre las 12 cuentas. Informa `per_account`.

### 7.8 Intragrupo, cierre y balance

**Intragrupo (`score_ic`):**

- Clave = `(pareja ordenada, cause)`. Si se entregan dos filas con la misma clave, prevalece la última.
- det = F1 sobre los conjuntos de claves.
- adj = media, sobre las claves del golden, de `je_match(golden.adjustment, entrega.adjustment)`, o 0 si la clave no se entregó. Un golden con `adjustment: []` contra una entrega vacía da 1; contra una entrega con líneas da 0.
- **S_IC = 0,6 · det + 0,4 · adj**.
- `amount` y `responsible` no puntúan.

**Cierre (`score_close`):**

- **Clave:** `ACCRUAL` `(type, company, vendor)`; `PREPAID` `(…, invoice)`; `FX_REVAL` `(…, item)`; `BAD_DEBT` `(…, customer)`; `WIP_REVENUE` `(…, billing_item)`; cualquier otro tipo, incluido `DOUBTFUL_RECLASS`, `(…, customer)`.
- **Agregación:** se **suman** los `amount` de las filas con la misma clave, en el golden y en la entrega. En `DOUBTFUL_RECLASS` se cuentan filas (cada fila suma 1).
- **Aciertos,** por clave del golden presente en la entrega (G = golden, S = entrega):
  - acierto completo (1) si |S − G| ≤ max(100 céntimos, tol·|G|), con tol = **0,15** en `ACCRUAL` y 0 en el resto;
  - acierto parcial (**0,4**) si no, pero |S − G| ≤ 0,5·|G|.
- **Puntuación:** S_CLOSE = f1(hits, nº claves entregadas − hits, nº claves golden − hits). Informa `recall` y `precision`.
- El `journal_entry` del cierre **no** puntúa en esta tarea; solo cuenta en el balance.

**Balance (`score_tb`):**

```
T  = trial_balance_truth    {(company, account): balance}
R  = trial_balance_recorded {(company, account): balance}
team = R + Σ (debe − haber) de cada línea de cada asiento entregado, agregado por (company, account)
diff = Σ_k |T_k − team_k|          sobre k ∈ claves(T) ∪ claves(team)
base = Σ_k |T_k − R_k|             sobre las mismas claves (1 si fuera 0)
S_TB = max(0, 1 − diff / base)
```

- **Asientos que entran:** `ap` y `ar_billing` → `journal_entry`; `ar_cash` e `ic` → `adjustment`; `bank_rec` → cada `adjustments[].lines`; `close` → `journal_entry`.
- **Sociedad de cada línea:** `line.company`, si no `fila.company`, si no `journal_entry.company`. En `ar_cash` e `ic` la fila no tiene `company`, así que cada línea debe traerla.
- La cuenta se compara como string.
- Socio y objeto de coste **no** influyen en el balance. Los importes se suman en moneda local; el detalle `abs_difference_eur` mezcla EUR y MXN.

---

## 8. Reglas del reto y entrega

Según la web y el README:

- **Cualquier modelo, herramienta o arquitectura.** Se valora que **el trabajo lo haga el agente**.
- **Solo valen los datos del paquete.**
- **Septiembre se entrega una sola vez.** No hay leaderboard de test.
- Junto a la entrega se indica:
  - el **modelo** usado;
  - el **coste aproximado**;
  - el **tiempo de ejecución**.
- La entrega es una carpeta por fase con los seis JSONL de §6. En dev podemos autoevaluarnos con `score.py` y el golden; en septiembre no hay golden.
- El enlace de descarga de dev caduca el **9 de octubre de 2026**.

---

## 9. Dependencias entre tareas

Los organizadores lo avisan: «Banco, cobros e intragrupo están conectados: un barrido de pooling sin registrar descuadra el banco **y** la relación con la holding». Según la web, un error descuadra dos tareas. Como **todos** los asientos se suman al diario, un mismo hecho económico debe contabilizarse **una sola vez**, en el fichero que le corresponde.

| Conexión | Qué dicen las políticas o los datos |
|---|---|
| **Bancos ↔ AR cobros** | Los abonos del N43 se importaron a Dr 572 / Cr 55500000 (`N43AUTO`). AR cobros vacía 55500000 contra clientes y diferencias. Si el N43 de un día no se importó, el abono no está en libros: bancos lo registra como `UNRECORDED_RECEIPT` (Dr 572 / Cr 55500000). Los recibos devueltos (`RETURNED_DIRECT_DEBIT`) reabren la deuda del cliente en 43000000. |
| **Bancos ↔ intragrupo (pooling)** | Los barridos de saldo cero entre `BIN-1000` y `BIN-1100`/`BIN-1200` se registran contra 55200000. Un barrido sin registrar es `POOLING_NOT_BOOKED`: se ajusta en `bank_rec` (contra 55200000, socio 1000) y en `ic` se informa la causa **sin ajuste** (§6). |
| **Intragrupo ↔ AP** | Las facturas de management fees de 1000 llegan a la bandeja de AP de las filiales (proveedor `V-IC1000`). Si se emitió y no se recibió al cierre, es una factura en tránsito: Dr gasto / Cr 40090000, socio = emisora. Un asiento IC duplicado descuadra 43300000 ↔ 40300000. |
| **Intragrupo ↔ cierre (préstamo KMI)** | Intereses act/360 en EUR en ambas partes (55200000). En 3100, préstamo e intereses en EUR se valoran en divisa (`FX_REVAL` `GL:16330000` y `GL:55200000`). |
| **AR facturación ↔ cierre** | Una certificación no aprobada (`SKIP_PENDING_APPROVAL`) genera `WIP_REVENUE` en el cierre. |
| **AP ↔ cierre** | Se periodifican solo los servicios **sin pedido** no facturados; lo que tiene pedido ya está en GR/IR (40090000). Las facturas de AP en USD/GBP abiertas al cierre se valoran (`FX_REVAL` `AP:<doc_id>`). Seguros, arrendamientos rústicos y cuotas anuales generan `PREPAID`. |
| **AR cobros ↔ cierre** | El deterioro (`BAD_DEBT`) se calcula sobre el saldo pendiente de clientes, que depende de los cobros aplicados. |
| **AP ↔ bancos** | Adeudos domiciliados no registrados (`DIRECT_DEBIT_NOT_BOOKED`, Dr cuenta del proveedor con asignación = nº de factura). Errores de importe en pagos (`BOOK_AMOUNT_ERROR`, contra la cuenta del proveedor). Diferencias de cambio SWIFT (`FX_RATE_DIFFERENCE`). |
| **Factoring (dos caras)** | En **AP**, un proveedor cede sus créditos a un factor: `FACTORING_NOTICE`, `payee FACTOR`, y un IBAN distinto respaldado por la cesión. En **AR**, 1100 cede facturas a su factor (BAE): `factoring_assignments`, 55300000 `FACTOR-BAE`. Si el cliente paga a Kalmora una factura cedida, es `FACTORED_MISDIRECTED`. Los intereses y comisiones del factor no registrados son `FACTORING_CHARGES_NOT_BOOKED` (Dr 66500000 / Cr 55300000). |
| **UTE** | 1100 aporta fondos a 1910 (55210000 en 1100 ↔ 55220000 en 1910). Las facturas de proveedores de la obra de la UTE deben ir a 1910 (`WRONG_ADDRESSEE` si van a 1100). |

---

## 10. Glosario

| Término | Significado en este reto |
|---|---|
| **AP / AR** | Cuentas a pagar (proveedores) y cuentas a cobrar (clientes) |
| **Asiento** (`journal_entry`) | Registro contable de partida doble: líneas con cuenta, debe, haber, socio y objeto de coste. Σ debe = Σ haber. |
| **Asignación** (`assignment`) | Referencia que identifica una partida abierta: nº de factura, `pedido/posición`, `PAG<n>`, recibo… |
| **Balance de sumas y saldos** (TB) | Saldo por sociedad y cuenta (Σ debe − Σ haber). Aquí se compara con el correcto. |
| **Partida abierta** | Saldo pendiente de compensar por socio y asignación (`open_items`) |
| **Socio** (`partner`) | Proveedor, cliente, sociedad del grupo o factor asociado a una línea de cuenta de partidas abiertas |
| **Sociedad** | Entidad legal del grupo (`1000`…`3100`) |
| **Retrocesión** | Asiento inverso automático el día 1 del mes siguiente (periodificaciones, WIP, FX) |
| **Centro de coste / PEP (WBS)** | Objetos de coste. CC para estructura y servicios; PEP (elemento del plan de estructura de proyecto) para obra. |
| **Pedido / posición** (PO / `po_item`) | Orden de compra y su línea (10, 20…) |
| **Entrada de mercancía (GR) / hoja de entrada de servicios (SES)** | Recepción de bienes o servicios contra pedido. Abona 40090000. |
| **Albarán** | Nota de entrega del proveedor (`AL-nnnnnn`), referenciada en la entrada y en la factura |
| **GR/IR** (cuenta puente) | 40090000: recoge el valor recibido y aún no facturado. La factura la salda. |
| **ISP** (inversión del sujeto pasivo) | El destinatario autorrepercute el IVA (Dr 47210000 / Cr 47710000). En obra: art. 84.Uno.2º f) LIVA. |
| **SISP / SIC / SIS** | Códigos de IVA soportado autorrepercutido: ISP de obra, adquisición intracomunitaria, servicios de no establecidos |
| **SIMP** | IVA a la importación liquidado en el DUA, suplido por el transitario (Dr 47200000) |
| **SND** | IVA soportado no deducible (mayor gasto) |
| **REAV / SREAV** | Régimen especial de agencias de viajes: la factura no lleva cuota deducible |
| **RISP** | Factura emitida sin IVA por ISP (obra de edificación a promotor empresario), con leyenda art. 84.Uno.2º f |
| **Autoliquidação** (PAUT / PSIS / PRAUT) | ISP portugués: construcción civil (art. 2.º n.º 1 j CIVA) y servicios de no residentes (art. 2.º n.º 1 i). En ventas, la factura va sin IVA. |
| **ATCUD** | Código único de documento de las facturas portuguesas. Lo menciona la web; no aparece en el paquete. |
| **IRPF** | Retención del impuesto sobre la renta (España): 15 % profesionales, 7 % nuevos profesionales, 19 % arrendamiento urbano. Va a 47510000. |
| **IRS** | Retenção na fonte en Portugal, categoría B, 25 % |
| **ISR / IVA retenido / fletes** | Retenciones mexicanas: ISR 10 % de honorarios de persona física, IVA retenido 10,67 % (2/3 del IVA), autotransporte 4 % |
| **Retención de garantía** | 5 % de la base retenido a la subcontrata (40000900) o por el cliente privado (43000900) hasta la recepción de la obra |
| **Certificado art. 43.1.f LGT** | Certificado de la AEAT de estar al corriente de obligaciones tributarias para contratistas y subcontratistas. Vale 12 meses; sin él vigente se contabiliza con bloqueo de pago. |
| **Diligencia de embargo AEAT** | Orden de Hacienda de pagarle a ella los créditos de un proveedor hasta un límite (`payee AEAT_EMBARGO`) |
| **Cesión de créditos / factoring** | El acreedor vende sus facturas a un factor, que pasa a ser quien cobra (`FACTORING_NOTICE`, `payee FACTOR`). En AR, Kalmora cede sus facturas a BAE (55300000). |
| **Confirming** | Servicio bancario de pago a proveedores: el banco paga al vencimiento (`CONFIRMING`, `BAE-1100`) |
| **Pagaré** | Efecto de pago aplazado entregado por un cliente; se cobra al vencimiento (43100000, `PAG<n>`) |
| **Cash pooling (zero balancing)** | Barrido diario del saldo de las cuentas de las filiales a la cabecera (`BIN-1000`), contra 55200000 |
| **UTE** | Unión Temporal de Empresas (Ley 18/1982): 1910, al 50 % entre 1100 y Hidrocon. **Llamada de fondos** = aportación de los socios. |
| **DIR3** | Directorio común de unidades de la Administración: oficina contable, órgano gestor y unidad tramitadora, obligatorios en facturas a la Administración |
| **FACe** | Punto general de entrada de facturas electrónicas de la Administración española. El CSV de estado informa de las facturas pagadas. |
| **Facturae 3.2.2** | Formato XML español de factura electrónica |
| **CFDI 4.0** | Comprobante Fiscal Digital por Internet (México): XML timbrado con UUID, RFC de emisor y receptor |
| **RFC / NIF / NIPC** | Identificador fiscal mexicano / español / portugués |
| **DUA** | Documento Único Administrativo de importación: MRN, levante, aranceles, IVA a la importación |
| **Transitario** | Agente aduanero que suple el IVA de importación y lo refactura |
| **N43** (Norma 43 AEB/CSB) | Formato español de extracto bancario en registros de 80 posiciones |
| **CAMT.053** | Extracto bancario ISO 20022 en XML |
| **CLABE / SPEI** | Cuenta bancaria estandarizada mexicana / sistema de transferencias mexicano (con «clave de rastreo») |
| **SEPA (recibo, mandato, remesa, devolución)** | Adeudos directos: Kalmora cobra recibos a comunidades (`sepa_remittances`, mandatos `KSU-…`). Una devolución (código de motivo AM04, MD06…) reabre la deuda. |
| **Adeudo domiciliado** (DD) | Cargo en cuenta de una factura de proveedor (suministros), contra la cuenta del proveedor |
| **SWIFT** | Transferencia internacional en divisa; el banco aplica su propio cambio (registro N43 `24`) |
| **SYN-BCE** | Serie sintética de tipos de cambio de referencia del reto (`fx_rates`) |
| **act/360** | Base de cálculo de intereses: días reales / 360 |
| **KMI-2025-01** | Préstamo intragrupo de 1000 a 3100: 5.000.000 EUR al 6 %, act/360 |
| **Management fees** | Cuotas mensuales de servicios corporativos que 1000 factura a las filiales |
| **Certificación de obra** | Relación valorada mensual de la obra ejecutada. **A origen** = acumulado; **anterior** = acumulado hasta el mes previo; **esta certificación** = a origen − anterior. La aprueba la **Dirección Facultativa**. |
| **Estimación** | Equivalente mexicano de la certificación (`EST-…`) |
| **Anticipo de obra pública (MX)** | 30 % del contrato pagado por adelantado (`ANT-…`); se amortiza en cada estimación contra 43800000 |
| **5 al millar** | Derecho de inspección y vigilancia de obra pública en México: 0,5 % de la base, deducido por el cliente (63100000) |
| **Canon** | Precio mensual fijo de un contrato municipal de servicios |
| **Conformidad del técnico municipal** | Aprobación que permite facturar los servicios extraordinarios |
| **Revisión de precios / decreto / fecha de efectos / atrasos** | Actualización del canon aprobada por decreto de Alcaldía. Se facturan las diferencias de cada mes desde la fecha de efectos. |
| **Penalidad** | Descuento impuesto por la administración por incumplimiento (art. 194 LCSP), deducido del siguiente pago (70590000) |
| **PPA** | Power Purchase Agreement: venta a precio fijo de un % de la producción |
| **Representante de mercado / desvíos** | Agente que vende la energía en el mercado y liquida por planta, descontando el coste de los desvíos. Factura sus honorarios aparte y los compensa en el pago (netting). |
| **IVPEE** | Impuesto sobre el valor de la producción de energía eléctrica |
| **Periodificación** (`ACCRUAL`) | Gasto devengado y no facturado al cierre: Dr gasto / Cr 40090000, con retrocesión |
| **Gasto anticipado** (`PREPAID`) | Parte no devengada de un gasto facturado por adelantado (48000000) |
| **Obra ejecutada pendiente de certificar** (`WIP_REVENUE`) | Ingreso de obra hecha sin certificación aprobada (43090000 / 71300000) |
| **Valoración en divisa** (`FX_REVAL`) | Ajuste al tipo de cierre de partidas en moneda extranjera (66800000 / 76800000) |
| **Deterioro** (`BAD_DEBT`) | Provisión por riesgo de impago (49000000 contra 69400000 / 79400000) |
| **Concurso (de acreedores)** | Procedimiento de insolvencia. Su saldo se deteriora al 100 % y se reclasifica a dudoso cobro (43600000) en el mes de la declaración. |
| **Proforma** | Oferta sin validez fiscal; no se contabiliza |
| **Extracto de proveedor** | Recordatorio de deuda; no se contabiliza |
| **Rappel** | Descuento por volumen, normalmente vía abono |
| **Partidas en tránsito** | Movimientos registrados en un lado y aún no en el otro (pagos pendientes de cargo, traspasos pendientes de abono) |

---

## 11. Definición de terminado y ambigüedades abiertas

### 11.1 Definición de terminado (por fase)

Una solución completa para una fase produce una carpeta con **los seis ficheros**:

1. **`ap.jsonl`:** **una** fila por cada `doc_id` de `tasks/ap_documents.json` (305 en dev, 297 en test), ni más ni menos.
   - Cada fila lleva `document_type` y `decision` válidos y `reasons` coherente con §2.2.
   - `duplicate_of` en `DUPLICATE`; `action` en `NOT_INVOICE`.
   - Cabecera y `lines` en las facturas.
   - `journal_entry` **solo** en `POST` y `POST_PAYMENT_BLOCK`, cuadrado.
2. **`ar_billing.jsonl`:** una fila por partida (26 / 25), con `invoice` y `journal_entry` cuadrado cuando `expected = INVOICE`.
3. **`ar_cash.jsonl`:** una fila por `bank_line` (32 / 34). Su `adjustment` cuadra, lleva `company` en cada línea y vacía exactamente el importe del abono en 55500000.
4. **`bank_rec.jsonl`:** una fila por cuenta (12).
   - Cada línea del extracto del mes está casada o clasificada en `unmatched_bank`.
   - Cada línea de libro candidata de esa cuenta (572; alcance en la pregunta 24) está casada o clasificada en `unmatched_book`.
   - Hay un ajuste por cada categoría que lo exige (§5.4).
5. **`ic.jsonl`:** una fila por diferencia detectada en las parejas de `tasks/intercompany.json`, con causa y ajuste. `[]` en `POOLING_NOT_BOOKED`.
6. **`close.jsonl`:** una fila por partida de cierre de los seis tipos de `tasks/close.json`, con su clave, `amount` con el signo de §5.6 y `journal_entry` fechado a fin de mes, sin retrocesiones.

**Reglas transversales:**

- Importes en céntimos enteros y en moneda local.
- Sociedades y cuentas como strings de cuentas existentes en el plan.
- `partner` en las cuentas de partidas abiertas, con el valor de §2.2.
- `cost_center` **o** `wbs` (nunca ambos) en las cuentas 6/7/2.
- Todo asiento cuadra por sociedad.
- Ningún hecho económico se contabiliza dos veces entre ficheros.
- Los ficheros se validan contra el esquema de §6 y `score.py` los lee sin errores.
- Se declara el modelo, el coste aproximado y el tiempo de ejecución.

### 11.2 Ambigüedades que las políticas no cierran

Preguntas abiertas, sin respuesta en este documento. Se resuelven con el histórico y el golden de dev, y cada respuesta se documenta donde corresponda.

**General**

1. ¿Puntúa septiembre exactamente con el mismo `score.py`? Los materiales lo presentan como la forma de medir, pero no lo afirman para test.
2. `FORMATO_ENTREGA.md` dice que los importes van en moneda local. ¿Aplica también a la cabecera y las `lines` de AP de documentos en divisa? En el golden de dev esos importes están en moneda del documento (§4.7).
3. ¿Qué campos de texto, fecha o asignación del asiento debemos emitir? El scorer no los lee, pero forman parte del «cómo contabiliza el grupo».

**AP**

4. Duplicados: ¿qué cuenta como «prefijo» al normalizar el número? ¿Cómo se trata un documento con el mismo proveedor y número que otro previo que fue **rechazado**?
5. Si fallan varias comprobaciones del mismo nivel (por ejemplo dos motivos de `REJECT`), ¿se informan todas o solo la primera según el orden de la tabla?
6. `PRICE_VARIANCE`: ¿los 150 € se miden sobre el precio unitario o sobre el importe de la línea? ¿El 2 % es sobre el precio unitario del pedido?
7. ¿Qué proveedores son «subcontratista de obra» a efectos de `ISP_NOT_APPLIED` y `CONTRACTOR_CERTIFICATE_EXPIRED`: arquetipo, tipo de pedido o PEP?
8. `WITHHOLDING_MISSING`: ¿incluye a arrendadores urbanos personas jurídicas, o solo a los proveedores con `withholding` en la ficha?
9. `BANK_DETAILS_CHANGED`: ¿qué es un «dominio parecido al habitual» y con qué se compara (`email` de la ficha, `from` del correo, `uploaded_by` del portal)? ¿Una carta de cambio recibida en el mismo mes respalda facturas anteriores a su fecha de efectos?
10. `payee`: la cesión debe estar «vigente a la fecha de la factura» y el embargo «recibido antes que la factura». ¿«Antes» se refiere a la fecha de la factura o a la de recepción?
11. Certificado art. 43: ¿`valid_until` es inclusivo? ¿Cuenta un certificado recibido en el mismo mes pero después de la factura?
12. En facturas con varias entradas por posición o entregas parciales, ¿qué entradas cubre cada línea facturada?
13. `CREDIT_NOTE`: ¿cómo se identifica la factura original cuyo asiento se invierte cuando el abono no la cita?
14. `DOWN_PAYMENT_REQUEST` y su aplicación posterior: ¿a qué tipo de cambio se registra la solicitud, y con qué socio y objeto de coste las líneas de 40700000?
15. Facturas con DUA: ¿cómo se reparten el servicio del transitario, los suplidos y el IVA de importación entre líneas y cuentas?

**AR facturación**

16. Fecha de factura de lo que no es certificación (servicios, revisión, PPA, mercado): las políticas solo la fijan para certificaciones.
17. Redondeo del IVA y de las deducciones: ¿por línea o sobre el total? ¿En qué paso se trunca en PPA?
18. PPA y mercado: ¿una línea por planta o agregada? ¿A qué centro de coste? ¿Cómo se reparten los desvíos entre plantas?
19. Revisión de precios: ¿hasta qué mes se facturan atrasos (el decreto los enumera)? ¿El canon del mes en curso ya va al precio nuevo?
20. Numeración de las facturas emitidas, que se usa como asignación de 43000000. El scorer no la compara.

**AR cobros**

21. Pagos agrupados sin referencia: ¿qué criterio de asignación a facturas se aplica (antigüedad, importe exacto, aviso de pago)?
22. Penalidades: ¿cuáles se consideran «descontadas» en un cobro (las de `penalty_notices`, las de `inbox/ar/notices` o ambas)? ¿Y si el descuento no coincide con la penalidad notificada?
23. `FACTORED_MISDIRECTED` y `OVERPAYMENT_DUPLICATE`: ¿llevan también `applications`, o solo el residual?

**Bancos**

24. ¿Qué líneas de libro son candidatas: solo las 572 de la cuenta contabilizadas en el mes, o también las de meses anteriores aún sin casar?
25. ¿Un ajuste por partida o agrupados por categoría? El scorer aplana las líneas.
26. `FX_RATE_DIFFERENCE`: ¿qué fecha del tipo de referencia (factura, pago, valor)?
27. `WRONG_BANK_ACCOUNT` aparece en ambos lados: ¿cómo se reparte entre `unmatched_bank` y `unmatched_book`?

**Intragrupo**

28. Semántica exacta de `amount` (con qué signo y desde qué lado) y de `responsible`. No puntúan.
29. ¿Cómo se redondea el devengo act/360 y en qué moneda se mide la diferencia en 3100 (EUR o MXN)?
30. `INVOICE_IN_TRANSIT`: ¿el gasto se registra sin IVA, y con qué objeto de coste?

**Cierre**

31. `ACCRUAL`: ¿qué proveedores y periodos se consideran «consumidos y no facturados»? ¿Cómo se estima a partir del histórico? ¿Una fila por proveedor o por tramo? El scorer suma por proveedor.
32. `PREPAID`: ¿qué meses de cobertura y qué redondeo de la mensualidad?
33. `FX_REVAL`: ¿qué «valor contable» se toma para facturas parcialmente pagadas o contabilizadas este mismo mes, y qué tipo para el préstamo en EUR de 3100?
34. `BAD_DEBT`: ¿la antigüedad se mide desde el vencimiento o desde la fecha de factura? ¿La base incluye IVA? ¿Cómo se trata un cliente con cobros parciales?
35. `DOUBTFUL_RECLASS`: ¿qué `amount` se informa? El scorer solo cuenta filas.
