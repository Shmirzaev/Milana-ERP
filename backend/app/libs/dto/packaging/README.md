# Packaging: DTO contracts

**Engineer:** Mirshoir. **Reviewer:** Ismail. **Business acceptance:** Shavkat.

Existing Pydantic definitions in this group:

- [tracking.py](tracking.py)
- [package_source_output.py](package_source_output.py): read-only same-department
  sibling-Nastil balances for direct package creation; canonical PackagingDepartment
  output, saved/labelled quantities, actual Sewing and unrecorded input. An optional
  unbatched balance supports legacy orders without Nastils.
- [packaging_damage_input.py](packaging_damage_input.py): keyed damage-only action;
  constrained work-order/batch IDs and a positive integer damage quantity.
- The existing fulfillment `PrintRunCreatePackagesIn` adds optional `work_order_id`
  to select direct mode and zero-default `damaged_qty` for a single source. The
  established no-anchor saved-output-only body/fingerprint is preserved. Print-run
  creation remains bounded to 200 packages; all-damaged output uses its own action.

These describe accepted inputs and returned data. They do not execute database
writes, implement permissions or manage transactions. Existing filenames/class
names are retained; the folder move does not alter validation or defaults.

Before adding a file, find the existing contract and its router/service callers.
Keep creation fields/defaults, allowed update fields and response filtering distinct.
For updates preserve omitted versus explicit null; do not apply creation defaults.
Add action/query contracts only for actual operations. New <entity>_input.py, <entity>_update.py or
<entity>_output.py files are useful when the feature needs them, not a quota for every table.

Reuse shared bases from ../common.py and existing fixed values. Test validation,
serialization, denied/privileged fields and the consuming workflow; then perform
the required visual and release acceptance checks.

See [DTO rules](../README.md), [business services](../../../models/README.md),
[database definitions](../../../schemas/README.md) and
[ownership](../../../../../docs/TEAM_OWNERSHIP.md).

`package_allocation_items.py` declares the strict full-identity cells used by
`PackageBatchAllocationIn/Out.item_breakdown`. New mixed allocations require a
complete matrix; historical read output remains nullable. Input serialization omits
an absent/None matrix so existing keyed request fingerprints remain valid. Source
balance outputs add actual-size verification and nullable per-size remaining values;
none are inferred from the production plan. Existing mixed tracking DTO files stay
in place; this slice does not claim every package/status/internal dict is migrated.
