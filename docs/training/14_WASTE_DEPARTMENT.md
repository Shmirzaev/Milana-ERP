# Waste Department Training Manual

Version: 1.0
Date: 2026-07-02
Department code: WST
Default role: Waste

## Purpose

Waste Department records, receives, sells, or disposes production waste. Waste records help management understand loss, recover value from sellable waste, and approve disposal of non-sellable waste.

## Main Pages

- Waste Dashboard
- Material/Item list for waste item selection
- Departments list for source department selection
- Finance Waste Report, read by Finance/Management

## Key Permissions

- `waste.receive`
- `waste.sell`
- `waste.disposal`

## Daily Workflow

1. Open Waste Dashboard.
2. Review sellable and non-sellable waste counts.
3. Record waste if your team creates the waste record directly.
4. Receive waste physically from source department.
5. Sell sellable waste when approved by local procedure.
6. Request disposal for non-sellable waste.
7. Mark disposed only after approval and physical disposal.

## Recording Waste

Fields:

1. Item.
2. Source department.
3. Waste type.
4. Quantity.
5. Unit.
6. Sellable checkbox.
7. Reason, when required by process.

Use the physical count/weight. Do not estimate unless supervisor explicitly allows it.

## Receiving Waste

1. Match the waste record to the physical waste.
2. Confirm source department and waste type.
3. Confirm quantity and unit.
4. Select Receive.
5. Store physical waste in the waste area.

## Selling Sellable Waste

1. Confirm waste status is received by waste department.
2. Confirm waste is marked sellable.
3. Confirm buyer and price according to local approval process.
4. Select Sell.
5. Keep sale documents for Finance.

## Disposal For Non-Sellable Waste

1. Confirm waste status is received by waste department.
2. Confirm waste is not sellable.
3. Select Request Disposal.
4. Enter reason.
5. Wait for Management approval.
6. After approval and physical disposal, mark disposed.

Non-sellable waste must not be disposed before approval.

## Status Meaning

| Status | Meaning |
| --- | --- |
| recorded | Waste was logged but not yet received by Waste Department. |
| received_by_waste_department | Waste Department accepted the physical waste. |
| sold | Sellable waste was sold. |
| pending_disposal_approval | Disposal requested and waiting for Management. |
| disposal_approved | Management approved disposal. |
| disposed | Waste was physically disposed and ERP was updated. |

## Common Problems

| Problem | Likely cause | Action |
| --- | --- | --- |
| Waste quantity does not match physical waste | Source department entry mistake | Ask source supervisor to confirm before receiving. |
| Cannot sell | Waste not received or not sellable | Receive first or correct sellable flag through supervisor/Admin. |
| Cannot dispose | Management approval missing | Request approval and wait. |
| Finance report mismatch | Sale/disposal not recorded correctly | Review waste status and sale documents. |

